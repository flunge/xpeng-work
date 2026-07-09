"""Offline VAE-latent pre-encoder for InSpatio-World training.

WHY
---
The 32-GPU overnight run was input-bound: per-step timing showed the frozen-VAE encode
costing ~5-6s (up to ~50% of each step) and DataLoader ``data_wait`` up to ~59%. Both are
pure recomputation of the *same* latents every epoch. This script encodes every training
clip **once** to disk so training can read latents directly (no video decode, no VAE
forward) - removing the ``vae_encode`` cost entirely and shrinking the DataLoader payload.

It deliberately reuses the *exact* encode path used in training
(``encode_videos`` / ``convert_mask_video``), so the cached latents are numerically
identical to the on-the-fly ones.

USAGE
-----
Single process (the VAE is small; one GPU is usually enough)::

    python tools/precompute_latents.py \
        --config configs/train_lora_1.3b.yaml \
        --out ./data/latent_cache \
        --num-crops 1

``--num-crops N`` stores N independent random crops per metadata entry, so you keep some
temporal-crop diversity even though the cache is fixed. ``--num-crops 1`` with the
dataset's ``random_start`` gives one (random) crop per entry.

Then enable the cache in your training YAML::

    data:
      use_latent_cache: true
      latent_cache_index: ./data/latent_cache/index.json

and launch training as usual.

OUTPUT
------
``<out>/latents/000000.safetensors`` ... (one file per cached clip) plus
``<out>/index.json`` consumed by ``custom_datasets.cached_latent_dataset``.
"""

import argparse
import json
import os
import sys

import torch
from einops import rearrange
from omegaconf import OmegaConf
from safetensors.torch import save_file

# Make the inspatio-world package root importable when run as tools/precompute_latents.py.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(_THIS_DIR)
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from custom_datasets.train_dataset import DEFAULT_PROMPT, TrainV2VDataset  # noqa: E402
from utils.render_warper import convert_mask_video  # noqa: E402
from utils.wan_wrapper import WanVAEWrapper  # noqa: E402


@torch.no_grad()
def encode_videos(vae, videos_btchw, device, dtype):
    """Mirror of train.encode_videos: [B,T,C,H,W] pixels in [-1,1] -> [B,T,16,h,w]."""
    v = rearrange(videos_btchw, "b t c h w -> b c t h w").to(device=device, dtype=dtype)
    return vae.encode_to_latent(v).to(device=device, dtype=dtype)


def load_config():
    parser = argparse.ArgumentParser(description="Pre-encode VAE latents for training")
    parser.add_argument("--config", type=str, required=True,
                        help="Training YAML (same one used for train.py)")
    parser.add_argument("--out", type=str, required=True,
                        help="Output directory for the latent cache")
    parser.add_argument("--num-crops", type=int, default=1,
                        help="Random crops stored per metadata entry (>=1)")
    args, overrides = parser.parse_known_args()
    cfg = OmegaConf.load(args.config)
    if overrides:
        cfg = OmegaConf.merge(cfg, OmegaConf.from_dotlist(overrides))
    return cfg, args


def load_pipeline_config(cfg):
    inline = OmegaConf.select(cfg, "model.pipeline", default=None)
    if inline is not None:
        return OmegaConf.create(inline)
    config_path = OmegaConf.select(cfg, "model.config_path", default=None)
    if not config_path:
        raise ValueError("Missing pipeline config: set model.pipeline or model.config_path")
    return OmegaConf.load(config_path)


def main():
    cfg, args = load_config()
    assert args.num_crops >= 1, "--num-crops must be >= 1"

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16

    # --- Build the frozen VAE (same weights/path as training) ------------
    config = load_pipeline_config(cfg)
    checkpoint_path = cfg.model.checkpoint_path
    wan_model_folder = os.path.join(checkpoint_path, config.wan_model_folder)
    print(f"[precompute] loading VAE from {wan_model_folder}")
    vae = WanVAEWrapper(model_folder=wan_model_folder).to(device=device, dtype=dtype).eval()

    # --- Build the pixel dataset (same config as training) ---------------
    dataset = TrainV2VDataset(
        metadata_path=cfg.data.metadata,
        base_path=cfg.data.base_path,
        video_size=(cfg.data.height, cfg.data.width),
        num_frames=cfg.data.num_frames,
        target_fps=cfg.data.target_fps,
        repeat=1,  # repeat is handled by --num-crops here
        random_start=bool(OmegaConf.select(cfg, "data.random_start", default=True)),
        ref_time_shift_seconds=OmegaConf.select(cfg, "data.ref_time_shift_seconds", default=0.0),
        random_ref_shift=OmegaConf.select(cfg, "data.random_ref_shift", default=True),
    )
    n_entries = len(dataset)
    total = n_entries * args.num_crops
    print(f"[precompute] {n_entries} entries x {args.num_crops} crops -> {total} cached clips")

    latent_dir = os.path.join(args.out, "latents")
    os.makedirs(latent_dir, exist_ok=True)

    samples = []
    written = 0
    for crop in range(args.num_crops):
        for idx in range(n_entries):
            item = dataset[idx]  # pixel dict: [T,C,H,W] tensors in [-1,1], plus text

            # Replicate compute_loss's encode path exactly (batch dim of 1).
            target_lat = encode_videos(vae, item["target_video"].unsqueeze(0), device, dtype)
            render_lat = encode_videos(vae, item["render_video"].unsqueeze(0), device, dtype)
            source_lat = encode_videos(vae, item["source_video"].unsqueeze(0), device, dtype)
            mask_pix = rearrange(item["mask_video"].unsqueeze(0).to(device, dtype),
                                 "b t c h w -> b c t h w")
            mask_lat = convert_mask_video(mask_pix).to(device, dtype)

            tensors = {
                "target_lat": target_lat.squeeze(0).contiguous().cpu(),
                "render_lat": render_lat.squeeze(0).contiguous().cpu(),
                "source_lat": source_lat.squeeze(0).contiguous().cpu(),
                "mask_lat": mask_lat.squeeze(0).contiguous().cpu(),
            }
            fname = os.path.join("latents", f"{written:06d}.safetensors")
            text = item.get("text", DEFAULT_PROMPT)
            save_file(tensors, os.path.join(args.out, fname), metadata={"text": text})
            samples.append({"file": fname, "text": text})
            written += 1

            # Real-time progress, batched per the runbook (<=20 between prints).
            if written % 20 == 0 or written == total:
                print(f"[precompute] {written}/{total} clips encoded", flush=True)

    index_path = os.path.join(args.out, "index.json")
    with open(index_path, "w") as f:
        json.dump({"version": 1, "samples": samples}, f)
    print(f"[precompute] done. wrote {written} clips + index -> {index_path}")
    print("[precompute] enable with:  data.use_latent_cache=true "
          f"data.latent_cache_index={index_path}")


if __name__ == "__main__":
    main()
