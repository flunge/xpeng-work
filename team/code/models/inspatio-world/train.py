"""LoRA fine-tuning for InSpatio-World-1.3B.

This script adapts the DiffSynth-Studio LoRA training recipe (flow-matching SFT
loss + PEFT LoRA on the DiT) to the InSpatio-World causal video diffusion model.

Unlike a plain text-to-video model, InSpatio-World is a *causal* video diffusion
model that generates a target (novel-view) video conditioned on:
  - a reference/source view (injected through the per-block KV cache),
  - a 3DGS render of the target trajectory + its coverage mask (channel-wise
    conditioning), and
  - a text prompt (cross attention).

Training therefore mirrors the block-wise causal inference loop, but with:
  - **teacher forcing**: the ground-truth latents of previous blocks are used as
    KV-cache context (instead of the model's own predictions), and
  - a **single random flow-matching timestep** per block (instead of the
    multi-step inference schedule).

Only LoRA adapters on the DiT are trained; the base DiT, VAE and text encoder
are frozen. Prompt embeddings are pre-computed once so the 11 GB text encoder is
not kept resident during training.

All training settings live in a YAML config (see configs/train_lora_1.3b.yaml).

Example (single GPU)::

    accelerate launch train.py --config configs/train_lora_1.3b.yaml

Individual fields can be overridden from the CLI using dotted keys::

    accelerate launch train.py --config configs/train_lora_1.3b.yaml \
        train.learning_rate=2e-4 lora.rank=16
"""

import argparse
import gc
import os
import time
from datetime import datetime, timedelta

import accelerate
import torch
import torch.distributed as dist
from accelerate.utils import gather_object
from einops import rearrange
from omegaconf import OmegaConf
from torch.utils.tensorboard import SummaryWriter
from peft import LoraConfig, inject_adapter_in_model
from safetensors.torch import load_file, save_file
from torch.utils.data import DataLoader

from custom_datasets.train_dataset import DEFAULT_PROMPT, TrainV2VDataset
from custom_datasets.cached_latent_dataset import CachedLatentV2VDataset
from pipeline import CausalInferencePipeline
from utils.misc import set_seed
from utils.render_warper import convert_mask_video


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
def load_config():
    """Load the training config from a YAML file with optional CLI overrides.

    Usage:
        train.py --config path/to/train.yaml [section.key=value ...]
    """
    parser = argparse.ArgumentParser(description="LoRA fine-tuning for InSpatio-World-1.3B")
    parser.add_argument("--config", type=str, required=True,
                        help="Path to the training YAML config (e.g. configs/train_lora_1.3b.yaml)")
    args, overrides = parser.parse_known_args()

    cfg = OmegaConf.load(args.config)
    if overrides:
        # Support dotted-key overrides such as train.learning_rate=2e-4.
        cfg = OmegaConf.merge(cfg, OmegaConf.from_dotlist(overrides))
    return cfg, args.config, overrides


def load_pipeline_config(cfg):
    """Load pipeline/model structure config from train config.

    Preferred: inline ``model.pipeline`` in the training YAML so one file
    controls all train-time parameters.
    Fallback: ``model.config_path`` for backward compatibility.
    """
    inline = OmegaConf.select(cfg, "model.pipeline", default=None)
    if inline is not None:
        return OmegaConf.create(inline)

    config_path = OmegaConf.select(cfg, "model.config_path", default=None)
    if not config_path:
        raise ValueError(
            "Missing pipeline config: set either model.pipeline (preferred) "
            "or model.config_path in your training YAML."
        )
    return OmegaConf.load(config_path)


def prepare_run_output(cfg, source_config_path, overrides, accelerator):
    """Create a per-run output folder and save effective config for reproducibility."""
    run_name = OmegaConf.select(cfg, "output.run_name", default=None)
    if not run_name:
        mode = str(OmegaConf.select(cfg, "train.mode", default="lora")).lower()
        run_name = f"{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    base_output = cfg.output.path
    cfg.output.path = os.path.join(base_output, run_name)

    if accelerator.is_main_process:
        os.makedirs(cfg.output.path, exist_ok=True)

        # Save the final, effective config used for this run.
        used_cfg_path = os.path.join(cfg.output.path, "config_used.yaml")
        with open(used_cfg_path, "w", encoding="utf-8") as f:
            f.write(OmegaConf.to_yaml(cfg))

        # Keep source and CLI overrides for traceability.
        with open(os.path.join(cfg.output.path, "config_source.txt"), "w", encoding="utf-8") as f:
            f.write(f"source_config: {source_config_path}\n")
            if overrides:
                f.write("overrides:\n")
                for item in overrides:
                    f.write(f"  - {item}\n")
            else:
                f.write("overrides: []\n")

    accelerator.wait_for_everyone()


# ---------------------------------------------------------------------------
# Conditioning helpers (kept identical to causal_inference for fidelity)
# ---------------------------------------------------------------------------
def pad_to_36ch(latent_block):
    """Pad a 16-channel latent block to the 36-channel context format.

    [B, F, 16, h, w] -> [B, F, 36, h, w]  (16 latent + 4 zeros + 16 zeros)
    """
    zeros = torch.zeros_like(latent_block)
    return torch.cat([latent_block, zeros[:, :, :4], zeros], dim=2)


@torch.no_grad()
def encode_videos(vae, videos_btchw, device, dtype):
    """VAE-encode a [B, T, C, H, W] pixel video in [-1, 1] to [B, T_lat, 16, h, w]."""
    v = rearrange(videos_btchw, "b t c h w -> b c t h w").to(device=device, dtype=dtype)
    return vae.encode_to_latent(v).to(device=device, dtype=dtype)


