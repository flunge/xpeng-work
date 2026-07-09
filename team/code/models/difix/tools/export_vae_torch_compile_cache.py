#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.append(str(REPO_ROOT / "src"))

import torch

from src.pipeline_difix import DifixPipeline
from src.config_train import load_config as load_train_config


@dataclass(frozen=True)
class Bucket:
    width: int
    height: int

    @property
    def tag(self) -> str:
        return f"{self.width}x{self.height}"


def _validate_bucket(w: int, h: int) -> Bucket:
    if w <= 0 or h <= 0:
        raise ValueError(f"Invalid bucket {w}x{h}, width/height must be > 0")
    if (w % 8) != 0 or (h % 8) != 0:
        raise ValueError(f"Invalid bucket {w}x{h}, width/height must be divisible by 8")
    return Bucket(width=w, height=h)


def build_buckets_from_train_config(train_cfg: dict) -> List[Bucket]:
    if train_cfg.get("enable_dual_resolution_bucket", False):
        b1 = _validate_bucket(
            int(train_cfg.get("bucket_16_9_width", 1024)),
            int(train_cfg.get("bucket_16_9_height", 576)),
        )
        b2 = _validate_bucket(
            int(train_cfg.get("bucket_5_4_width", 960)),
            int(train_cfg.get("bucket_5_4_height", 768)),
        )
        if b1 == b2:
            return [b1]
        return [b1, b2]
    return [
        _validate_bucket(
            int(train_cfg.get("image_width", 1024)),
            int(train_cfg.get("image_height", 576)),
        )
    ]


def dtype_from_train_config(train_cfg: dict) -> torch.dtype:
    mp = str(train_cfg.get("mixed_precision", "")).lower()
    if mp == "fp16":
        return torch.float16
    if mp == "bf16":
        return torch.bfloat16
    # 训练配置未显式设置 mixed_precision 时，保持与当前推理一致默认 bf16。
    return torch.bfloat16


def resolve_ckpt_file(ckpt_path: str) -> Path:
    p = Path(ckpt_path)
    if p.is_dir():
        p = p / "model.pkl"
    if not p.exists():
        raise FileNotFoundError(f"Checkpoint file not found: {p}")
    return p


def load_modules(pretrained_path: str, ckpt_path: str, dtype: torch.dtype):
    pipe = DifixPipeline.from_pretrained(
        pretrained_path,
        torch_dtype=dtype,
        local_files_only=True,
    )
    vae = pipe.vae.to("cuda", dtype=dtype)
    unet = pipe.unet.to("cuda", dtype=dtype)

    if ckpt_path:
        ckpt_file = resolve_ckpt_file(ckpt_path)
        sd = torch.load(ckpt_file, map_location="cpu")
        if "state_dict_vae" not in sd:
            raise KeyError(f"'state_dict_vae' not found in {ckpt_file}")
        vae_sd = vae.state_dict()
        copied = 0
        for k, v in sd["state_dict_vae"].items():
            if k in vae_sd:
                vae_sd[k] = v
                copied += 1
        missing, unexpected = vae.load_state_dict(vae_sd, strict=False)
        print(
            f"[INFO] Loaded VAE checkpoint keys={copied}, "
            f"missing={len(missing)}, unexpected={len(unexpected)}"
        )
        if "state_dict_unet" in sd:
            unet_sd = unet.state_dict()
            copied_unet = 0
            for k, v in sd["state_dict_unet"].items():
                if k in unet_sd:
                    unet_sd[k] = v
                    copied_unet += 1
            missing_u, unexpected_u = unet.load_state_dict(unet_sd, strict=False)
            print(
                f"[INFO] Loaded UNet checkpoint keys={copied_unet}, "
                f"missing={len(missing_u)}, unexpected={len(unexpected_u)}"
            )
        else:
            print(f"[WARN] 'state_dict_unet' not found in {ckpt_file}, keep pretrained UNet.")

    vae.eval()
    unet.eval()
    return vae, unet


def try_merge_vae_lora(vae) -> bool:
    merged = False
    if hasattr(vae, "fuse_lora"):
        try:
            vae.fuse_lora(lora_scale=1.0, safe_fusing=True)
            print("[INFO] VAE LoRA merged via fuse_lora(lora_scale=1.0, safe_fusing=True).")
            return True
        except TypeError:
            try:
                vae.fuse_lora()
                print("[INFO] VAE LoRA merged via fuse_lora().")
                return True
            except Exception as e:
                print(f"[WARN] fuse_lora() failed: {e}")
        except Exception as e:
            print(f"[WARN] fuse_lora(...) failed: {e}")
    if hasattr(vae, "merge_and_unload"):
        try:
            vae.merge_and_unload()
            print("[INFO] VAE LoRA merged via merge_and_unload().")
            return True
        except Exception as e:
            print(f"[WARN] merge_and_unload failed: {e}")
    if not merged:
        print("[WARN] LoRA merge not applied; continue with current VAE weights.")
    return merged


def compile_modules(vae, unet, mode: str):
    vae.to(memory_format=torch.channels_last)
    vae.encoder = torch.compile(vae.encoder, mode=mode)
    vae.decoder = torch.compile(vae.decoder, mode=mode)
    unet = torch.compile(unet, mode=mode)
    return vae, unet


