import math
from typing import Dict, Optional, Tuple

import torch
from torch import Tensor

# lazy import built extension
class _LazyC:
    _mod = None
    def __getattr__(self, name):
        if self._mod is None:
            import importlib
            self._mod = importlib.import_module('xpeng_raster._C')
        return getattr(self._mod, name)

_C = _LazyC()


def rasterization(
    means: Tensor,  # [..., N, 3]
    quats: Tensor,  # [..., N, 4]
    scales: Tensor,  # [..., N, 3]
    opacities: Tensor,  # [..., N]
    colors: Tensor,  # [..., (C,) N, 3] RGB only
    viewmats: Tensor,  # [..., C, 4, 4]
    Ks: Tensor,  # [..., C, 3, 3]
    width: int,
    height: int,
    near_plane: float = 0.01,
    far_plane: float = 1e10,
    radius_clip: float = 0.0,
    eps2d: float = 0.3,
    packed: bool = False,
    tile_size: int = 16,
    backgrounds: Optional[Tensor] = None,
    masks: Optional[Tensor] = None,
    far_planes: Optional[Tensor] = None,
) -> Tuple[Tensor, Tensor, Dict]:
    """简化的前向渲染，仅支持 RGB、非分布式、非稀疏，不计算梯度。

    返回: (render_colors, render_alphas, meta)
    shapes:
      - render_colors: [..., C, H, W, 3]
      - render_alphas: [..., C, H, W, 1]
    """
    assert colors.shape[-1] == 3, 'Only RGB supported'

    batch_dims = means.shape[:-2]
    N = means.shape[-2]
    C = viewmats.shape[-3]
    device = means.device

    assert means.shape == batch_dims + (N, 3)
    assert quats.shape == batch_dims + (N, 4)
    assert scales.shape == batch_dims + (N, 3)
    assert opacities.shape == batch_dims + (N,)
    assert viewmats.shape == batch_dims + (C, 4, 4)
    assert Ks.shape == batch_dims + (C, 3, 3)

    if far_planes is None:
        far_planes = torch.full(batch_dims + (N,), far_plane, dtype=means.dtype, device=device)

    # 投影到图像平面（非 packed）
    # 使用不暴露枚举的 int 接口：0=pinhole
    radii, means2d, depths, conics, _ = _C.projection_ewa_3dgs_fused_fwd_i(
        means.contiguous(),
        None,
        quats.contiguous(),
        scales.contiguous(),
        opacities.contiguous(),
        viewmats.contiguous(),
        Ks.contiguous(),
        int(width),
        int(height),
        float(eps2d),
        float(near_plane),
        far_planes.contiguous(),
        float(radius_clip),
        False,
        0,
    )

    # 计算 tile 相交
    tile_width = (width + tile_size - 1) // tile_size
    tile_height = (height + tile_size - 1) // tile_size

    # means2d: [..., C, N, 2]; radii: [..., C, N, 2]; depths: [..., C, N]
    image_dims = means2d.shape[:-2]
    tiles_per_gauss, isect_ids, flatten_ids = _intersect_tiles(
        means2d, radii, depths, tile_size, tile_width, tile_height
    )
    isect_offsets = _C.intersect_offset(
        isect_ids.contiguous(), math.prod(image_dims), tile_width, tile_height
    )

    # 整理 colors/opacities 形状到 [..., C, N, 3] / [..., C, N]
    if colors.dim() == len(batch_dims) + 2:
        colors = colors[..., None, :, :].expand(*batch_dims, C, N, 3)
    else:
        assert colors.shape == batch_dims + (C, N, 3)
    opacities = opacities[..., None, :].expand(*batch_dims, C, N)

    # 栅格化（2D响应）
    render_colors, render_alphas, _last_ids = _C.rasterize_to_pixels_3dgs_fwd(
        means2d.contiguous(),
        conics.contiguous(),
        colors.contiguous(),
        opacities.contiguous(),
        backgrounds.contiguous() if backgrounds is not None else None,
        masks.contiguous() if masks is not None else None,
        int(width),
        int(height),
        int(tile_size),
        isect_offsets.contiguous(),
        flatten_ids.contiguous(),
    )

    meta = dict(
        radii=radii,
        means2d=means2d,
        depths=depths,
        conics=conics,
        tiles_per_gauss=tiles_per_gauss,
        isect_ids=isect_ids,
        flatten_ids=flatten_ids,
        isect_offsets=isect_offsets,
        tile_width=tile_width,
        tile_height=tile_height,
        width=width,
        height=height,
        tile_size=tile_size,
    )
    return render_colors, render_alphas, meta


def _intersect_tiles(
    means2d: Tensor,
    radii: Tensor,
    depths: Tensor,
    tile_size: int,
    tile_width: int,
    tile_height: int,
):
    # 将多维批次展平为图像维度 [..., C] 以复用 gsplat 的 API 约定
    image_dims = means2d.shape[:-2]
    I = math.prod(image_dims)
    means2d_f = means2d.reshape(I, means2d.shape[-2], 2)
    radii_f = radii.reshape(I, radii.shape[-2], 2)
    depths_f = depths.reshape(I, depths.shape[-1])
    tiles_per_gauss, isect_ids, flatten_ids = _C.intersect_tile(
        means2d_f.contiguous(),
        radii_f.contiguous(),
        depths_f.contiguous(),
        None,
        None,
        int(I),
        int(tile_size),
        int(tile_width),
        int(tile_height),
        True,
        False,
    )
    return tiles_per_gauss, isect_ids, flatten_ids

