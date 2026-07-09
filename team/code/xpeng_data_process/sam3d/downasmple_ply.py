import torch
import numpy as np
from plyfile import PlyData,PlyElement
import torch
from torch_scatter import scatter_add, scatter_max

def parse_ply_for_fusion(ply_path):
    # 读取 ply 文件
    ply_data = PlyData.read(ply_path)
    vertices = ply_data['vertex']  # 获取顶点数据
    
    # 1. 提取高斯 3D 坐标 (means)
    # 对应属性：x, y, z
    x = vertices['x']
    y = vertices['y']
    z = vertices['z']
    means = np.stack([x, y, z], axis=1)  # 形状：(N, 3)
    means = torch.tensor(means, dtype=torch.float32)  # 转换为张量
    
    # 2. 提取高斯特征 (features)
    # 包含颜色（f_dc）、不透明度、缩放、旋转等，按头文件顺序排列
    f_dc_0 = vertices['f_dc_0']
    f_dc_1 = vertices['f_dc_1']
    f_dc_2 = vertices['f_dc_2']
    opacity = vertices['opacity']
    scale_0 = vertices['scale_0']
    scale_1 = vertices['scale_1']
    scale_2 = vertices['scale_2']
    rot_0 = vertices['rot_0']
    rot_1 = vertices['rot_1']
    rot_2 = vertices['rot_2']
    rot_3 = vertices['rot_3']
    
    # 堆叠特征（顺序可根据需求调整，此处按头文件顺序）
    features = np.stack([
        f_dc_0, f_dc_1, f_dc_2,
        opacity,
        scale_0, scale_1, scale_2,
        rot_0, rot_1, rot_2, rot_3
    ], axis=1)  # 形状：(N, 11)，C=11
    features = torch.tensor(features, dtype=torch.float32)  # 转换为张量
    
    # 3. 提取置信度 (confidence)
    # 通常使用不透明度作为融合权重（值越高，该高斯越重要）
    confidence = torch.tensor(vertices['opacity'], dtype=torch.float32)  # 形状：(N,)
    
    return means, features, confidence
def voxelizaton_with_fusion(img_feat, pts3d, voxel_size, conf=None):
    # img_feat: B*V, C, H, W
    # pts3d: B*V, 3, H, W
    V, C, H, W = img_feat.shape
    pts3d_flatten = pts3d.permute(0, 2, 3, 1).flatten(0, 2)

    voxel_indices = (pts3d_flatten / voxel_size).round().int()  # [B*V*N, 3]
    unique_voxels, inverse_indices, counts = torch.unique(
        voxel_indices, dim=0, return_inverse=True, return_counts=True
    )

    # Flatten confidence scores and features
    conf_flat = conf.flatten()  # [B*V*N]
    anchor_feats_flat = img_feat.permute(0, 2, 3, 1).flatten(0, 2)  # [B*V*N, ...]

    # Compute softmax weights per voxel
    conf_voxel_max, _ = scatter_max(conf_flat, inverse_indices, dim=0)
    conf_exp = torch.exp(conf_flat - conf_voxel_max[inverse_indices])
    voxel_weights = scatter_add(
        conf_exp, inverse_indices, dim=0
    )  # [num_unique_voxels]
    weights = (conf_exp / (voxel_weights[inverse_indices] + 1e-6)).unsqueeze(
        -1
    )  # [B*V*N, 1]

    # Compute weighted average of positions and features
    weighted_pts = pts3d_flatten * weights
    weighted_feats = anchor_feats_flat.squeeze(1) * weights

    # Aggregate per voxel
    voxel_pts = scatter_add(
        weighted_pts, inverse_indices, dim=0
    )  # [num_unique_voxels, 3]
    voxel_feats = scatter_add(
        weighted_feats, inverse_indices, dim=0
    )  # [num_unique_voxels, feat_dim]

    return voxel_pts, voxel_feats

