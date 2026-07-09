"""
Filename: 3dgs.py

Author: Ziyu Chen (ziyu.sjtu@gmail.com)

Description:
Unofficial implementation of 3DGS based on the work by Bernhard Kerbl, Georgios Kopanas, Thomas Leimkühler,
and George Drettakis.
This implementation is modified from the nerfstudio GaussianSplattingModel.

- Original work by Bernhard Kerbl, Georgios Kopanas, Thomas Leimkühler, and George Drettakis.
- Codebase reference: nerfstudio GaussianSplattingModel
(https://github.com/nerfstudio-project/nerfstudio/blob/gaussian-splatting/nerfstudio/models/gaussian_splatting.py)

Original paper: https://arxiv.org/abs/2308.04079
"""

import logging
from typing import Dict, List, Optional
import numpy as np

import torch
import torch.nn as nn
from gsplat.cuda._wrapper import spherical_harmonics
from omegaconf import OmegaConf
from torch.nn import Parameter

from ..appearance_embedding import AppearanceEmbeddingModel
from .basics import (
    dataclass_camera,
    num_sh_bases,
    IDFT,
)

from plyfile import PlyData
from .basics import (
    RGB2SH,
    k_nearest_sklearn,
    random_quat_tensor,
    inverse_sigmoid,
    IDFT,
)

logger = logging.getLogger()

MAX_FROZEN_Z_GAUSSIAN_SCALE = 0.1
MAX_FROZEN_GAUSSIAN_SCALE = 2.0
MAX_2D_SCREEN_SIZE = 0.5


