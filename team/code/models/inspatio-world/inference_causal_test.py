import argparse
import gc
import json
import os
import re
import time
from pathlib import Path

import torch
import torch.distributed as dist
from einops import rearrange
from omegaconf import OmegaConf
from safetensors.torch import load_file
from torch.utils.data import DataLoader, SequentialSampler
from torch.utils.data.distributed import DistributedSampler
from torchvision.io import write_video
from tqdm import tqdm

from demo_utils.memory import DynamicSwapInstaller, get_cuda_free_memory_gb, gpu
from pipeline import CausalInferencePipeline
from pipeline.causal_inference import denoise_block
from utils.misc import set_seed
from utils.render_warper import convert_mask_video
from custom_datasets.video_dataset import VideoDataset
from custom_datasets.train_dataset import DEFAULT_PROMPT


PROJECT_ROOT = Path(__file__).resolve().parent
# Shared prompt embeddings cache. All train/test data use a single prompt, so the
# T5 embeddings are encoded once and reused (generated on first run if missing).
PROMPT_EMBEDS_CACHE = PROJECT_ROOT / "data" / "prompt_embeds.pt"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Causal inference for InSpatio-World from a training run directory."
    )

    parser.add_argument("--run_dir", type=str, default="output/lora_run/debug",
                        help="Training run folder containing config_used.yaml and *.safetensors")
    parser.add_argument("--output_folder", type=str, default=None, help="Output folder")
    parser.add_argument("--seed", type=int, default=0, help="Random seed")

    # Reference temporal offset. NOTE: this is an explicit, deterministic
    # inference shift and is independent from training's
    # data.ref_time_shift_seconds, which is a *random* ±range augmentation.
    parser.add_argument("--ref_time_shift", type=float, default=0.0,
                        help="Deterministic temporal shift (seconds) applied to the reference/source "
                             "video at inference. Positive = ref sampled from later (future) frames "
                             "relative to the target; negative = earlier. 0 = time-aligned (default). "
                             "Independent of the training-time random augmentation.")
    # Limit how many metadata entries are rendered.
    parser.add_argument("--max_videos", type=int, default=0,
                        help="If >0, only render the first N entries from --metadata_json.")

    # Acceleration options
    parser.add_argument("--use_tae", action="store_true",
                        help="Use Tiny Auto Encoder (TAE) instead of WanVAE")
    parser.add_argument("--compile_dit", action="store_true",
                        help="Apply torch.compile to the DiT model")
    parser.add_argument("--metadata_json", type=str, default=None,
                        help="JSON list of {target_path, render_path, ref_path?} (same format as training data.metadata). "
                             "All videos are loaded into a single dataset; outputs go to <output_folder>/<scene>/<cam>/.")
    parser.add_argument("--no_finetune", action="store_true",
                        help="Do NOT load the fine-tuned weights from run_dir; run the base pretrained "
                             "model only. Output is tagged '<train_mode>_step0' (i.e. zero fine-tune steps).")
    parser.add_argument("--ckpt_step", type=int, default=-1,
                        help="Select the checkpoint saved at this exact optimizer step "
                             "(loads <run_dir>/*_step<N>.safetensors). -1 (default) = auto: "
                             "prefer *_final, else the largest step. Ignored when --no_finetune is set.")
    parser.add_argument("--no_ref", action="store_true",
                        help="Run WITHOUT a reference/source image: skip ref encoding and drop the ref "
                             "from the KV-cache context, while KEEPING the autoregressive previous-block "
                             "history. Generation is then driven by the chunk history + 3DGS render/mask "
                             "+ text prompt. Mirrors training's no_ref path; use with a model trained "
                             "with no_ref_prob>0.")
    return parser.parse_args()