def get_final_ply(fused_features, fused_means, output_ply_path, voxel_size_scale_factor=1.0):
    # 构建 PlyData 对象
    f_dc_0 = fused_features[:, 0].cpu().numpy()
    f_dc_1 = fused_features[:, 1].cpu().numpy()
    f_dc_2 = fused_features[:, 2].cpu().numpy()
    opacity = fused_features[:, 3].cpu().numpy()
    # 获取原始的 scale
    scale_0 = fused_features[:, 4].cpu().numpy()
    scale_1 = fused_features[:, 5].cpu().numpy()
    scale_2 = fused_features[:, 6].cpu().numpy()

    # 根据 voxel_size 调整 scale
    scale_0 += np.log(voxel_size_scale_factor +1+ 1e-8)
    scale_1 += np.log(voxel_size_scale_factor + 1+1e-8)
    scale_2 += np.log(voxel_size_scale_factor +1+ 1e-8)
    rot_0 = fused_features[:, 7].cpu().numpy()
    rot_1 = fused_features[:, 8].cpu().numpy()
    rot_2 = fused_features[:, 9].cpu().numpy()
    rot_3 = fused_features[:, 10].cpu().numpy()

    # 融合后的坐标和法向量
    # 法向量：融合后可复用输入的法向量（或用融合后坐标重新计算，这里简化为复用）
    fused_x = fused_means[:, 0].cpu().numpy()
    fused_y = fused_means[:, 1].cpu().numpy()
    fused_z = fused_means[:, 2].cpu().numpy()

    # 法向量处理：如果融合后高斯数量 M 与输入 N 不同，这里用融合后坐标的单位向量作为法向量（更合理）
    # （可选：也可以对输入法向量按体素融合，逻辑类似高斯特征融合）
    fused_normals = fused_means.cpu().numpy()
    fused_normals = fused_normals / (np.linalg.norm(fused_normals, axis=1, keepdims=True) + 1e-8)  # 单位化
    fused_nx = fused_normals[:, 0]
    fused_ny = fused_normals[:, 1]
    fused_nz = fused_normals[:, 2]

    # --------------------------
    # 4. 写入融合后的 PLY 文件
    # --------------------------
    # 构造 PLY 顶点数据（与输入 PLY 格式完全一致）
    vertex_data = np.array([
        (fused_x[i], fused_y[i], fused_z[i],
        fused_nx[i], fused_ny[i], fused_nz[i],
        f_dc_0[i], f_dc_1[i], f_dc_2[i],
        opacity[i],
        scale_0[i], scale_1[i], scale_2[i],
        rot_0[i], rot_1[i], rot_2[i], rot_3[i])
        for i in range(len(fused_means))
    ], dtype=[
        ('x', 'f4'), ('y', 'f4'), ('z', 'f4'),
        ('nx', 'f4'), ('ny', 'f4'), ('nz', 'f4'),
        ('f_dc_0', 'f4'), ('f_dc_1', 'f4'), ('f_dc_2', 'f4'),
        ('opacity', 'f4'),
        ('scale_0', 'f4'), ('scale_1', 'f4'), ('scale_2', 'f4'),
        ('rot_0', 'f4'), ('rot_1', 'f4'), ('rot_2', 'f4'), ('rot_3', 'f4')
    ])

    # 创建 PLY 元素并写入文件
    vertex_element = PlyElement.describe(vertex_data, 'vertex')
    PlyData([vertex_element], byte_order='<').write(output_ply_path)


def main():
    ply_path = "/workspace/wangyd13@xiaopeng.com/sam-3d-objects/visualization/14965_multiview/result.ply"
    means, features, confidence = parse_ply_for_fusion(ply_path)
    N = means.shape[0] 
    print(f"number of gaussians: {N}")
    pts3d = means.permute(1, 0).unsqueeze(0).unsqueeze(2)   # 形状：(1, 1, N, 3)
    img_feat = features.permute(1, 0).unsqueeze(0).unsqueeze(2)  # 形状：(1, 11, 1, N)
    conf = confidence.unsqueeze(0).unsqueeze(0).unsqueeze(0)     # 形状：(1, 1, N)
    voxel_size = 0.01  # 设置体素大小
    base_voxel_size = 0.005  # 示例基础体素大小

    voxel_size_scale_factor = voxel_size / base_voxel_size
    fused_means, fused_features = voxelizaton_with_fusion(
        img_feat=img_feat,
        pts3d=pts3d,
        voxel_size=voxel_size,
        conf=conf
    )
    print(f"number of fused gaussians: {fused_means.shape[0]}")
    output_ply_path = "/workspace/wangyd13@xiaopeng.com/sam-3d-objects/visualization/14965_multiview/result_fused.ply"
    get_final_ply(fused_features, fused_means, output_ply_path, voxel_size_scale_factor)
    print(f"Your fused reconstruction has been saved to {output_ply_path}")

if __name__ == "__main__":
    main()