class VanillaGaussians_render(nn.Module):
    def __init__(
        self,
        class_name: str,
        ctrl: OmegaConf,
        reg: OmegaConf = None,
        networks: OmegaConf = None,
        appearance_embedding: OmegaConf = None,
        scene_scale: float = 30.0,
        scene_origin: torch.Tensor = torch.zeros(3),
        num_train_images: int = 300,
        device: torch.device = torch.device("cuda"),
        data_source: str = 'lidar',
        model_path: str = None,
        **kwargs,
    ):
        super().__init__()

        self.class_prefix = class_name + "#"
        self.ctrl_cfg = ctrl
        self.reg_cfg = reg
        self.networks_cfg = networks
        self.appearance_embedding_cfg = appearance_embedding
        self.scene_scale = scene_scale
        self.scene_origin = scene_origin
        self.num_train_images = num_train_images
        self.step = 0
        self.data_source = data_source
        self.use_feedforawrd = False
        self.hil_mode = False
        self.model_path = model_path

        self.device = device
        self.ball_gaussians = self.ctrl_cfg.get("ball_gaussians", False)
        self.gaussian_2d = self.ctrl_cfg.get("gaussian_2d", False)
        self.freeze_means = self.ctrl_cfg.get("freeze_means", False)

        # Initialize Trafficlight
        self.fourier_dim = self.ctrl_cfg.get("fourier_dim", 100)
        self.fourier_scale = self.ctrl_cfg.get("fourier_scale", 1.0)
        self.start_frame = 0
        self.end_frame = num_train_images // 7
        self.class_name = class_name

        # for evaluation
        self.in_test_set = False

        # init models
        self.xys_grad_norm = None
        self.max_2Dsize = None
        self._means = torch.zeros(1, 3, device=self.device)
        if self.ball_gaussians:
            self._scales = torch.zeros(1, 1, device=self.device)
        else:
            if self.gaussian_2d:
                self._scales = torch.zeros(1, 2, device=self.device)
            else:
                self._scales = torch.zeros(1, 3, device=self.device)
        self._quats = torch.zeros(1, 4, device=self.device)
        self._opacities = torch.zeros(1, 1, device=self.device)
        if class_name == "Trafficlight":
            self._features_dc = torch.zeros(1, self.fourier_dim, 3, device=self.device)
        else:
            self._features_dc = torch.zeros(1, 3, device=self.device)
        self._features_rest = torch.zeros(1, num_sh_bases(self.sh_degree) - 1, 3, device=self.device)

        if self.appearance_embedding_cfg:
            self.appearance_feature_dims = self.appearance_embedding_cfg.get("input_feature_dims", 8)
            self._appearance_features = Parameter(torch.zeros((1, self.appearance_feature_dims), device=self.device))
            self.appearance_embedding_model = AppearanceEmbeddingModel(**self.appearance_embedding_cfg).to(self.device)

        self.activated_opacities = None
        self.activated_scales = None
        self.activated_rotations = None
        self.in_training_job = True

    def create_from_feedforward(self, g3r_path, num_points, class_name, random_pts = None):
        self.use_feedforawrd = True
        plydata = PlyData.read(g3r_path)
        vertices = plydata['vertex']

        if len(vertices) > num_points:
            indices = np.random.choice(len(vertices), size=num_points, replace=False)
            vertices = vertices[indices]
        print(f"Feed forward points from ply: {len(vertices)}")

        # means
        ply_means = np.vstack([vertices['px'], vertices['py'], vertices['pz']]).T
        ply_means = torch.from_numpy(ply_means).float().to(self.device)
        random_means = torch.empty(0, 3).float().to(self.device)
        num_random_pts = 0
        if random_pts is not None:
            random_means = random_pts.float().to(self.device)
            num_random_pts = random_means.shape[0]
            logging.info(f"Additional random points: {num_random_pts}")

        combined_means = torch.cat([ply_means, random_means], dim=0)
        num_combined = combined_means.shape[0]
        logging.info(f"Total combined points: {num_combined}")
        self._means = Parameter(combined_means)
        if self.freeze_means:
            self._means.requires_grad = False

        # colors
        ply_colors = torch.from_numpy(np.vstack([vertices['red'], vertices['green'], vertices['blue']]).T).float()
        ply_colors = ply_colors.to(self.device)
        random_colors = torch.empty(0, 3).float().to(self.device)
        if num_random_pts > 0:
            random_colors = torch.rand(random_means.shape).to(self.device)
        random_colors_convert = RGB2SH(random_colors)
        ply_colors_convert = RGB2SH(ply_colors)
        fused_color = torch.cat([ply_colors_convert, random_colors_convert], dim=0)

        dim_sh = num_sh_bases(self.sh_degree)
        shs = torch.zeros((fused_color.shape[0], dim_sh, 3)).float().to(self.device)
        if self.sh_degree > 0:
            shs[:, 0, :3] = fused_color
            shs[:, 1:, 3:] = 0.0
        else:
            init_colors = fused_color
            shs[:, 0, :3] = torch.logit(init_colors, eps=1e-10)
        self._features_dc = Parameter(shs[:, 0, :])
        self._features_rest = Parameter(shs[:, 1:, :])

        # rotation
        ply_quats = torch.from_numpy(np.vstack([vertices['qw'], vertices['qx'], vertices['qy'], vertices['qz']]).T).float()
        ply_quats = ply_quats.to(self.device)
        random_quats = torch.empty(0, 4).float().to(self.device)
        if num_random_pts > 0:
            random_quats = random_quat_tensor(num_random_pts).to(self.device)
        combined_quats = torch.cat([ply_quats, random_quats], dim=0)
        self._quats = Parameter(combined_quats.requires_grad_(True))

        # scales
        ply_scales = torch.from_numpy(np.vstack([vertices['sx'], vertices['sy'], vertices['sz']]).T).float()
        ply_scales = ply_scales.to(self.device)
        num_ply_points = ply_scales.shape[0]
        random_scales = torch.empty(0, 3).float().to(self.device)
        if num_random_pts > 0:
            distances, _ = k_nearest_sklearn(combined_means, k=3)
            distances = torch.from_numpy(distances).float().to(self.device)
            random_distances = distances[num_ply_points:, :]
            avg_dist = random_distances.mean(dim=-1, keepdim=True)
            random_scales = avg_dist.repeat(1, 3)

        combined_scales = torch.cat([ply_scales, random_scales], dim=0)
        eps = 1e-8
        scales_safe = torch.clamp(combined_scales, min=eps, max=1 - eps)
        self._scales = torch.log(scales_safe).to(self.device)
        self._scales = Parameter(self._scales.requires_grad_(True))

        # opacities
        ply_opacities = torch.from_numpy(np.array(vertices['opacity']).reshape(-1, 1)).float()
        ply_opacities = ply_opacities.to(self.device)
        random_opacities = torch.empty(0, 1).float().to(self.device)
        if num_random_pts > 0:
            random_opacities = torch.logit(0.1 * torch.ones(num_random_pts, 1, device=self.device))
        if class_name == "Ground":
            opacities = inverse_sigmoid(ply_opacities).to(self.device)
        else:
            opacities = ply_opacities
        combined_opacities = torch.cat([ply_opacities, random_opacities], dim=0)
        self._opacities = nn.Parameter(combined_opacities)

        if self.freeze_means:
            self._opacities = Parameter(torch.logit(torch.ones(self.num_points, 1, device=self.device)))
            self._opacities.requires_grad = False

        if self.appearance_embedding_cfg:
            self._appearance_features = Parameter(
                torch.zeros((self._means.shape[0], self.appearance_feature_dims)).float().to(self.device)
            )
        logging.info(f"Create from feedforward success")
        return self._means.shape[0]

    def create_from_2dgs_ply(self, ply_path: str) -> None:
        """
        从2dgs的ply文件初始化高斯模型，支持rgb和SH两种颜色表示
        """
        plydata = PlyData.read(ply_path)
        vertices = plydata['vertex']

        # 坐标
        means = torch.from_numpy(np.vstack([vertices['x'], vertices['y'], vertices['z']]).T).to(self.device)
        self._means = Parameter(means)
        if self.freeze_means:
            self._means.requires_grad = False

        # 缩放
        names = vertices.data.dtype.names
        if 'scale_2' in names:
            scales = torch.from_numpy(np.vstack([vertices['scale_0'], vertices['scale_1'], vertices['scale_2']]).T)
        else:
            # 只用scale_0和scale_1，scale_2补一个小值
            scale_0 = np.array(vertices['scale_0'])
            scale_1 = np.array(vertices['scale_1'])
            scale_2 = np.full_like(scale_0, np.log(0.01))  # 或 0.1，根据实际需求
            scales = torch.from_numpy(np.vstack([scale_0, scale_1, scale_2]).T)
        self._scales = Parameter(scales.to(self.device).requires_grad_(True))

        # 旋转
        quats = torch.from_numpy(np.vstack([vertices['rot_0'], vertices['rot_1'], vertices['rot_2'], vertices['rot_3']]).T).to(self.device)
        self._quats = Parameter(quats.requires_grad_(True))

        # 透明度
        raw_opacities = torch.from_numpy(np.array(vertices['opacity']).reshape(-1, 1)).to(self.device)
        opacities = torch.sigmoid(raw_opacities)
        opacities *= 0.5 # 初始透明度缩小一半，避免初始阶段过于浓密
        self._opacities = nn.Parameter(torch.logit(opacities))
        if self.freeze_means:
            self._opacities = Parameter(torch.logit(torch.ones(self.num_points, 1, device=self.device)))
            self._opacities.requires_grad = False

        # 颜色分支
        names = vertices.data.dtype.names
        if 'r' in names and 'g' in names and 'b' in names:
            # RGB颜色
            init_colors = torch.from_numpy(np.vstack([vertices['r'], vertices['g'], vertices['b']]).T).to(self.device)
            fused_color = RGB2SH(init_colors)
            dim_sh = num_sh_bases(self.sh_degree)
            shs = torch.zeros((fused_color.shape[0], dim_sh, 3)).float().to(self.device)
            if self.sh_degree > 0:
                shs[:, 0, :3] = fused_color
                shs[:, 1:, 3:] = 0.0
            else:
                shs[:, 0, :3] = torch.logit(init_colors, eps=1e-10)
            self._features_dc = Parameter(shs[:, 0, :])
            self._features_rest = Parameter(shs[:, 1:, :])
        elif 'f_dc_0' in names and 'f_dc_1' in names and 'f_dc_2' in names:
            # SH颜色
            f_dc = torch.from_numpy(np.vstack([vertices['f_dc_0'], vertices['f_dc_1'], vertices['f_dc_2']]).T).to(self.device)
            # f_rest数量自动推断
            f_rest_names = [n for n in names if n.startswith('f_rest_')]
            f_rest = torch.from_numpy(np.vstack([vertices[n] for n in f_rest_names]).T).to(self.device)
            if f_rest.dim() == 2:
                f_rest = f_rest.unsqueeze(-1).expand(-1, -1, 3).clone() 
            # shape调整为 (N, SH, 3) 或 (N, SH)
            # 这里假设 f_rest 是 (N, SH, 3)，如有不同请根据实际调整
            self._features_dc = Parameter(f_dc)
            self._features_rest = Parameter(f_rest)
        else:
            raise ValueError("Ply file doesn't contain recognizable color fields (r/g/b or f_dc/f_rest)")

        # appearance embedding
        if self.appearance_embedding_cfg:
            self._appearance_features = Parameter(
                torch.zeros((self._means.shape[0], self.appearance_feature_dims)).float().to(self.device)
            )

    @property
    def get_xyz(self):
        return self._means

    @property
    def sh_degree(self):
        return self.ctrl_cfg.sh_degree

    @property
    def get_opacity(self):
        return torch.sigmoid(self._opacities)

    @property
    def get_quats(self):
        return self.quat_act(self._quats)

    def quat_act(self, x: torch.Tensor) -> torch.Tensor:
        return x / x.norm(dim=-1, keepdim=True)

    def get_features_fourier(self, frame=0):
        normalized_frame = (frame - self.start_frame) / (self.end_frame - self.start_frame)
        time = self.fourier_scale * normalized_frame
        idft_base = IDFT(time, self.fourier_dim)[0].cuda()
        features_dc = self._features_dc # [N, C, 3]
        features_dc = torch.sum(features_dc * idft_base[..., None], dim=1, keepdim=True) # [N, 1, 3]
        features_rest = self._features_rest # [N, sh, 3]
        features = torch.cat([features_dc, features_rest], dim=1) # [N, (sh + 1) * C, 3]
        return features

    @property
    def get_scaling(self):
        if self.ball_gaussians:
            if self.gaussian_2d:
                scaling = torch.exp(self._scales).repeat(1, 2)
                scaling = torch.cat([scaling, torch.zeros_like(scaling[..., :1])], dim=-1)
                return scaling
            else:
                return torch.exp(self._scales).repeat(1, 3)
        else:
            if self.gaussian_2d:
                scaling = torch.exp(self._scales)
                scaling = torch.cat([scaling[..., :2], torch.zeros_like(scaling[..., :1])], dim=-1)
                return scaling
            else:
                return torch.exp(self._scales)

    def get_param_groups(self) -> Dict[str, List[Parameter]]:
        param_groups = self.get_gaussian_param_groups()
        if self.appearance_embedding_cfg:
            param_groups.update(
                {self.class_prefix + "appearance_embedding_model": list(self.appearance_embedding_model.parameters())}
            )
        return param_groups

    def get_gaussian_param_groups(self) -> Dict[str, List[Parameter]]:
        param_groups = {
            self.class_prefix + "sh_dc": [self._features_dc],
            self.class_prefix + "sh_rest": [self._features_rest],
            self.class_prefix + "scaling": [self._scales],
            self.class_prefix + "rotation": [self._quats],
        }
        if not self.freeze_means:
            param_groups.update({self.class_prefix + "xyz": [self._means]})
            param_groups.update({self.class_prefix + "opacity": [self._opacities]})
        if self.appearance_embedding_cfg:
            param_groups.update({self.class_prefix + "appearance_features": [self._appearance_features]})

        return param_groups

    def get_gaussians(self, cam: dataclass_camera, save_filter_mask: bool = True) -> Dict:
        if self.in_training_job:
            filter_mask = torch.ones_like(self._means[:, 0], dtype=torch.bool)
            if save_filter_mask:
                self.filter_mask = filter_mask

        # get colors of gaussians
        if self.class_name == "Trafficlight":
            colors = self.get_features_fourier(cam.timestep_id)
        else:
            colors = torch.cat((self._features_dc[:, None, :], self._features_rest), dim=1)
        if self.sh_degree > 0:
            viewdirs = self._means.detach() - cam.camtoworlds.data[..., :3, 3]  # (N, 3)
            viewdirs = viewdirs / viewdirs.norm(dim=-1, keepdim=True)
            n = min(self.step // self.ctrl_cfg.sh_degree_interval, self.sh_degree)
            rgbs = spherical_harmonics(n, viewdirs, colors)
            rgbs = torch.clamp(rgbs + 0.5, 0.0, 1.0)
        else:
            rgbs = torch.sigmoid(colors[:, 0, :])
        
        if self.in_training_job or self.activated_opacities is None:
            self.activated_opacities = self.get_opacity
            self.activated_scales = self.get_scaling
            self.activated_rotations = self.get_quats

        if self.appearance_embedding_cfg:
            rgb_offset = self.appearance_embedding_model(
                self._appearance_features,
                camera_id=torch.Tensor([cam.camera_id]).int().to(self.device),
                timestep_id=torch.Tensor([cam.timestep_id]).int().to(self.device),
                viewdirs=viewdirs,
                is_novel_view=torch.Tensor([cam.novel_view]).int().to(self.device),
            )
            # add rgb_offset to rgbs
            activated_colors = torch.clamp(rgbs + rgb_offset, min=0.0, max=1.0)
        else:
            activated_colors = rgbs

        # collect gaussians information
        if self.in_training_job:
            gs_dict = dict(
                _means=self._means[filter_mask],
                _opacities=self.activated_opacities[filter_mask],
                _rgbs=activated_colors[filter_mask],
                _scales=self.activated_scales[filter_mask],
                _quats=self.activated_rotations[filter_mask],
            )
        else:
            gs_dict = dict(
                _means=self._means,
                _opacities=self.activated_opacities,
                _rgbs=activated_colors,
                _scales=self.activated_scales,
                _quats=self.activated_rotations,
            )

        return gs_dict

    def get_gaussians_multi_cam(self, cams: list[dataclass_camera], save_filter_mask: bool = True) -> Dict:
        multi_cam_rgbs = {}
        # get colors of gaussians
        if self.class_name == "Trafficlight":
            colors = self.get_features_fourier(cams[0].timestep_id)
        else:
            colors = torch.cat((self._features_dc[:, None, :], self._features_rest), dim=1)
        if self.sh_degree > 0:
            for cam in cams:
                viewdirs = self._means.detach() - cam.camtoworlds.data[..., :3, 3]  # (N, 3)
                viewdirs = viewdirs / viewdirs.norm(dim=-1, keepdim=True)
                n = min(self.step // self.ctrl_cfg.sh_degree_interval, self.sh_degree)
                rgbs = spherical_harmonics(n, viewdirs, colors)
                rgbs = torch.clamp(rgbs + 0.5, 0.0, 1.0)
                multi_cam_rgbs[cam.camera_id] = rgbs
        else:
            for cam in cams:
                rgbs = torch.sigmoid(colors[:, 0, :])
                multi_cam_rgbs[cam.camera_id] = rgbs
        
        if self.in_training_job or self.activated_opacities is None:
            self.activated_opacities = self.get_opacity
            self.activated_scales = self.get_scaling
            self.activated_rotations = self.get_quats

        if self.appearance_embedding_cfg:
            for cam in cams:
                rgb_offset = self.appearance_embedding_model(
                    self._appearance_features,
                    camera_id=torch.Tensor([cam.camera_id]).int().to(self.device),
                    timestep_id=torch.Tensor([cam.timestep_id]).int().to(self.device),
                    viewdirs=viewdirs,
                    is_novel_view=torch.Tensor([cam.novel_view]).int().to(self.device),
                )
                # add rgb_offset to rgbs
                multi_cam_rgbs[cam.camera_id] = torch.clamp(multi_cam_rgbs[cam.camera_id] + rgb_offset, min=0.0, max=1.0)
        
        activated_colors = torch.stack(list(multi_cam_rgbs.values()), dim=0)

        # collect gaussians information
        gs_dict = dict(
            _means=self._means,
            _opacities=self.activated_opacities,
            _rgbs=activated_colors,
            _scales=self.activated_scales,
            _quats=self.activated_rotations,
        )

        return gs_dict

    def load_state_dict(self, state_dict: Dict, **kwargs) -> str:
        N = state_dict["_means"].shape[0]
        self._means = Parameter(torch.zeros((N,) + self._means.shape[1:], device=self.device))
        self._scales = Parameter(torch.zeros((N,) + self._scales.shape[1:], device=self.device))
        self._quats = Parameter(torch.zeros((N,) + self._quats.shape[1:], device=self.device))
        self._features_dc = Parameter(torch.zeros((N,) + self._features_dc.shape[1:], device=self.device))
        self._features_rest = Parameter(torch.zeros((N,) + self._features_rest.shape[1:], device=self.device))
        self._opacities = Parameter(torch.zeros((N,) + self._opacities.shape[1:], device=self.device))

        if self.appearance_embedding_cfg:
            self._appearance_features = Parameter(
                torch.zeros((N,) + self._appearance_features.shape[1:], device=self.device)
            )
        msg = super().load_state_dict(state_dict, **kwargs)
        if self.freeze_means:
            self._means.requires_grad = False
            self._opacities.requires_grad = False
        return msg
    
    