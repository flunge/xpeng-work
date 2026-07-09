#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Dict, List, Sequence, Tuple

import torch
import torch.nn as nn

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.append(str(REPO_ROOT / "src"))

from src.pipeline_difix import DifixPipeline  # noqa: E402
from src.config_train import load_config as load_train_config  # noqa: E402

BUCKET_CAMERA_GROUPS = {
    "bucket_16_9": ["cam0", "cam2", "cam7"],
    "bucket_5_4": ["cam3", "cam4", "cam5", "cam6"],
}
TENSORRT_SEARCH_ROOTS = [
    "/workspace/yangxh7@xiaopeng.com/Installers/TensorRT-10.13.3.9",
]
DEFAULT_TRTEXEC_BIN = (
    "/workspace/yangxh7@xiaopeng.com/Installers/TensorRT-10.13.3.9/bin/trtexec"
)
DEFAULT_TRT_LIB_DIR = (
    "/workspace/yangxh7@xiaopeng.com/Installers/TensorRT-10.13.3.9/lib"
)


@dataclass(frozen=True)
class Bucket:
    height: int
    width: int

    @property
    def tag(self) -> str:
        return f"{self.width}x{self.height}"


class VAEEncoderExportWrapper(nn.Module):
    """
    Export-friendly VAE encoder wrapper.
    Outputs quant moments + 4 skip tensors used by Difix decoder.
    """

    def __init__(self, vae: nn.Module):
        super().__init__()
        self.vae = vae

    def forward(self, image: torch.Tensor):
        h = self.vae.encoder(image)
        moments = self.vae.quant_conv(h)
        s0, s1, s2, s3 = self.vae.encoder.current_down_blocks
        return moments, s0, s1, s2, s3


class VAEDecoderExportWrapper(nn.Module):
    """
    Export-friendly VAE decoder wrapper.
    Inputs are latent z + 4 skip tensors from encoder.
    """

    def __init__(self, vae: nn.Module):
        super().__init__()
        self.vae = vae

    def forward(
        self,
        z: torch.Tensor,
        skip0: torch.Tensor,
        skip1: torch.Tensor,
        skip2: torch.Tensor,
        skip3: torch.Tensor,
    ):
        self.vae.decoder.incoming_skip_acts = [skip0, skip1, skip2, skip3]
        z = self.vae.post_quant_conv(z)
        image = self.vae.decoder(z)
        return image


class FixedPromptUNetExportWrapper(nn.Module):
    """
    Export-friendly UNet wrapper with fixed prompt embeddings and fixed timestep.
    Only supports V=2 inputs for the Difix multi-view UNet path.
    """

    def __init__(self, unet: nn.Module, encoder_hidden_states: torch.Tensor, timestep: int):
        super().__init__()
        self.unet = unet
        self.register_buffer("encoder_hidden_states_const", encoder_hidden_states.detach())
        self.register_buffer(
            "timestep_const",
            torch.tensor([int(timestep)], device=encoder_hidden_states.device, dtype=torch.long),
        )

    def forward(self, latent: torch.Tensor):
        return self.unet(
            latent,
            self.timestep_const,
            encoder_hidden_states=self.encoder_hidden_states_const,
            return_dict=False,
        )[0]


def _validate_bucket(w: int, h: int) -> Bucket:
    if w <= 0 or h <= 0:
        raise ValueError(f"Invalid bucket {w}x{h}, width/height must be > 0")
    if (w % 8) != 0 or (h % 8) != 0:
        raise ValueError(f"Invalid bucket {w}x{h}, width/height must be divisible by 8")
    return Bucket(height=h, width=w)


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
    return torch.bfloat16


def parse_export_dtype(export_dtype: str, train_cfg: dict) -> torch.dtype:
    export_dtype = str(export_dtype).lower()
    if export_dtype == "auto":
        return dtype_from_train_config(train_cfg)
    if export_dtype == "fp16":
        return torch.float16
    if export_dtype == "bf16":
        return torch.bfloat16
    raise ValueError(f"Unsupported --export_dtype={export_dtype}")


def resolve_ckpt_file(ckpt_path: str) -> Path:
    p = Path(ckpt_path)
    if p.is_dir():
        p = p / "model.pkl"
    if not p.exists():
        raise FileNotFoundError(f"Checkpoint file not found: {p}")
    return p