def _resolve_run_dir(run_dir: str) -> str:
    raw = Path(run_dir).expanduser()

    candidates: list[Path] = [raw]
    if not raw.is_absolute():
        candidates.extend([
            Path.cwd() / raw,
            PROJECT_ROOT / raw,
            PROJECT_ROOT / "output" / raw,
            PROJECT_ROOT / "output" / "lora_run" / raw,
            PROJECT_ROOT / "output" / "partial_run" / raw,
            PROJECT_ROOT / "output" / "full_run" / raw,
        ])

        # For short aliases like "debug", scan output tree for matching run dirs.
        for cfg_path in PROJECT_ROOT.glob(f"output/**/{raw.name}/config_used.yaml"):
            candidates.append(cfg_path.parent)

    seen = set()
    for c in candidates:
        rc = c.resolve() if c.exists() else c
        key = str(rc)
        if key in seen:
            continue
        seen.add(key)
        if c.is_dir():
            return str(c.resolve())

    hint = (
        f"run_dir not found: {run_dir}. Try an absolute path, e.g. "
        f"{PROJECT_ROOT / 'output' / 'lora_run' / 'debug'}"
    )
    raise FileNotFoundError(hint)


def _find_run_config(run_dir: str) -> str:
    cfg_path = os.path.join(run_dir, "config_used.yaml")
    if os.path.exists(cfg_path):
        return cfg_path
    raise FileNotFoundError(
        f"config_used.yaml not found in run_dir: {run_dir}."
    )


def _param_suffix(args) -> str:
    """Build an output-filename suffix from the extra inference params that
    actually affect the generated result. Returns "" when all are at defaults.

    Included: --ref_time_shift (always), and non-default --use_tae/--no_ref/--seed.
    """
    parts = []
    # Always include ref_time_shift in output file names for traceability.
    parts.append(f"refshift{args.ref_time_shift:g}")
    if args.use_tae:
        parts.append("tae")
    if getattr(args, "no_ref", False):
        parts.append("noref")
    if args.seed:
        parts.append(f"seed{args.seed}")
    return "_".join(parts)


def _count_params_from_state_dict(state_dict) -> int:
    """Count parameters in a safetensors state dict."""
    return int(sum(v.numel() for v in state_dict.values()))


def _count_model_total_params(model) -> int:
    """Count total parameters of a torch model."""
    return int(sum(p.numel() for p in model.parameters()))


def _find_weights(run_dir: str, target_step=None):
    """Locate inference weights inside ``run_dir``.

    If ``target_step`` is given (>= 0), select ``*_step<target_step>.safetensors`` for
    that exact step and raise if it does not exist (listing the available steps).

    Otherwise pick automatically, with priority (no special-casing of "lora"):
      1. any ``*_final.safetensors``
      2. ``*_step<N>.safetensors`` with the largest N

    Returns ``(weights_path | None, tag | None)`` where ``tag`` is the file stem
    (e.g. ``lora_final`` or ``lora_step1500``) which encodes the training mode and
    the number of steps, used to build a descriptive output path.
    """
    def _step_num(p: Path) -> int:
        m = re.search(r"_step(\d+)", p.stem)
        return int(m.group(1)) if m else -1

    step_files = [p for p in Path(run_dir).glob("*_step*.safetensors") if _step_num(p) >= 0]

    # Explicit step selection.
    if target_step is not None and target_step >= 0:
        for p in step_files:
            if _step_num(p) == target_step:
                return str(p), p.stem
        available = sorted({_step_num(p) for p in step_files})
        raise FileNotFoundError(
            f"No checkpoint for step {target_step} in run_dir: {run_dir}. "
            f"Available steps: {available or 'none'}."
        )

    finals = sorted(Path(run_dir).glob("*_final.safetensors"))
    if finals:
        p = finals[0]
        return str(p), p.stem

    if step_files:
        p = max(step_files, key=_step_num)
        return str(p), p.stem

    return None, None


