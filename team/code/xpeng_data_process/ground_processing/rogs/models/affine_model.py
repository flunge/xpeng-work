import logging
import math
import os
from typing import Optional

import torch
import torch.nn as nn


logger = logging.getLogger(__name__)


class AffineTransform(nn.Module):
    """
    RoGS 版本的 AffineTransform，实现与 reconic.models.modules.AffineTransform
    相同的结构（embedding + MLP 输出 3x4 仿射矩阵），但去掉了对 ImageInfo/CameraInfo 的依赖。

    当前仅支持基于图像索引的全局颜色仿射（pixel_affine=False）。
    """

    def __init__(
        self,
        n: int,
        embedding_dim: int = 4,
        pixel_affine: bool = False,
        base_mlp_layer_width: int = 64,
        device: torch.device = torch.device("cuda"),
        use_random_init: bool = False,
    ):
        super().__init__()
        self.device = device
        self.embedding_dim = embedding_dim
        self.pixel_affine = pixel_affine
        self.embedding = nn.Embedding(n, embedding_dim, dtype=torch.float32)

        if pixel_affine:
            raise NotImplementedError("RoGS AffineTransform 当前不支持 pixel_affine=True")

        input_dim = embedding_dim
        self.decoder = nn.Sequential(
            nn.Linear(input_dim, base_mlp_layer_width),
            nn.ReLU(),
            nn.Linear(base_mlp_layer_width, 12),
        )

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
        logger.info("[RoGS][AffineTransform] Randomly initializing AffineTransform")
        # 与 reconic 版本保持一致：embedding 有微小噪声，最后一层保持 0
        torch.nn.init.normal_(self.embedding.weight, mean=0.0, std=1e-3)

        linear_layers = [m for m in self.decoder if isinstance(m, nn.Linear)]
        for i, layer in enumerate(linear_layers):
            is_last = i == len(linear_layers) - 1
            if is_last:
                torch.nn.init.zeros_(layer.weight)
                torch.nn.init.zeros_(layer.bias)
            else:
                torch.nn.init.normal_(layer.weight, mean=0.0, std=1e-3)
                torch.nn.init.zeros_(layer.bias)

    def get_affine_matrix(self, image_idx: torch.Tensor) -> torch.Tensor:
        """
        根据图像索引返回仿射矩阵。

        Args:
            image_idx: LongTensor，形状 (1,) 或 (B,)，每个元素为图像索引。

        Returns:
            仿射矩阵张量，形状 (B, 3, 4)，其中前 3x3 为接近单位阵的颜色线性变换，后一列为偏置。
        """
        if image_idx.dim() == 0:
            image_idx = image_idx.view(1)
        embed = self.embedding(image_idx.to(self.device))  # (B, D)
        affine_vec = self.decoder(embed)  # (B, 12)
        affine = affine_vec.view(-1, 3, 4)  # (B, 3, 4)
        # 在对角线上加 1，从零矩阵开始学习到接近单位阵的偏移
        eye = torch.eye(3, device=affine.device).view(1, 3, 3)
        affine[:, :, :3] = affine[:, :, :3] + eye
        return affine


