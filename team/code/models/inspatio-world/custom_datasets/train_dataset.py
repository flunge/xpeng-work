import json
import os
import random

import numpy as np
import torch
from torchvision import transforms

from custom_datasets.utils import read_frames_at_fps

# read_frames_at_fps relies on decord returning torch tensors.
try:
    import decord

    decord.bridge.set_bridge("torch")
except ImportError:
    pass

# Default driving-scene prompt used when an entry does not provide its own text.
DEFAULT_PROMPT = (
    "A forward-facing driving scene captured from a vehicle moving through an "
    "urban road environment, with surrounding lanes, roadside structures, "
    "vehicles, and natural perspective changes from motion."
)


class TrainV2VDataset(torch.utils.data.Dataset):
    """Video-to-video training dataset for InSpatio-World LoRA fine-tuning.

    Each metadata entry is a dict describing one training sample::

        {
            "target_path": "gt_new_view.mp4",   # ground-truth video (supervision)
            "render_path": "gs_render.mp4",      # 3DGS render of the same trajectory
            "ref_path":    "ref_view.mp4",       # optional reference/conditioning view
            "text":        "a driving scene ..."  # optional prompt
        }

    ``ref_path`` defaults to ``target_path`` (self-reconstruction conditioning) and
    ``text`` defaults to :data:`DEFAULT_PROMPT`.

    Returns a dict per sample with all videos as ``[T, C, H, W]`` float tensors:
      - ``target_video``: ground-truth, normalized to ``[-1, 1]``
      - ``render_video``: render, normalized to ``[-1, 1]``
      - ``mask_video``  : 3-channel render-coverage mask in ``[-1, 1]``
      - ``source_video``: reference view, normalized to ``[-1, 1]``
      - ``text``        : prompt string
    """

    def __init__(
        self,
        metadata_path,
        base_path="",
        video_size=(480, 832),
        num_frames=45,
        target_fps=15,
        repeat=1,
        random_start=True,
        ref_time_shift_seconds=0.0,
        random_ref_shift=True,
    ):
        super().__init__()
        self.base_path = base_path
        self.sample_size = tuple(video_size)  # (H, W)
        self.num_frames = num_frames
        self.target_fps = target_fps
        self.random_start = random_start
        self.ref_time_shift_seconds = float(ref_time_shift_seconds)
        self.ref_max_shift_frames = max(0, int(round(self.ref_time_shift_seconds * self.target_fps)))
        self.random_ref_shift = random_ref_shift

        with open(metadata_path, "r") as f:
            metadata = json.load(f)
        assert isinstance(metadata, list) and len(metadata) > 0, \
            f"metadata at {metadata_path} must be a non-empty list"
        self.metadata = metadata * max(1, int(repeat))

        h, w = self.sample_size
        self.resize = transforms.Resize((h, w), antialias=True)
        self.normalize = transforms.Normalize(
            mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5], inplace=False
        )
        print(f"[TrainV2VDataset] {len(metadata)} entries x repeat -> {len(self.metadata)} samples")
        if self.ref_max_shift_frames > 0:
            print(
                "[TrainV2VDataset] ref_time_shift_seconds="
                f"{self.ref_time_shift_seconds:g}s (max ±{self.ref_max_shift_frames} frames @ {self.target_fps} fps)"
            )

    def __len__(self):
        return len(self.metadata)

    def _abs(self, path):
        if self.base_path and not os.path.isabs(path):
            return os.path.join(self.base_path, path)
        return path

    def _sample_clip(self, video):
        """Take a contiguous clip of ``self.num_frames`` frames, padding if short."""
        t = video.shape[0]
        n = self.num_frames
        if t >= n:
            start = random.randint(0, t - n) if self.random_start else 0
            return video[start:start + n]
        # pad by repeating the last frame
        pad = video[-1:].expand(n - t, *video.shape[1:])
        return torch.cat([video, pad], dim=0)

    def _clip_with_start(self, video, start):
        """Return a clip starting at ``start`` with ``self.num_frames`` frames."""
        t = video.shape[0]
        n = self.num_frames
        if t >= n:
            s = max(0, min(int(start), t - n))
            return video[s:s + n]
        pad = video[-1:].expand(n - t, *video.shape[1:])
        return torch.cat([video, pad], dim=0)

    def _load(self, path):
        frames = read_frames_at_fps(self._abs(path), target_fps=self.target_fps)  # [T,C,H,W] in [0,1]
        return self.resize(frames)

    def _get(self, index):
        entry = self.metadata[index]
        target_path = entry["target_path"]
        render_path = entry["render_path"]
        ref_path = entry.get("ref_path", target_path)
        text = entry.get("text", DEFAULT_PROMPT)

        target = self._load(target_path)   # [T,C,H,W] [0,1]
        render = self._load(render_path)
        ref = self._load(ref_path) if ref_path != target_path else target

        # align frame counts across all three streams
        min_t = min(target.shape[0], render.shape[0], ref.shape[0])
        target, render, ref = target[:min_t], render[:min_t], ref[:min_t]

        # joint temporal crop so all streams stay aligned
        t = target.shape[0]
        n = self.num_frames
        if t >= n:
            target_start = random.randint(0, t - n) if self.random_start else 0

            # Optionally shift the reference clip by a random temporal offset
            # within [-ref_time_shift_seconds, +ref_time_shift_seconds].
            if self.ref_max_shift_frames > 0:
                if self.random_ref_shift:
                    ref_shift = random.randint(-self.ref_max_shift_frames, self.ref_max_shift_frames)
                else:
                    ref_shift = self.ref_max_shift_frames
            else:
                ref_shift = 0
            ref_start = max(0, min(target_start + ref_shift, t - n))

            target = self._clip_with_start(target, target_start)
            render = self._clip_with_start(render, target_start)
            ref = self._clip_with_start(ref, ref_start)
        else:
            target = self._sample_clip(target)
            render = self._sample_clip(render)
            ref = self._sample_clip(ref)

        # render-coverage mask: pixels with any signal are valid
        mask = (render.sum(dim=1, keepdim=True) > 0).float()  # [T,1,H,W]
        mask = mask.expand(-1, 3, -1, -1) * 2.0 - 1.0          # [T,3,H,W] in {-1,1}

        return {
            "target_video": self.normalize(target),
            "render_video": render * 2.0 - 1.0,
            "mask_video": mask,
            "source_video": self.normalize(ref),
            "text": text,
        }

    def __getitem__(self, index):
        attempts = 0
        while True:
            try:
                return self._get(index)
            except Exception as e:  # skip unreadable samples
                import traceback
                print(f"[TrainV2VDataset] error on index {index}: {e}")
                traceback.print_exc()
                attempts += 1
                if attempts > 10:
                    raise
                index = random.randrange(len(self.metadata))