def camera_prompt(camera_name: str) -> str:
    return f"Corrected rendering distortion for {str(camera_name).upper()} camera view."


def normalize_overwrite_prompt(prompt) -> str:
    if prompt is None:
        return ""
    text = str(prompt).strip()
    return text


def should_share_unet_engine(train_cfg: dict) -> bool:
    return normalize_overwrite_prompt(train_cfg.get("overwrite_prompt", None)) != ""


def build_bucket_camera_map_from_train_config(train_cfg: dict) -> Dict[str, List[str]]:
    if train_cfg.get("enable_dual_resolution_bucket", False):
        bucket_16_9 = _validate_bucket(
            int(train_cfg.get("bucket_16_9_width", 1024)),
            int(train_cfg.get("bucket_16_9_height", 576)),
        )
        bucket_5_4 = _validate_bucket(
            int(train_cfg.get("bucket_5_4_width", 960)),
            int(train_cfg.get("bucket_5_4_height", 768)),
        )
        bucket_camera_map: Dict[str, List[str]] = {
            bucket_16_9.tag: list(BUCKET_CAMERA_GROUPS["bucket_16_9"])
        }
        if bucket_5_4.tag == bucket_16_9.tag:
            bucket_camera_map[bucket_16_9.tag].extend(BUCKET_CAMERA_GROUPS["bucket_5_4"])
        else:
            bucket_camera_map[bucket_5_4.tag] = list(BUCKET_CAMERA_GROUPS["bucket_5_4"])
        return bucket_camera_map

    single_bucket = _validate_bucket(
        int(train_cfg.get("image_width", 1024)),
        int(train_cfg.get("image_height", 576)),
    )
    all_cameras = list(BUCKET_CAMERA_GROUPS["bucket_16_9"]) + list(BUCKET_CAMERA_GROUPS["bucket_5_4"])
    return {single_bucket.tag: all_cameras}


def camera_names_for_bucket(bucket: Bucket, bucket_camera_map: Dict[str, List[str]]) -> List[str]:
    camera_names = bucket_camera_map.get(bucket.tag)
    if camera_names is None:
        raise ValueError(
            f"No fixed camera mapping configured for bucket={bucket.tag}. "
            f"Available mappings: {sorted(bucket_camera_map.keys())}"
        )
    return list(camera_names)


def load_modules(pretrained_path: str, ckpt_path: str, dtype: torch.dtype):
    pipe = DifixPipeline.from_pretrained(
        pretrained_path,
        torch_dtype=dtype,
        local_files_only=True,
    )
    pipe.text_encoder = pipe.text_encoder.to("cuda")
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
    pipe.text_encoder.eval()
    vae.eval()
    unet.eval()
    return pipe, vae, unet


def merge_vae_lora_inplace(vae: nn.Module):
    """
    Try to fuse/merge LoRA weights into base VAE weights.
    Different diffusers/peft versions expose different APIs.
    """
    merged = False

    if hasattr(vae, "fuse_lora"):
        try:
            vae.fuse_lora(lora_scale=1.0, safe_fusing=True)
            merged = True
            print("[INFO] VAE LoRA merged via vae.fuse_lora(...).")
        except TypeError:
            vae.fuse_lora()
            merged = True
            print("[INFO] VAE LoRA merged via vae.fuse_lora().")
        except Exception as e:
            print(f"[WARN] vae.fuse_lora failed: {e}")

    if (not merged) and hasattr(vae, "merge_and_unload"):
        try:
            vae.merge_and_unload()
            merged = True
            print("[INFO] VAE LoRA merged via vae.merge_and_unload().")
        except Exception as e:
            print(f"[WARN] vae.merge_and_unload failed: {e}")

    if not merged:
        print("[WARN] No merge API succeeded. Continue export with current VAE weights.")


