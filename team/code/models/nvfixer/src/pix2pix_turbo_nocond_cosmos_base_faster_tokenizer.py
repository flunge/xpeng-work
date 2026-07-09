# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import requests
import sys
import copy
import numpy as np
from tqdm import tqdm
import torch
import torch.nn as nn
from einops import rearrange, repeat
import time
import torch.nn.functional as F

import sys


from cosmos_predict2.models.utils import init_weights_on_device, load_state_dict
from cosmos_predict2.tokenizers.tokenizer import ResidualBlock, CausalConv3d
from cosmos_predict2.configs.base.config_text2image import (
    get_cosmos_predict2_text2image_pipeline,
)

from cosmos_predict2.conditioner import DataType
from cosmos_predict2.pipelines.text2image import Text2ImagePipeline


from imaginaire.lazy_config import LazyDict, instantiate

config = get_cosmos_predict2_text2image_pipeline(model_size="0.6B", fast_tokenizer=True)

### MiniTrainDIT
config.dit_path = '/workspace/group_share/adc-sim/users/wangyd13/Fixer/base/model_fast_tokenizer.pt'
config.tokenizer["vae_pth"] = '/workspace/group_share/adc-sim/users/wangyd13/Fixer/base/tokenizer_fast.pth'
config.guardrail_config.enabled=False

from model import make_1step_sched_base as make_1step_sched  # , my_vae_encoder_fwd, my_vae_decoder_fwd


def _strip_module_prefix(state_dict):
    if state_dict is None:
        return None
    stripped = {}
    for key, value in state_dict.items():
        if key.startswith("module."):
            stripped[key[7:]] = value
        else:
            stripped[key] = value
    return stripped


def load_ckpt_from_state_dict(
    net_pix2pix,
    optimizer,
    pretrained_path,
    lr_scheduler=None,
    load_optimizer=True
):
    sd = torch.load(pretrained_path, map_location="cpu")
        
    net_pix2pix.unet.load_state_dict(sd["state_dict_unet"], strict=False)
    net_pix2pix.vae.load_state_dict(sd["state_dict_vae"], strict=False)
    if sd.get("state_dict_ref_token_adapter") is not None:
        net_pix2pix.ref_token_adapter.load_state_dict(sd["state_dict_ref_token_adapter"], strict=False)
    if sd.get("state_dict_ref_detail_adapter") is not None:
        net_pix2pix.ref_detail_adapter.load_state_dict(sd["state_dict_ref_detail_adapter"], strict=False)

    if load_optimizer and optimizer is not None and sd.get("optimizer") is not None:
        optimizer.load_state_dict(sd["optimizer"], strict=False)
    if lr_scheduler is not None and sd.get("lr_scheduler_state") is not None:
        lr_scheduler.load_state_dict(sd["lr_scheduler_state"], strict=False)
    
    print()
    print('!!!! loading, load pretrained weight from', pretrained_path)
    print()
    resume_info = {
        "epoch": sd.get("epoch"),
        "global_step": sd.get("global_step"),
        "lr_scheduler_state": sd.get("lr_scheduler_state"),
    }
    return net_pix2pix, optimizer, resume_info


def save_ckpt(
    net_pix2pix,
    optimizer,
    outf,
    train_full_unet=False,
    freeze_vae=False,
    epoch=None,
    global_step=None,
    lr_scheduler=None,
):
    sd = {}

    sd["state_dict_unet"] = net_pix2pix.unet.state_dict()
    sd["state_dict_vae"] = net_pix2pix.vae.state_dict()
    sd["state_dict_ref_token_adapter"] = net_pix2pix.ref_token_adapter.state_dict()
    sd["state_dict_ref_detail_adapter"] = net_pix2pix.ref_detail_adapter.state_dict()
        
    sd["optimizer"] = optimizer.state_dict() if optimizer is not None else None
    sd["epoch"] = epoch
    sd["global_step"] = global_step
    sd["lr_scheduler_state"] = lr_scheduler.state_dict() if lr_scheduler is not None else None
    
    torch.save(sd, outf)


def _get_module_param_dtype(module, fallback_dtype):
    try:
        return next(module.parameters()).dtype
    except StopIteration:
        return fallback_dtype
    except TypeError:
        return fallback_dtype


