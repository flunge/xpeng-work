import os
import requests
import sys
import time
from typing import Dict, Iterable, List, Tuple, Union
from PIL import Image
from tqdm import tqdm
import torch
from torchvision.transforms import functional as F
from torchvision import transforms
from transformers import AutoTokenizer, CLIPTextModel
from diffusers import AutoencoderKL, DDPMScheduler
from peft import LoraConfig
p = "src/"
sys.path.append(p)
from einops import rearrange, repeat


def make_1step_sched():
    noise_scheduler_1step = DDPMScheduler.from_pretrained("stabilityai/sd-turbo", subfolder="scheduler")
    noise_scheduler_1step.set_timesteps(1, device="cuda")
    noise_scheduler_1step.alphas_cumprod = noise_scheduler_1step.alphas_cumprod.cuda()
    return noise_scheduler_1step


def my_vae_encoder_fwd(self, sample):
    sample = self.conv_in(sample)
    l_blocks = []
    # down
    for down_block in self.down_blocks:
        l_blocks.append(sample)
        sample = down_block(sample)
    # middle
    sample = self.mid_block(sample)
    sample = self.conv_norm_out(sample)
    sample = self.conv_act(sample)
    sample = self.conv_out(sample)
    self.current_down_blocks = l_blocks
    return sample


def my_vae_decoder_fwd(self, sample, latent_embeds=None):
    sample = self.conv_in(sample)
    upscale_dtype = next(iter(self.up_blocks.parameters())).dtype
    # middle
    sample = self.mid_block(sample, latent_embeds)
    sample = sample.to(upscale_dtype)
    if not self.ignore_skip:
        skip_convs = [self.skip_conv_1, self.skip_conv_2, self.skip_conv_3, self.skip_conv_4]
        # up
        for idx, up_block in enumerate(self.up_blocks):
            skip_in = skip_convs[idx](self.incoming_skip_acts[::-1][idx] * self.gamma)
            # add skip
            sample = sample + skip_in
            sample = up_block(sample, latent_embeds)
    else:
        for idx, up_block in enumerate(self.up_blocks):
            sample = up_block(sample, latent_embeds)
    # post-process
    if latent_embeds is None:
        sample = self.conv_norm_out(sample)
    else:
        sample = self.conv_norm_out(sample, latent_embeds)
    sample = self.conv_act(sample)
    sample = self.conv_out(sample)
    return sample


def download_url(url, outf):
    if not os.path.exists(outf):
        print(f"Downloading checkpoint to {outf}")
        response = requests.get(url, stream=True)
        total_size_in_bytes = int(response.headers.get('content-length', 0))
        block_size = 1024  # 1 Kibibyte
        progress_bar = tqdm(total=total_size_in_bytes, unit='iB', unit_scale=True)
        with open(outf, 'wb') as file:
            for data in response.iter_content(block_size):
                progress_bar.update(len(data))
                file.write(data)
        progress_bar.close()
        if total_size_in_bytes != 0 and progress_bar.n != total_size_in_bytes:
            print("ERROR, something went wrong")
        print(f"Downloaded successfully to {outf}")
    else:
        print(f"Skipping download, {outf} already exists")


def load_ckpt_from_state_dict(net_difix, pretrained_path, optimizer=None):
    sd = torch.load(pretrained_path, map_location="cpu")
    
    if "state_dict_vae" in sd:
        _sd_vae = net_difix.vae.state_dict()
        for k in sd["state_dict_vae"]:
            _sd_vae[k] = sd["state_dict_vae"][k]
        net_difix.vae.load_state_dict(_sd_vae)
    _sd_unet = net_difix.unet.state_dict()
    for k in sd["state_dict_unet"]:
        _sd_unet[k] = sd["state_dict_unet"][k]
    net_difix.unet.load_state_dict(_sd_unet)
        
    if optimizer is not None and "optimizer" in sd:
        optimizer.load_state_dict(sd["optimizer"])
    
    # resume_info: epoch / global_step / lr_scheduler_state 供 train 继承
    resume_info = {}
    if "epoch" in sd:
        resume_info["epoch"] = sd["epoch"]
    if "global_step" in sd:
        resume_info["global_step"] = sd["global_step"]
    if "lr_scheduler_state" in sd:
        resume_info["lr_scheduler_state"] = sd["lr_scheduler_state"]
    
    return net_difix, optimizer, resume_info


