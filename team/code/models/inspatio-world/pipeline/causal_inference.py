from typing import List, Optional
import torch
import time
import os
from contextlib import nullcontext
from einops import rearrange
from utils.wan_wrapper import WanDiffusionWrapper, WanTextEncoder, WanVAEWrapper
from utils.render_warper import convert_mask_video


def denoise_block(
    generator,
    scheduler,
    noisy_input,
    conditional_dict,
    kv_cache,
    *,
    context_frames=None,
    context_no_grad=True,
    context_freqs_offset=0,
    context_kv_size_0=0,
    render_block=None,
    denoising_kv_size=0,
    denoising_kv_size_0=0,
    denoising_steps=None,
    profile_timing: bool = False,
    profile_prefix: str = "",
):
    """
    Shared block-based diffusion core: optional context encoding pass + denoising.

    Returns (denoised_pred, noise_before_last_step).
    """
    B, F = noisy_input.shape[:2]
    device, dtype = noisy_input.device, noisy_input.dtype
    noise_before_last_step = None
    t_denoise_block_start = time.perf_counter() if profile_timing else None
    denoising_freqs_offset = context_frames.shape[1] if context_frames is not None else 0

    if context_frames is not None:
        if profile_timing:
            if torch.cuda.is_available():
                torch.cuda.synchronize(device)
            t_ctx_start = time.perf_counter()
        times_zero = torch.zeros([B, F], device=device, dtype=torch.int64)
        ctx = torch.no_grad() if context_no_grad else nullcontext()
        with ctx:
            generator(
                noisy_image_or_video=context_frames,
                conditional_dict=conditional_dict,
                timestep=times_zero,
                kv_cache=kv_cache,
                render_latent_input=render_block,
                kv_size=(context_kv_size_0, -1),
                freqs_offset=context_freqs_offset,
            )
        if profile_timing:
            if torch.cuda.is_available():
                torch.cuda.synchronize(device)
            t_ctx_end = time.perf_counter()
            ctx_shape = tuple(context_frames.shape)
            print(
                f"{profile_prefix}[denoise_block] context encode: "
                f"{t_ctx_end - t_ctx_start:.4f}s "
                f"(frames={F}, shape={ctx_shape}, kv_size=({context_kv_size_0}, -1))"
            )

    if profile_timing:
        step_times = []

    for index, current_timestep in enumerate(denoising_steps):
        is_last_step = (index == len(denoising_steps) - 1)
        timestep = torch.ones([B, F], device=device, dtype=torch.int64) * current_timestep

        if profile_timing:
            if torch.cuda.is_available():
                torch.cuda.synchronize(device)
            t_step_start = time.perf_counter()

        ctx = torch.no_grad() if not is_last_step else nullcontext()
        with ctx:
            _, denoised_pred = generator(
                noisy_image_or_video=noisy_input,
                conditional_dict=conditional_dict,
                timestep=timestep,
                kv_cache=kv_cache,
                kv_size=(denoising_kv_size_0, denoising_kv_size),
                render_latent_input=render_block,
                freqs_offset=denoising_freqs_offset,
            )

        if profile_timing:
            if torch.cuda.is_available():
                torch.cuda.synchronize(device)
            t_step_end = time.perf_counter()
            step_times.append(t_step_end - t_step_start)

        if is_last_step:
            noise_before_last_step = noisy_input.clone()
        else:
            if profile_timing:
                if torch.cuda.is_available():
                    torch.cuda.synchronize(device)
                t_renoise_start = time.perf_counter()
            next_t = denoising_steps[index + 1]
            noisy_input = scheduler.add_noise(
                denoised_pred.flatten(0, 1),
                torch.randn_like(denoised_pred.flatten(0, 1)),
                next_t * torch.ones([B * F], device=device, dtype=torch.long)
            ).unflatten(0, denoised_pred.shape[:2])
            if profile_timing:
                if torch.cuda.is_available():
                    torch.cuda.synchronize(device)
                t_renoise_end = time.perf_counter()
                print(
                    f"{profile_prefix}[denoise_block] scheduler re-noise "
                    f"step {index} ({int(current_timestep)} -> {int(next_t)}): "
                    f"{t_renoise_end - t_renoise_start:.4f}s"
                    f" (denoising_freqs_offset={denoising_freqs_offset})"
                )

    if profile_timing:
        if torch.cuda.is_available():
            torch.cuda.synchronize(device)
        t_denoise_block_end = time.perf_counter()
        steps_str = ", ".join(
            f"t{int(t)}={dt:.4f}s" for t, dt in zip(denoising_steps, step_times)
        )
        print(
            f"{profile_prefix}[denoise_block] denoise steps total: "
            f"{sum(step_times):.4f}s ({steps_str})"
        )
        print(
            f"{profile_prefix}[denoise_block] block total: "
            f"{t_denoise_block_end - t_denoise_block_start:.4f}s"
        )

    return denoised_pred, noise_before_last_step