class RoGSAffineModule:
    """
    封装 RoGS 训练中用到的 affine 模块逻辑：
    - 从配置构建 AffineTransform 与优化器
    - 进行学习率调度（与 sim3dgs_v410.yaml 中 Affine 配置一致）
    - 在渲染 RGB 上应用仿射变换
    - 计算仿射正则损失
    - 负责优化器 step 与保存权重
    """
    def __init__(self, affine_cfg: dict, num_embeddings: int, device: torch.device, logger_: Optional[logging.Logger] = None):
        self.device = device
        self.logger = logger_ or logger

        affine_params = affine_cfg.get("params", {})
        affine_optim_all = affine_cfg.get("optim", {}).get("all", {})
        self.loss_weight = float(affine_cfg.get("loss_weight", 1.0e-5))

        self.model = AffineTransform(
            n=num_embeddings,
            embedding_dim=int(affine_params.get("embedding_dim", 4)),
            pixel_affine=bool(affine_params.get("pixel_affine", False)),
            base_mlp_layer_width=int(affine_params.get("base_mlp_layer_width", 64)),
            device=device,
            use_random_init=bool(affine_params.get("use_random_init", True)),
        ).to(device)

        self.base_lr = float(affine_optim_all.get("lr", 5.0e-4))
        self.lr_final = float(affine_optim_all.get("lr_final", 1.0e-4))
        self.warmup_steps = int(affine_optim_all.get("warmup_steps", 1000))
        self.max_steps = int(affine_optim_all.get("max_steps", 10000))
        self.lr_pre_warmup = float(affine_optim_all.get("lr_pre_warmup", 1.0e-7))
        self.ramp = affine_optim_all.get("ramp", "cosine")
        weight_decay = float(affine_optim_all.get("weight_decay", 1.0e-6))

        self.optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=self.base_lr,
            weight_decay=weight_decay,
        )

    def _lr_schedule(self, step: int) -> float:
        if step < self.warmup_steps:
            ratio = min(1.0, step / max(1, self.warmup_steps))
            if self.ramp == "cosine":
                lr = self.lr_pre_warmup + (self.base_lr - self.lr_pre_warmup) * math.sin(0.5 * math.pi * ratio)
            else:
                lr = self.lr_pre_warmup + (self.base_lr - self.lr_pre_warmup) * ratio
        else:
            t = min(1.0, (step - self.warmup_steps) / max(1, self.max_steps - self.warmup_steps))
            lr = math.exp(math.log(self.base_lr) * (1.0 - t) + math.log(self.lr_final) * t)
        return lr

    def update_lr(self, step: int):
        lr = self._lr_schedule(step)
        for g in self.optimizer.param_groups:
            g["lr"] = lr

    def apply(self, render_image: torch.Tensor, image_idx: int):
        """
        对渲染图像施加仿射颜色变换。

        Args:
            render_image: (H, W, 3) 的张量，值域假定在 [0,1]
            image_idx: 当前样本在数据集中的索引（int）

        Returns:
            render_image_affine: 施加仿射后的图像张量，形状同 render_image
            affine_mat: 对应的仿射矩阵，形状 (1, 3, 4)
        """
        idx_tensor = torch.tensor([image_idx], dtype=torch.long, device=self.device)
        affine_mat = self.model.get_affine_matrix(idx_tensor)  # (1, 3, 4)

        A = affine_mat[0, :, :3]  # (3, 3)
        b = affine_mat[0, :, 3:]  # (3, 1)

        H, W, _ = render_image.shape
        rgb_flat = render_image.view(-1, 3).T  # (3, N)
        rgb_affine_flat = (A @ rgb_flat + b)  # (3, N)
        render_image_affine = rgb_affine_flat.T.view(H, W, 3)
        render_image_affine = torch.clamp(render_image_affine, 0.0, 1.0)
        return render_image_affine, affine_mat

    def regularization_loss(self, affine_mat: torch.Tensor) -> torch.Tensor:
        """
        仿射正则：鼓励仿射矩阵接近单位矩阵和零偏置。

        Args:
            affine_mat: (1, 3, 4) 仿射矩阵
        """
        if affine_mat is None:
            return torch.zeros((), device=self.device)

        reg_mat = torch.eye(3, device=self.device).view(1, 3, 3)
        reg_shift = torch.zeros(1, 3, 1, device=self.device)
        loss_affine = (
            torch.abs(affine_mat[..., :3, :3] - reg_mat).mean()
            + torch.abs(affine_mat[..., :3, 3:] - reg_shift).mean()
        )
        return self.loss_weight * loss_affine

    def step(self):
        self.optimizer.step()

    def zero_grad(self):
        self.optimizer.zero_grad(set_to_none=True)

    def save(self, output_root: str):
        os.makedirs(output_root, exist_ok=True)
        affine_ckpt_path = os.path.join(output_root, "affine_transform.pth")
        torch.save(self.model.state_dict(), affine_ckpt_path)