def export_onnx_for_bucket(
    vae: nn.Module,
    bucket: Bucket,
    output_dir: Path,
    opset: int,
    num_views: int,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    encoder_onnx = output_dir / "vae_encoder.onnx"
    decoder_onnx = output_dir / "vae_decoder.onnx"
    shape_json = output_dir / "shapes.json"

    enc_wrap = VAEEncoderExportWrapper(vae).to("cuda")
    dec_wrap = VAEDecoderExportWrapper(vae).to("cuda")
    enc_wrap.eval()
    dec_wrap.eval()

    with torch.no_grad():
        image = torch.randn(
            num_views,
            3,
            bucket.height,
            bucket.width,
            device="cuda",
            dtype=next(vae.parameters()).dtype,
        )
        moments, s0, s1, s2, s3 = enc_wrap(image)
        # Match model.py decode_ref=False path:
        # encoder/unet run on all views, decoder only consumes target view (index 0).
        latent_all = moments[:, : moments.shape[1] // 2]
        latent = latent_all[:1]
        dec_s0 = s0[:1]
        dec_s1 = s1[:1]
        dec_s2 = s2[:1]
        dec_s3 = s3[:1]
        _ = dec_wrap(latent, dec_s0, dec_s1, dec_s2, dec_s3)

    torch.onnx.export(
        enc_wrap,
        (image,),
        str(encoder_onnx),
        input_names=["image"],
        output_names=["moments", "skip0", "skip1", "skip2", "skip3"],
        opset_version=opset,
        do_constant_folding=True,
    )

    torch.onnx.export(
        dec_wrap,
        (latent, dec_s0, dec_s1, dec_s2, dec_s3),
        str(decoder_onnx),
        input_names=["z", "skip0", "skip1", "skip2", "skip3"],
        output_names=["image"],
        opset_version=opset,
        do_constant_folding=True,
    )

    shapes = {
        "bucket": {"width": bucket.width, "height": bucket.height},
        "encoder": {
            "image": list(image.shape),
            "moments": list(moments.shape),
            "skip0": list(s0.shape),
            "skip1": list(s1.shape),
            "skip2": list(s2.shape),
            "skip3": list(s3.shape),
        },
        "decoder": {
            "z": list(latent.shape),
            "skip0": list(dec_s0.shape),
            "skip1": list(dec_s1.shape),
            "skip2": list(dec_s2.shape),
            "skip3": list(dec_s3.shape),
            "image": [1, 3, bucket.height, bucket.width],
        },
    }
    shape_json.write_text(json.dumps(shapes, indent=2))
    print(f"[INFO] Exported ONNX for bucket={bucket.tag} -> {output_dir}")
    return encoder_onnx, decoder_onnx, shapes


def export_unet_onnx_for_bucket(
    pipe: DifixPipeline,
    unet: nn.Module,
    bucket: Bucket,
    output_dir: Path,
    opset: int,
    timestep: int,
    camera_names: Sequence[str],
    overwrite_prompt: str = "",
) -> Dict[str, dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    latent_h = bucket.height // 8
    latent_w = bucket.width // 8
    latent_dtype = next(unet.parameters()).dtype
    latent = torch.randn(2, 4, latent_h, latent_w, device="cuda", dtype=latent_dtype)

    camera_meta: Dict[str, dict] = {}
    shared_prompt = normalize_overwrite_prompt(overwrite_prompt)
    share_unet = shared_prompt != ""
    with torch.no_grad():
        if share_unet:
            target_camera_names = ["shared"]
        else:
            target_camera_names = list(camera_names)
        for camera_name in target_camera_names:
            prompt = shared_prompt if share_unet else camera_prompt(camera_name)
            tokens = pipe.tokenizer(
                [prompt],
                max_length=pipe.tokenizer.model_max_length,
                padding="max_length",
                truncation=True,
                return_tensors="pt",
            ).input_ids.to(next(pipe.text_encoder.parameters()).device)
            prompt_embed = pipe.text_encoder(tokens)[0].to(device="cuda", dtype=latent_dtype)
            encoder_hidden_states = prompt_embed.repeat(2, 1, 1).contiguous()

            unet_wrap = FixedPromptUNetExportWrapper(
                unet=unet,
                encoder_hidden_states=encoder_hidden_states,
                timestep=timestep,
            ).to("cuda")
            unet_wrap.eval()
            sample = unet_wrap(latent)

            if share_unet:
                unet_onnx = output_dir / "unet.onnx"
            else:
                unet_onnx = output_dir / f"unet_{camera_name}.onnx"
            torch.onnx.export(
                unet_wrap,
                (latent,),
                str(unet_onnx),
                input_names=["latent"],
                output_names=["sample"],
                opset_version=opset,
                do_constant_folding=True,
            )
            key_name = camera_name if not share_unet else "__shared__"
            camera_meta[key_name] = {
                "prompt": prompt,
                "timestep": int(timestep),
                "onnx": str(unet_onnx),
                "latent": list(latent.shape),
                "encoder_hidden_states": list(encoder_hidden_states.shape),
                "sample": list(sample.shape),
                "share_unet_engine": bool(share_unet),
            }
            print(
                f"[INFO] Exported UNet ONNX for bucket={bucket.tag}, "
                f"camera={camera_name.upper()} -> {unet_onnx}"
            )
        if share_unet:
            camera_meta["__shared__"]["camera_names"] = list(camera_names)
    return camera_meta


def _shape_arg(name: str, shape: Sequence[int]) -> str:
    return f"{name}:{'x'.join(str(x) for x in shape)}"


def discover_trtexec_candidates() -> List[str]:
    candidates: List[str] = []
    default_trtexec = Path(DEFAULT_TRTEXEC_BIN)
    if default_trtexec.is_file():
        candidates.append(str(default_trtexec))
    path_hit = which("trtexec")
    if path_hit:
        candidates.append(path_hit)
    for root in TENSORRT_SEARCH_ROOTS:
        root_path = Path(root)
        if not root_path.exists():
            continue
        patterns = [
            "bin/trtexec",
            "targets/x86_64-linux-gnu/bin/trtexec",
            "**/bin/trtexec",
        ]
        for pattern in patterns:
            for p in root_path.glob(pattern):
                if p.is_file():
                    candidates.append(str(p))
    deduped = []
    seen = set()
    for item in candidates:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def discover_trt_lib_candidates(trtexec_bin: str = "") -> List[str]:
    candidates: List[str] = []
    default_lib = Path(DEFAULT_TRT_LIB_DIR)
    if default_lib.is_dir():
        candidates.append(str(default_lib))
    if trtexec_bin:
        trtexec_path = Path(trtexec_bin).resolve()
        candidates.extend(
            [
                str(trtexec_path.parents[1] / "lib"),
                str(trtexec_path.parents[2] / "lib"),
            ]
        )
    for root in TENSORRT_SEARCH_ROOTS:
        root_path = Path(root)
        if not root_path.exists():
            continue
        patterns = [
            "lib",
            "targets/x86_64-linux-gnu/lib",
            "**/lib",
        ]
        for pattern in patterns:
            for p in root_path.glob(pattern):
                if p.is_dir():
                    candidates.append(str(p))
    deduped = []
    seen = set()
    for item in candidates:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def resolve_trtexec_bin(trtexec_bin: str) -> str:
    if trtexec_bin:
        p = Path(trtexec_bin)
        if p.is_file():
            return str(p)
        resolved = which(trtexec_bin)
        if resolved:
            return resolved
    candidates = discover_trtexec_candidates()
    if candidates:
        return candidates[0]
    raise FileNotFoundError(
        "trtexec not found. Please install a TensorRT runtime package that includes "
        "the binary, or pass --trtexec_bin explicitly."
    )


def resolve_trt_lib_dir(trtexec_bin: str, trt_lib_dir: str) -> str:
    if trt_lib_dir:
        lib_dir = Path(trt_lib_dir)
        if not lib_dir.is_dir():
            raise FileNotFoundError(f"TensorRT lib dir not found: {lib_dir}")
        return str(lib_dir)

    for candidate in discover_trt_lib_candidates(trtexec_bin):
        candidate_path = Path(candidate)
        if candidate_path.is_dir():
            return str(candidate_path)

    raise FileNotFoundError(
        "TensorRT lib dir not found. Please install a TensorRT runtime package that includes "
        "libnvinfer*.so, or pass --trt_lib_dir explicitly."
    )


def validate_trt_runtime(trt_lib_dir: str):
    required_libs = ["libnvinfer.so", "libnvinfer_plugin.so"]
    missing = []
    for name in required_libs:
        matches = list(Path(trt_lib_dir).glob(f"{name}*"))
        if len(matches) == 0:
            missing.append(name)
    if missing:
        raise FileNotFoundError(
            f"Missing TensorRT runtime libs in {trt_lib_dir}: {missing}. "
            "Please make sure the full TensorRT runtime is installed."
        )


def build_trt_engine(
    trtexec_bin: str,
    trt_lib_dir: str,
    onnx_path: Path,
    engine_path: Path,
    io_shapes: List[Tuple[str, Sequence[int]]],
    fp16: bool,
    workspace_mib: int,
    timing_cache_file: str = "",
):
    my_env = os.environ.copy()
    if "LD_LIBRARY_PATH" in my_env:
        my_env["LD_LIBRARY_PATH"] = f"{trt_lib_dir}:{my_env['LD_LIBRARY_PATH']}"
    else:
        my_env["LD_LIBRARY_PATH"] = trt_lib_dir

    cmd = [
        trtexec_bin,
        f"--onnx={onnx_path}",
        f"--saveEngine={engine_path}",
        f"--memPoolSize=workspace:{workspace_mib}",
        "--builderOptimizationLevel=5",
        "--skipInference",
    ]
    if timing_cache_file:
        timing_cache_path = Path(timing_cache_file)
        timing_cache_path.parent.mkdir(parents=True, exist_ok=True)
        cmd.append(f"--timingCacheFile={timing_cache_path}")
    if io_shapes:
        shape_items = [_shape_arg(name, shape) for name, shape in io_shapes]
        print(f"[INFO] Static ONNX detected, skip explicit shapes: {','.join(shape_items)}")
    if fp16:
        cmd.append("--fp16")
    print("[INFO] Running:", " ".join(cmd))
    subprocess.run(cmd, env=my_env, check=True)


def build_trt_for_bucket(
    trtexec_bin: str,
    trt_lib_dir: str,
    bucket_dir: Path,
    shapes: dict,
    fp16: bool,
    workspace_mib: int,
    timing_cache_file: str = "",
):
    encoder_onnx = bucket_dir / "vae_encoder.onnx"
    decoder_onnx = bucket_dir / "vae_decoder.onnx"
    encoder_engine = bucket_dir / "vae_encoder.engine"
    decoder_engine = bucket_dir / "vae_decoder.engine"

    enc_inputs = [("image", shapes["encoder"]["image"])]
    dec_inputs = [
        ("z", shapes["decoder"]["z"]),
        ("skip0", shapes["decoder"]["skip0"]),
        ("skip1", shapes["decoder"]["skip1"]),
        ("skip2", shapes["decoder"]["skip2"]),
        ("skip3", shapes["decoder"]["skip3"]),
    ]

    build_trt_engine(
        trtexec_bin=trtexec_bin,
        trt_lib_dir=trt_lib_dir,
        onnx_path=encoder_onnx,
        engine_path=encoder_engine,
        io_shapes=enc_inputs,
        fp16=fp16,
        workspace_mib=workspace_mib,
        timing_cache_file=timing_cache_file,
    )
    build_trt_engine(
        trtexec_bin=trtexec_bin,
        trt_lib_dir=trt_lib_dir,
        onnx_path=decoder_onnx,
        engine_path=decoder_engine,
        io_shapes=dec_inputs,
        fp16=fp16,
        workspace_mib=workspace_mib,
        timing_cache_file=timing_cache_file,
    )
    print(f"[INFO] Built TensorRT engines in {bucket_dir}")


def build_trt_for_unet_bucket(
    trtexec_bin: str,
    trt_lib_dir: str,
    bucket_dir: Path,
    camera_meta: Dict[str, dict],
    fp16: bool,
    workspace_mib: int,
    timing_cache_file: str = "",
):
    built_engine_paths = set()
    for camera_name, meta in camera_meta.items():
        onnx_path_from_meta = meta.get("onnx", "")
        share_unet_engine = bool(meta.get("share_unet_engine", False))
        if onnx_path_from_meta:
            unet_onnx = Path(onnx_path_from_meta)
        elif share_unet_engine:
            unet_onnx = bucket_dir / "unet.onnx"
        else:
            unet_onnx = bucket_dir / f"unet_{camera_name}.onnx"
        if share_unet_engine or camera_name == "__shared__":
            unet_engine = bucket_dir / "unet.engine"
        else:
            unet_engine = bucket_dir / f"unet_{camera_name}.engine"
        if str(unet_engine) in built_engine_paths:
            meta["engine"] = str(unet_engine)
            continue
        build_trt_engine(
            trtexec_bin=trtexec_bin,
            trt_lib_dir=trt_lib_dir,
            onnx_path=unet_onnx,
            engine_path=unet_engine,
            io_shapes=[("latent", meta["latent"])],
            fp16=fp16,
            workspace_mib=workspace_mib,
            timing_cache_file=timing_cache_file,
        )
        built_engine_paths.add(str(unet_engine))
        meta["engine"] = str(unet_engine)
    print(f"[INFO] Built fixed-prompt UNet TensorRT engines in {bucket_dir}")


def build_existing_onnx_to_trt(
    output_dir: Path,
    buckets: Sequence[Bucket],
    bucket_camera_map: Dict[str, List[str]],
    export_unet: bool,
    trtexec_bin: str,
    trt_lib_dir: str,
    fp16: bool,
    workspace_mib: int,
    timing_cache_file: str = "",
    share_unet_engine: bool = False,
):
    for bucket in buckets:
        bucket_dir = output_dir / f"bucket_{bucket.tag}"
        shape_json = bucket_dir / "shapes.json"
        if not shape_json.exists():
            raise FileNotFoundError(f"shapes.json not found: {shape_json}")
        shapes = json.loads(shape_json.read_text())
        build_trt_for_bucket(
            trtexec_bin=trtexec_bin,
            trt_lib_dir=trt_lib_dir,
            bucket_dir=bucket_dir,
            shapes=shapes,
            fp16=fp16,
            workspace_mib=workspace_mib,
            timing_cache_file=timing_cache_file,
        )
        if export_unet:
            camera_meta = {}
            if share_unet_engine:
                unet_onnx = bucket_dir / "unet.onnx"
                if not unet_onnx.exists():
                    raise FileNotFoundError(f"UNet ONNX not found: {unet_onnx}")
                camera_meta["__shared__"] = {
                    "latent": [2, 4, bucket.height // 8, bucket.width // 8],
                    "onnx": str(unet_onnx),
                    "share_unet_engine": True,
                }
            else:
                for camera_name in camera_names_for_bucket(bucket, bucket_camera_map):
                    unet_onnx = bucket_dir / f"unet_{camera_name}.onnx"
                    if not unet_onnx.exists():
                        raise FileNotFoundError(f"UNet ONNX not found: {unet_onnx}")
                    camera_meta[camera_name] = {
                        "latent": [2, 4, bucket.height // 8, bucket.width // 8],
                        "onnx": str(unet_onnx),
                    }
            build_trt_for_unet_bucket(
                trtexec_bin=trtexec_bin,
                trt_lib_dir=trt_lib_dir,
                bucket_dir=bucket_dir,
                camera_meta=camera_meta,
                fp16=fp16,
                workspace_mib=workspace_mib,
                timing_cache_file=timing_cache_file,
            )


def main():
    parser = argparse.ArgumentParser(
        description="Merge Difix VAE LoRA, export ONNX, and build TensorRT engines for buckets."
    )
    parser.add_argument(
        "--pretrained_path",
        type=str,
        default="",
        help="Difix pretrained path (e.g. local difix_ref snapshot path).",
    )
    parser.add_argument(
        "--ckpt_path",
        type=str,
        required=True,
        help="Checkpoint dir/file that contains model.pkl and train_config.yaml.",
    )
    parser.add_argument("--opset", type=int, default=17, help="ONNX opset version.")
    parser.add_argument(
        "--export_dtype",
        type=str,
        choices=["auto", "fp16", "bf16"],
        default="fp16",
        help=(
            "ONNX export dtype. 'auto' follows train_config mixed_precision. "
            "Use fp16 for TensorRT 8.6.x compatibility."
        ),
    )
    parser.add_argument(
        "--trtexec_bin",
        type=str,
        default=DEFAULT_TRTEXEC_BIN,
        help="Path to trtexec binary.",
    )
    parser.add_argument(
        "--trt_lib_dir",
        type=str,
        default=DEFAULT_TRT_LIB_DIR,
        help="TensorRT lib directory used to populate LD_LIBRARY_PATH.",
    )
    parser.add_argument(
        "--workspace_mib",
        type=int,
        default=4096,
        help="TensorRT workspace size in MiB.",
    )
    parser.add_argument(
        "--no_fp16_engine",
        action="store_true",
        help="Disable fp16 flag when building TensorRT engine.",
    )
    parser.add_argument(
        "--skip_trt_build",
        action="store_true",
        help="Only export ONNX, do not build TensorRT engines.",
    )
    parser.add_argument(
        "--save_merged_vae",
        action="store_true",
        help="Save merged VAE weights to output_dir/vae_merged.",
    )
    parser.add_argument(
        "--export_unet",
        action="store_true",
        help=(
            "Also export fixed-prompt V=2 UNet ONNX/TRT using the fixed "
            "bucket-camera mapping."
        ),
    )
    parser.add_argument(
        "--only_trt_build",
        action="store_true",
        help="Skip model loading/export and convert existing ONNX files to TensorRT engines only.",
    )
    parser.add_argument(
        "--timing_cache_file",
        type=str,
        default="",
        help=(
            "Shared TensorRT timing cache file. "
            "If empty, defaults to ckpt_path/vae_onnx_trt/trt_timing_cache.cache."
        ),
    )
    parser.add_argument(
        "--disable_timing_cache",
        action="store_true",
        help="Disable TensorRT timing cache when building engines.",
    )
    args = parser.parse_args()

    ckpt_dir = Path(args.ckpt_path) if Path(args.ckpt_path).is_dir() else Path(args.ckpt_path).parent
    train_cfg_path = ckpt_dir / "train_config.yaml"
    if not train_cfg_path.exists():
        raise FileNotFoundError(f"train_config.yaml not found: {train_cfg_path}")
    train_cfg = load_train_config(str(train_cfg_path))
    if not isinstance(train_cfg, dict):
        raise ValueError(f"Invalid train_config.yaml: {train_cfg_path}")

    export_dtype = parse_export_dtype(args.export_dtype, train_cfg)
    buckets = build_buckets_from_train_config(train_cfg)
    bucket_camera_map = build_bucket_camera_map_from_train_config(train_cfg)
    output_dir = ckpt_dir / "vae_onnx_trt"
    output_dir.mkdir(parents=True, exist_ok=True)
    merge_lora = bool(train_cfg.get("compile_merge_lora", True))
    timestep = int(train_cfg.get("timestep", 199))
    use_ref_img = bool(train_cfg.get("use_ref_img", False))
    num_views = 2 if use_ref_img else 1
    overwrite_prompt = normalize_overwrite_prompt(train_cfg.get("overwrite_prompt", None))
    share_unet_engine = should_share_unet_engine(train_cfg)

    print(f"[INFO] output_dir={output_dir}")
    print(
        f"[INFO] export_params from train_config.yaml: "
        f"buckets={[b.tag for b in buckets]}, dtype={export_dtype}, "
        f"merge_lora={merge_lora}, num_views={num_views}, "
        f"share_unet_engine={share_unet_engine}"
    )
    if share_unet_engine:
        print(f"[INFO] overwrite_prompt detected, use shared UNet per bucket: {overwrite_prompt}")

    timing_cache_file = ""
    if not args.disable_timing_cache:
        timing_cache_file = args.timing_cache_file or str(output_dir / "trt_timing_cache.cache")
    print(f"[INFO] timing_cache_file={timing_cache_file or 'disabled'}")

    resolved_trtexec_bin = resolve_trtexec_bin(args.trtexec_bin)
    resolved_trt_lib_dir = resolve_trt_lib_dir(resolved_trtexec_bin, args.trt_lib_dir)
    print(f"[INFO] trtexec_bin={resolved_trtexec_bin}")
    print(f"[INFO] trt_lib_dir={resolved_trt_lib_dir}")

    if not args.skip_trt_build or args.only_trt_build:
        validate_trt_runtime(resolved_trt_lib_dir)

    if args.only_trt_build:
        build_existing_onnx_to_trt(
            output_dir=output_dir,
            buckets=buckets,
            bucket_camera_map=bucket_camera_map,
            export_unet=bool(args.export_unet),
            trtexec_bin=resolved_trtexec_bin,
            trt_lib_dir=resolved_trt_lib_dir,
            fp16=(not args.no_fp16_engine),
            workspace_mib=args.workspace_mib,
            timing_cache_file=timing_cache_file,
            share_unet_engine=share_unet_engine,
        )
        print(f"[DONE] TensorRT build finished from existing ONNX. Output dir: {output_dir}")
        return

    if not args.pretrained_path:
        raise ValueError("--pretrained_path is required unless --only_trt_build is set.")

    if (not args.skip_trt_build) and export_dtype == torch.bfloat16:
        raise ValueError(
            "Current TensorRT build path does not support BF16 ONNX export reliably. "
            "Please rerun with --export_dtype fp16, or export ONNX only via --skip_trt_build."
        )

    if args.export_unet and (not use_ref_img):
        print(
            "[WARN] train_config.yaml sets use_ref_img=False, but UNet TensorRT export "
            "is forced to V=2 with fixed prompt embeddings."
        )

    pipe, vae, unet = load_modules(
        pretrained_path=args.pretrained_path,
        ckpt_path=args.ckpt_path,
        dtype=export_dtype,
    )
    if merge_lora:
        merge_vae_lora_inplace(vae)
    else:
        print("[INFO] Skip VAE LoRA merge by train_config setting.")

    if args.save_merged_vae:
        merged_dir = output_dir / "vae_merged"
        vae.save_pretrained(str(merged_dir))
        print(f"[INFO] Saved merged VAE to {merged_dir}")

    all_meta = {
        "pretrained_path": args.pretrained_path,
        "ckpt_path": args.ckpt_path,
        "train_config_yaml": str(train_cfg_path),
        "dtype": str(export_dtype),
        "merge_lora": merge_lora,
        "timestep": timestep,
        "overwrite_prompt": overwrite_prompt if overwrite_prompt else None,
        "share_unet_engine": bool(share_unet_engine),
        "export_unet": bool(args.export_unet),
        "buckets": [],
    }
    for bucket in buckets:
        bucket_dir = output_dir / f"bucket_{bucket.tag}"
        encoder_onnx, decoder_onnx, shapes = export_onnx_for_bucket(
            vae=vae,
            bucket=bucket,
            output_dir=bucket_dir,
            opset=args.opset,
            num_views=num_views,
        )
        bucket_meta = {
            "bucket": {"width": bucket.width, "height": bucket.height},
            "encoder_onnx": str(encoder_onnx),
            "decoder_onnx": str(decoder_onnx),
            "shapes": shapes,
        }
        if not args.skip_trt_build:
            build_trt_for_bucket(
                trtexec_bin=resolved_trtexec_bin,
                trt_lib_dir=resolved_trt_lib_dir,
                bucket_dir=bucket_dir,
                shapes=shapes,
                fp16=(not args.no_fp16_engine),
                workspace_mib=args.workspace_mib,
                timing_cache_file=timing_cache_file,
            )
        if args.export_unet:
            bucket_camera_names = camera_names_for_bucket(bucket, bucket_camera_map)
            unet_meta = export_unet_onnx_for_bucket(
                pipe=pipe,
                unet=unet,
                bucket=bucket,
                output_dir=bucket_dir,
                opset=args.opset,
                timestep=timestep,
                camera_names=bucket_camera_names,
                overwrite_prompt=overwrite_prompt,
            )
            bucket_meta["unet_v2_fixed_prompt"] = {
                "camera_names": bucket_camera_names,
                "share_unet_engine": bool(share_unet_engine),
                "camera_exports": unet_meta,
            }
            if not args.skip_trt_build:
                build_trt_for_unet_bucket(
                    trtexec_bin=resolved_trtexec_bin,
                    trt_lib_dir=resolved_trt_lib_dir,
                    bucket_dir=bucket_dir,
                    camera_meta=unet_meta,
                    fp16=(not args.no_fp16_engine),
                    workspace_mib=args.workspace_mib,
                    timing_cache_file=timing_cache_file,
                )
        all_meta["buckets"].append(bucket_meta)

    (output_dir / "export_manifest.json").write_text(json.dumps(all_meta, indent=2))
    print(f"[DONE] Export finished. Manifest: {output_dir / 'export_manifest.json'}")


if __name__ == "__main__":
    main()

""" #######################
nohup python export_vae_onnx_trt.py --pretrained_path /workspace/group_share/adc-sim/users/led/ckpts/difix_ref --ckpt_path /workspace/yangxh7@xiaopeng.com/difix3D_train/train_v4_1w/v4_1w_1prompt/checkpoints_epoch_0060_step_480000 --export_unet > log.txt 2>&1 &
####################### """
