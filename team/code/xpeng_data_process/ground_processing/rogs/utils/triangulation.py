import numpy as np
import torch
from scipy.spatial import Delaunay


def _unique_edges_from_triangles(triangles: np.ndarray) -> np.ndarray:
    """
    triangles: (T, 3) int indices
    return edges: (E, 2) sorted int indices, unique
    """
    if triangles.size == 0:
        return np.empty((0, 2), dtype=np.int64)
    i = triangles[:, 0]
    j = triangles[:, 1]
    k = triangles[:, 2]
    edges = np.stack([
        np.sort(np.stack([i, j], axis=1), axis=1),
        np.sort(np.stack([j, k], axis=1), axis=1),
        np.sort(np.stack([k, i], axis=1), axis=1),
    ], axis=0).reshape(-1, 2)
    edges = np.unique(edges, axis=0)
    return edges


@torch.no_grad()
def densify_by_triangulation(
    gaussians,
    target_classes=(1, 2, 4),
    edge_samples=1,
    add_triangle_centroid=True,
    max_new_points=None,
):
    """
    对高斯中心的 XY 平面做 Delaunay 三角化：
    - 若一条边的两个端点的主类均属于 target_classes，则在该边上插入 edge_samples 个新高斯（等距内插）。
    - 若一个三角形的三个端点主类均属于 target_classes，则在三角形质心插入一个新高斯（可选）。

    新高斯的参数（_z, _opacity, _label, _scaling_xy, _rotation 以及可选 _rgb/SH 特征）
    采用端点参数的线性插值（边）或三点平均（三角形）。

    该函数会直接调用 gaussians.densification_postfix 追加参数，并正确拼接优化器参数组。
    """
    device = gaussians._xy.device

    # 原始数据（参数空间）
    xy_cpu = gaussians._xy.detach().cpu().numpy()
    xy_t = gaussians._xy.detach()  # on device
    z = gaussians._z.detach()
    scaling = gaussians._scaling_xy.detach()
    rotation = gaussians._rotation.detach()
    opacity = gaussians._opacity.detach()
    label_param = gaussians._label.detach()

    use_rgb = gaussians.use_rgb
    if use_rgb:
        rgb_param = gaussians._rgb.detach()
        features_dc = None
        features_rest = None
    else:
        rgb_param = None
        features_dc = gaussians._features_dc.detach()
        features_rest = gaussians._features_rest.detach()

    # 以概率 argmax 作为类别
    probs = gaussians.get_label  # (N, C)
    gs_classes = torch.argmax(probs, dim=-1).detach().cpu().numpy()
    target_set = set(list(target_classes))
    in_target = np.isin(gs_classes, list(target_set))  # (N,)

    # 三角化
    if xy_cpu.shape[0] < 3:
        return 0
    try:
        tri = Delaunay(xy_cpu)
    except Exception:
        return 0

    simplices = tri.simplices  # (T,3)
    if simplices.size == 0:
        return 0

    # 选边：两端均在目标类
    edges = _unique_edges_from_triangles(simplices)
    if edges.size == 0:
        qualified_edges = np.empty((0, 2), dtype=np.int64)
    else:
        mask_edges = np.logical_and(in_target[edges[:, 0]], in_target[edges[:, 1]])
        qualified_edges = edges[mask_edges]

    # 选三角形：三点均在目标类
    if add_triangle_centroid:
        # 对每个三角形的3个端点做“全在目标类”的判定，需沿axis=1归约
        tri_mask = np.all(in_target[simplices], axis=1)
        qualified_tris = simplices[tri_mask]
    else:
        qualified_tris = np.empty((0, 3), dtype=np.int64)

    # 如需限制新增点总数，则按比例随机下采样候选边与三角形
    if max_new_points is not None:
        edge_new = int(qualified_edges.shape[0] * max(0, edge_samples))
        tri_new = int(qualified_tris.shape[0])
        total_new = edge_new + tri_new
        if total_new > max_new_points and total_new > 0:
            keep_ratio = max_new_points / float(total_new)
            # 边与三角形分别按相同比例下采样
            if qualified_edges.shape[0] > 0 and edge_samples > 0:
                e_keep = max(1, int(qualified_edges.shape[0] * keep_ratio))
                choose = np.random.choice(qualified_edges.shape[0], size=e_keep, replace=False)
                qualified_edges = qualified_edges[choose]
            if qualified_tris.shape[0] > 0:
                t_keep = max(1, int(qualified_tris.shape[0] * keep_ratio))
                choose = np.random.choice(qualified_tris.shape[0], size=t_keep, replace=False)
                qualified_tris = qualified_tris[choose]

    # 矢量化构建新增点（边内插）
    new_xyz_list = []
    new_scaling_list = []
    new_rotation_list = []
    new_opacity_list = []
    new_label_list = []
    new_rgb_list = [] if use_rgb else None
    new_fdc_list = [] if not use_rgb else None
    new_frest_list = [] if not use_rgb else None

    if qualified_edges.size > 0 and edge_samples > 0:
        idx0 = torch.from_numpy(qualified_edges[:, 0]).long().to(device)
        idx1 = torch.from_numpy(qualified_edges[:, 1]).long().to(device)
        M = int(edge_samples)
        t_vals = torch.linspace(1.0 / (M + 1), float(M) / (M + 1), M, device=device)
        w1 = t_vals.repeat(idx0.shape[0])  # (E*M,)
        w0 = 1.0 - w1
        idx0_exp = torch.repeat_interleave(idx0, M)
        idx1_exp = torch.repeat_interleave(idx1, M)

        xy_interp = w0[:, None] * xy_t[idx0_exp] + w1[:, None] * xy_t[idx1_exp]
        z_interp = w0[:, None] * z[idx0_exp] + w1[:, None] * z[idx1_exp]
        xyz_interp = torch.cat([xy_interp, z_interp], dim=1)
        scaling_interp = w0[:, None] * scaling[idx0_exp] + w1[:, None] * scaling[idx1_exp]
        rotation_interp = w0[:, None] * rotation[idx0_exp] + w1[:, None] * rotation[idx1_exp]
        opacity_interp = w0[:, None] * opacity[idx0_exp] + w1[:, None] * opacity[idx1_exp]
        label_interp = w0[:, None] * label_param[idx0_exp] + w1[:, None] * label_param[idx1_exp]

        new_xyz_list.append(xyz_interp)
        new_scaling_list.append(scaling_interp)
        new_rotation_list.append(rotation_interp)
        new_opacity_list.append(opacity_interp)
        new_label_list.append(label_interp)

        if use_rgb:
            rgb_interp = w0[:, None] * rgb_param[idx0_exp] + w1[:, None] * rgb_param[idx1_exp]
            new_rgb_list.append(rgb_interp)
        else:
            fdc_interp = w0[:, None, None] * features_dc[idx0_exp] + w1[:, None, None] * features_dc[idx1_exp]
            frest_interp = w0[:, None, None] * features_rest[idx0_exp] + w1[:, None, None] * features_rest[idx1_exp]
            new_fdc_list.append(fdc_interp)
            new_frest_list.append(frest_interp)

    # 矢量化构建新增点（三角质心）
    if qualified_tris.size > 0:
        idx0 = torch.from_numpy(qualified_tris[:, 0]).long().to(device)
        idx1 = torch.from_numpy(qualified_tris[:, 1]).long().to(device)
        idx2 = torch.from_numpy(qualified_tris[:, 2]).long().to(device)

        xy_m = (xy_t[idx0] + xy_t[idx1] + xy_t[idx2]) / 3.0
        z_m = (z[idx0] + z[idx1] + z[idx2]) / 3.0
        xyz_m = torch.cat([xy_m, z_m], dim=1)
        scaling_m = (scaling[idx0] + scaling[idx1] + scaling[idx2]) / 3.0
        rotation_m = (rotation[idx0] + rotation[idx1] + rotation[idx2]) / 3.0
        opacity_m = (opacity[idx0] + opacity[idx1] + opacity[idx2]) / 3.0
        label_m = (label_param[idx0] + label_param[idx1] + label_param[idx2]) / 3.0

        new_xyz_list.append(xyz_m)
        new_scaling_list.append(scaling_m)
        new_rotation_list.append(rotation_m)
        new_opacity_list.append(opacity_m)
        new_label_list.append(label_m)

        if use_rgb:
            rgb_m = (rgb_param[idx0] + rgb_param[idx1] + rgb_param[idx2]) / 3.0
            new_rgb_list.append(rgb_m)
        else:
            fdc_m = (features_dc[idx0] + features_dc[idx1] + features_dc[idx2]) / 3.0
            frest_m = (features_rest[idx0] + features_rest[idx1] + features_rest[idx2]) / 3.0
            new_fdc_list.append(fdc_m)
            new_frest_list.append(frest_m)

    if len(new_xyz_list) == 0:
        return 0

    new_xyz = torch.cat(new_xyz_list, dim=0).to(device)
    new_opacity = torch.cat(new_opacity_list, dim=0).to(device)
    new_label = torch.cat(new_label_list, dim=0).to(device)
    new_scaling = torch.cat(new_scaling_list, dim=0).to(device)
    new_rotation = torch.cat(new_rotation_list, dim=0).to(device)

    if use_rgb:
        new_rgb = torch.cat(new_rgb_list, dim=0).to(device)
        new_fdc = None
        new_frest = None
    else:
        new_rgb = None
        new_fdc = torch.cat(new_fdc_list, dim=0).to(device)
        new_frest = torch.cat(new_frest_list, dim=0).to(device)

    # 追加参数到模型
    gaussians.densification_postfix(new_xyz, new_fdc, new_frest, new_opacity, new_label, new_scaling, new_rotation, new_rgb)

    return new_xyz.shape[0]