def load_runtime_configs(args):
    """Load runtime settings strictly from run_dir/config_used.yaml."""
    run_dir = _resolve_run_dir(args.run_dir)
    cfg_path = _find_run_config(run_dir)
    train_cfg = OmegaConf.load(cfg_path)

    pipeline_cfg = OmegaConf.select(train_cfg, "model.pipeline", default=None)
    if pipeline_cfg is None:
        raise ValueError(
            "config_used.yaml is missing model.pipeline. "
            "Please run inference with a newer training run output."
        )

    config = OmegaConf.create(pipeline_cfg)

    train_data_cfg = OmegaConf.select(train_cfg, "data", default=None)
    if train_data_cfg is None:
        raise ValueError("config_used.yaml is missing data section.")
    dataset_config = {
        "video_size": [int(train_data_cfg.height), int(train_data_cfg.width)],
        "min_num_frames": int(train_data_cfg.num_frames),
        "target_fps": int(OmegaConf.select(train_cfg, "data.target_fps", default=10)),
    }

    # Base checkpoint root is read from the run config, exactly like training
    # (model.checkpoint_path). No CLI override is needed.
    checkpoint_path = OmegaConf.select(train_cfg, "model.checkpoint_path", default=None)
    if checkpoint_path is None:
        raise ValueError("model.checkpoint_path missing in config_used.yaml.")

    output_folder = args.output_folder 

    target_step = getattr(args, "ckpt_step", -1)
    lora_path, ckpt_tag = _find_weights(run_dir, target_step=target_step)
    # run_tag encodes the run timestamp + mode (e.g. lora_20260616_153045);
    # ckpt_tag encodes mode + rounds (e.g. lora_step1500 / lora_final).
    run_tag = os.path.basename(os.path.normpath(run_dir))
    train_mode = OmegaConf.select(train_cfg, "train.mode", default=None)
    lora_rank = OmegaConf.select(train_cfg, "lora.rank", default=None)
    lora_alpha = OmegaConf.select(train_cfg, "lora.alpha", default=None)
    lora_target_modules = OmegaConf.select(train_cfg, "lora.target_modules", default=None)
 
    # --no_finetune: ignore the fine-tuned weights in run_dir and run the base
    # pretrained model only. Tag the output as zero fine-tune steps (*_step0).
    if getattr(args, "no_finetune", False):
        if lora_path:
            print(f"[runtime] --no_finetune set: skipping fine-tuned weights {lora_path}")
        lora_path = None
        ckpt_tag = f"{train_mode}_step0" if train_mode else "step0"
 
    if lora_path and (lora_rank is None or lora_target_modules is None):
        raise ValueError(
            "LoRA inference requires rank and target_modules. "
            "Please check lora fields in config_used.yaml."
        )

    return {
        "run_dir": run_dir,
        "run_config_path": cfg_path,
        "config": config,
        "dataset_config": dataset_config,
        "checkpoint_path": checkpoint_path,
        "output_folder": output_folder,
        "lora_path": lora_path,
        "ckpt_tag": ckpt_tag,
        "run_tag": run_tag,
        "train_mode": train_mode,
        "lora_rank": lora_rank,
        "lora_alpha": lora_alpha,
        "lora_target_modules": lora_target_modules,
    }


def _maybe_apply_lora(model, lora_path, target_modules, rank, alpha, rank_id):
    """Inject LoRA adapters and load weights when lora_path is provided."""
    if not lora_path:
        return model

    try:
        from peft import LoraConfig, inject_adapter_in_model
    except ImportError as exc:
        raise ImportError(
            "peft is required for LoRA inference. Please install peft first."
        ) from exc

    modules = [m.strip() for m in (target_modules or "").split(",") if m.strip()]
    if not modules:
        raise ValueError("LoRA target modules are empty. Please set --lora_target_modules or config lora.target_modules")

    lora_rank = int(rank)
    lora_alpha = int(alpha) if alpha is not None else lora_rank
    lora_cfg = LoraConfig(r=lora_rank, lora_alpha=lora_alpha, target_modules=modules)
    model = inject_adapter_in_model(lora_cfg, model)

    print(f"[Rank {rank_id}] Loading LoRA from {lora_path}")
    incompat = model.load_state_dict(load_file(lora_path), strict=False)
    print(f"[Rank {rank_id}] LoRA load: missing={len(incompat.missing_keys)}, unexpected={len(incompat.unexpected_keys)}")
    return model

def print_runtime_summary(args, runtime):
    print("[runtime] Resolved settings:")
    print(f"  run_dir={runtime['run_dir']}")
    print(f"  run_config={runtime['run_config_path']}")
    print(f"  checkpoint_path={runtime['checkpoint_path']}")
    print(f"  output_folder={runtime['output_folder']}")
    print(f"  weights={runtime['lora_path']}")
    print(f"  train_mode={runtime['train_mode']}  run_tag={runtime['run_tag']}  ckpt_tag={runtime['ckpt_tag']}")