class CausalInferencePipeline(torch.nn.Module):
    def __init__(
            self,
            args,
            ckpt,
            device,
            generator=None,
            text_encoder=None,
            vae=None,
            skip_vae=False,
            skip_text_encoder=False,
    ):
        super().__init__()
        # Step 1: Initialize all models 
        time_start = time.time() 
        self.generator = WanDiffusionWrapper(ckpt, **getattr(args, "generator", {}), is_causal=True)
        print(f"Time taken to initialize generator: {time.time() - time_start} seconds")

        time_start = time.time()
        wan_model_folder = os.path.join(ckpt, getattr(args, "wan_model_folder", None))
        if skip_text_encoder:
            self.text_encoder = None
            print("Skipping text encoder initialization (skip_text_encoder=True)")
        else:
            self.text_encoder = WanTextEncoder(model_folder=wan_model_folder) if text_encoder is None else text_encoder
            print(f"Time taken to initialize text encoder: {time.time() - time_start} seconds")

        if skip_vae:
            self.vae = None
            print("Skipping VAE initialization (skip_vae=True)")
        else:
            time_start = time.time()
            self.vae = WanVAEWrapper(model_folder=wan_model_folder) if vae is None else vae
            print(f"Time taken to initialize vae: {time.time() - time_start} seconds")

        # Step 2: Initialize all causal hyperparmeters
        self.scheduler = self.generator.get_scheduler()
        self.denoising_step_list = torch.tensor(
            args.denoising_step_list, dtype=torch.long)
        if args.warp_denoising_step:
            print("warping denoising step list")
            timesteps = torch.cat((self.scheduler.timesteps.cpu(), torch.tensor([0], dtype=torch.float32)))
            self.denoising_step_list = timesteps[1000 - self.denoising_step_list]

        # Get the underlying model (handle DDP wrapping)
        model = self.generator.model
        if hasattr(model, 'module'):
            model = model.module
        
        self.num_transformer_blocks = len(model.blocks)
        self._model = model  # Store for later use
        self.frame_seq_length = 1560

        self.kv_cache1 = None
        self.args = args
        self.num_frame_per_block = getattr(args, "num_frame_per_block", 1)

        print(f"KV inference with {self.num_frame_per_block} frames per block")

        if self.num_frame_per_block > 1:
            self._model.num_frame_per_block = self.num_frame_per_block
        
        self.max_num_context_frames = 6

    def inference(
        self,
        noise: torch.Tensor,
        text_prompts: Optional[List[str]] = None,
        ref_latent: Optional[torch.Tensor] = None,
        render_latent: Optional[torch.Tensor] = None,
        mask_latent: Optional[torch.Tensor] = None,
        decode: bool = True,
        prompt_embeds: Optional[torch.Tensor] = None,
        use_ref: bool = True,
    ) -> torch.Tensor:
        """
        Perform inference on the given noise and text prompts.
        Inputs:
            noise (torch.Tensor): The input noise tensor of shape
                (batch_size, num_output_frames, num_channels, height, width).
            text_prompts (List[str]): The list of text prompts. Ignored when
                prompt_embeds is provided.
            prompt_embeds (torch.Tensor): Pre-encoded prompt embeddings of shape
                [B, 512, 4096]. When provided, the text encoder is skipped entirely.
            decode (bool): If True (default), decode latents to pixel space via VAE.
                If False, return denoised latents directly (e.g. for external TAE decoder).
            use_ref (bool): If True (default), inject the reference/source view into the
                KV cache alongside the autoregressive history. If False - or if
                ``ref_latent`` is None - run in NO-REF mode: the ref part of the context is
                dropped but the previous block's prediction (the chunk history) is KEPT, so
                block 0 runs as pure self-attention while later blocks still attend to the
                previous block. The render + mask (channel-wise) and text prompt
                (cross-attn) still condition the generation. Mirrors training's no_ref path;
                use with a model trained with no_ref_prob>0.
        Outputs:
            video (torch.Tensor): The generated video tensor of shape
                (batch_size, num_output_frames, num_channels, height, width).
                When decode=True, normalized to [0, 1]. When decode=False, raw latents.
        """
        # No-ref mode is selected explicitly (use_ref=False) or implicitly (no ref given).
        use_ref_eff = use_ref and (ref_latent is not None)
        batch_size, num_frames, num_channels, height, width = noise.shape
        assert num_frames % self.num_frame_per_block == 0, f"num_frames {num_frames} is not a multiple of num_frame_per_block {self.num_frame_per_block}"
        num_blocks = num_frames // self.num_frame_per_block
        device = noise.device
        log_prefix = "[CausalInference.inference]"

        def _sync():
            if torch.cuda.is_available():
                torch.cuda.synchronize(device)

        t_inference_start = time.perf_counter()
        print(
            f"{log_prefix} start | "
            f"batch={batch_size}, frames={num_frames}, blocks={num_blocks}, "
            f"frames_per_block={self.num_frame_per_block}, latent=({num_channels},{height},{width}), "
            f"denoise_steps={list(self.denoising_step_list)}, decode={decode}, use_ref={use_ref_eff}"
        )

        num_output_frames = num_frames
        _sync()
        t_text_start = time.perf_counter()
        if prompt_embeds is not None:
            conditional_dict = {"prompt_embeds": prompt_embeds.to(device=device, dtype=noise.dtype)}
            print(f"{log_prefix} using cached prompt_embeds, skipping text encoder")
        else:
            conditional_dict = self.text_encoder(text_prompts=text_prompts)
        _sync()
        t_text_end = time.perf_counter()
        print(f"{log_prefix} text_encoder: {t_text_end - t_text_start:.4f}s")

        _sync()
        t_alloc_start = time.perf_counter()
        output = torch.zeros(
            [batch_size, num_output_frames, num_channels, height, width],
            device=noise.device,
            dtype=noise.dtype,
        )
        _sync()
        t_alloc_end = time.perf_counter()
        print(f"{log_prefix} output buffer alloc: {t_alloc_end - t_alloc_start:.4f}s")

        _sync()
        t_kv_start = time.perf_counter()
        if self.kv_cache1 is None:
            self._initialize_kv_cache(
                batch_size=batch_size,
                dtype=noise.dtype,
                device=noise.device,
            )
            kv_action = "init"
        else:
            for block_index in range(len(self.kv_cache1)):
                self.kv_cache1[block_index]["k"].detach_().zero_()
                self.kv_cache1[block_index]["v"].detach_().zero_()
            kv_action = "reset"
        _sync()
        t_kv_end = time.perf_counter()
        print(f"{log_prefix} kv_cache {kv_action}: {t_kv_end - t_kv_start:.4f}s")

        print(f"{log_prefix} generating {num_blocks} blocks...")
        t_sampling_start = time.perf_counter()
        all_num_frames = [self.num_frame_per_block] * num_blocks
        block_timings = []

        start_index = 0
        last_pred = None
        for block_idx, num_block_frame in enumerate(all_num_frames):
            block_prefix = f"{log_prefix} block {block_idx}/{num_blocks - 1}"
            t_block_start = time.perf_counter()

            _sync()
            t_slice_start = time.perf_counter()
            noisy_input = noise[:, start_index : start_index + num_block_frame].to(
                device=noise.device, dtype=noise.dtype
            )
            render_block = render_latent[:, start_index : start_index + num_block_frame].to(
                device=noise.device, dtype=noise.dtype
            )
            mask_block = mask_latent[:, start_index : start_index + num_block_frame].to(
                device=noise.device, dtype=noise.dtype
            )
            render_block = torch.cat([mask_block, render_block], dim=2)
            _sync()
            t_slice_end = time.perf_counter()

            _sync()
            t_ctx_prep_start = time.perf_counter()
            # Build the KV-cache context for this block, in temporal order:
            #   [ref view]            -> included when use_ref_eff
            #   [previous block pred] -> included for start_index > 0 (the chunk history)
            # NO-REF mode (use_ref=False) drops only the ref part and KEEPS the
            # autoregressive history, so block 0 becomes pure self-attention while later
            # blocks still attend to the previous block's prediction through the cache.
            context_parts = []
            ctx_modes = []
            if use_ref_eff:
                ref_block = ref_latent[:, start_index : start_index + num_block_frame].to(
                    device=noise.device, dtype=noise.dtype
                )
                zero_latents = torch.zeros_like(ref_block)
                ref_block = torch.cat([ref_block, zero_latents[:, :, :4], zero_latents], dim=2)
                context_parts.append(ref_block)
                ctx_modes.append("ref")
            if start_index > 0:
                zero_latents = torch.zeros_like(last_pred)
                last_pred_padded = torch.cat(
                    [last_pred, zero_latents[:, :, :4], zero_latents], dim=2
                )
                context_parts.append(last_pred_padded)
                ctx_modes.append("last_pred")

            if context_parts:
                context_frames = torch.cat(context_parts, dim=1) if len(context_parts) > 1 \
                    else context_parts[0]
                kv_size = 1560 * context_frames.shape[1]
                ctx_mode = "+".join(ctx_modes)
            else:
                # block 0 under no-ref: no preceding context -> pure self-attention.
                context_frames = None
                kv_size = 0
                ctx_mode = "self_only"
            _sync()
            t_ctx_prep_end = time.perf_counter()

            print(
                f"{block_prefix} prep | "
                f"slice={t_slice_end - t_slice_start:.4f}s, "
                f"context={t_ctx_prep_end - t_ctx_prep_start:.4f}s ({ctx_mode}), "
                f"kv_size={kv_size}, frame_range=[{start_index}:{start_index + num_block_frame})"
            )

            _sync()
            t_denoise_start = time.perf_counter()
            denoised_pred, _ = denoise_block(
                self.generator,
                self.scheduler,
                noisy_input,
                conditional_dict,
                self.kv_cache1,
                context_frames=context_frames,
                context_no_grad=True,
                context_freqs_offset=0,
                render_block=render_block,
                denoising_kv_size=kv_size,
                denoising_steps=self.denoising_step_list,
                profile_timing=True,
                profile_prefix=f"{block_prefix} ",
            )
            _sync()
            t_denoise_end = time.perf_counter()

            _sync()
            t_accum_start = time.perf_counter()
            output[:, start_index : start_index + num_block_frame] = denoised_pred
            last_pred = denoised_pred.clone().detach()
            _sync()
            t_accum_end = time.perf_counter()

            t_block_end = time.perf_counter()
            block_record = {
                "block": block_idx,
                "slice": t_slice_end - t_slice_start,
                "context_prep": t_ctx_prep_end - t_ctx_prep_start,
                "denoise_block": t_denoise_end - t_denoise_start,
                "accumulate": t_accum_end - t_accum_start,
                "total": t_block_end - t_block_start,
            }
            block_timings.append(block_record)
            print(
                f"{block_prefix} done | "
                f"denoise_block={block_record['denoise_block']:.4f}s, "
                f"accumulate={block_record['accumulate']:.4f}s, "
                f"block_total={block_record['total']:.4f}s"
            )

            start_index += num_block_frame

        _sync()
        t_sampling_end = time.perf_counter()
        total_block_time = sum(b["total"] for b in block_timings)
        total_denoise_time = sum(b["denoise_block"] for b in block_timings)
        print(
            f"{log_prefix} sampling loop: {t_sampling_end - t_sampling_start:.4f}s "
            f"(blocks={num_blocks}, sum_block_total={total_block_time:.4f}s, "
            f"sum_denoise_block={total_denoise_time:.4f}s)"
        )
        if block_timings:
            avg_block = total_block_time / len(block_timings)
            print(
                f"{log_prefix} per-block avg: total={avg_block:.4f}s, "
                f"denoise={total_denoise_time / len(block_timings):.4f}s"
            )

        if not decode:
            t_inference_end = time.perf_counter()
            print(
                f"{log_prefix} finished (latents only) | "
                f"wall_total={t_inference_end - t_inference_start:.4f}s"
            )
            return output

        _sync()
        t_decode_start = time.perf_counter()
        video = self.vae.decode_to_pixel(output, use_cache=False)
        _sync()
        t_decode_mid = time.perf_counter()
        video = (video * 0.5 + 0.5).clamp(0, 1)
        _sync()
        t_decode_end = time.perf_counter()
        print(
            f"{log_prefix} vae.decode_to_pixel: {t_decode_mid - t_decode_start:.4f}s, "
            f"postprocess clamp: {t_decode_end - t_decode_mid:.4f}s, "
            f"vae_total={t_decode_end - t_decode_start:.4f}s"
        )

        t_inference_end = time.perf_counter()
        print(
            f"{log_prefix} finished | wall_total={t_inference_end - t_inference_start:.4f}s | "
            f"breakdown: text={t_text_end - t_text_start:.4f}s, "
            f"kv={t_kv_end - t_kv_start:.4f}s, "
            f"sampling={t_sampling_end - t_sampling_start:.4f}s, "
            f"vae={t_decode_end - t_decode_start:.4f}s"
        )

        return video

    def _initialize_kv_cache(self, batch_size, dtype, device):
        """
        Initialize or reuse KV cache for the Wan model.
        Uses detach() + zero_() to safely reuse cache without gradient issues.
        Cache is allocated only once; subsequent calls only zero the existing tensors.
        """
        if self.kv_cache1 is not None and len(self.kv_cache1) == self.num_transformer_blocks \
                and self.kv_cache1[0]["k"].shape[0] == batch_size \
                and self.kv_cache1[0]["k"].dtype == dtype \
                and self.kv_cache1[0]["k"].device == device:
            for block_cache in self.kv_cache1:
                block_cache["k"].detach_().zero_()
                block_cache["v"].detach_().zero_()
            return

        kv_cache_size = 1560 * self.num_frame_per_block * 2  # ref + last_pred
        
        num_heads = self._model.config.num_heads
        dim = self._model.config.dim

        print(f"Initializing kv cache with size: {kv_cache_size}")
        self.kv_cache1 = []
        for _ in range(self.num_transformer_blocks):
            self.kv_cache1.append({
                "k": torch.zeros([batch_size, kv_cache_size, num_heads, dim // num_heads], dtype=dtype, device=device),
                "v": torch.zeros([batch_size, kv_cache_size, num_heads, dim // num_heads], dtype=dtype, device=device),
            })
