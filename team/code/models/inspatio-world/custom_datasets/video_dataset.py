import json
import random
import traceback

import torch
from torchvision import transforms

from custom_datasets.utils import read_frames_at_fps

try:
    import decord

    decord.bridge.set_bridge('torch')
except ImportError:
    pass


class VideoDataset(torch.utils.data.Dataset):
    """Inference dataset reading the same metadata format as ``TrainV2VDataset``.

    Each metadata entry is a dict::

        {"target_path": "gt.mp4", "render_path": "render.mp4", "ref_path"?: "ref.mp4"}

    ``ref_path`` defaults to ``target_path`` (self-reconstruction conditioning).
    No ``text`` field is read: all samples share a single prompt whose embeddings
    are cached separately (see ``data/prompt_embeds.pt`` in inference).

    Each item is a dict of ``[T, C, H, W]`` float tensors:
      - ``target_video``: ground-truth view (target_path), normalized to ``[-1, 1]``
      - ``source_video``: reference view (ref_path), normalized to ``[-1, 1]``
      - ``render_video``: 3DGS render (render_path), normalized to ``[-1, 1]``
      - ``mask_video``  : 3-channel render-coverage mask in ``[-1, 1]``

    Full sequences are read (capped at 1000 frames) then temporally subsampled to
    ``min_num_frames`` when longer.
    """

    def __init__(self, metadata_path, video_size, min_num_frames=None,
                 target_fps=10, ref_time_shift_seconds=0.0, limit=None):
        # ``min_num_frames`` is a *training* parameter (clip length). Inference
        # reads every frame at ``target_fps`` and does no temporal subsampling,
        # so it is accepted for API compatibility but intentionally unused.
        self.num_frames = min_num_frames
        target_height, target_width = video_size
        self.target_fps = int(target_fps)

        # Temporal offset applied to the reference/source stream. This is an
        # explicit, deterministic inference knob (default 0 = time-aligned). It is
        # NOT the training augmentation: training's data.ref_time_shift_seconds is
        # a *random* ±range augmentation; here the value is a fixed shift the user
        # passes via --ref_time_shift. Positive = ref from later (future) frames.
        self.ref_time_shift_seconds = float(ref_time_shift_seconds)
        self.ref_shift_frames = int(round(self.ref_time_shift_seconds * self.target_fps))

        if not isinstance(metadata_path, str):
            metadata_path = metadata_path[0]
        with open(metadata_path, 'r') as f:
            self.metadata_list = json.load(f)
        assert isinstance(self.metadata_list, list) and self.metadata_list, \
            f"metadata at {metadata_path} must be a non-empty list"

        # Optionally render only the first ``limit`` entries.
        if limit is not None and int(limit) > 0:
            self.metadata_list = self.metadata_list[:int(limit)]

        # Key each sample by its target_path; inference uses these keys to build
        # per-sample output directories (<scene>/<cam>).
        self.dataset = {entry['target_path']: entry for entry in self.metadata_list}

        self._resize = transforms.Resize((target_height, target_width))
        self._normalize = transforms.Normalize(
            mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5], inplace=False
        )
        print(f"Loaded {len(self.dataset)} videos.")
        if self.ref_shift_frames != 0:
            print(f"[VideoDataset] ref_time_shift={self.ref_time_shift_seconds:g}s "
                  f"({self.ref_shift_frames:+d} frames @ {self.target_fps} fps)")

    def _read(self, path):
        frames = read_frames_at_fps(path, target_fps=self.target_fps)  # [T, C, H, W] in [0, 1]
        if frames.shape[0] > 1000:
            frames = frames[:1000]
        return self._resize(frames)

    def _get_data(self, entry):
        target_path = entry['target_path']
        ref_path = entry.get('ref_path', target_path)

        target = self._read(target_path)
        render = self._read(entry['render_path'])
        ref = target if ref_path == target_path else self._read(ref_path)

        # render-coverage mask: pixels with any signal are valid
        mask = (render.sum(dim=1, keepdim=True) > 0).float()
        mask = mask.expand(-1, 3, -1, -1) * 2.0 - 1.0  # [T, 3, H, W] in {-1, 1}

        # align frame counts across all streams
        min_t = min(target.shape[0], render.shape[0], ref.shape[0])
        target, render, ref, mask = target[:min_t], render[:min_t], ref[:min_t], mask[:min_t]

        # Temporally shift the reference stream by a fixed offset (seconds ->
        # frames at target_fps). Edge frames are clamped so length is unchanged.
        if self.ref_shift_frames != 0 and min_t > 1:
            idx = torch.arange(min_t) + self.ref_shift_frames
            idx = idx.clamp_(0, min_t - 1)
            ref = ref[idx]

        data = {
            'target_video': self._normalize(target),
            'source_video': self._normalize(ref),
            'render_video': render * 2.0 - 1.0,
            'mask_video': mask,
        }
        print(f"target_video {data['target_video'].shape}, "
              f"render_video {data['render_video'].shape}, "
              f"mask_video {data['mask_video'].shape}")
        return data

    def __getitem__(self, index):
        while True:
            try:
                key = list(self.dataset.keys())[index]
                data = self._get_data(self.dataset[key])
                # No temporal subsampling at inference: every frame (read at
                # target_fps) is kept, so the output preserves real-time pacing.
                data['index'] = index
                return data
            except Exception as e:
                print("Error info:", e)
                traceback.print_exc()
                index = random.randrange(len(self.dataset))

    def __len__(self):
        return len(self.dataset)