def print_model_param_summary(runtime, model, rank):
    """Print trained-checkpoint params and full model params for this inference run."""
    trained_param_count = 0
    lora_path = runtime.get("lora_path")
    if lora_path:
        trained_state = load_file(lora_path)
        trained_param_count = _count_params_from_state_dict(trained_state)
    total_param_count = _count_model_total_params(model)

    print(
        f"[Rank {rank}] Model params: "
        f"trained_ckpt={trained_param_count:,} ({trained_param_count / 1e6:.3f}M), "
        f"total_model={total_param_count:,} ({total_param_count / 1e6:.3f}M)"
    )


def setup_distributed(seed):
    if "LOCAL_RANK" in os.environ:
        dist.init_process_group(backend='nccl')
        local_rank = int(os.environ["LOCAL_RANK"])
        torch.cuda.set_device(local_rank)
        device = torch.device(f"cuda:{local_rank}")
        world_size = dist.get_world_size()
        rank = dist.get_rank()
        set_seed(seed + local_rank)
    else:
        device = torch.device("cuda")
        local_rank = 0
        world_size = 1
        rank = 0
        set_seed(seed)

        # WanDiffusionWrapper expects torch.distributed to be initialized
        # (it calls dist.get_rank()/dist.barrier() internally).
        if not dist.is_initialized():
            backend = 'nccl' if torch.cuda.is_available() else 'gloo'
            os.environ.setdefault("MASTER_ADDR", "127.0.0.1")
            os.environ.setdefault("MASTER_PORT", "29556")
            dist.init_process_group(backend=backend, rank=0, world_size=1)
    return device, local_rank, world_size, rank


def setup_pipeline(args, runtime, config, device, rank, low_memory, skip_text_encoder):
    pipeline = CausalInferencePipeline(
        config,
        runtime["checkpoint_path"],
        device=device,
        skip_vae=args.use_tae,
        skip_text_encoder=skip_text_encoder,
    )

    checkpoint_name = "None"
    method_name = "default"
    inspatio_ckpt = os.path.join(runtime["checkpoint_path"], "InSpatio-World-1.3B/InSpatio-World-1.3B.safetensors")
    tae_ckpt = os.path.join(runtime["checkpoint_path"], "taehv/taew2_1.pth")

    print(f"[Rank {rank}] Loading checkpoint from {inspatio_ckpt}")
    state_dict = load_file(inspatio_ckpt)
    mismatch, missing = pipeline.generator.load_state_dict(state_dict, strict=False)
    print(f"[Rank {rank}] Mismatch: {mismatch}, Missing: {missing}")
    checkpoint_name = inspatio_ckpt.split("/")[-2]
    method_name = inspatio_ckpt.split("/")[-3]

    lora_path = runtime["lora_path"]
    if lora_path:
        pipeline.generator.model = _maybe_apply_lora(
            pipeline.generator.model,
            lora_path=lora_path,
            target_modules=runtime["lora_target_modules"],
            rank=runtime["lora_rank"],
            alpha=runtime["lora_alpha"],
            rank_id=rank,
        )
        checkpoint_name = Path(lora_path).stem
        method_name = "lora"

    pipeline = pipeline.to(dtype=torch.bfloat16)
    if not skip_text_encoder:
        if low_memory:
            DynamicSwapInstaller.install_model(pipeline.text_encoder, device=device)
        else:
            pipeline.text_encoder.to(device=device)
    pipeline.generator.to(device=device)

    return pipeline, checkpoint_name, method_name, tae_ckpt


def setup_vae_or_tae(args, pipeline, tae_ckpt, device, rank):
    tae_model = None
    if args.use_tae:
        from utils.taehv import TAEHV

        print(f"[Rank {rank}] Loading TAE from {tae_ckpt}...")
        tae_model = TAEHV(checkpoint_path=tae_ckpt).to(device, torch.float16)
        tae_model.eval()

        print(f"[Rank {rank}] Warming up TAE...")
        with torch.no_grad():
            dummy_enc = torch.randn(1, 9, 3, 480, 832, device=device, dtype=torch.float16)
            _ = tae_model.encode_video(dummy_enc, show_progress_bar=False)
            dummy_lat = torch.randn(1, 3, tae_model.latent_channels, 60, 104, device=device, dtype=torch.float16)
            _ = tae_model.decode_video(dummy_lat, show_progress_bar=False)
            del dummy_enc, dummy_lat
        torch.cuda.synchronize(device)
        print(f"[Rank {rank}] TAE warmup complete.")
    else:
        pipeline.vae.to(device=device)
    return tae_model


