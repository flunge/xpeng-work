"""Dataset that serves pre-encoded VAE latents from disk.

The overnight 32-GPU run was input-bound: the per-step timing showed the VAE encode
costing ~5-6s (up to ~50% of each step) and DataLoader ``data_wait`` up to ~59%. Both
costs are pure recomputation of the *same* frozen-VAE latents on *every* epoch.

This dataset removes that work. An offline pass (``tools/precompute_latents.py``)
encodes every training clip once - using the exact same ``encode_videos`` /
``convert_mask_video`` code path as training - and writes the latents to disk. At train
time we just load the small latent tensors (no video decode, no VAE forward), so the GPU
stops starving and each step drops to roughly the model forward/backward time.

Cache layout
------------
``precompute_latents.py`` writes one ``.safetensors`` file per cached clip plus an index
JSON::

    {
      "version": 1,
      "samples": [
        {"file": "latents/000000.safetensors", "text": "a driving scene ..."},
        ...
      ]
    }

Each ``.safetensors`` file holds four latent tensors with the SAME shapes the training
loop expects after ``encode_videos`` / ``convert_mask_video`` (batch dim dropped):

    target_lat : [T, 16, h, w]
    render_lat : [T, 16, h, w]
    source_lat : [T, 16, h, w]   (ref view)
    mask_lat   : [L', 4, h, w]

``__getitem__`` returns exactly these (plus ``text``); the default collate stacks them to
``[B, ...]``, and ``compute_loss`` detects the ``*_lat`` keys and skips the VAE encode.

Tradeoff vs the on-the-fly pixel dataset: random temporal crop / random ref shift are
*frozen into the cache* at precompute time (you can still get crop diversity by passing
``--num-crops > 1`` to the precompute script, which stores several random crops per
entry). This is the standard precomputed-latent training tradeoff: a fixed, finite set of
pre-encoded clips reused every epoch, in exchange for removing all per-step VAE/decoding
cost.
"""

import json
import os

import torch
from safetensors.torch import load_file


class CachedLatentV2VDataset(torch.utils.data.Dataset):
    """Serve pre-encoded latents produced by ``tools/precompute_latents.py``.

    Args:
        index_path: path to the cache index JSON.
        base_path: optional override for the directory that the per-sample ``file``
            paths are resolved against. Defaults to the index file's own directory.
    """

    # Tensor keys stored per cache file (must match precompute_latents.py).
    LATENT_KEYS = ("target_lat", "render_lat", "source_lat", "mask_lat")

    def __init__(self, index_path, base_path=""):
        super().__init__()
        with open(index_path, "r") as f:
            index = json.load(f)
        assert isinstance(index, dict) and "samples" in index, \
            f"bad cache index at {index_path}: expected a dict with a 'samples' list"
        samples = index["samples"]
        assert isinstance(samples, list) and len(samples) > 0, \
            f"cache index at {index_path} has no samples"

        # Resolve per-sample files against base_path (or the index's directory).
        self.base_path = base_path or os.path.dirname(os.path.abspath(index_path))
        # ``metadata`` mirrors TrainV2VDataset.metadata: a list of dicts each carrying a
        # "text" key, so train.py's val-split and prompt-cache code works unchanged.
        self.metadata = [
            {"file": s["file"], "text": s.get("text", "")} for s in samples
        ]
        print(f"[CachedLatentV2VDataset] {len(self.metadata)} cached clips "
              f"(index={index_path})")

    def __len__(self):
        return len(self.metadata)

    def _abs(self, path):
        if self.base_path and not os.path.isabs(path):
            return os.path.join(self.base_path, path)
        return path

    def __getitem__(self, index):
        entry = self.metadata[index]
        tensors = load_file(self._abs(entry["file"]))
        missing = [k for k in self.LATENT_KEYS if k not in tensors]
        if missing:
            raise KeyError(
                f"cache file {entry['file']} missing latent keys {missing}; "
                f"re-run tools/precompute_latents.py")
        out = {k: tensors[k] for k in self.LATENT_KEYS}
        out["text"] = entry["text"]
        return out