CACHE_T = 2


class ReferenceDetailAdapter(nn.Module):
    def __init__(self, latent_channels=16, hidden_channels=32, num_scales=3):
        super().__init__()
        self.num_scales = max(int(num_scales), 1)
        self.stem = nn.Sequential(
            nn.Conv2d(latent_channels, hidden_channels, kernel_size=3, padding=1),
            nn.GroupNorm(8, hidden_channels),
            nn.SiLU(),
        )
        self.scale_blocks = nn.ModuleList([
            nn.Sequential(
                nn.Conv2d(hidden_channels, hidden_channels, kernel_size=3, padding=1),
                nn.GroupNorm(8, hidden_channels),
                nn.SiLU(),
                nn.Conv2d(hidden_channels, hidden_channels, kernel_size=3, padding=1),
                nn.GroupNorm(8, hidden_channels),
                nn.SiLU(),
            )
            for _ in range(self.num_scales)
        ])
        self.gates = nn.ParameterList([nn.Parameter(torch.zeros(1)) for _ in range(self.num_scales)])
        self.fuse = nn.Sequential(
            nn.Conv2d(hidden_channels, hidden_channels, kernel_size=3, padding=1),
            nn.SiLU(),
            nn.Conv2d(hidden_channels, 3, kernel_size=3, padding=1),
        )
        self._init_weights()

    def _init_weights(self):
        for module in self.modules():
            if isinstance(module, nn.Conv2d):
                nn.init.normal_(module.weight, mean=0.0, std=1e-5)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
        for module in self.fuse:
            if isinstance(module, nn.Conv2d):
                nn.init.zeros_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def forward(self, ref_latent, output_hw):
        if ref_latent is None:
            return None
        target_h, target_w = output_hw
        feat = self.stem(ref_latent[:, :, 0].float())
        detail = None
        cur = feat
        for idx, (block, gate) in enumerate(zip(self.scale_blocks, self.gates)):
            cur = block(cur)
            cur_up = F.interpolate(cur, size=(target_h, target_w), mode="bilinear", align_corners=False)
            cur_up = cur_up * torch.tanh(gate).view(1, 1, 1, 1)
            detail = cur_up if detail is None else detail + cur_up
            if idx != self.num_scales - 1:
                cur = F.avg_pool2d(cur, kernel_size=2, stride=2, ceil_mode=True)
        if detail is None:
            return None
        return self.fuse(detail)