def maybe_compile_dit(args, pipeline, rank):
    if not args.compile_dit:
        return

    print(f"[Rank {rank}] Compiling DiT model with torch.compile (mode=max-autotune)...")
    import torch._inductor.config as inductor_config

    inductor_config.fx_graph_cache = True
    torch._dynamo.config.cache_size_limit = 32

    # Use /dev/shm (tmpfs) for inductor cache to avoid fcntl.flock issues
    # on certain filesystems where unlink + flock causes FileNotFoundError
    cache_dir = f"/dev/shm/torchinductor_cache_rank{rank}"
    os.makedirs(cache_dir, exist_ok=True)
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = cache_dir

    pipeline.generator.model = torch.compile(
        pipeline.generator.model,
        mode="max-autotune",
        fullgraph=False,
        dynamic=False,
        backend="inductor",
    )
    print(f"[Rank {rank}] DiT model compiled.")


def warmup_dit(args, pipeline, num_frame_per_block, device, rank):
    pipeline._initialize_kv_cache(batch_size=1, dtype=torch.bfloat16, device=device)

    def reset_kv_cache():
        for block_cache in pipeline.kv_cache1:
            block_cache['k'].detach_().zero_()
            block_cache['v'].detach_().zero_()

    print(f"[Rank {rank}] Warming up DiT...")
    t_warmup_start = time.time()

    with torch.no_grad():
        dummy_noise = torch.randn(1, num_frame_per_block, 16, 60, 104, device=device, dtype=torch.bfloat16)
        dummy_render = torch.randn(1, num_frame_per_block, 20, 60, 104, device=device, dtype=torch.bfloat16)
        dummy_cond = {"prompt_embeds": torch.randn(1, 512, 4096, device=device, dtype=torch.bfloat16)}

        if args.compile_dit:
            warmup_ctx_sizes = [num_frame_per_block, num_frame_per_block * 2]
            for wi, n_ctx in enumerate(warmup_ctx_sizes):
                kv_size = n_ctx * 1560
                dummy_ctx = torch.randn(1, n_ctx, 36, 60, 104, device=device, dtype=torch.bfloat16)
                print(f"[Rank {rank}]   Compile warmup pattern {wi + 1}/{len(warmup_ctx_sizes)} (kv_size={kv_size})...")
                t_pat = time.time()

                for _ in range(3):
                    reset_kv_cache()
                    denoise_block(
                        pipeline.generator, pipeline.scheduler, dummy_noise, dummy_cond,
                        pipeline.kv_cache1,
                        context_frames=dummy_ctx, context_no_grad=True, context_freqs_offset=0,
                        render_block=dummy_render, denoising_kv_size=kv_size,
                        denoising_steps=pipeline.denoising_step_list,
                    )

                torch.cuda.synchronize(device)
                print(f"[Rank {rank}]     Pattern {wi + 1} done ({time.time() - t_pat:.1f}s)")
                torch.cuda.empty_cache()
                gc.collect()
        else:
            dummy_ctx = torch.randn(1, num_frame_per_block * 2, 36, 60, 104, device=device, dtype=torch.bfloat16)
            reset_kv_cache()
            denoise_block(
                pipeline.generator, pipeline.scheduler, dummy_noise, dummy_cond,
                pipeline.kv_cache1,
                context_frames=dummy_ctx, context_no_grad=True, context_freqs_offset=0,
                render_block=dummy_render, denoising_kv_size=1560 * num_frame_per_block * 2,
                denoising_steps=pipeline.denoising_step_list,
            )
            torch.cuda.synchronize(device)
            reset_kv_cache()

    del dummy_noise, dummy_render, dummy_cond
    torch.cuda.empty_cache()
    gc.collect()
    print(f"[Rank {rank}] DiT warmup complete ({time.time() - t_warmup_start:.1f}s).")