def save_ckpt(net_difix, optimizer, outf, for_inference=False, epoch=None, global_step=None, lr_scheduler=None):
    sd = {}
    sd["vae_lora_target_modules"] = net_difix.target_modules_vae
    sd["rank_vae"] = net_difix.lora_rank_vae
    sd["state_dict_unet"] = net_difix.unet.state_dict()
    sd["state_dict_vae"] = {k: v for k, v in net_difix.vae.state_dict().items() if "lora" in k or "skip" in k}
    
    if not for_inference:
        sd["optimizer"] = optimizer.state_dict()
    # 始终保存 epoch/global_step/lr_scheduler，便于 resume 继承
    if epoch is not None:
        sd["epoch"] = epoch
    if global_step is not None:
        sd["global_step"] = global_step
    if lr_scheduler is not None:
        sd["lr_scheduler_state"] = lr_scheduler.state_dict()

    torch.save(sd, outf)
    

class Difix(torch.nn.Module):
    def __init__(self, pipe=None, pretrained_path=None, lora_rank_vae=4, mv_unet=False, timestep=999):
        super().__init__()
        self.lora_rank_vae = lora_rank_vae
        self.timesteps = torch.tensor([timestep], device="cuda").long()
        self.target_part_vae = ["conv1", "conv2", "conv_in", "conv_shortcut", "conv", "conv_out",
            "skip_conv_1", "skip_conv_2", "skip_conv_3", "skip_conv_4",
            "to_k", "to_q", "to_v", "to_out.0",
        ]
        
        if pipe is not None:
            self.setup_model_from_pretrained(pipe)
        else:
            self.setup_model_from_scratch(pretrained_path, mv_unet)

        self.vae.decoder.gamma = 1
        self._text_embed_cache: Dict[Tuple[str, Union[str, Tuple[int, ...]]], torch.Tensor] = {}
        self._inference_vae_optimized = False
        self._inference_vae_compiled = False
        self._inference_unet_compiled = False
        self._inference_vae_compile_disabled = False
        self._vae_encoder_eager = self.vae.encoder
        self._vae_decoder_eager = self.vae.decoder
        self._unet_eager = self.unet
        # 7 个固定 camera prompt 预缓存；同时缓存 prompt 字符串与 token key。
        self.prime_camera_prompt_cache(["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"])

    @staticmethod
    def _prompt_key(prompt: str) -> Tuple[str, str]:
        return ("prompt", prompt)

    @staticmethod
    def _token_key(token_row: torch.Tensor) -> Tuple[str, Tuple[int, ...]]:
        token_row = token_row.detach().reshape(-1).to("cpu")
        return ("tokens", tuple(int(x) for x in token_row.tolist()))

    def prime_camera_prompt_cache(self, camera_names: Iterable[str]):
        prompts = [
            f"Corrected rendering distortion for {str(cam).upper()} camera view."
            for cam in camera_names
        ]
        if len(prompts) == 0:
            return
        with torch.no_grad():
            tokens = self.tokenizer(
                prompts,
                max_length=self.tokenizer.model_max_length,
                padding="max_length",
                truncation=True,
                return_tensors="pt",
            ).input_ids.to(next(self.text_encoder.parameters()).device)
            embeds = self.text_encoder(tokens)[0]
        for idx, prompt in enumerate(prompts):
            emb = embeds[idx:idx + 1].detach()
            self._text_embed_cache[self._prompt_key(prompt)] = emb
            self._text_embed_cache[self._token_key(tokens[idx])] = emb

    def _encode_text_cached(self, prompt=None, prompt_tokens=None):
        assert (prompt is None) != (prompt_tokens is None), "Either prompt or prompt_tokens should be provided"
        text_device = next(self.text_encoder.parameters()).device
        cached_embeds: List[torch.Tensor] = []
        missing_indices: List[int] = []
        missing_keys: List[Tuple[str, Union[str, Tuple[int, ...]]]] = []
        missing_payload: List[Union[str, torch.Tensor]] = []

        if prompt is not None:
            prompts = [prompt] if isinstance(prompt, str) else list(prompt)
            for idx, p in enumerate(prompts):
                key = self._prompt_key(p)
                cached = self._text_embed_cache.get(key)
                if cached is None:
                    missing_indices.append(idx)
                    missing_keys.append(key)
                    missing_payload.append(p)
                    cached_embeds.append(None)
                else:
                    cached_embeds.append(cached)
            if missing_payload:
                with torch.no_grad():
                    miss_tokens = self.tokenizer(
                        missing_payload,
                        max_length=self.tokenizer.model_max_length,
                        padding="max_length",
                        truncation=True,
                        return_tensors="pt",
                    ).input_ids.to(text_device)
                    miss_embeds = self.text_encoder(miss_tokens)[0]
                for local_i, global_i in enumerate(missing_indices):
                    emb = miss_embeds[local_i:local_i + 1].detach()
                    cached_embeds[global_i] = emb
                    self._text_embed_cache[missing_keys[local_i]] = emb
                    self._text_embed_cache[self._token_key(miss_tokens[local_i])] = emb
        else:
            while prompt_tokens.dim() > 2 and prompt_tokens.shape[1] == 1:
                prompt_tokens = prompt_tokens.squeeze(1)
            if prompt_tokens.dim() == 1:
                prompt_tokens = prompt_tokens.unsqueeze(0)
            if prompt_tokens.dim() != 2:
                raise ValueError(
                    f"Expected prompt_tokens to have shape [B, L] after normalization, got {tuple(prompt_tokens.shape)}"
                )
            prompt_tokens = prompt_tokens.to(text_device)
            for idx in range(prompt_tokens.shape[0]):
                row = prompt_tokens[idx]
                key = self._token_key(row)
                cached = self._text_embed_cache.get(key)
                if cached is None:
                    missing_indices.append(idx)
                    missing_keys.append(key)
                    missing_payload.append(row.unsqueeze(0))
                    cached_embeds.append(None)
                else:
                    cached_embeds.append(cached)
            if missing_payload:
                miss_tokens = torch.cat(missing_payload, dim=0).to(text_device)
                with torch.no_grad():
                    miss_embeds = self.text_encoder(miss_tokens)[0]
                for local_i, global_i in enumerate(missing_indices):
                    emb = miss_embeds[local_i:local_i + 1].detach()
                    cached_embeds[global_i] = emb
                    self._text_embed_cache[missing_keys[local_i]] = emb

        return torch.cat(cached_embeds, dim=0)

    def prepare_inference_optimizations(self, compile_cache_dir=None):
        if self._inference_vae_optimized:
            return
        if compile_cache_dir:
            os.environ["TORCHINDUCTOR_CACHE_DIR"] = compile_cache_dir
            print(f"[INFO] Set TORCHINDUCTOR_CACHE_DIR to: {compile_cache_dir}", flush=True)
        self.vae.to(memory_format=torch.channels_last)
        if hasattr(torch, "compile") and (not self._inference_vae_compile_disabled):
            try:
                self.vae.encoder = torch.compile(self._vae_encoder_eager, mode="max-autotune-no-cudagraphs")
                self.vae.decoder = torch.compile(self._vae_decoder_eager, mode="max-autotune-no-cudagraphs")
                self._inference_vae_compiled = True
                self.unet = torch.compile(self._unet_eager, mode="max-autotune-no-cudagraphs")
                self._inference_unet_compiled = True
            except Exception as e:
                print(f"[WARN] Inference torch.compile failed, fallback to eager mode: {e}")
                self._inference_vae_compiled = False
                self._inference_unet_compiled = False
        self._inference_vae_optimized = True

    def _disable_vae_compile_for_inference(self, reason=""):
        if not self._inference_vae_compiled:
            self._inference_vae_compile_disabled = True
            return
        self.vae.encoder = self._vae_encoder_eager
        self.vae.decoder = self._vae_decoder_eager
        self.unet = self._unet_eager
        self._inference_vae_compiled = False
        self._inference_unet_compiled = False
        self._inference_vae_compile_disabled = True
        if reason:
            print(f"[WARN] Disable VAE torch.compile due to runtime issue: {reason}")
        
    def setup_model_from_pretrained(self, pipe):
        self.vae = pipe.vae.to("cuda")
        self.unet = pipe.unet.to("cuda")
        self.tokenizer = pipe.tokenizer
        self.text_encoder = pipe.text_encoder.to("cuda")
        self.sched = pipe.scheduler
        self.sched.set_timesteps(1, device="cuda")
        self.sched.alphas_cumprod = self.sched.alphas_cumprod.cuda()
        
        target_modules = []
        for id, (name, param) in enumerate(self.vae.named_modules()):
            if 'decoder' in name and any(name.endswith(x) for x in self.target_part_vae):
                target_modules.append(name)
        self.target_modules_vae = target_modules
            
    def setup_model_from_scratch(self, pretrained_path=None, mv_unet=False):
        self.tokenizer = AutoTokenizer.from_pretrained("stabilityai/sd-turbo", subfolder="tokenizer")
        self.text_encoder = CLIPTextModel.from_pretrained("stabilityai/sd-turbo", subfolder="text_encoder").cuda()
        self.sched = make_1step_sched()

        vae = AutoencoderKL.from_pretrained("stabilityai/sd-turbo", subfolder="vae")
        vae.encoder.forward = my_vae_encoder_fwd.__get__(vae.encoder, vae.encoder.__class__)
        vae.decoder.forward = my_vae_decoder_fwd.__get__(vae.decoder, vae.decoder.__class__)
        # add the skip connection convs
        vae.decoder.skip_conv_1 = torch.nn.Conv2d(512, 512, kernel_size=(1, 1), stride=(1, 1), bias=False).cuda()
        vae.decoder.skip_conv_2 = torch.nn.Conv2d(256, 512, kernel_size=(1, 1), stride=(1, 1), bias=False).cuda()
        vae.decoder.skip_conv_3 = torch.nn.Conv2d(128, 512, kernel_size=(1, 1), stride=(1, 1), bias=False).cuda()
        vae.decoder.skip_conv_4 = torch.nn.Conv2d(128, 256, kernel_size=(1, 1), stride=(1, 1), bias=False).cuda()
        vae.decoder.ignore_skip = False
        
        if mv_unet:
            from mv_unet import UNet2DConditionModel
        else:
            from diffusers import UNet2DConditionModel

        unet = UNet2DConditionModel.from_pretrained("stabilityai/sd-turbo", subfolder="unet")

        if pretrained_path is not None:
            sd = torch.load(pretrained_path, map_location="cpu")
            vae_lora_config = LoraConfig(r=sd["rank_vae"], init_lora_weights="gaussian", target_modules=sd["vae_lora_target_modules"])
            vae.add_adapter(vae_lora_config, adapter_name="vae_skip")
            _sd_vae = vae.state_dict()
            for k in sd["state_dict_vae"]:
                _sd_vae[k] = sd["state_dict_vae"][k]
            vae.load_state_dict(_sd_vae)
            _sd_unet = unet.state_dict()
            for k in sd["state_dict_unet"]:
                _sd_unet[k] = sd["state_dict_unet"][k]
            unet.load_state_dict(_sd_unet)
        else:
            print("Initializing model with random weights")
            torch.nn.init.constant_(vae.decoder.skip_conv_1.weight, 1e-5)
            torch.nn.init.constant_(vae.decoder.skip_conv_2.weight, 1e-5)
            torch.nn.init.constant_(vae.decoder.skip_conv_3.weight, 1e-5)
            torch.nn.init.constant_(vae.decoder.skip_conv_4.weight, 1e-5)
            
            target_modules = []
            for id, (name, param) in enumerate(vae.named_modules()):
                if 'decoder' in name and any(name.endswith(x) for x in self.target_part_vae):
                    target_modules.append(name)
            self.target_modules_vae = target_modules
            vae.encoder.requires_grad_(False)

            vae_lora_config = LoraConfig(r=self.lora_rank_vae, init_lora_weights="gaussian",
                target_modules=self.target_modules_vae)
            vae.add_adapter(vae_lora_config, adapter_name="vae_skip")
                
        # unet.enable_xformers_memory_efficient_attention()
        unet.to("cuda")
        vae.to("cuda")
        self.unet, self.vae = unet, vae

    def set_eval(self):
        self.unet.eval()
        self.vae.eval()
        self.unet.requires_grad_(False)
        self.vae.requires_grad_(False)
        self.text_encoder.requires_grad_(False)
        
    def set_train(self):
        self.unet.train()
        self.vae.train()
        
        self.unet.requires_grad_(True)
        self.text_encoder.requires_grad_(False)
        self.vae.encoder.requires_grad_(False)
        
        for n, _p in self.vae.named_parameters():
            if "lora" in n:
                _p.requires_grad = True
        self.vae.decoder.skip_conv_1.requires_grad_(True)
        self.vae.decoder.skip_conv_2.requires_grad_(True)
        self.vae.decoder.skip_conv_3.requires_grad_(True)
        self.vae.decoder.skip_conv_4.requires_grad_(True)
        # print number of trainable parameters
        print("="*50)
        print(f"Number of trainable parameters in UNet: {sum(p.numel() for p in self.unet.parameters() if p.requires_grad) / 1e6:.2f}M")
        print(f"Number of trainable parameters in VAE: {sum(p.numel() for p in self.vae.parameters() if p.requires_grad) / 1e6:.2f}M")
        print("="*50)

    @staticmethod
    def _sync_cuda():
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        
    def forward(
        self,
        x,
        timesteps=None,
        prompt=None,
        prompt_tokens=None,
        profile=False,
        decode_ref=True,
        use_text_cache=True,
        use_channels_last=False,
        ref_mask=None,
    ):
        """
        ref_mask: 可选, shape = [B, 1, H_pix, W_pix] 或 [B, 1, H_lat, W_lat]
            取值: 1.0 = 该位置 ref 应在 attn1 中被忽略 (mask out);
                  0.0 = 该位置正常参与 attn1.
            仅当 num_views >= 2 (即 use_ref_img=True) 时生效;
            若 ref_mask 全为 0 或 None, 行为等价于未启用.
        """
        # either the prompt or the prompt_tokens should be provided
        assert (prompt is None) != (prompt_tokens is None), "Either prompt or prompt_tokens should be provided"
        assert (timesteps is None) != (self.timesteps is None), "Either timesteps or self.timesteps should be provided"
        vae_param = next(self.vae.parameters())
        unet_param = next(self.unet.parameters())
        profile_stats = {}
        if profile:
            self._sync_cuda()
            t_forward_start = time.perf_counter()
        
        if profile:
            self._sync_cuda()
            t_text_start = time.perf_counter()
        if use_text_cache:
            caption_enc = self._encode_text_cached(prompt=prompt, prompt_tokens=prompt_tokens)
        else:
            if prompt is not None:
                caption_tokens = self.tokenizer(
                    prompt,
                    max_length=self.tokenizer.model_max_length,
                    padding="max_length",
                    truncation=True,
                    return_tensors="pt",
                ).input_ids.to(next(self.text_encoder.parameters()).device)
                caption_enc = self.text_encoder(caption_tokens)[0]
            else:
                caption_enc = self.text_encoder(prompt_tokens.to(next(self.text_encoder.parameters()).device))[0]
        if profile:
            self._sync_cuda()
            profile_stats["text_encode_ms"] = (time.perf_counter() - t_text_start) * 1000.0
                                
        num_views = x.shape[1]
        original_batch_size = x.shape[0]  # 真实 batch (B), rearrange 前的值, 用于 ref_mask 校验
        x = rearrange(x, 'b v c h w -> (b v) c h w')
        if use_channels_last:
            x = x.contiguous(memory_format=torch.channels_last)
        x = x.to(device=vae_param.device, dtype=vae_param.dtype)
        if profile:
            self._sync_cuda()
            t_vae_encode_start = time.perf_counter()
        z = self.vae.encode(x).latent_dist.sample() * self.vae.config.scaling_factor 
        if profile:
            self._sync_cuda()
            profile_stats["vae_encode_ms"] = (time.perf_counter() - t_vae_encode_start) * 1000.0
        caption_enc = repeat(caption_enc, 'b n c -> (b v) n c', v=num_views).to(device=unet_param.device, dtype=unet_param.dtype)
        
        unet_input = z
        # 仅当 多 view + ref_mask 有有效屏蔽区时, 构造 cross_attention_kwargs 给 attn1 用
        cross_attention_kwargs = None
        if num_views >= 2 and ref_mask is not None:
            unet_param = next(self.unet.parameters())
            H_lat, W_lat = unet_input.shape[-2], unet_input.shape[-1]
            rm = ref_mask
            if rm.dim() == 3:  # [B, H, W] -> [B, 1, H, W]
                rm = rm.unsqueeze(1)
            if rm.dim() != 4 or rm.shape[1] != 1:
                raise ValueError(
                    f"ref_mask shape must be [B,1,H,W] or [B,H,W], got {tuple(rm.shape)}"
                )
            if rm.shape[0] != original_batch_size:
                raise ValueError(
                    f"ref_mask batch ({rm.shape[0]}) != input batch ({original_batch_size})"
                )
            rm = rm.to(device=unet_param.device, dtype=unet_param.dtype)
            if rm.shape[-2:] != (H_lat, W_lat):
                rm = torch.nn.functional.interpolate(rm, size=(H_lat, W_lat), mode="nearest")
            if float(rm.max().item()) > 0.5:
                cross_attention_kwargs = {
                    "ref_mask": rm,
                    "ref_mask_lat_shape": (H_lat, W_lat),
                    "ref_mask_num_views": num_views,
                }
        if profile:
            self._sync_cuda()
            t_unet_start = time.perf_counter()
        model_pred = self.unet(
            unet_input,
            self.timesteps,
            encoder_hidden_states=caption_enc,
            cross_attention_kwargs=cross_attention_kwargs,
        ).sample
        if profile:
            self._sync_cuda()
            profile_stats["unet_ms"] = (time.perf_counter() - t_unet_start) * 1000.0
            self._sync_cuda()
            t_scheduler_start = time.perf_counter()
        z_denoised = self.sched.step(model_pred, self.timesteps, z, return_dict=True).prev_sample
        if profile:
            self._sync_cuda()
            profile_stats["scheduler_ms"] = (time.perf_counter() - t_scheduler_start) * 1000.0
        z_denoised = z_denoised.to(device=vae_param.device, dtype=vae_param.dtype)
        incoming_skip_acts = self.vae.encoder.current_down_blocks
        decode_latent = z_denoised
        decode_num_views = num_views
        if (not decode_ref) and num_views > 1:
            decode_latent = rearrange(z_denoised, '(b v) c h w -> b v c h w', v=num_views)[:, 0]
            incoming_skip_acts = [
                rearrange(x_skip, '(b v) c h w -> b v c h w', v=num_views)[:, 0]
                for x_skip in incoming_skip_acts
            ]
            decode_num_views = 1
        if use_channels_last:
            decode_latent = decode_latent.contiguous(memory_format=torch.channels_last)
        self.vae.decoder.incoming_skip_acts = incoming_skip_acts
        if profile:
            self._sync_cuda()
            t_vae_decode_start = time.perf_counter()
        output_image = (self.vae.decode(decode_latent / self.vae.config.scaling_factor).sample).clamp(-1, 1)
        if profile:
            self._sync_cuda()
            profile_stats["vae_decode_ms"] = (time.perf_counter() - t_vae_decode_start) * 1000.0
        if decode_num_views == 1 and num_views > 1 and (not decode_ref):
            output_image = output_image.unsqueeze(1)
        else:
            output_image = rearrange(output_image, '(b v) c h w -> b v c h w', v=num_views)
        if profile:
            self._sync_cuda()
            profile_stats["forward_total_ms"] = (time.perf_counter() - t_forward_start) * 1000.0
        
        if profile:
            return output_image, profile_stats
        return output_image
    
    def sample(self, image, width, height, ref_image=None, timesteps=None, prompt=None, prompt_tokens=None, profile=False):
        input_width, input_height = image.size
        sample_profile = {}
        if profile:
            self._sync_cuda()
            t_sample_start = time.perf_counter()
            t_pre_start = time.perf_counter()
        new_width = image.width - image.width % 8
        new_height = image.height - image.height % 8
        image = image.resize((new_width, new_height), Image.LANCZOS)
        if height == 0 or width == 0:
            height, width = new_height, new_width
        
        T = transforms.Compose([
            transforms.Resize((height, width), interpolation=Image.LANCZOS),
            transforms.ToTensor(),
            transforms.Normalize([0.5], [0.5]),
        ])
        if ref_image is None:
            x = T(image).unsqueeze(0).unsqueeze(0).cuda()
        else:
            ref_image = ref_image.resize((new_width, new_height), Image.LANCZOS)
            x = torch.stack([T(image), T(ref_image)], dim=0).unsqueeze(0).cuda()

        # Align input tensor dtype/device with VAE weights to avoid matmul/conv dtype mismatch.
        vae_param = next(self.vae.parameters())
        x = x.to(device=vae_param.device, dtype=vae_param.dtype)
        if profile:
            self._sync_cuda()
            sample_profile["preprocess_ms"] = (time.perf_counter() - t_pre_start) * 1000.0

        with torch.inference_mode():
            if profile:
                output_image, forward_profile = self.forward(
                    x, timesteps, prompt, prompt_tokens, profile=True
                )
                sample_profile.update(forward_profile)
                output_image = output_image[:, 0]
            else:
                output_image = self.forward(x, timesteps, prompt, prompt_tokens)[:, 0]
        if profile:
            self._sync_cuda()
            t_post_start = time.perf_counter()
        output_image_vis = output_image[0].float().cpu() * 0.5 + 0.5
        output_pil = transforms.ToPILImage()(output_image_vis)
        output_pil = output_pil.resize((input_width, input_height), Image.LANCZOS)
        if profile:
            sample_profile["postprocess_ms"] = (time.perf_counter() - t_post_start) * 1000.0
            self._sync_cuda()
            sample_profile["sample_total_ms"] = (time.perf_counter() - t_sample_start) * 1000.0
            return output_pil, sample_profile
        return output_pil

    def sample_xpeng(self,  image_tensor, width, height, ref_image=None, ref_mask=None, timesteps=None, prompt=None, prompt_tokens=None, profile=False, enable_infer_optimizations=True):
        """
        Args:
            ref_mask: 可选, shape = [H, W] / [1, H, W] / [B=1, 1, H, W];
                      取值: >0.5 (或 >127 if uint8) = 该位置 ref 应在 attn1 中被忽略.
                      仅当 ref_image 不为 None 时生效.
        """
        _, input_height, input_width = image_tensor.shape
        # new_width = image.width - image.width % 8
        # new_height = image.height - image.height % 8
        # image = image.resize((new_width, new_height), Image.LANCZOS)
        sample_profile = {}
        if profile:
            self._sync_cuda()
            t_sample_start = time.perf_counter()
            t_pre_start = time.perf_counter()
        
        model_dtype = next(self.vae.parameters()).dtype
        
        img_float = image_tensor.float() / 255.0               
        x_main = F.resize(img_float, (height, width), interpolation=F.InterpolationMode.BICUBIC)
        x_main = (x_main - 0.5) / 0.5
        x_main = x_main.unsqueeze(0).unsqueeze(0).to(dtype=model_dtype)

        if ref_image is not None:
            ref_image = ref_image.float() / 255.0
            ref_tensor = F.resize(ref_image, (height, width), interpolation=F.InterpolationMode.BICUBIC)
            ref_tensor = (ref_tensor - 0.5) / 0.5
            ref_tensor = ref_tensor.unsqueeze(0).unsqueeze(0).to(dtype=model_dtype)

            # 将主图像和参考图像拼接为多视图输入
            x = torch.cat([x_main, ref_tensor], dim=1)  # Shape: (1, 2, C, H, W)
        else:
            # 如果没有参考图像，则仅使用主图像
            x = x_main

        # ref_mask 预处理: 转 [B=1, 1, H_input, W_input] float, 1.0=ignore
        # (forward 内部会再 resize 到 latent 分辨率)
        ref_mask_for_forward = None
        if ref_image is not None and ref_mask is not None:
            rm = ref_mask
            if not torch.is_tensor(rm):
                rm = torch.as_tensor(rm)
            if rm.dim() == 2:
                rm = rm.unsqueeze(0).unsqueeze(0)  # [H,W] -> [1,1,H,W]
            elif rm.dim() == 3:
                rm = rm.unsqueeze(0)              # [1,H,W] -> [1,1,H,W]
            elif rm.dim() == 4:
                pass                              # [1,1,H,W]
            else:
                raise ValueError(f"ref_mask shape must be 2D/3D/4D, got {tuple(rm.shape)}")
            rm = rm.float()
            # 兼容 uint8 mask (>127 视为屏蔽)
            if rm.max() > 1.5:
                rm = (rm > 127).float()
            # resize 到模型输入分辨率 (与 x_main 对齐), NEAREST 保持二值
            rm = torch.nn.functional.interpolate(rm, size=(height, width), mode="nearest")
            ref_mask_for_forward = rm.to(dtype=model_dtype)

        if profile:
            self._sync_cuda()
            sample_profile["preprocess_ms"] = (time.perf_counter() - t_pre_start) * 1000.0
        with torch.inference_mode():
            def _run_forward_once():
                if profile:
                    _output_image, _forward_profile = self.forward(
                        x,
                        timesteps,
                        prompt,
                        prompt_tokens,
                        profile=True,
                        decode_ref=not enable_infer_optimizations,
                        use_text_cache=enable_infer_optimizations,
                        use_channels_last=enable_infer_optimizations,
                        ref_mask=ref_mask_for_forward,
                    )
                    return _output_image[:, 0], _forward_profile
                _output_image = self.forward(
                    x,
                    timesteps,
                    prompt,
                    prompt_tokens,
                    decode_ref=not enable_infer_optimizations,
                    use_text_cache=enable_infer_optimizations,
                    use_channels_last=enable_infer_optimizations,
                    ref_mask=ref_mask_for_forward,
                )[:, 0]
                return _output_image, None

            try:
                output_image, forward_profile = _run_forward_once()
            except RuntimeError as e:
                err_msg = str(e)
                if enable_infer_optimizations and ("cudagraph" in err_msg.lower()):
                    self._disable_vae_compile_for_inference(err_msg.splitlines()[0])
                    output_image, forward_profile = _run_forward_once()
                else:
                    raise
            if profile and forward_profile is not None:
                sample_profile.update(forward_profile)

        if profile:
            self._sync_cuda()
            t_post_start = time.perf_counter()
        img = output_image[0].float() * 0.5 + 0.5                             
        img = F.resize(img, (input_height, input_width), interpolation=F.InterpolationMode.BICUBIC)  
        output_tensor2 = (img * 255).to(torch.uint8).to(image_tensor.device)         
        if profile:
            sample_profile["postprocess_ms"] = (time.perf_counter() - t_post_start) * 1000.0
            self._sync_cuda()
            sample_profile["sample_total_ms"] = (time.perf_counter() - t_sample_start) * 1000.0
            return output_tensor2, sample_profile
        return output_tensor2

    def warmup_inference_compile_buckets(
        self,
        bucket_sizes,
        use_ref=False,
        camera_names=None,
        enable_infer_optimizations=True,
    ):
        """
        Pre-run inference once for each bucket size so torch.compile/inductor
        shape-specialized kernels are prepared before real profiling/inference.
        """
        if not enable_infer_optimizations:
            return
        if bucket_sizes is None:
            return

        unique_buckets = []
        seen = set()
        for h, w in bucket_sizes:
            h_i, w_i = int(h), int(w)
            if h_i <= 0 or w_i <= 0:
                continue
            key = (h_i, w_i)
            if key in seen:
                continue
            seen.add(key)
            unique_buckets.append(key)
        if len(unique_buckets) == 0:
            return

        cam = "cam0"
        if camera_names is not None:
            camera_list = list(camera_names)
            if len(camera_list) > 0:
                cam = str(camera_list[0]).lower()
        warmup_prompt = f"Corrected rendering distortion for {cam.upper()} camera view."

        for h_i, w_i in unique_buckets:
            dummy = torch.randint(0, 255, (3, h_i, w_i), dtype=torch.uint8, device="cuda")
            dummy_ref = dummy.clone() if use_ref else None
            with torch.inference_mode():
                _ = self.sample_xpeng(
                    image_tensor=dummy,
                    width=w_i,
                    height=h_i,
                    ref_image=dummy_ref,
                    prompt=warmup_prompt,
                    profile=False,
                    enable_infer_optimizations=True,
                )
    
    def save_model(self, outf, optimizer):
        sd = {}
        sd["vae_lora_target_modules"] = self.target_modules_vae
        sd["rank_vae"] = self.lora_rank_vae
        sd["state_dict_unet"] = {k: v for k, v in self.unet.state_dict().items() if "lora" in k or "conv_in" in k}
        sd["state_dict_vae"] = {k: v for k, v in self.vae.state_dict().items() if "lora" in k or "skip" in k}
        
        sd["optimizer"] = optimizer.state_dict()
        
        torch.save(sd, outf)
