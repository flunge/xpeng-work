import logging
from typing import List, Literal, Optional, Tuple

import nvdiffrast.torch as dr
import torch
import torch.nn as nn
import torch.nn.functional as F
# from pytorch3d.ops import knn_points
from torch import Tensor

from ..datasets.base.data_proto import ImageInfo, CameraInfo
from ..utils.geometry import rotation_6d_to_matrix

logger = logging.getLogger()


class XYZ_Encoder(nn.Module):
    encoder_type = "XYZ_Encoder"
    """Encode XYZ coordinates or directions to a vector."""

    def __init__(self, n_input_dims):
        super().__init__()
        self.n_input_dims = n_input_dims

    @property
    def n_output_dims(self) -> int:
        raise NotImplementedError


class SinusoidalEncoder(XYZ_Encoder):
    encoder_type = "SinusoidalEncoder"
    """Sinusoidal Positional Encoder used in Nerf."""

    def __init__(
        self,
        n_input_dims: int = 3,
        min_deg: int = 0,
        max_deg: int = 10,
        enable_identity: bool = True,
    ):
        super().__init__(n_input_dims)
        self.n_input_dims = n_input_dims
        self.min_deg = min_deg
        self.max_deg = max_deg
        self.enable_identity = enable_identity
        self.register_buffer("scales", Tensor([2**i for i in range(min_deg, max_deg + 1)]))

    @property
    def n_output_dims(self) -> int:
        return (int(self.enable_identity) + (self.max_deg - self.min_deg + 1) * 2) * self.n_input_dims

    @torch.no_grad()
    def forward(self, x: Tensor) -> Tensor:
        """
        Args:
            x: [..., n_input_dims]
        Returns:
            encoded: [..., n_output_dims]
        """
        if self.max_deg == self.min_deg:
            return x
        xb = torch.reshape(
            (x[..., None, :] * self.scales[:, None]),
            list(x.shape[:-1]) + [(self.max_deg - self.min_deg + 1) * self.n_input_dims],
        )
        encoded = torch.sin(torch.cat([xb, xb + 0.5 * torch.pi], dim=-1))
        if self.enable_identity:
            encoded = torch.cat([x] + [encoded], dim=-1)
        return encoded


class MLP(nn.Module):
    """A simple MLP with skip connections."""

    def __init__(
        self,
        in_dims: int,
        out_dims: int,
        num_layers: int = 3,
        hidden_dims: Optional[int] = 256,
        skip_connections: Optional[Tuple[int]] = [0],
    ) -> None:
        super().__init__()
        self.in_dims = in_dims
        self.hidden_dims = hidden_dims
        self.n_output_dims = out_dims
        self.num_layers = num_layers
        self.skip_connections = skip_connections
        layers = []
        if self.num_layers == 1:
            layers.append(nn.Linear(in_dims, out_dims))
        else:
            for i in range(self.num_layers - 1):
                if i == 0:
                    layers.append(nn.Linear(in_dims, hidden_dims))
                elif i in skip_connections:
                    layers.append(nn.Linear(in_dims + hidden_dims, hidden_dims))
                else:
                    layers.append(nn.Linear(hidden_dims, hidden_dims))
            layers.append(nn.Linear(hidden_dims, out_dims))
        self.layers = nn.ModuleList(layers)

    def forward(self, x: Tensor) -> Tensor:
        input = x
        for i, layer in enumerate(self.layers):
            if i in self.skip_connections:
                x = torch.cat([x, input], -1)
            x = layer(x)
            if i < len(self.layers) - 1:
                x = nn.functional.relu(x)
        return x