def warmup_vae_if_needed(args, pipeline, device, rank):
    if args.use_tae:
        return

    print(f"[Rank {rank}] Warming up VAE...")
    with torch.no_grad():
        vae_mean = pipeline.vae.mean.to(device=device, dtype=torch.bfloat16)
        vae_inv_std = (1.0 / pipeline.vae.std).to(device=device, dtype=torch.bfloat16)
        scale = [vae_mean, vae_inv_std]
        dummy_enc = torch.randn(1, 3, 9, 480, 832, device=device, dtype=torch.bfloat16)
        _ = pipeline.vae.model.encode(dummy_enc, scale)
        pipeline.vae.model.clear_cache()
        dummy_dec = torch.randn(1, 16, 3, 60, 104, device=device, dtype=torch.bfloat16)
        _ = pipeline.vae.model.decode(dummy_dec, scale)
        pipeline.vae.model.clear_cache()
        del dummy_enc, dummy_dec
    torch.cuda.synchronize(device)
    print(f"[Rank {rank}] VAE warmup complete.")


def cleanup_distributed():
    if dist.is_initialized():
        dist.barrier()
        dist.destroy_process_group()


def load_or_build_prompt_embeds(pipeline, device, rank):
    """Return shared prompt embeddings [1, 512, 4096], cached at data/prompt_embeds.pt.

    All train/test data share a single prompt (DEFAULT_PROMPT), so the T5
    embeddings are encoded only once. On a cache hit the text encoder is never
    loaded; on a miss it is encoded here and saved (rank 0) for future runs.
    """
    if PROMPT_EMBEDS_CACHE.exists():
        print(f"[Rank {rank}] Loading cached prompt embeds: {PROMPT_EMBEDS_CACHE}")
        cached = torch.load(PROMPT_EMBEDS_CACHE, map_location="cpu", weights_only=True)
        return cached["prompt_embeds"].to(device=device, dtype=torch.bfloat16)

    assert pipeline.text_encoder is not None, (
        "Text encoder is required to build prompt embeds but was not loaded."
    )
    print(f"[Rank {rank}] Encoding DEFAULT_PROMPT -> {PROMPT_EMBEDS_CACHE}")
    prompt_embeds = pipeline.text_encoder(text_prompts=[DEFAULT_PROMPT])["prompt_embeds"]  # [1,512,4096]
    if rank == 0:
        PROMPT_EMBEDS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {"prompt_embeds": prompt_embeds.detach().cpu(), "prompt": DEFAULT_PROMPT},
            PROMPT_EMBEDS_CACHE,
        )
        print(f"[Rank {rank}] Saved prompt embeds: {PROMPT_EMBEDS_CACHE} "
              f"shape={tuple(prompt_embeds.shape)}")
    return prompt_embeds.to(device=device, dtype=torch.bfloat16)