def snapshot_kv_cache(kv_cache, kv_size):
    """Clone the readable region of every layer's KV cache into a private copy.

    The block-wise training loop reuses a *single* shared KV cache: each block's
    context pass overwrites it in-place. The denoise pass runs with gradient
    checkpointing, so its forward is replayed during ``backward`` and reads the
    cache *again* at that point - by then the following blocks have already
    clobbered the shared tensors, so the recompute would attend to the wrong
    context and yield wrong gradients for every block except the last.

    Cloning the freshly written region (tokens ``[0:kv_size]``) into a per-block
    cache makes those values immutable for the block, keeping the forward and the
    checkpoint recompute consistent. The cached K/V are detached constants (the
    context pass runs under ``no_grad``), so cloning adds no autograd overhead.
    """
    return [
        {
            "k": layer["k"][:, :kv_size].clone(),
            "v": layer["v"][:, :kv_size].clone(),
        }
        for layer in kv_cache
    ]


# ---------------------------------------------------------------------------
# Prompt embedding cache (load text encoder once, then free it)
# ---------------------------------------------------------------------------
@torch.no_grad()
def build_prompt_embedding_cache(prompts, wan_model_folder, device):
    from utils.wan_wrapper import WanTextEncoder

    unique = sorted(set(prompts))
    print(f"[prompt-cache] encoding {len(unique)} unique prompt(s)...")
    text_encoder = WanTextEncoder(model_folder=wan_model_folder).to(device).eval()
    cache = {}
    for prompt in unique:
        out = text_encoder(text_prompts=[prompt])["prompt_embeds"]  # [1, 512, 4096]
        cache[prompt] = out[0].detach().to("cpu", torch.bfloat16).clone()
    del text_encoder
    gc.collect()
    torch.cuda.empty_cache()
    return cache


# ---------------------------------------------------------------------------
# LoRA setup
# ---------------------------------------------------------------------------
def add_lora(model, target_modules, rank, alpha, upcast):
    # Freeze every base parameter first.
    for param in model.parameters():
        param.requires_grad_(False)

    modules = [m.strip() for m in target_modules.split(",") if m.strip()]
    lora_config = LoraConfig(r=rank, lora_alpha=alpha or rank, target_modules=modules)
    model = inject_adapter_in_model(lora_config, model)

    # Make sure only the LoRA adapters are trainable.
    n_trainable = 0
    for name, param in model.named_parameters():
        is_lora = "lora_" in name
        param.requires_grad_(is_lora)
        if is_lora:
            if upcast:
                param.data = param.data.float()
            n_trainable += param.numel()
    print(f"[lora] injected into {modules}, trainable params: {n_trainable/1e6:.2f}M")
    return model


def setup_full(model, freeze_modules=None, upcast=True):
    """Full fine-tuning: every DiT parameter is trainable.

    ``freeze_modules`` optionally keeps a few submodules frozen (substring match
    on the parameter name), e.g. to hold the VAE-aligned patch embedding fixed.
    ``upcast`` keeps the trainable params as fp32 master weights so AdamW updates
    do not underflow under bf16 autocast (the base model runs in bf16).
    """
    freeze = [m.strip() for m in (freeze_modules or []) if m.strip()]
    n_trainable = 0
    for name, param in model.named_parameters():
        keep_frozen = any(f in name for f in freeze)
        param.requires_grad_(not keep_frozen)
        if not keep_frozen:
            if upcast:
                param.data = param.data.float()
            n_trainable += param.numel()
    print(f"[full] trainable params: {n_trainable/1e6:.2f}M "
          f"(frozen modules: {freeze or 'none'}, upcast_fp32={upcast})")
    return model


def setup_partial(model, trainable_modules, upcast=True):
    """Partial fine-tuning: only parameters whose name matches one of the given
    substrings are trainable (everything else frozen).

    ``upcast`` keeps the trainable params as fp32 master weights so AdamW updates
    do not underflow under bf16 autocast (the base model runs in bf16).
    """
    patterns = [m.strip() for m in trainable_modules if m.strip()]
    assert patterns, "train.trainable_modules must be non-empty for mode=partial"
    n_trainable = 0
    for name, param in model.named_parameters():
        is_trainable = any(p in name for p in patterns)
        param.requires_grad_(is_trainable)
        if is_trainable:
            if upcast:
                param.data = param.data.float()
            n_trainable += param.numel()
    assert n_trainable > 0, (
        f"No parameters matched trainable_modules={patterns}. "
        "Check the module names against the DiT state dict.")
    print(f"[partial] trainable modules {patterns}, "
          f"trainable params: {n_trainable/1e6:.2f}M (upcast_fp32={upcast})")
    return model


def setup_trainable(model, cfg):
    """Configure which parameters are trainable based on ``train.mode``.

    Returns ``(model, mode)`` where mode is one of ``lora|full|partial``.
    """
    mode = str(OmegaConf.select(cfg, "train.mode", default="lora")).lower()
    upcast = bool(OmegaConf.select(cfg, "train.upcast", default=True))
    if mode == "lora":
        model = add_lora(model, cfg.lora.target_modules,
                         cfg.lora.rank, cfg.lora.alpha, cfg.lora.upcast)
    elif mode == "full":
        freeze_modules = OmegaConf.select(cfg, "train.freeze_modules", default=None)
        if isinstance(freeze_modules, str):
            freeze_modules = [s for s in freeze_modules.split(",")]
        model = setup_full(model, freeze_modules, upcast=upcast)
    elif mode == "partial":
        trainable_modules = OmegaConf.select(cfg, "train.trainable_modules", default="")
        if isinstance(trainable_modules, str):
            trainable_modules = [s for s in trainable_modules.split(",")]
        model = setup_partial(model, trainable_modules, upcast=upcast)
    else:
        raise ValueError(f"Unknown train.mode={mode!r}; expected lora|full|partial")
    return model, mode


def trainable_state_dict(model, mode):
    """Collect the parameters that should be persisted for this training mode.

    - lora    -> only the injected LoRA adapters (``lora_*``).
    - full    -> every trainable parameter (the whole adapted DiT).
    - partial -> only the unfrozen submodules.
    """
    if mode == "lora":
        return {n: p.detach().cpu() for n, p in model.named_parameters() if "lora_" in n}
    return {n: p.detach().cpu() for n, p in model.named_parameters() if p.requires_grad}