class SkyModel(nn.Module):
    def __init__(
        self,
        class_name: str,
        n: int,
        head_mlp_layer_width: int = 64,
        enable_appearance_embedding: bool = True,
        appearance_embedding_dim: int = 16,
        mode: str = "default",
        device: torch.device = torch.device("cuda"),
    ):
        super().__init__()
        self.class_prefix = class_name + "#"
        self.device = device
        self.mode = mode
        assert mode in ["default", "sky_only", "first_frame_sky_only"]
        self.direction_encoding = SinusoidalEncoder(n_input_dims=3, min_deg=0, max_deg=6)
        self.direction_encoding.requires_grad_(False)

        self.enable_appearance_embedding = enable_appearance_embedding
        if self.enable_appearance_embedding:
            self.appearance_embedding_dim = appearance_embedding_dim
            self.appearance_embedding = nn.Embedding(n, appearance_embedding_dim, dtype=torch.float32)

        in_dims = (
            self.direction_encoding.n_output_dims + appearance_embedding_dim
            if self.enable_appearance_embedding
            else self.direction_encoding.n_output_dims
        )
        self.sky_head = MLP(
            in_dims=in_dims,
            out_dims=3,
            num_layers=3,
            hidden_dims=head_mlp_layer_width,
            skip_connections=[1],
        )
        self.in_test_set = False

    def forward(self, image_info: ImageInfo, opacity: Optional[torch.Tensor] = None):
        mask = None
        is_sky_mode = self.mode == "sky_only" or (
            self.mode == "first_frame_sky_only" and image_info.frame_index.cpu().item() < 30
        )
        if self.training and image_info.masks is not None and image_info.masks.sky_mask is not None and is_sky_mode:
            mask = image_info.masks.sky_mask.bool()
        elif opacity is not None:
            mask = (1.0 - opacity.squeeze(-1)) > 5.0e-3

        directions = image_info.rays.viewdirs
        self.device = directions.device
        prefix = directions.shape[:-1]

        if mask is not None:
            back_light = torch.zeros_like(directions)  # Default back color: black
            if not mask.any():
                return back_light
            directions = directions[mask]

        dd = self.direction_encoding(directions.reshape(-1, 3)).to(self.device)
        if self.enable_appearance_embedding:
            # optionally add appearance embedding
            if image_info.image_index is not None and not self.in_test_set:
                appearance_embedding = self.appearance_embedding(image_info.image_index).reshape(
                    -1, self.appearance_embedding_dim
                )
            else:
                # use mean appearance embedding
                appearance_embedding = torch.ones(
                    (*dd.shape[:-1], self.appearance_embedding_dim),
                    device=dd.device,
                ) * self.appearance_embedding.weight.mean(dim=0)
            dd = torch.cat([dd, appearance_embedding.repeat(dd.shape[0], 1)], dim=-1)
        rgb_sky = self.sky_head(dd).to(self.device)
        rgb_sky = F.sigmoid(rgb_sky)

        if mask is not None:
            back_light[mask] = rgb_sky
            return back_light

        return rgb_sky.reshape(prefix + (3,))

    def forward_lowres(self, image_info: ImageInfo, opacity: torch.Tensor, H: int, W: int, sky_scale: int = 4):
        H_low, W_low = H // sky_scale, W // sky_scale

        opacity_low = F.interpolate(
            opacity.detach().permute(2, 0, 1).unsqueeze(0),
            size=(H_low, W_low), mode='bilinear', align_corners=False
        ).squeeze(0).permute(1, 2, 0)

        viewdirs_low = F.interpolate(
            image_info.rays.viewdirs.permute(2, 0, 1).unsqueeze(0),
            size=(H_low, W_low), mode='bilinear', align_corners=False
        ).squeeze(0).permute(1, 2, 0)
        viewdirs_low = F.normalize(viewdirs_low, dim=-1)

        from types import SimpleNamespace
        low_res_info = SimpleNamespace(
            rays=SimpleNamespace(viewdirs=viewdirs_low),
            image_index=image_info.image_index,
            frame_index=image_info.frame_index,
            masks=SimpleNamespace(sky_mask=None),
        )
        rgb_sky_low = self.forward(low_res_info, opacity=opacity_low)

        rgb_sky = F.interpolate(
            rgb_sky_low.permute(2, 0, 1).unsqueeze(0),
            size=(H, W), mode='bilinear', align_corners=False
        ).squeeze(0).permute(1, 2, 0)
        return rgb_sky

    def get_param_groups(self):
        return {
            self.class_prefix + "all": self.parameters(),
        }