def run_inference(args, runtime):
    print_runtime_summary(args, runtime)
    device, local_rank, world_size, rank = setup_distributed(args.seed)
    del local_rank

    print(f'[Rank {rank}] Free VRAM {get_cuda_free_memory_gb(gpu)} GB')
    low_memory = get_cuda_free_memory_gb(gpu) < 40

    torch.set_grad_enabled(False)

    config = runtime["config"]
    dataset_config = runtime["dataset_config"]
    args.output_folder = runtime["output_folder"]
    num_frame_per_block = getattr(config, "num_frame_per_block", 3)

    # Shared prompt embeds are cached under data/; load the text encoder only when
    # the cache must be (re)built.
    skip_text_encoder = PROMPT_EMBEDS_CACHE.exists()

    pipeline, checkpoint_name, method_name, tae_ckpt = setup_pipeline(
        args=args,
        runtime=runtime,
        config=config,
        device=device,
        rank=rank,
        low_memory=low_memory,
        skip_text_encoder=skip_text_encoder,
    )
    print_model_param_summary(runtime, pipeline.generator.model, rank)
    prompt_embeds = load_or_build_prompt_embeds(pipeline, device, rank)
    tae_model = setup_vae_or_tae(args, pipeline, tae_ckpt, device, rank)
    maybe_compile_dit(args, pipeline, rank)
    warmup_dit(args, pipeline, num_frame_per_block, device, rank)
    warmup_vae_if_needed(args, pipeline, device, rank)

    def tae_encode(video_bcthw: torch.Tensor) -> torch.Tensor:
        video = video_bcthw.permute(0, 2, 1, 3, 4)
        video = ((video * 0.5 + 0.5).clamp(0, 1)).to(torch.float16)
        latent = tae_model.encode_video(video, show_progress_bar=False)
        return latent.to(torch.bfloat16)

    def tae_decode(latent: torch.Tensor) -> torch.Tensor:
        video = tae_model.decode_video(latent.to(torch.float16), show_progress_bar=False)
        return video.float()

    def encode_video(video_bcthw: torch.Tensor) -> torch.Tensor:
        if args.use_tae:
            return tae_encode(video_bcthw)
        return pipeline.vae.encode_to_latent(video_bcthw).to(device, dtype=torch.bfloat16)

    def build_dataset():
        """Build a VideoDataset from --metadata_json (same format as training data.metadata)."""
        if not args.metadata_json:
            raise ValueError("Provide --metadata_json (JSON list of {target_path, render_path, ref_path?}).")
        return VideoDataset(
            args.metadata_json,
            video_size=dataset_config["video_size"],
            min_num_frames=dataset_config["min_num_frames"],
            target_fps=dataset_config["target_fps"],
            ref_time_shift_seconds=args.ref_time_shift,
            limit=(args.max_videos if args.max_videos and args.max_videos > 0 else None),
        )

    def sample_output_subdir(video_path: str) -> str:
        """Derive a unique, readable per-sample subdir: <scene>/<cam>."""
        scene = os.path.basename(os.path.dirname(video_path)) or "scene"
        stem = os.path.splitext(os.path.basename(video_path))[0]
        m = re.search(r"(cam\d+)", stem.lower())
        cam = m.group(1) if m else re.sub(r"_(gt|rgb)$", "", stem)
        return os.path.join(scene, cam)

    def run_dataset_inference(cam_dataset, output_root: str, prompt_embeds: torch.Tensor) -> None:
        # Order of keys matches the index assigned in VideoDataset.__getitem__.
        ordered_keys = list(cam_dataset.dataset.keys())
        print(f'[Rank {rank}] Dataset: {len(cam_dataset)} video(s); output root: {output_root}')

        if dist.is_initialized():
            cam_sampler = DistributedSampler(cam_dataset, shuffle=False, drop_last=False)
        else:
            cam_sampler = SequentialSampler(cam_dataset)
        cam_dataloader = DataLoader(cam_dataset, batch_size=1, sampler=cam_sampler,
                                    num_workers=0, drop_last=False)

        if dist.is_initialized():
            dist.barrier()

        for i, batch_data in tqdm(enumerate(cam_dataloader), total=len(cam_dataloader),
                                  disable=(rank != 0), desc="inference"):
            global_idx = i * world_size + rank if dist.is_initialized() else i
            print("global_idx ", global_idx)

            batch = batch_data if isinstance(batch_data, dict) else batch_data[0]

            # Resolve this sample's source video_path to build a unique output dir.
            sample_index = batch.get("index")
            if isinstance(sample_index, torch.Tensor):
                sample_index = int(sample_index.reshape(-1)[0].item())
            elif isinstance(sample_index, (list, tuple)):
                sample_index = int(sample_index[0])
            elif sample_index is not None:
                sample_index = int(sample_index)
            if sample_index is not None and 0 <= sample_index < len(ordered_keys):
                video_path = ordered_keys[sample_index]
            else:
                video_path = ordered_keys[global_idx % len(ordered_keys)]
            cam_output_folder = os.path.join(output_root, sample_output_subdir(video_path))
            print(f"[Rank {rank}] === Sample {global_idx}: {os.path.basename(video_path)} "
                  f"-> {cam_output_folder} ===")

            render_videos_ori = rearrange(batch["render_video"].to(device, dtype=torch.bfloat16), 'b t c h w -> b c t h w')
            mask_videos_ori = rearrange(batch["mask_video"].to(device, dtype=torch.bfloat16), 'b t c h w -> b c t h w')

            torch.cuda.synchronize(device)
            t_enc_start = time.time()

            render_latent = encode_video(render_videos_ori)
            mask_latent = convert_mask_video(mask_videos_ori)

            target_video = batch.get("target_video", batch["source_video"]).to(device=device, dtype=torch.bfloat16)
            target_video = rearrange(target_video, 'b t c h w -> b c t h w')
            latent = encode_video(target_video)

            ref_video = rearrange(batch["source_video"].to(device=device, dtype=torch.bfloat16), 'b t c h w -> b c t h w')
            if args.no_ref:
                ref_latent = None
                print("no_ref enabled: skipping reference encoding (chunk history is kept)")
            else:
                print("ref_video shape ", ref_video.shape)
                ref_latent = encode_video(ref_video)

            torch.cuda.synchronize(device)
            t_enc_end = time.time()
            print("vae encode time ", t_enc_end - t_enc_start)

            latent_length = latent.shape[1]
            num_output_frames = latent_length - (latent_length % config.num_frame_per_block)
            if num_output_frames == 0:
                num_output_frames = latent_length

            sampled_noise = torch.randn(
                [1, num_output_frames, 16, 60, 104], device=device, dtype=torch.bfloat16
            )
            render_latent = render_latent[:, :num_output_frames, ...].to(device=device, dtype=torch.bfloat16)
            mask_latent = mask_latent[:, :num_output_frames, ...].to(device=device, dtype=torch.bfloat16)

            torch.cuda.synchronize(device)
            t_dit_start = time.time()
            result = pipeline.inference(
                noise=sampled_noise,
                text_prompts=None,
                ref_latent=ref_latent,
                render_latent=render_latent,
                mask_latent=mask_latent,
                decode=not args.use_tae,
                prompt_embeds=prompt_embeds,
                use_ref=not args.no_ref,
            )
            torch.cuda.synchronize(device)
            t_dit_end = time.time()
            print("dit inference time ", t_dit_end - t_dit_start)

            torch.cuda.synchronize(device)
            t_dec_start = time.time()
            if args.use_tae:
                current_video = rearrange(tae_decode(result), 'b t c h w -> b t h w c').cpu()
            else:
                current_video = rearrange(result, 'b t c h w -> b t h w c').cpu()
            torch.cuda.synchronize(device)
            t_dec_end = time.time()
            print("vae decode time ", t_dec_end - t_dec_start)

            print(f"[Rank {rank}] Video {global_idx} timing: "
                  f"VAE Encode={t_enc_end - t_enc_start:.2f}s, "
                  f"DiT={'(+VAE Dec) ' if not args.use_tae else ''}{t_dit_end - t_dit_start:.2f}s, "
                  f"{'TAE' if args.use_tae else 'VAE'} Decode={t_dec_end - t_dec_start:.2f}s, "
                  f"Total={t_dec_end - t_enc_start:.2f}s")

            source_video = rearrange(target_video, 'b c t h w -> b t h w c').cpu()
            source_video = (source_video * 0.5 + 0.5).clamp(0, 1)
            render_video_vis = rearrange(render_videos_ori, 'b c t h w -> b t h w c').cpu()
            render_video_vis = (render_video_vis * 0.5 + 0.5).clamp(0, 1)

            pred_video = 255.0 * current_video
            source_video_out = 255.0 * source_video
            render_video_out = 255.0 * render_video_vis

            if not args.use_tae:
                pipeline.vae.model.clear_cache()

            # Output path reflects which run (timestamp + mode) and which
            # checkpoint (mode + rounds) produced this result.
            cam_out_dir = os.path.join(cam_output_folder, runtime["run_tag"], runtime["ckpt_tag"] or "base")
            os.makedirs(cam_out_dir, exist_ok=True)

            # Every frame was read at target_fps and kept (no subsampling), so the
            # clip plays back in real time at target_fps (10 by default).
            out_fps = float(dataset_config["target_fps"])
            _t = min(render_video_out.shape[1], source_video_out.shape[1], pred_video.shape[1])
            print(f"[Rank {rank}] writing {_t} frames @ {out_fps} fps -> {cam_out_dir}")
            combined = torch.cat([
                render_video_out[0, :_t],
                source_video_out[0, :_t],
                pred_video[0, :_t],
            ], dim=2)
            _suffix = _param_suffix(args)
            out_name = f"{global_idx}_combined_{_suffix}.mp4" if _suffix else f"{global_idx}_combined.mp4"
            write_video(
                os.path.join(cam_out_dir, out_name),
                combined,
                fps=out_fps,
                options={"crf": "0"},
            )

    dataset = build_dataset()
    run_dataset_inference(dataset, args.output_folder, prompt_embeds)

    cleanup_distributed()
    print(f"[Rank {rank}] Inference completed!")


def main():
    args = parse_args()
    runtime = load_runtime_configs(args)
    run_inference(args, runtime)


if __name__ == "__main__":
    main()