def warmup_bucket(vae, bucket: Bucket, use_ref: bool, dtype: torch.dtype):
    h, w = bucket.height, bucket.width
    with torch.inference_mode():
        x = torch.randn(1, 3, h, w, device="cuda", dtype=dtype).contiguous(memory_format=torch.channels_last)
        z = vae.encode(x).latent_dist.sample() * vae.config.scaling_factor
        vae.decoder.incoming_skip_acts = vae.encoder.current_down_blocks
        _ = vae.decode(z / vae.config.scaling_factor).sample

        if use_ref:
            xr = torch.randn(1, 3, h, w, device="cuda", dtype=dtype).contiguous(memory_format=torch.channels_last)
            x2 = torch.cat([x, xr], dim=0)
            z2 = vae.encode(x2).latent_dist.sample() * vae.config.scaling_factor
            # no-ref-decode path warmup: decode only first sample
            skips = [s[:1] for s in vae.encoder.current_down_blocks]
            vae.decoder.incoming_skip_acts = skips
            _ = vae.decode(z2[:1] / vae.config.scaling_factor).sample


def warmup_unet_bucket(unet, bucket: Bucket, use_ref: bool, dtype: torch.dtype, timestep: int):
    h, w = bucket.height // 8, bucket.width // 8
    text_dim = unet.config.cross_attention_dim
    if isinstance(text_dim, (list, tuple)):
        text_dim = int(text_dim[0])
    else:
        text_dim = int(text_dim)

    # difix_ref 的 mv_unet 逻辑要求 2-view，不能先跑 bsz=1。
    b_list = [2] if use_ref else [1]
    t = torch.tensor([int(timestep)], device="cuda").long()
    with torch.inference_mode():
        for bsz in b_list:
            latents = torch.randn(bsz, 4, h, w, device="cuda", dtype=dtype).contiguous(
                memory_format=torch.channels_last
            )
            text_emb = torch.randn(bsz, 77, text_dim, device="cuda", dtype=dtype)
            _ = unet(latents, t, encoder_hidden_states=text_emb).sample


def main():
    parser = argparse.ArgumentParser(
        description="Offline torch.compile cache exporter for Difix VAE + UNet."
    )
    parser.add_argument("--pretrained_path", type=str, 
        default="/workspace/group_share/adc-sim/users/led/ckpts/difix_ref/",
        help="Difix pretrained path."
    )
    parser.add_argument("--ckpt_path", type=str, 
        default="/workspace/yangxh7@xiaopeng.com/difix3D_train/train_v3/v3_2buckets/checkpoints_epoch_0012_step_36000",
        help="Checkpoint dir/file containing model.pkl and train_config.yaml.",
    )
    args = parser.parse_args()

    ckpt_dir = Path(args.ckpt_path) if Path(args.ckpt_path).is_dir() else Path(args.ckpt_path).parent
    train_cfg_path = ckpt_dir / "train_config.yaml"
    if not train_cfg_path.exists():
        raise FileNotFoundError(f"train_config.yaml not found: {train_cfg_path}")
    train_cfg = load_train_config(str(train_cfg_path))
    if not isinstance(train_cfg, dict):
        raise ValueError(f"Invalid train_config.yaml: {train_cfg_path}")

    buckets = build_buckets_from_train_config(train_cfg)
    dtype = dtype_from_train_config(train_cfg)
    use_ref_warmup = bool(train_cfg.get("use_ref_img", True))
    force_two_view = "difix_ref" in str(args.pretrained_path).lower()
    if force_two_view and (not use_ref_warmup):
        print(
            "[INFO] pretrained_path indicates difix_ref, force use_ref_warmup=True "
            "for VAE/UNet compile warmup."
        )
    use_ref_warmup = use_ref_warmup or force_two_view
    timestep = int(train_cfg.get("timestep", 199))
    compile_mode = "max-autotune-no-cudagraphs"
    merge_lora = bool(train_cfg.get("compile_merge_lora", True))

    output_dir = ckpt_dir / "torch_compile_cache"
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / "inductor_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = str(cache_dir)

    print(f"[INFO] output_dir={output_dir}")
    print(f"[INFO] TORCHINDUCTOR_CACHE_DIR={cache_dir}")
    print(
        f"[INFO] compile_params from train_config.yaml: "
        f"buckets={[b.tag for b in buckets]}, dtype={dtype}, use_ref_warmup={use_ref_warmup}, "
        f"compile_mode={compile_mode}, timestep={timestep}, force_two_view={force_two_view}, merge_lora={merge_lora}"
    )
    vae, unet = load_modules(args.pretrained_path, args.ckpt_path, dtype)
    if merge_lora:
        try_merge_vae_lora(vae)
    vae, unet = compile_modules(vae, unet, compile_mode)

    warmup_meta = []
    for b in buckets:
        print(f"[INFO] Warmup compile (VAE+UNet) for bucket={b.tag}, use_ref={use_ref_warmup}")
        warmup_bucket(vae, b, use_ref_warmup, dtype)
        warmup_unet_bucket(unet, b, use_ref_warmup, dtype, timestep)
        warmup_meta.append({"width": b.width, "height": b.height, "use_ref_warmup": bool(use_ref_warmup)})

    tar_path = output_dir / "inductor_cache.tar.gz"
    if tar_path.exists():
        tar_path.unlink()
    shutil.make_archive(str(output_dir / "inductor_cache"), "gztar", root_dir=str(cache_dir))
    print(f"[INFO] Packed compile cache: {tar_path}")

    manifest = {
        "pretrained_path": args.pretrained_path,
        "ckpt_path": args.ckpt_path,
        "train_config_yaml": str(train_cfg_path),
        "compile_mode": compile_mode,
        "dtype": str(dtype),
        "use_ref_warmup": use_ref_warmup,
        "force_two_view_for_difix_ref": force_two_view,
        "timestep": timestep,
        "compile_modules": ["vae.encoder", "vae.decoder", "unet"],
        "cache_dir": str(cache_dir),
        "cache_tar": str(tar_path),
        "buckets": warmup_meta,
    }
    (output_dir / "compile_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"[DONE] Manifest: {output_dir / 'compile_manifest.json'}")


if __name__ == "__main__":
    main()