class EnvLight(torch.nn.Module):
    def __init__(
        self,
        class_name: str,
        resolution: int = 1024,
        mode: str = "default",
        device: torch.device = torch.device("cuda"),
        **kwargs
    ):
        super().__init__()
        self.class_prefix = class_name + "#"
        self.device = device
        self.to_opengl = torch.tensor([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=torch.float32, device="cuda")
        self.base = torch.nn.Parameter(
            torch.zeros(6, resolution, resolution, 3, requires_grad=True),
        )
        self.mode = mode
        assert mode in ["default", "sky_only", "first_frame_sky_only"]

    def forward(self, image_info: ImageInfo, opacity: Optional[torch.Tensor] = None):
        mask = None
        is_sky_mode = self.mode == "sky_only" or (
            self.mode == "first_frame_sky_only" and image_info.frame_index.cpu().item() < 30
        )
        if self.training and image_info.masks is not None and image_info.masks.sky_mask is not None and is_sky_mode:
            # Design inspired by: https://github.com/zju3dv/street_gaussians/blob/
            # 5288f7890eea00a744394650b4e55aee2ceebf00/lib/models/sky_cubemap.py:L82
            # Note: If sky mask quality is poor, avoid using sky_only mode.
            mask = image_info.masks.sky_mask.bool()
        elif opacity is not None:
            mask = (1.0 - opacity.squeeze(-1)) > 5.0e-3

        directions = image_info.rays.viewdirs

        directions = (directions.reshape(-1, 3) @ self.to_opengl.T).reshape(*directions.shape)
        directions = directions.contiguous()
        prefix = directions.shape[:-1]
        if mask is not None:
            back_light = torch.zeros_like(directions)  # Default back color: black
            if not mask.any():
                return back_light
            directions = directions[mask]

        directions = directions.reshape(-1, 3)
        light = dr.texture(
            self.base[None, ...], directions[None, None, ...], filter_mode="linear", boundary_mode="cube"
        )

        if mask is not None:
            back_light[mask] = light
            return back_light

        return light.view(*prefix, -1)

    def get_param_groups(self):
        return {
            self.class_prefix + "all": self.parameters(),
        }


class AffineTransform(nn.Module):
    def __init__(
        self,
        class_name: str,
        n: int,
        embedding_dim: int = 4,
        pixel_affine: bool = False,
        base_mlp_layer_width: int = 64,
        device: torch.device = torch.device("cuda"),
        apply_camera_names: List[str] = [],
        use_random_init: bool = False,
        use_camera_embedding: bool = False,
    ):
        super().__init__()
        self.class_prefix = class_name + "#"
        self.device = device
        self.embedding_dim = embedding_dim
        self.pixel_affine = pixel_affine
        self.use_camera_embedding = use_camera_embedding
        self.embedding = nn.Embedding(n, embedding_dim, dtype=torch.float32)

        input_dim = (embedding_dim + 2) if self.pixel_affine else embedding_dim
        self.decoder = nn.Sequential(
            nn.Linear(input_dim, base_mlp_layer_width),
            nn.ReLU(),
            nn.Linear(base_mlp_layer_width, 12),
        )
        self.in_test_set = False

        if use_random_init:
            self.random_init()
        else:
            self.zero_init()

    def zero_init(self):
        torch.nn.init.zeros_(self.embedding.weight)
        for layer in self.decoder:
            if isinstance(layer, nn.Linear):
                torch.nn.init.zeros_(layer.weight)
                torch.nn.init.zeros_(layer.bias)

    def random_init(self):
        logger.info(f"[INFO] Randomly initializing AffineTransform")
        # Initialize embedding with small noise to ensure gradients flow even when pixel_affine is False
        torch.nn.init.normal_(self.embedding.weight, mean=0.0, std=1e-3)

        # Keep the final layer at zero to start from identity affine, but allow earlier layers to learn
        linear_layers = [m for m in self.decoder if isinstance(m, nn.Linear)]
        for i, layer in enumerate(linear_layers):
            is_last = (i == len(linear_layers) - 1)
            if is_last:
                torch.nn.init.zeros_(layer.weight)
                torch.nn.init.zeros_(layer.bias)
            else:
                torch.nn.init.normal_(layer.weight, mean=0.0, std=1e-3)
                torch.nn.init.zeros_(layer.bias)

    def forward(self, image_info: ImageInfo, camera_info: Optional[CameraInfo] = None):
        # Select embedding id by camera or image
        if self.use_camera_embedding and not self.in_test_set:
            embed_id = camera_info.camera_id
            embed_id_tensor = torch.tensor([embed_id], device=image_info.image_index.device)
            embedding = self.embedding(embed_id_tensor)
        elif image_info.image_index is not None and not self.in_test_set:
            embedding = self.embedding(image_info.image_index)
        else:
            # use mean appearance embedding
            embedding = torch.ones(
                (*image_info.rays.viewdirs.shape[:-1], self.embedding_dim),
                device=image_info.rays.viewdirs.device,
            ) * self.embedding.weight.mean(dim=0)
        if self.pixel_affine:
            height, width = image_info.pixel_coords.shape[:2]
            embedding = embedding.view(1, 1, -1).expand(height, width, -1)
            embedding = torch.cat([embedding, image_info.pixel_coords], dim=-1)
        affine = self.decoder(embedding)
        affine = affine.reshape(*embedding.shape[:-1], 3, 4)

        affine[..., :3, :3] = affine[..., :3, :3] + torch.eye(3, device=affine.device).reshape(1, 3, 3)
        return affine

    def get_param_groups(self):
        return {
            self.class_prefix + "all": self.parameters(),
        }


class CameraOptModule(torch.nn.Module):
    """Camera pose optimization module."""

    def __init__(
        self,
        class_name: str,
        n: int,
        device: torch.device = torch.device("cuda"),
        use_random_init: bool = False,
    ):
        super().__init__()
        self.class_prefix = class_name + "#"
        self.device = device
        # Delta positions (3D) + Delta rotations (6D)
        self.embeds = torch.nn.Embedding(n, 9)
        # Identity rotation in 6D representation
        self.register_buffer("identity", torch.tensor([1.0, 0.0, 0.0, 0.0, 1.0, 0.0]))

        if use_random_init:
            self.random_init()
        else:
            self.zero_init()

    def zero_init(self):
        torch.nn.init.zeros_(self.embeds.weight)

    def random_init(self, std: float = 1e-3):
        logger.info("[INFO] Randomly initializing CameraOptModule")
        torch.nn.init.normal_(self.embeds.weight, std=std)

    def forward(self, camtoworlds: Tensor, embed_ids: Tensor) -> Tensor:
        """Adjust camera pose based on deltas.

        Args:
            camtoworlds: (..., 4, 4)
            embed_ids: (...,)

        Returns:
            updated camtoworlds: (..., 4, 4)
        """
        assert camtoworlds.shape[:-2] == embed_ids.shape
        batch_shape = camtoworlds.shape[:-2]
        pose_deltas = self.embeds(embed_ids)  # (..., 9)
        dx, drot = pose_deltas[..., :3], pose_deltas[..., 3:]
        rot = rotation_6d_to_matrix(drot + self.identity.expand(*batch_shape, -1))  # (..., 3, 3)
        transform = torch.eye(4, device=pose_deltas.device, dtype=camtoworlds.dtype).repeat((*batch_shape, 1, 1))
        transform[..., :3, :3] = rot
        transform[..., :3, 3] = dx
        return torch.matmul(camtoworlds, transform)

    def get_param_groups(self):
        return {
            self.class_prefix + "all": self.parameters(),
        }


def get_embedder(multires, i=1):
    if i == -1:
        return nn.Identity(), 3

    embed_kwargs = {
        "include_input": True,
        "input_dims": i,
        "max_freq_log2": multires - 1,
        "num_freqs": multires,
        "log_sampling": True,
        "periodic_fns": [torch.sin, torch.cos],
    }

    embedder_obj = Embedder(**embed_kwargs)

    def embed(x, eo=embedder_obj):
        return eo.embed(x)

    return embed, embedder_obj.out_dim


class Embedder:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.create_embedding_fn()

    def create_embedding_fn(self):
        embed_fns = []
        d = self.kwargs["input_dims"]
        out_dim = 0
        if self.kwargs["include_input"]:
            embed_fns.append(lambda x: x)
            out_dim += d

        max_freq = self.kwargs["max_freq_log2"]
        N_freqs = self.kwargs["num_freqs"]

        if self.kwargs["log_sampling"]:
            freq_bands = 2.0 ** torch.linspace(0.0, max_freq, steps=N_freqs)
        else:
            freq_bands = torch.linspace(2.0**0.0, 2.0**max_freq, steps=N_freqs)

        for freq in freq_bands:
            for p_fn in self.kwargs["periodic_fns"]:
                embed_fns.append(lambda x, p_fn=p_fn, freq=freq: p_fn(x * freq))
                out_dim += d

        self.embed_fns = embed_fns
        self.out_dim = out_dim

    def embed(self, inputs):
        return torch.cat([fn(inputs) for fn in self.embed_fns], -1)


class DeformNetwork(nn.Module):
    def __init__(self, D=8, W=256, input_ch=3, output_ch=59, x_multires=10, t_multires=10):
        super(DeformNetwork, self).__init__()
        self.D = D
        self.W = W
        self.input_ch = input_ch
        self.output_ch = output_ch
        self.x_multires = x_multires
        self.t_multires = t_multires
        self.skips = [D // 2]

        self.embed_time_fn, time_input_ch = get_embedder(self.t_multires, 1)
        self.embed_fn, xyz_input_ch = get_embedder(self.x_multires, 3)
        self.input_ch = xyz_input_ch + time_input_ch

        self.linear = nn.ModuleList(
            [nn.Linear(self.input_ch, W)]
            + [(nn.Linear(W, W) if i not in self.skips else nn.Linear(W + self.input_ch, W)) for i in range(D - 1)]
        )

        self.gaussian_warp = nn.Linear(W, 3)
        self.gaussian_rotation = nn.Linear(W, 4)
        self.gaussian_scaling = nn.Linear(W, 3)

    def forward(self, x, t):
        t_emb = self.embed_time_fn(t)
        x_emb = self.embed_fn(x)
        h = torch.cat([x_emb, t_emb], dim=-1)
        for i, l in enumerate(self.linear):
            h = self.linear[i](h)
            h = F.relu(h)
            if i in self.skips:
                h = torch.cat([x_emb, t_emb, h], -1)

        d_xyz = self.gaussian_warp(h)
        scaling = self.gaussian_scaling(h)
        rotation = self.gaussian_rotation(h)

        return d_xyz, rotation, scaling


class ConditionalDeformNetwork(nn.Module):
    def __init__(
        self,
        D=8,
        W=256,
        input_ch=3,
        embed_dim=10,
        x_multires=10,
        t_multires=10,
        deform_quat=True,
        deform_scale=True,
    ):
        super(ConditionalDeformNetwork, self).__init__()
        self.D = D
        self.W = W
        self.input_ch = input_ch
        self.embed_dim = embed_dim
        self.deform_quat = deform_quat
        self.deform_scale = deform_scale
        self.skips = [D // 2]

        self.embed_time_fn, time_input_ch = get_embedder(t_multires, 1)
        self.embed_fn, xyz_input_ch = get_embedder(x_multires, 3)
        self.input_ch = xyz_input_ch + time_input_ch + embed_dim

        self.linear = nn.ModuleList(
            [nn.Linear(self.input_ch, W)]
            + [(nn.Linear(W, W) if i not in self.skips else nn.Linear(W + self.input_ch, W)) for i in range(D - 1)]
        )

        self.gaussian_warp = nn.Linear(W, 3)
        if self.deform_quat:
            self.gaussian_rotation = nn.Linear(W, 4)
        if self.deform_scale:
            self.gaussian_scaling = nn.Linear(W, 3)

    def forward(self, x, t, condition):
        t_emb = self.embed_time_fn(t)
        x_emb = self.embed_fn(x)
        h = torch.cat([x_emb, t_emb, condition], dim=-1)
        for i, l in enumerate(self.linear):
            h = self.linear[i](h)
            h = F.relu(h)
            if i in self.skips:
                h = torch.cat([x_emb, t_emb, condition, h], -1)

        d_xyz = self.gaussian_warp(h)
        scaling, rotation = None, None
        if self.deform_scale:
            scaling = self.gaussian_scaling(h)
        if self.deform_quat:
            rotation = self.gaussian_rotation(h)

        return d_xyz, rotation, scaling


class VoxelDeformer(nn.Module):
    def __init__(
        self,
        vtx,
        vtx_features,
        resolution_dhw=[8, 32, 32],
        short_dim_dhw=0,  # 0 is d, corresponding to z
        long_dim_dhw=1,
        is_resume=False,
    ) -> None:
        super().__init__()
        # vtx B,N,3, vtx_features: B,N,J
        # d-z h-y w-x; human is facing z; dog is facing x, z is upward, should compress on y
        B = vtx.shape[0]
        assert vtx.shape[0] == vtx_features.shape[0], "Batch size mismatch"

        # * Prepare Grid
        self.resolution_dhw = resolution_dhw
        device = vtx.device
        d, h, w = self.resolution_dhw

        self.register_buffer(
            "ratio",
            torch.Tensor([self.resolution_dhw[long_dim_dhw] / self.resolution_dhw[short_dim_dhw]]).squeeze(),
        )
        self.ratio_dim = -1 - short_dim_dhw
        x_range = (torch.linspace(-1, 1, steps=w, device=device)).view(1, 1, 1, w).expand(1, d, h, w)
        y_range = (torch.linspace(-1, 1, steps=h, device=device)).view(1, 1, h, 1).expand(1, d, h, w)
        z_range = (torch.linspace(-1, 1, steps=d, device=device)).view(1, d, 1, 1).expand(1, d, h, w)
        grid = torch.cat((x_range, y_range, z_range), dim=0).reshape(1, 3, -1).permute(0, 2, 1)
        grid = grid.expand(B, -1, -1)

        gt_bbox_min = (vtx.min(dim=1).values).to(device)
        gt_bbox_max = (vtx.max(dim=1).values).to(device)
        offset = (gt_bbox_min + gt_bbox_max) * 0.5
        self.register_buffer("global_scale", torch.Tensor([1.2]).squeeze())  # from Fast-SNARF
        scale = ((gt_bbox_max - gt_bbox_min).max(dim=-1).values / 2 * self.global_scale).unsqueeze(-1)

        corner = torch.ones_like(offset) * scale
        corner[:, self.ratio_dim] /= self.ratio
        min_vert = (offset - corner).reshape(-1, 1, 3)
        max_vert = (offset + corner).reshape(-1, 1, 3)
        self.bbox = torch.cat([min_vert, max_vert], dim=1)

        self.register_buffer("scale", scale.unsqueeze(1))  # [B, 1, 1]
        self.register_buffer("offset", offset.unsqueeze(1))  # [B, 1, 3]

        grid_denorm = self.denormalize(grid)  # grid_denorm is in the same scale as the canonical body

        if not is_resume:
            weights = (
                self._query_weights_smpl(
                    grid_denorm,
                    smpl_verts=vtx.detach().clone(),
                    smpl_weights=vtx_features.detach().clone(),
                )
                .detach()
                .clone()
            )
        else:
            # random initialization
            weights = torch.randn(B, vtx_features.shape[-1], *resolution_dhw).to(device)

        self.register_buffer("lbs_voxel_base", weights.detach())
        self.register_buffer("grid_denorm", grid_denorm)

        self.num_bones = vtx_features.shape[-1]

        # # debug
        # import numpy as np
        # np.savetxt("./debug/dbg.xyz", grid_denorm[0].detach().cpu())
        # np.savetxt("./debug/vtx.xyz", vtx[0].detach().cpu())
        return

    def enable_voxel_correction(self):
        voxel_w_correction = torch.zeros_like(self.lbs_voxel_base)
        self.voxel_w_correction = nn.Parameter(voxel_w_correction)

    def enable_additional_correction(self, additional_channels, std=1e-4):
        additional_correction = (
            torch.ones(self.lbs_voxel_base.shape[0], additional_channels, *self.lbs_voxel_base.shape[2:]) * std
        )
        self.additional_correction = nn.Parameter(additional_correction)

    @property
    def get_voxel_weight(self):
        w = self.lbs_voxel_base
        if hasattr(self, "voxel_w_correction"):
            w = w + self.voxel_w_correction
        if hasattr(self, "additional_correction"):
            w = torch.cat([w, self.additional_correction], dim=1)
        return w

    def get_tv(self, name="dc"):
        if name == "dc":
            if not hasattr(self, "voxel_w_correction"):
                return torch.zeros(1).squeeze().to(self.lbs_voxel_base.device)
            d = self.voxel_w_correction
        elif name == "rest":
            if not hasattr(self, "additional_correction"):
                return torch.zeros(1).squeeze().to(self.lbs_voxel_base.device)
            d = self.additional_correction
        tv_x = torch.abs(d[:, :, 1:, :, :] - d[:, :, :-1, :, :]).mean()
        tv_y = torch.abs(d[:, :, :, 1:, :] - d[:, :, :, :-1, :]).mean()
        tv_z = torch.abs(d[:, :, :, :, 1:] - d[:, :, :, :, :-1]).mean()
        return (tv_x + tv_y + tv_z) / 3.0
        # tv_x = torch.abs(d[:, :, 1:, :, :] - d[:, :, :-1, :, :]).sum()
        # tv_y = torch.abs(d[:, :, :, 1:, :] - d[:, :, :, :-1, :]).sum()
        # tv_z = torch.abs(d[:, :, :, :, 1:] - d[:, :, :, :, :-1]).sum()
        # return tv_x + tv_y + tv_z

    def get_mag(self, name="dc"):
        if name == "dc":
            if not hasattr(self, "voxel_w_correction"):
                return torch.zeros(1).squeeze().to(self.lbs_voxel_base.device)
            d = self.voxel_w_correction
        elif name == "rest":
            if not hasattr(self, "additional_correction"):
                return torch.zeros(1).squeeze().to(self.lbs_voxel_base.device)
            d = self.additional_correction
        return torch.norm(d, dim=1).mean()

    def forward(self, xc, mode="bilinear"):
        shape = xc.shape  # ..., 3
        # xc = xc.reshape(1, -1, 3)
        w = F.grid_sample(
            self.get_voxel_weight,
            self.normalize(xc)[:, :, None, None],
            align_corners=True,
            mode=mode,
            padding_mode="border",
        )
        w = w.squeeze(3, 4).permute(0, 2, 1)
        w = w.reshape(*shape[:-1], -1)
        # * the w may have more channels
        return w

    def normalize(self, x):
        x_normalized = x.clone()
        x_normalized -= self.offset
        x_normalized /= self.scale
        x_normalized[..., self.ratio_dim] *= self.ratio
        return x_normalized

    def denormalize(self, x):
        x_denormalized = x.clone()
        x_denormalized[..., self.ratio_dim] /= self.ratio
        x_denormalized *= self.scale
        x_denormalized += self.offset
        return x_denormalized

    def _query_weights_smpl(self, x, smpl_verts, smpl_weights):
        # adapted from https://github.com/jby1993/SelfReconCode/blob/main/model/Deformer.py
        dist, idx, _ = knn_points(x, smpl_verts.detach(), K=30)  # [B, N, 30]
        dist = dist.sqrt().clamp_(0.0001, 1.0)
        expanded_smpl_weights = smpl_weights.unsqueeze(2).expand(-1, -1, idx.shape[2], -1)  # [B, N, 30, J]
        weights = expanded_smpl_weights.gather(
            1, idx.unsqueeze(-1).expand(-1, -1, -1, expanded_smpl_weights.shape[-1])
        )  # [B, N, 30, J]

        ws = 1.0 / dist
        ws = ws / ws.sum(-1, keepdim=True)
        weights = (ws[..., None] * weights).sum(-2)

        b = x.shape[0]
        c = smpl_weights.shape[-1]
        d, h, w = self.resolution_dhw
        weights = weights.permute(0, 2, 1).reshape(b, c, d, h, w)
        for _ in range(30):
            mean = (
                weights[:, :, 2:, 1:-1, 1:-1]
                + weights[:, :, :-2, 1:-1, 1:-1]
                + weights[:, :, 1:-1, 2:, 1:-1]
                + weights[:, :, 1:-1, :-2, 1:-1]
                + weights[:, :, 1:-1, 1:-1, 2:]
                + weights[:, :, 1:-1, 1:-1, :-2]
            ) / 6.0
            weights[:, :, 1:-1, 1:-1, 1:-1] = (weights[:, :, 1:-1, 1:-1, 1:-1] - mean) * 0.7 + mean
            sums = weights.sum(1, keepdim=True)
            weights = weights / sums
        return weights.detach()


class Conv1DMLP(nn.Module):
    def __init__(
        self,
        input_channels: int,
        output_channels: int,
        channels: List[int],  # List of channels, different for each layer
        activation: Literal["ReLU", "SiLU", "ELU", "None"] = "ReLU",
        output_activation: Literal["ReLU", "Sigmoid", "None"] = "None",
        kernel_size: int = 1,
    ):
        """
        1D CNN version of MLP network, suitable for point cloud feature extraction.

        Args:
            input_channels (int): Input channels (equivalent to input features in MLP)
            output_channels (int): Output channels
            channels (List[int]): Number of channels per layer (length represents number of network layers)
            activation (str): Activation function for hidden layers (ReLU, SiLU, ELU, None)
            output_activation (str): Activation function for output layer (ReLU, Sigmoid, None)
            kernel_size (int): 1D convolution kernel size (default: 1)
        """
        super().__init__()

        assert len(channels) > 0, "Must have at least one hidden layer"

        self.layers = nn.ModuleList()
        in_channels = input_channels

        # 1. Add hidden layers
        for out_channels in channels:
            self.layers.append(self._conv_block(in_channels, out_channels, kernel_size, activation))
            in_channels = out_channels  # Update input channels

        # 2. Add output layer
        self.layers.append(
            self._conv_block(in_channels, output_channels, kernel_size, output_activation, is_output=True)
        )

        self.weight_init()

    def weight_init(self):
        """
        Initialize all weights and biases in the network to zero.
        """
        for layer in self.layers:
            for module in layer:
                if isinstance(module, nn.Conv1d):
                    nn.init.normal_(module.weight, mean=0.0, std=0.01)
                    nn.init.zeros_(module.bias)

    def _conv_block(self, in_channels, out_channels, kernel_size, activation, is_output=False):
        """
        Build a 1D CNN convolution block, including Conv1d + activation function.
        """
        layers = []
        layers.append(nn.Conv1d(in_channels, out_channels, kernel_size, stride=1, padding=kernel_size // 2))

        if not is_output and activation != "None":
            layers.append(self._get_activation(activation))

        return nn.Sequential(*layers)

    def _get_activation(self, name: str):
        if name == "None":
            return None
        if name == "ReLU":
            return nn.ReLU()
        if name == "Sigmoid":
            return nn.Sigmoid()
        if name == "SiLU":  # SiLU (Sigmoid Linear Unit)
            return nn.SiLU()
        if name == "ELU":  # ELU (Exponential Linear Unit)
            return nn.ELU()
        if name == "tanh":
            return nn.Tanh()
        raise ValueError("unsupported activation type {}".format(name))

    def forward(self, x):
        """
        Forward pass
        Input `x`: [batch_size, channels, point cloud numbers]
        """
        x = x.unsqueeze(0)  # [1, N, C]
        x = x.permute(0, 2, 1)  # [1, C, N]

        for layer in self.layers:
            x = layer(x)

        x = x.permute(0, 2, 1).squeeze(0)  # [N, output_channels]
        return x


class PositionalEncoding(torch.nn.Module):
    def __init__(self, input_channels: int, num_frequencies: int, log_sampling: bool = True):
        """
        Defines a function that embeds x to (x, sin(2^k x), cos(2^k x), ...)
        in_channels: number of input channels (3 for both xyz and direction)
        """
        super().__init__()
        self.num_frequencies = num_frequencies
        self.input_channels = input_channels
        self.funcs = [torch.sin, torch.cos]
        self.output_channels = input_channels * (len(self.funcs) * num_frequencies + 1)

        max_frequencies = num_frequencies - 1
        if log_sampling:
            self.freq_bands = 2.0 ** torch.linspace(0.0, max_frequencies, steps=num_frequencies)
        else:
            self.freq_bands = torch.linspace(2.0**0.0, 2.0**max_frequencies, steps=num_frequencies)

    def forward(self, x):
        """
        Embeds x to (x, sin(2^k x), cos(2^k x), ...)
        Different from the paper, "x" is also in the output
        See https://github.com/bmild/nerf/issues/12

        Inputs:
            x: (B, self.in_channels)

        Outputs:
            out: (B, self.out_channels)
        """
        out = [x]
        for freq in self.freq_bands:
            for func in self.funcs:
                out += [func(freq * x)]

        return torch.cat(out, -1)

    def get_output_n_channels(self) -> int:
        return self.output_channels