class ReferenceTokenAdapter(nn.Module):
    def __init__(self, latent_channels=16, hidden_dim=256, token_dim=1024, token_count=32):
        super().__init__()
        self.token_count = int(token_count)
        self.grid_h, self.grid_w = self._factorize_token_grid(self.token_count)
        self.proj_in = nn.Sequential(
            nn.Conv2d(latent_channels, hidden_dim, kernel_size=3, padding=1),
            nn.GroupNorm(8, hidden_dim),
            nn.SiLU(),
            nn.Conv2d(hidden_dim, hidden_dim, kernel_size=3, padding=1),
            nn.GroupNorm(8, hidden_dim),
            nn.SiLU(),
        )
        self.token_mlp = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, token_dim),
        )

    @staticmethod
    def _factorize_token_grid(token_count):
        grid_h = int(np.floor(np.sqrt(token_count)))
        while grid_h > 1 and token_count % grid_h != 0:
            grid_h -= 1
        grid_w = max(token_count // grid_h, 1)
        return grid_h, grid_w

    def forward(self, latent):
        latent_2d = latent.squeeze(2)
        features = self.proj_in(latent_2d)
        pooled = F.adaptive_avg_pool2d(features, (self.grid_h, self.grid_w))
        tokens = rearrange(pooled, "b c h w -> b (h w) c")
        return self.token_mlp(tokens)


def my_vae_encoder_fwd(self, x, feat_cache=None, feat_idx=[0]):
    if feat_cache is not None:
        idx = feat_idx[0]
        cache_x = x[:, :, -CACHE_T:, :, :].clone()
        if cache_x.shape[2] < 2 and feat_cache[idx] is not None:
            # cache last frame of last two chunk
            cache_x = torch.cat([feat_cache[idx][:, :, -1, :, :].unsqueeze(2).to(cache_x.device), cache_x], dim=2)
        x = self.conv1(x, feat_cache[idx])
        feat_cache[idx] = cache_x
        feat_idx[0] += 1
    else:
        x = self.conv1(x)

    l_blocks = []
    # downsamples
    for layer in self.downsamples:
        if feat_cache is not None:
            x = layer(x, feat_cache, feat_idx)
        else:
            x = layer(x)
            
        l_blocks.append(x) 

    # middle
    for layer in self.middle:
        if isinstance(layer, ResidualBlock) and feat_cache is not None:
            x = layer(x, feat_cache, feat_idx)
        else:
            x = layer(x)

    # head
    for layer in self.head:
        if isinstance(layer, CausalConv3d) and feat_cache is not None:
            idx = feat_idx[0]
            cache_x = x[:, :, -CACHE_T:, :, :].clone()
            if cache_x.shape[2] < 2 and feat_cache[idx] is not None:
                # cache last frame of last two chunk
                cache_x = torch.cat(
                    [feat_cache[idx][:, :, -1, :, :].unsqueeze(2).to(cache_x.device), cache_x], dim=2
                )
            x = layer(x, feat_cache[idx])
            feat_cache[idx] = cache_x
            feat_idx[0] += 1
        else:
            x = layer(x)
            
    self.current_down_blocks = l_blocks
    return x


def my_vae_decoder_fwd(self, x, feat_cache=None, feat_idx=[0]):
    # conv1
    if feat_cache is not None:
        idx = feat_idx[0]
        cache_x = x[:, :, -CACHE_T:, :, :].clone()
        if cache_x.shape[2] < 2 and feat_cache[idx] is not None:
            # cache last frame of last two chunk
            cache_x = torch.cat([feat_cache[idx][:, :, -1, :, :].unsqueeze(2).to(cache_x.device), cache_x], dim=2)
        x = self.conv1(x, feat_cache[idx])
        feat_cache[idx] = cache_x
        feat_idx[0] += 1
    else:
        x = self.conv1(x)

        
    # middle
    for layer in self.middle:
        if isinstance(layer, ResidualBlock) and feat_cache is not None:
            x = layer(x, feat_cache, feat_idx)
        else:
            x = layer(x)

    for dec_idx, layer in enumerate(self.upsamples):
        if feat_cache is not None:
            x = layer(x, feat_cache, feat_idx)
        else:
            x = layer(x)
            

    # head
    for layer in self.head:
        if isinstance(layer, CausalConv3d) and feat_cache is not None:
            idx = feat_idx[0]
            cache_x = x[:, :, -CACHE_T:, :, :].clone()
            if cache_x.shape[2] < 2 and feat_cache[idx] is not None:
                # cache last frame of last two chunk
                cache_x = torch.cat(
                    [feat_cache[idx][:, :, -1, :, :].unsqueeze(2).to(cache_x.device), cache_x], dim=2
                )
            x = layer(x, feat_cache[idx])
            feat_cache[idx] = cache_x
            feat_idx[0] += 1
        else:
            x = layer(x)
    return x


import time


class Pix2Pix_Turbo(torch.nn.Module):
    
    def __init__(self, experiment_name = None, s3_checkpoint_dir = None, pretrained_path = None,
                 ckpt_folder="checkpoints", lora_rank_unet=8, lora_rank_vae=4, hf_path = None,
                 unet_in_channels=4, freeze_vae_encoder=False, 
                 freeze_vae=False, train_full_unet=True, timestep=999, 
                 use_sched = False, vae_skip_connection = False, batch_size = 1,
                 use_reference_image = False, use_ref_cross_attn = False,
                 use_ref_detail_adapter = False, ref_token_count = 32):
        super().__init__()
        
        self.experiment_name = experiment_name
        self.s3_checkpoint_dir = s3_checkpoint_dir
        self.batch_size = batch_size

        
        self.timesteps = torch.tensor([timestep], device="cuda")#.half()#.long()
        self.timesteps = torch.cat([self.timesteps] * batch_size, 0)
        
        self.timesteps_int =  timestep
        
        self.train_full_unet = train_full_unet
        self.freeze_vae = freeze_vae
        self.freeze_vae_encoder = freeze_vae_encoder
        self.vae_skip_connection = vae_skip_connection
        self.use_reference_image = use_reference_image
        self.use_ref_cross_attn = use_ref_cross_attn
        self.use_ref_detail_adapter = use_ref_detail_adapter
        self.ref_token_count = ref_token_count
        
        self.use_sched = use_sched
        if self.use_sched:
            self.sched = None #make_1step_sched()
         

        self.initialize_cosmos_model()
        self.ref_token_adapter = ReferenceTokenAdapter(token_count=self.ref_token_count)
        self.ref_detail_adapter = ReferenceDetailAdapter()
        self.ref_token_adapter.to("cuda")
        self.ref_detail_adapter.to("cuda")
        self.set_train()

        if pretrained_path is not None:
            print('loading from', pretrained_path)
            sd = torch.load(pretrained_path, map_location="cpu")

            self.unet.load_state_dict(sd["state_dict_unet"], strict=False)
            self.vae.load_state_dict(sd["state_dict_vae"], strict=False)
            if sd.get("state_dict_ref_token_adapter") is not None:
                self.ref_token_adapter.load_state_dict(sd["state_dict_ref_token_adapter"], strict=False)
            if sd.get("state_dict_ref_detail_adapter") is not None:
                self.ref_detail_adapter.load_state_dict(sd["state_dict_ref_detail_adapter"], strict=False)

            
        # print number of trainable parameters
        print("="*50)
        print(f"Number of trainable parameters in UNet: {sum(p.numel() for p in self.unet.parameters() if p.requires_grad) / 1e6:.2f}M")
        print(f"Number of trainable parameters in VAE: {sum(p.numel() for p in self.vae.parameters() if p.requires_grad) / 1e6:.2f}M")
        print("="*50)

    def sample_batch_image(self):
        #h, w = 384, 640
        #h, w = 768, 1360
        h, w = 544, 960
        
        batch_size = self.batch_size
        data_batch = {
            "dataset_name": "image_data",
            "images": torch.zeros(batch_size, 3, h, w).cuda(),
            "t5_text_embeddings": torch.zeros(batch_size, 512, 1024).cuda(),
            "fps": torch.ones((batch_size,)).cuda() * 24,
            "padding_mask": torch.zeros(batch_size, 1, h, w).cuda(),
        }
        return data_batch


    def initialize_cosmos_model(self):
        model = Text2ImagePipeline.from_config(
            config,
            dit_path=config.dit_path,
            use_text_encoder = False
        )
        
        
        ##### conditioning
        conditioner = model.conditioner
        data_batch = self.sample_batch_image()
        is_image_batch = True
        
        condition, uncondition = conditioner.get_condition_uncondition(data_batch)
        del condition
        
        uncondition = uncondition.edit_data_type(DataType.IMAGE if is_image_batch else DataType.VIDEO)
        self.condition = uncondition

        self.unet = model#.net # MiniTrainDIT
        vae = model.tokenizer #model.tokenizer <projects.cosmos.diffusion.v2.tokenizers.wan2pt1.Wan2pt1VAEInterface object at 0x155401d12c20>

        self.sigma_data = model.sigma_data  
        self.vae = vae
              

        print('=' * 50)
        print('SUCCESS in initializing Cosmos Model')
        print(f"Number of parameters in UNet: {sum(p.numel() for p in self.unet.parameters() ) / 1e6:.2f}M")
        print(f"Number of parameters in VAE: {sum(p.numel() for p in self.vae.parameters()) / 1e6:.2f}M")
        print('=' * 50)

        self.unet.to("cuda")
        self.vae.to("cuda")
        
    def vae_encode(self, state: torch.Tensor) -> torch.Tensor:
        in_dtype = state.dtype
        if hasattr(self.vae, "encoder") and hasattr(self.vae, "normalize_latent"):
            encoder_dtype = _get_module_param_dtype(
                self.vae.encoder,
                getattr(self.vae, "latent_mean", state).dtype,
            )
            if not self.vae.squeeze_for_image:
                assert state.shape[2] == 1, f"Expect the number of frames {state.shape[2]} to be 1"
            encoder_input = state.to(encoder_dtype)
            if self.vae.squeeze_for_image and not getattr(self.vae, "_use_skip_adapter", False):
                encoder_input = encoder_input.squeeze(2)
            latent = self.vae.encoder(encoder_input)
            if isinstance(latent, tuple):
                latent = latent[0]
            if self.vae.squeeze_for_image and not getattr(self.vae, "_use_skip_adapter", False):
                latent = latent.unsqueeze(2)
            if self.vae.apply_mean_std:
                latent = self.vae.normalize_latent(latent)
        else:
            vae_wrapper = self.vae.model
            vae_model = vae_wrapper.model
            with vae_wrapper.context:
                if not vae_wrapper.is_amp:
                    state = state.to(vae_wrapper.dtype)
                latent = vae_model.encode(state, vae_wrapper.scale)
            num_frames = latent.shape[2]
            if num_frames == 1:
                latent = (latent - vae_wrapper.img_mean.type_as(latent)) / vae_wrapper.img_std.type_as(latent)
            else:
                latent = (
                    latent - vae_wrapper.video_mean[:, :, :num_frames].type_as(latent)
                ) / vae_wrapper.video_std[:, :, :num_frames].type_as(latent)
        latent = latent.to(in_dtype)
        return latent * self.sigma_data        

    def vae_decode(self, latent: torch.Tensor) -> torch.Tensor:
        latent = latent / self.sigma_data
        in_dtype = latent.dtype
        if hasattr(self.vae, "decoder") and hasattr(self.vae, "denormalize_latent"):
            decoder_dtype = _get_module_param_dtype(
                self.vae.decoder,
                getattr(self.vae, "latent_mean", latent).dtype,
            )
            if self.vae.apply_mean_std:
                latent = self.vae.denormalize_latent(latent.to(decoder_dtype))
            else:
                latent = latent.to(decoder_dtype)
            if self.vae.squeeze_for_image and not getattr(self.vae, "_use_skip_adapter", False):
                latent = latent.squeeze(2)
            decoded = self.vae.decoder(latent)
            if self.vae.squeeze_for_image and not getattr(self.vae, "_use_skip_adapter", False):
                decoded = decoded.unsqueeze(2)
        else:
            vae_wrapper = self.vae.model
            vae_model = vae_wrapper.model
            num_frames = latent.shape[2]
            if num_frames == 1:
                latent = latent * vae_wrapper.img_std.type_as(latent) + vae_wrapper.img_mean.type_as(latent)
            else:
                latent = (
                    latent * vae_wrapper.video_std[:, :, :num_frames].type_as(latent)
                    + vae_wrapper.video_mean[:, :, :num_frames].type_as(latent)
                )
            with vae_wrapper.context:
                if not vae_wrapper.is_amp:
                    latent = latent.to(vae_wrapper.dtype)
                decoded = vae_model.decode(latent, vae_wrapper.scale)
        return decoded.to(in_dtype)
        
    def set_eval(self):
        self.unet.eval()
        self.vae.eval()
        self.ref_token_adapter.eval()
        self.ref_detail_adapter.eval()
        self.unet.requires_grad_(False)
        self.vae.requires_grad_(False)
        self.ref_token_adapter.requires_grad_(False)
        self.ref_detail_adapter.requires_grad_(False)

    def set_train(self):
        self.unet.train()
        
        if self.train_full_unet:
            self.unet.requires_grad_(True)
            #self.unet.net_ema.requires_grad_(False)
        else:
            raise ValueError('!! train partial Unet not implemented')
            
            
        self.vae.train()
        self.vae.requires_grad_(True)
        self.ref_token_adapter.train()
        self.ref_detail_adapter.train()
        self.ref_token_adapter.requires_grad_(self.use_ref_cross_attn)
        self.ref_detail_adapter.requires_grad_(self.use_ref_detail_adapter)
        
        for name, param in self.vae.named_parameters():
            if "time_conv" in name:
                param.requires_grad = False
                print("set ", name, "grad to be false")
                
            
        if self.freeze_vae:
            self.vae.requires_grad_(False)
            self.vae.eval()

        if self.freeze_vae_encoder:
            self.vae.encoder.eval()
            # self.vae.encoder.requires_grad_(False)
            for param in self.vae.encoder.parameters():
                param.requires_grad = False

    def _clone_condition(self, crossattn_emb=None):
        kwargs = self.condition.to_dict(skip_underscore=False)
        if crossattn_emb is not None:
            kwargs["crossattn_emb"] = crossattn_emb
        return type(self.condition)(**kwargs)

    def _expand_condition_tensor(self, value, batch_size, field_name):
        if not isinstance(value, torch.Tensor) or value.ndim == 0:
            return value
        if value.shape[0] == batch_size:
            return value
        if value.shape[0] == 1:
            return value.expand(batch_size, *value.shape[1:])
        raise ValueError(
            f"Condition field '{field_name}' has batch dimension {value.shape[0]}, "
            f"but current input batch size is {batch_size}"
        )

    def _build_condition_for_batch(self, batch_size, crossattn_emb=None):
        kwargs = self.condition.to_dict(skip_underscore=False)
        if crossattn_emb is not None:
            kwargs["crossattn_emb"] = crossattn_emb
        for key, value in list(kwargs.items()):
            kwargs[key] = self._expand_condition_tensor(value, batch_size, key)
        return type(self.condition)(**kwargs)

    def _sigma_for_batch(self, batch_size, dtype, device):
        return torch.full(
            (batch_size,),
            self.timesteps_int / 1000,
            device=device,
            dtype=dtype,
        )

    def _encode_reference_tokens(self, ref_latent):
        dit_dtype = getattr(self.unet, "precision", ref_latent.dtype)
        ref_tokens = self.ref_token_adapter(ref_latent.float())
        return ref_tokens.to(device=ref_latent.device, dtype=dit_dtype)

    def _clear_decoder_reference_state(self):
        return None

    def forward(self, x, timesteps=None, ref=None):

        assert (timesteps is None) != (self.timesteps is None), "Either timesteps or self.timesteps should be provided"
        assert len(x.shape) == 4 
        if ref is not None:
            assert len(ref.shape) == 4, f"Expected ref to have shape [B, C, H, W], got {tuple(ref.shape)}"
            assert ref.shape[0] == x.shape[0], f"ref batch {ref.shape[0]} != input batch {x.shape[0]}"

        self._clear_decoder_reference_state()
        x = x[:, :, None, :, :]
        unet_input = self.vae_encode(x)
        reference_skip_acts = None
        batch_size = unet_input.shape[0]

        ref_condition = self._build_condition_for_batch(batch_size)
        if self.use_reference_image:
            ref_image = ref if ref is not None else x[:, :, 0]
            ref_latent = self.vae_encode(ref_image[:, :, None, :, :])
            if self.use_ref_cross_attn:
                ref_tokens = self._encode_reference_tokens(ref_latent)
                ref_condition = self._build_condition_for_batch(batch_size, crossattn_emb=ref_tokens)
            if self.use_ref_detail_adapter:
                reference_skip_acts = ref_latent
        
        sigma_B_T = self._sigma_for_batch(batch_size, unet_input.dtype, unet_input.device)
        
        model_pred = self.unet.denoise(xt_B_C_T_H_W = unet_input, 
                               sigma = sigma_B_T,
                               condition = ref_condition ).x0
       
        z_denoised = model_pred
        output_image = self.vae_decode(z_denoised)
        if self.use_ref_detail_adapter and reference_skip_acts is not None:
            detail_residual = self.ref_detail_adapter(reference_skip_acts, output_image.shape[-2:])
            if detail_residual is not None:
                output_image = output_image + detail_residual.unsqueeze(2).to(output_image.dtype)
        
        output_image = output_image[:, :, 0]
        self._clear_decoder_reference_state()

        return output_image

    def save_model(self, outf, optimizer):
        sd = {}
        
        sd["state_dict_unet"] = self.unet.state_dict()
        sd["state_dict_vae"] = self.vae.state_dict()
        sd["state_dict_ref_token_adapter"] = self.ref_token_adapter.state_dict()
        sd["state_dict_ref_detail_adapter"] = self.ref_detail_adapter.state_dict()
        
        sd["optimizer"] = optimizer.state_dict()
        
        torch.save(sd, outf)