def save_checkpoint(model, path, mode):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sd = {k: v.to(torch.float32).contiguous()
          for k, v in trainable_state_dict(model, mode).items()}
    save_file(sd, path)
    print(f"[save] {mode} -> {path} ({len(sd)} tensors)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    cfg, source_config_path, overrides = load_config()

    # Bind this process to its local GPU BEFORE constructing the Accelerator / any
    # distributed collective. accelerate only calls torch.cuda.set_device lazily (when
    # accelerator.device is first accessed), but the first collective here is the barrier
    # inside prepare_run_output() - which runs earlier. Without an explicit bind, that
    # barrier executes with an "unknown" current device, producing the
    #   "using GPU X ... is currently unknown" / "No device id is provided"
    # warnings and, on multi-node NCCL, a rank->GPU mis-mapping that aborts the job with
    # "remote process exited or there was a network error". Setting the device up front
    # from LOCAL_RANK makes the mapping explicit and deterministic.
    if torch.cuda.is_available():
        _local_rank = int(os.environ.get("LOCAL_RANK", 0))
        torch.cuda.set_device(_local_rank)

    # Initialize debug mode if enabled
    if OmegaConf.select(cfg, "debug.enabled", default=False):
        debug_cfg = cfg.debug
        cfg.train.max_steps = debug_cfg.num_steps
        cfg.train.num_epochs = 1
        cfg.data.repeat = 1
        cfg.output.path = os.path.join(cfg.output.path, debug_cfg.save_dir)
        is_debug = True
    else:
        is_debug = False

    # NCCL collective timeout. The default 10 min watchdog fires when ranks drift out of
    # lockstep across a non-collective phase (validation, video decode + VAE encode, or a
    # slow checkpoint save), aborting the whole job. Raise it so transient stragglers do
    # not kill training; the real fixes (sharded validation + save barriers) are below.
    ddp_timeout_minutes = int(OmegaConf.select(cfg, "train.ddp_timeout_minutes", default=30))
    accelerator = accelerate.Accelerator(
        gradient_accumulation_steps=cfg.train.gradient_accumulation_steps,
        kwargs_handlers=[
            accelerate.DistributedDataParallelKwargs(find_unused_parameters=False),
            accelerate.InitProcessGroupKwargs(timeout=timedelta(minutes=ddp_timeout_minutes)),
        ],
    )

    prepare_run_output(cfg, source_config_path, overrides, accelerator)

    device = accelerator.device
    set_seed(cfg.train.seed + accelerator.process_index)
    if accelerator.is_main_process:
        if is_debug:
            accelerator.print("[DEBUG MODE] Quick smoke test enabled")
        accelerator.print("[config]\n" + OmegaConf.to_yaml(cfg))

    # WanDiffusionWrapper relies on torch.distributed being initialised
    # (it calls dist.get_rank()/dist.barrier()). accelerate sets the env vars;
    # initialise a process group here if the launcher did not.
    if not dist.is_initialized():
        backend = "nccl" if torch.cuda.is_available() else "gloo"
        os.environ.setdefault("MASTER_ADDR", "127.0.0.1")
        os.environ.setdefault("MASTER_PORT", "29555")
        dist.init_process_group(
            backend=backend,
            rank=accelerator.process_index,
            world_size=accelerator.num_processes,
            timeout=timedelta(minutes=ddp_timeout_minutes),
        )

    # --- Config -----------------------------------------------------------
    config = load_pipeline_config(cfg)
    num_frame_per_block = int(getattr(config, "num_frame_per_block", 3))
    checkpoint_path = cfg.model.checkpoint_path
    wan_model_folder = os.path.join(checkpoint_path, config.wan_model_folder)

    # Optional pre-encoded latent cache (see scripts/precompute_latents.py). When on, the
    # dataset yields VAE latents directly and the VAE is never loaded (skip_vae below),
    # removing both video decode and online VAE encode from the per-step hot path - the
    # dominant source of per-rank step-time variance that drifts ranks out of lockstep.
    use_latent_cache = bool(OmegaConf.select(cfg, "data.use_latent_cache", default=False))
    if use_latent_cache:
        accelerator.print("[data] latent cache ON (VAE skipped)")

    # --- Pipeline (generator + frozen VAE; text encoder handled separately)
    pipeline = CausalInferencePipeline(
        config, checkpoint_path, device=device,
        skip_vae=use_latent_cache, skip_text_encoder=True,
    )

    inspatio_ckpt = cfg.model.inspatio_ckpt or os.path.join(
        checkpoint_path, "InSpatio-World-1.3B/InSpatio-World-1.3B.safetensors")
    accelerator.print(f"[load] InSpatio-World checkpoint: {inspatio_ckpt}")
    state_dict = load_file(inspatio_ckpt)
    missing, unexpected = pipeline.generator.load_state_dict(state_dict, strict=False)
    accelerator.print(f"[load] missing={len(missing)} unexpected={len(unexpected)}")
    del state_dict

    pipeline.generator.to(device=device, dtype=torch.bfloat16)
    if pipeline.vae is not None:
        pipeline.vae.to(device=device, dtype=torch.bfloat16)
    generator = pipeline.generator
    scheduler = generator.scheduler  # FlowMatchScheduler (training=True already set)

    # Trainable-fp32 mode requires autocast-enabled forward. If launcher uses
    # mixed_precision=no, bf16 activations will meet fp32 trainable weights and
    # fail inside Linear matmul.
    if str(accelerator.mixed_precision).lower() == "no":
        wants_fp32_trainable = bool(OmegaConf.select(cfg, "train.upcast", default=False)) \
            or bool(OmegaConf.select(cfg, "lora.upcast", default=False))
        if wants_fp32_trainable:
            raise RuntimeError(
                "train/lora upcast is enabled but accelerate mixed_precision=no. "
                "Use accelerate --mixed_precision bf16 (or fp16), or set upcast=false."
            )

    # --- Trainable parameters (lora | full | partial) --------------------
    generator.model, train_mode = setup_trainable(generator.model, cfg)

    # Hard guarantee: every trainable parameter stays in fp32.
    n_fp32_trainable = 0
    n_non_fp32_trainable = 0
    for param in generator.model.parameters():
        if not param.requires_grad:
            continue
        if param.dtype != torch.float32:
            param.data = param.data.float()
        if param.dtype == torch.float32:
            n_fp32_trainable += param.numel()
        else:
            n_non_fp32_trainable += param.numel()
    if n_non_fp32_trainable > 0:
        raise RuntimeError(
            f"Found non-fp32 trainable params after cast: {n_non_fp32_trainable}"
        )
    accelerator.print(
        f"[dtype] trainable params forced to fp32: {n_fp32_trainable/1e6:.2f}M"
    )

    # Backward-compatible resume: `lora.checkpoint` (lora) or `train.resume`.
    resume_ckpt = OmegaConf.select(cfg, "lora.checkpoint", default=None) \
        or OmegaConf.select(cfg, "train.resume", default=None)
    if resume_ckpt is not None:
        accelerator.print(f"[load] resuming {train_mode} weights from {resume_ckpt}")
        incompat = generator.model.load_state_dict(load_file(resume_ckpt), strict=False)
        accelerator.print(f"[load] resume missing={len(incompat.missing_keys)}")

    if cfg.train.gradient_checkpointing:
        generator.model._set_gradient_checkpointing(True)
    generator.model.train()

    # --- Dataset / prompt cache ------------------------------------------
    # When data.use_latent_cache is on, the train loader serves pre-encoded latents
    # (built offline by scripts/precompute_latents.py), skipping the per-step VAE encode
    # and the video decode entirely. Otherwise fall back to the on-the-fly pixel dataset.
    if use_latent_cache:
        cache_index = OmegaConf.select(cfg, "data.latent_cache_index", default=None)
        if not cache_index:
            raise ValueError(
                "data.use_latent_cache=true requires data.latent_cache_index "
                "(run scripts/precompute_latents.py first).")
        accelerator.print(f"[data] latent cache ON -> {cache_index}")
        dataset = CachedLatentV2VDataset(index_path=cache_index)
    else:
        dataset = TrainV2VDataset(
            metadata_path=cfg.data.metadata,
            base_path=cfg.data.base_path,
            video_size=(cfg.data.height, cfg.data.width),
            num_frames=cfg.data.num_frames,
            target_fps=cfg.data.target_fps,
            repeat=cfg.data.repeat,
            ref_time_shift_seconds=OmegaConf.select(cfg, "data.ref_time_shift_seconds", default=0.0),
            random_ref_shift=OmegaConf.select(cfg, "data.random_ref_shift", default=True),
        )

    # In debug mode, limit to num_samples for faster iteration
    if is_debug:
        num_samples = cfg.debug.num_samples
        dataset.metadata = dataset.metadata[:num_samples]
        if accelerator.is_main_process:
            accelerator.print(f"[DEBUG] Using first {num_samples} samples")

    # --- DataLoader performance knobs ------------------------------------
    # The overnight run was input-bound (timing showed data_wait up to ~59% of each
    # step), so make the loader pipeline configurable. persistent_workers keeps the
    # worker processes alive across epochs - important here because the dataset is
    # small (many short epochs), so without it the workers are torn down and respawned
    # every epoch, paying the cold-start cost dozens of times a night. prefetch_factor
    # lets each worker stage several batches ahead so the GPU is less likely to stall.
    _num_workers = int(OmegaConf.select(cfg, "data.num_workers", default=4))
    _persistent = bool(OmegaConf.select(cfg, "data.persistent_workers", default=True))
    _prefetch = int(OmegaConf.select(cfg, "data.prefetch_factor", default=4))

    def make_loader_kwargs(num_workers=None):
        """Build DataLoader kwargs, guarding options that require num_workers > 0.

        persistent_workers and prefetch_factor are only valid when num_workers > 0;
        passing them with num_workers=0 raises, so we drop them in that case.
        """
        nw = _num_workers if num_workers is None else num_workers
        kwargs = dict(num_workers=nw, pin_memory=True)
        if nw > 0:
            kwargs["persistent_workers"] = _persistent
            kwargs["prefetch_factor"] = _prefetch
        return kwargs

    accelerator.print(
        f"[data] num_workers={_num_workers} persistent_workers={_persistent} "
        f"prefetch_factor={_prefetch}")

    # --- Val split (done in code; no separate JSON needed) ---------------
    val_split = float(OmegaConf.select(cfg, "data.val_split", default=0.0))
    import random as _random
    rng = _random.Random(cfg.train.seed)
    all_meta = list(dataset.metadata)
    rng.shuffle(all_meta)
    n_val = max(1, round(len(all_meta) * val_split)) if val_split > 0 else 0
    val_meta   = all_meta[:n_val]
    train_meta = all_meta[n_val:]
    dataset.metadata = train_meta
    accelerator.print(f"[data] train={len(train_meta)} val={len(val_meta)} (val_split={val_split})")

    # Persist the val-split membership so every run is fully reproducible and the
    # held-out samples can be reviewed or reused offline.
    if accelerator.is_main_process and n_val > 0:
        import json as _json
        val_log_path = os.path.join(cfg.output.path, "val_split.json")
        with open(val_log_path, "w", encoding="utf-8") as _f:
            _json.dump(
                {"seed": cfg.train.seed, "val_split": val_split,
                 "n_val": n_val, "n_train": len(train_meta),
                 "val_metadata": val_meta},
                _f, indent=2, ensure_ascii=False,
            )
        accelerator.print(f"[data] val split saved -> {val_log_path}")

    # Build val datasets (no repeat, deterministic crops). We evaluate each val sample
    # under TWO fixed reference temporal shifts so we can plot two comparable curves:
    #   shift=0s -> ref view aligned with the target window (easiest case);
    #   shift=4s -> ref view taken 4s away from the target (tests robustness to a
    #               temporally distant reference).
    # Both use random_start=False and random_ref_shift=False, so per-sample losses are
    # reproducible across validation rounds (the only thing changing is the model).
    VAL_REF_SHIFTS_SECONDS = [0.0, 4.0]
    # tag -> dataset. The validation loop indexes these directly (sharded [rank::world]),
    # so no DataLoader is built here.
    val_datasets = {}
    if n_val > 0 and use_latent_cache:
        # Latent-cache mode: the held-out cache clips already have a frozen (random) crop
        # and ref shift, so the two-shift pixel protocol does not apply. Evaluate a single
        # cached val curve instead (logged under tag "cache").
        vds = CachedLatentV2VDataset(index_path=cfg.data.latent_cache_index)
        vds.metadata = val_meta
        val_datasets["cache"] = vds
    elif n_val > 0:
        for shift in VAL_REF_SHIFTS_SECONDS:
            vds = TrainV2VDataset(
                metadata_path=cfg.data.metadata,
                base_path=cfg.data.base_path,
                video_size=(cfg.data.height, cfg.data.width),
                num_frames=cfg.data.num_frames,
                target_fps=cfg.data.target_fps,
                repeat=1,
                random_start=False,
                ref_time_shift_seconds=shift,
                random_ref_shift=False,
            )
            vds.metadata = val_meta
            val_datasets[shift] = vds

    prompts = [e.get("text") or DEFAULT_PROMPT for e in dataset.metadata]
    if val_meta:
        # All val datasets share val_meta, so collect prompts once.
        prompts += [e.get("text") or DEFAULT_PROMPT for e in val_meta]
    prompt_cache = build_prompt_embedding_cache(prompts, wan_model_folder, device)

    train_batch_size = int(OmegaConf.select(cfg, "data.batch_size", default=1))
    accelerator.print(f"[data] train batch_size={train_batch_size}")
    dataloader = DataLoader(
        dataset, batch_size=train_batch_size, shuffle=True, drop_last=True,
        **make_loader_kwargs(),
    )

    # --- TensorBoard writer (main process only) --------------------------
    tb_writer = None
    if accelerator.is_main_process:
        tb_log_dir = os.path.join(cfg.output.path, "tensorboard")
        tb_writer = SummaryWriter(log_dir=tb_log_dir)
        accelerator.print(f"[tensorboard] logging to {tb_log_dir}")

    # --- Optimizer --------------------------------------------------------
    trainable = [p for p in generator.model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(
        trainable, lr=cfg.train.learning_rate, weight_decay=cfg.train.weight_decay)

    warmup_steps = cfg.train.warmup_steps

    def lr_lambda(step):
        if warmup_steps > 0 and step < warmup_steps:
            return step / max(1, warmup_steps)
        return 1.0
    lr_scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)

    generator.model, optimizer, dataloader, lr_scheduler = accelerator.prepare(
        generator.model, optimizer, dataloader, lr_scheduler)
    # NOTE: val datasets are intentionally NOT wrapped in a prepared DataLoader. The
    # validation loop indexes them directly and shards samples across ranks by index
    # ([rank::world]), so the val set is evaluated exactly once in aggregate (not once per
    # rank) while every rank still joins the same gather collective and stays in lockstep.

    # Compute step counts AFTER accelerator.prepare(): the dataloader is now sharded
    # across ranks, so len(dataloader) is the per-GPU batch count. With a
    # DistributedSampler each rank sees a disjoint 1/num_processes slice, so summed over
    # all ranks one epoch iterates every video exactly once. The real number of optimizer
    # steps per epoch is therefore len(dataloader) // grad_accum (NOT the unsharded
    # dataset size), and total_steps below counts true optimizer steps for the whole run.
    # One optimizer step consumes batch_size * num_processes * grad_accum videos.
    steps_per_epoch = len(dataloader) // cfg.train.gradient_accumulation_steps
    videos_per_step = train_batch_size * accelerator.num_processes \
        * cfg.train.gradient_accumulation_steps
    total_steps = steps_per_epoch * cfg.train.num_epochs
    if cfg.train.max_steps > 0:
        total_steps = min(total_steps, cfg.train.max_steps)
    accelerator.print(
        f"[train] steps/epoch={steps_per_epoch} total_steps={total_steps} "
        f"videos/step={videos_per_step} "
        f"(world_size={accelerator.num_processes}, batch_size={train_batch_size}, "
        f"grad_accum={cfg.train.gradient_accumulation_steps})")

    # --- Training loop ----------------------------------------------------
    accelerator.print(
        f"[train] steps={total_steps} epochs={cfg.train.num_epochs} "
        f"frames/block={num_frame_per_block} lr={cfg.train.learning_rate}")
    if is_debug:
        accelerator.print(f"[DEBUG] Smoke-test: {total_steps} steps × {cfg.debug.num_samples} sample(s) → {cfg.output.path}")
    
    # Per-block backward: back-propagate (and free) each block's graph as soon as
    # its loss is computed, instead of summing all blocks' losses and doing a single
    # backward. The blocks are independent given the detached teacher-forced context,
    # so this is numerically identical but keeps only ONE block's activations resident
    # (removes the ~num_blocks memory multiplier -> usually lets you disable
    # gradient_checkpointing for a big speed-up). Default on.
    per_block_backward = bool(OmegaConf.select(cfg, "train.per_block_backward", default=True))
    accelerator.print(f"[train] per_block_backward={per_block_backward}")

    # Fraction of clips trained WITHOUT the reference view (the ref is injected only
    # through the KV cache, so this drops just the ref part of the context while keeping
    # the previous-block history). Decided independently per clip below.
    no_ref_prob = float(OmegaConf.select(cfg, "train.no_ref_prob", default=0.0))
    no_ref_prob = min(max(no_ref_prob, 0.0), 1.0)
    accelerator.print(f"[train] no_ref_prob={no_ref_prob}")
    # Running count of clips trained without the ref (for logging the realised rate).
    n_no_ref_clips = 0
    n_train_clips = 0

    # Lightweight wall-time profiler: when on, compute_loss fills a per-section timing
    # dict and we also measure the DataLoader wait. Averages are printed every log_steps
    # so you can see which phase (data / vae / ctx fwd / denoise fwd / backward) dominates.
    profile_timing = bool(OmegaConf.select(cfg, "train.profile_timing", default=False))
    accelerator.print(f"[train] profile_timing={profile_timing}")
    prof_acc = {}          # section -> accumulated seconds since last print
    prof_data_wait = 0.0   # DataLoader fetch/wait seconds since last print
    prof_steps = 0         # micro-steps since last print

    def make_backward_fn():
        """Build a per-block backward callback that is DDP-correct.

        Only the final block's backward triggers gradient all-reduce; earlier blocks
        accumulate grads locally under ``no_sync``. (During grad-accumulation micro
        steps the outer ``accumulate`` context already wraps everything in no_sync, so
        nothing syncs until the real sync step - this stays correct in both cases.)
        """
        def _backward_fn(block_loss, block_idx, num_blocks):
            if block_idx < num_blocks - 1:
                with accelerator.no_sync(generator.model):
                    accelerator.backward(block_loss)
            else:
                accelerator.backward(block_loss)
        return _backward_fn

    # Validation cadence, decoupled from log_steps so we can validate far less often than
    # we log (validation is the main cross-rank straggler source). Falls back to log_steps.
    val_steps = int(OmegaConf.select(cfg, "output.val_steps", default=cfg.output.log_steps))
    accelerator.print(f"[train] val_steps={val_steps}")

    global_step = 0
    t0 = time.time()
    stop = False

    for epoch in range(cfg.train.num_epochs):
        if stop:
            break
        # Reshuffle the DistributedSampler each epoch so every rank sees a different
        # ordering/slice across epochs (without this the shuffle is frozen after epoch 0).
        if hasattr(dataloader, "set_epoch"):
            dataloader.set_epoch(epoch)
        _data_t0 = time.time() if profile_timing else None
        for batch in dataloader:
            if profile_timing:
                # Time spent waiting on the DataLoader (data prep / GPU-starvation).
                prof_data_wait += time.time() - _data_t0
            step_timing = {} if profile_timing else None
            with accelerator.accumulate(generator.model):
                # Per-clip random decision: drop the ref view for this clip with
                # probability no_ref_prob (training only; validation always uses the ref).
                no_ref = (no_ref_prob > 0.0
                          and torch.rand(1).item() < no_ref_prob)
                n_train_clips += 1
                if no_ref:
                    n_no_ref_clips += 1
                if per_block_backward:
                    loss = compute_loss(
                        pipeline, generator, scheduler, batch, prompt_cache,
                        num_frame_per_block, device, backward_fn=make_backward_fn(),
                        no_ref=no_ref, timing=step_timing,
                    )
                else:
                    loss = compute_loss(
                        pipeline, generator, scheduler, batch, prompt_cache,
                        num_frame_per_block, device, no_ref=no_ref,
                        timing=step_timing,
                    )
                    accelerator.backward(loss)
                if accelerator.sync_gradients:
                    accelerator.clip_grad_norm_(trainable, cfg.train.max_grad_norm)
                optimizer.step()
                lr_scheduler.step()
                optimizer.zero_grad(set_to_none=True)

            if profile_timing:
                for k, v in step_timing.items():
                    prof_acc[k] = prof_acc.get(k, 0.0) + v
                prof_steps += 1

            if accelerator.sync_gradients:
                global_step += 1
                if global_step % cfg.output.log_steps == 0:
                    g = accelerator.gather(loss.detach()).mean().item()
                    rate = global_step / max(1e-6, time.time() - t0)
                    videos_seen = global_step * videos_per_step
                    accelerator.print(
                        f"[step {global_step}/{total_steps}] epoch {epoch} "
                        f"videos={videos_seen} "
                        f"loss={g:.4f} lr={lr_scheduler.get_last_lr()[0]:.2e} "
                        f"({rate:.2f} it/s)")

                    # Timing breakdown: mean per micro-step seconds per section since the
                    # last print, sorted by cost, plus % of measured step time.
                    if profile_timing and prof_steps > 0:
                        n = prof_steps
                        parts = {"data_wait": prof_data_wait, **prof_acc}
                        measured = sum(parts.values())
                        ordered = sorted(parts.items(), key=lambda kv: kv[1], reverse=True)
                        brk = "  ".join(
                            f"{k}={v / n * 1000:.0f}ms({v / max(1e-9, measured) * 100:.0f}%)"
                            for k, v in ordered
                        )
                        accelerator.print(
                            f"[timing step {global_step}] avg/step over {n} steps: "
                            f"total={measured / n:.2f}s  {brk}")
                        if tb_writer is not None:
                            for k, v in parts.items():
                                tb_writer.add_scalar(f"timing/{k}_ms", v / n * 1000, global_step)
                        prof_acc = {}
                        prof_data_wait = 0.0
                        prof_steps = 0
                    if tb_writer is not None:
                        tb_writer.add_scalar("loss/train", g, global_step)
                        tb_writer.add_scalar("lr", lr_scheduler.get_last_lr()[0], global_step)
                        if no_ref_prob > 0.0:
                            realised = n_no_ref_clips / max(1, n_train_clips)
                            tb_writer.add_scalar("no_ref/realised_rate", realised, global_step)

                # Validation: sharded across ranks so the val set is evaluated ONCE in
                # aggregate (not once per rank), and every rank joins the same gather
                # collective so no rank drifts out of lockstep and trips the NCCL watchdog.
                # Runs on its own val_steps cadence (decoupled from log_steps).
                if val_datasets and global_step % val_steps == 0:
                    accelerator.wait_for_everyone()
                    generator.model.eval()
                    world = accelerator.num_processes
                    rank = accelerator.process_index
                    with torch.no_grad():
                        for shift, vds in val_datasets.items():
                            tag = (f"shift{shift:g}"
                                   if isinstance(shift, (int, float)) else str(shift))
                            # Each rank evaluates a strided slice [rank::world] of the val
                            # set; gather_object reassembles the full per-sample list on
                            # every rank (the gather doubles as the lockstep barrier).
                            local = []
                            for idx in range(rank, len(vds), world):
                                vl = compute_loss(
                                    pipeline, generator, scheduler,
                                    _collate_single(vds[idx]),
                                    prompt_cache, num_frame_per_block, device,
                                )
                                local.append((idx, float(vl.detach().item())))
                            gathered = gather_object(local)
                            if accelerator.is_main_process and tb_writer is not None:
                                # gather_object concatenates each rank's `local` list into
                                # one flat list of (idx, loss) tuples; just sort by idx.
                                flat = sorted(gathered, key=lambda x: x[0])
                                per_sample = [v for _, v in flat]
                                if per_sample:
                                    val_loss_mean = sum(per_sample) / len(per_sample)
                                    accelerator.print(
                                        f"[step {global_step}/{total_steps}] "
                                        f"val_loss[{tag}]={val_loss_mean:.4f}")
                                    tb_writer.add_scalar(
                                        f"loss/val_{tag}", val_loss_mean, global_step)
                                    for sidx, v in flat:
                                        tb_writer.add_scalar(
                                            f"val_sample{sidx}/{tag}", v, global_step)
                    generator.model.train()
                    accelerator.wait_for_everyone()
                if global_step % cfg.output.save_steps == 0:
                    # All ranks rendezvous around the (slow) checkpoint write so a straggler
                    # main process cannot blow the NCCL watchdog on the next all-reduce.
                    accelerator.wait_for_everyone()
                    if accelerator.is_main_process:
                        save_checkpoint(accelerator.unwrap_model(generator.model),
                                        os.path.join(cfg.output.path, f"{train_mode}_step{global_step}.safetensors"),
                                        train_mode)
                    accelerator.wait_for_everyone()
                if global_step >= total_steps:
                    stop = True
                    break

            if profile_timing:
                _data_t0 = time.time()

    accelerator.wait_for_everyone()
    if accelerator.is_main_process:
        save_checkpoint(accelerator.unwrap_model(generator.model),
                        os.path.join(cfg.output.path, f"{train_mode}_final.safetensors"),
                        train_mode)
    accelerator.print("[train] done.")
    if tb_writer is not None:
        tb_writer.close()
    if dist.is_initialized():
        dist.destroy_process_group()


def _collate_single(sample):
    """Add a batch dim to a single dataset item so it matches a DataLoader batch.

    The validation loop indexes datasets directly (to shard samples across ranks by
    index) instead of using a DataLoader, so we replicate the default collate: give each
    video/latent tensor a length-1 batch dim and wrap the prompt string in a list.
    """
    out = {}
    for k, v in sample.items():
        out[k] = [v] if k == "text" else v.unsqueeze(0)
    return out


def compute_loss(pipeline, generator, scheduler, batch, prompt_cache,
                 num_frame_per_block, device, backward_fn=None, no_ref=False,
                 timing=None):
    """Teacher-forced, block-wise flow-matching loss for one clip (batch_size=1).

    If ``backward_fn`` is given (training), each block's loss is back-propagated
    immediately via ``backward_fn(block_loss, block_idx, num_blocks)`` and its
    autograd graph is freed before the next block runs. Because the per-block losses
    are independent given the detached teacher-forced context, the summed gradient is
    identical to one backward over the mean loss - but only one block's activations are
    ever resident, removing the ~num_blocks activation-memory multiplier.

    If ``backward_fn`` is None (e.g. validation), losses are just accumulated and the
    mean is returned for the caller to handle.

    If ``no_ref`` is True, the reference/source view is dropped from this clip while the
    autoregressive history is kept. The KV-cache context for each block normally holds
    ``[ref view] + [previous block's GT latents]``; with ``no_ref`` only the ref part is
    removed. So block 0 (whose only context was the ref) runs as pure self-attention
    (``kv_size=(0, 0)``), and every later block still attends to the previous block's GT
    latents through the cache - just not to the ref. Because the previous block always sits
    immediately before the current one in RoPE position, the history->current geometry is
    identical with or without the ref, so a model can be trained on a mix of both. The
    render + mask (channel-wise) and text (cross-attn) conditioning are unchanged, and the
    ref VAE encode is skipped. Randomly enabling this for a fraction of clips weakens the
    model's reliance on the ref image while preserving temporal continuity across chunks.
    """
    dtype = torch.bfloat16

    # --- Optional timing instrumentation --------------------------------
    # When ``timing`` is a dict, accumulate per-section GPU+CPU wall time into it.
    # ``_tick`` synchronizes CUDA first so async kernels are fully accounted for
    # (cheap, but only paid when profiling is enabled).
    def _tick():
        if timing is not None and torch.cuda.is_available():
            torch.cuda.synchronize(device)
        return time.time()

    def _add(key, t_start):
        if timing is not None:
            timing[key] = timing.get(key, 0.0) + (_tick() - t_start)

    _t = _tick()
    # 1) Obtain latents for all streams.
    #
    # Two paths:
    #   (a) Latent-cache path: the dataset already returns VAE-encoded latents
    #       ("*_lat" keys), so the per-step VAE encode (which the overnight timing
    #       showed costing ~5-6s / up to 50% of each step) is skipped entirely. The
    #       cached latents are produced offline by scripts/precompute_latents.py using
    #       this exact same encode_videos / convert_mask_video code, so the numbers
    #       are identical to the on-the-fly path.
    #   (b) On-the-fly path (default): encode pixel videos with the frozen VAE.
    if "target_lat" in batch:
        target_lat = batch["target_lat"].to(device, dtype)   # [B,T,16,h,w]
        render_lat = batch["render_lat"].to(device, dtype)
        # The ref/source view is injected only through the KV cache; skip it under no_ref.
        ref_lat = None if no_ref else batch["source_lat"].to(device, dtype)
        mask_lat = batch["mask_lat"].to(device, dtype)        # [B,L',4,h,w]
    else:
        # Encode all streams to latents (frozen VAE, no grad).
        target_lat = encode_videos(pipeline.vae, batch["target_video"], device, dtype)  # [B,12,16,h,w]
        render_lat = encode_videos(pipeline.vae, batch["render_video"], device, dtype)
        # The ref/source view is injected only through the KV cache; skip encoding it when
        # this clip drops the ref (no_ref).
        ref_lat = None if no_ref else encode_videos(pipeline.vae, batch["source_video"], device, dtype)

        mask_pix = rearrange(batch["mask_video"].to(device, dtype), "b t c h w -> b c t h w")
        mask_lat = convert_mask_video(mask_pix).to(device, dtype)  # [B,L',4,h,w]
    _add("vae_encode", _t)

    # 2) Trim to a multiple of num_frame_per_block.
    lengths = [target_lat.shape[1], render_lat.shape[1], mask_lat.shape[1]]
    if ref_lat is not None:
        lengths.append(ref_lat.shape[1])
    L = min(lengths)
    L = L - (L % num_frame_per_block)
    assert L >= num_frame_per_block, f"too few latent frames ({L}); increase --num_frames"
    target_lat = target_lat[:, :L]
    render_lat = render_lat[:, :L]
    mask_lat = mask_lat[:, :L]
    if ref_lat is not None:
        ref_lat = ref_lat[:, :L]

    B = target_lat.shape[0]
    num_blocks = L // num_frame_per_block

    # 3) Prompt embeddings (cached).
    embeds = torch.stack([prompt_cache[t] for t in batch["text"]], dim=0).to(device, dtype)
    conditional_dict = {"prompt_embeds": embeds}

    # 4) (Re)initialise the KV cache for this clip. Still needed even for block 0 under
    #    no_ref: the self-attention asserts the cache object is non-None, but with
    #    kv_size=(0, 0) it is neither read nor written.
    pipeline._initialize_kv_cache(batch_size=B, dtype=dtype, device=device)
    kv_cache = pipeline.kv_cache1

    total_loss = 0.0
    last_gt_block = None
    F = num_frame_per_block

    for block_idx in range(num_blocks):
        s = block_idx * F
        x0 = target_lat[:, s:s + F]                       # [B,F,16,h,w] clean target
        render_block = torch.cat([mask_lat[:, s:s + F], render_lat[:, s:s + F]], dim=2)  # [B,F,20,h,w]

        # Build the KV-cache context for this block (teacher forcing with GT latents).
        # Two independently-included parts, in temporal order:
        #   [ref view]                 -> included unless no_ref
        #   [previous block's GT]      -> included for block_idx > 0 (the chunk history)
        # Dropping the ref only removes the earliest part; the previous block always stays
        # immediately before the current one, so the history->current RoPE geometry is the
        # same with or without ref.
        context_parts = []
        if not no_ref:
            context_parts.append(pad_to_36ch(ref_lat[:, s:s + F]))   # ref view: [B,F,36,h,w]
        if block_idx > 0:
            context_parts.append(pad_to_36ch(last_gt_block))         # prev chunk: [B,F,36,h,w]

        if not context_parts:
            # Only happens for block 0 under no_ref: no preceding context at all, so the
            # block attends to its own frames only (kv_size[1]==0 -> self-attention). The
            # render block still provides the channel-wise 3DGS conditioning.
            denoise_cache = kv_cache
            denoise_kv_size = (0, 0)
            denoise_freqs_offset = 0
        else:
            context_frames = torch.cat(context_parts, dim=1) if len(context_parts) > 1 \
                else context_parts[0]
            ctx_F = context_frames.shape[1]
            kv_size = 1560 * ctx_F

            # Context encoding pass: fills the shared KV cache (no grad).
            _t = _tick()
            with torch.no_grad():
                generator(
                    noisy_image_or_video=context_frames,
                    conditional_dict=conditional_dict,
                    timestep=torch.zeros([B, ctx_F], device=device, dtype=torch.int64),
                    kv_cache=kv_cache,
                    render_latent_input=render_block,
                    kv_size=(0, -1),
                    freqs_offset=0,
                )
            _add("ctx_forward", _t)

            # Freeze this block's context into a private cache. The shared cache is
            # overwritten in-place by the next block's context pass; with gradient
            # checkpointing the denoise forward is replayed during backward and would
            # otherwise read a *later* block's context, corrupting the gradients of
            # every block but the last. (kv_size == ctx_F * 1560 == written region.)
            _t = _tick()
            denoise_cache = snapshot_kv_cache(kv_cache, kv_size)
            denoise_kv_size = (0, kv_size)
            denoise_freqs_offset = ctx_F
            _add("snapshot", _t)

        # Sample one flow-matching timestep for this block.
        idx = torch.randint(0, len(scheduler.timesteps), (1,)).item()
        t_val = scheduler.timesteps[idx].to(device)
        timestep = torch.full([B, F], float(t_val), device=device, dtype=torch.float32)

        noise = torch.randn_like(x0)
        noisy = scheduler.add_noise(
            x0.flatten(0, 1), noise.flatten(0, 1), timestep.flatten(0, 1)
        ).unflatten(0, (B, F)).to(dtype)

        # Denoising pass (with grad): predicts the flow. Reads the private
        # per-block snapshot so the checkpoint recompute stays consistent.
        _t = _tick()
        flow_pred, _ = generator(
            noisy_image_or_video=noisy,
            conditional_dict=conditional_dict,
            timestep=timestep,
            kv_cache=denoise_cache,
            render_latent_input=render_block,
            kv_size=denoise_kv_size,
            freqs_offset=denoise_freqs_offset,
        )

        target = (noise - x0).to(torch.float32)
        weight = scheduler.training_weight(timestep)[0]
        block_loss = torch.nn.functional.mse_loss(flow_pred.float(), target) * weight
        _add("denoise_forward", _t)

        if backward_fn is not None:
            # Back-prop and free this block's graph now. Scale by 1/num_blocks so the
            # accumulated gradient matches backward over the mean loss.
            _t = _tick()
            backward_fn(block_loss / num_blocks, block_idx, num_blocks)
            _add("backward", _t)
            total_loss = total_loss + block_loss.detach()
        else:
            total_loss = total_loss + block_loss

        last_gt_block = x0.detach()

    return total_loss / num_blocks


if __name__ == "__main__":
    main()
