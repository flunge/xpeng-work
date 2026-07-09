import argparse
import gc
import numpy as np
import torch
from plyfile import PlyData, PlyElement


def convert_model_to_ply(checkpoint_path=None, save_path=None, model_names=None, forced_sh=None):
    if model_names is None:
        model_names = ["Background", "Ground"]

    print("正在加载模型...")
    model = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    
    # 计算总点数以避免内存溢出
    total_points = 0
    for model_name in model_names:
        if model_name in model["models"]:
            total_points += model["models"][model_name]["_means"].shape[0]
    
    print(f"总点数: {total_points}")
    
    # 分批处理数据，避免内存溢出
    batch_size = min(1000000, total_points)  # 每批最多100万个点
    num_batches = (total_points + batch_size - 1) // batch_size
    
    print(f"将分 {num_batches} 批处理，每批 {batch_size} 个点")
    
    # 准备PLY文件头
    keys = prepare_ply_keys(model, model_names, forced_sh)
    dtype_full = [(attribute, "f4") for attribute in keys]
    
    # 创建PLY文件并分批写入
    with open(save_path, 'wb') as f:
        # 写入PLY头
        write_ply_header(f, total_points, keys)
        
        # 分批处理数据
        for batch_idx in range(num_batches):
            start_idx = batch_idx * batch_size
            end_idx = min((batch_idx + 1) * batch_size, total_points)
            print(f"处理批次 {batch_idx + 1}/{num_batches}: 点 {start_idx}-{end_idx}")
            
            # 处理当前批次
            batch_data = process_batch(model, model_names, start_idx, end_idx, forced_sh)
            
            # 写入当前批次
            write_batch_to_ply(f, batch_data, dtype_full)
            
            # 清理内存
            del batch_data
            gc.collect()
            torch.cuda.empty_cache() if torch.cuda.is_available() else None
    
    print(f"转换完成！文件保存到: {save_path}")


def prepare_ply_keys(model, model_names, forced_sh):
    """准备PLY文件的列名"""
    # 获取特征维度
    sample_model = None
    for model_name in model_names:
        if model_name in model["models"]:
            sample_model = model["models"][model_name]
            break
    
    if sample_model is None:
        raise ValueError("没有找到有效的模型")
    
    f_dc_dim = sample_model["_features_dc"].shape[1]
    f_rest_dim = sample_model["_features_rest"].shape[1] * 3
    
    # 如果指定了forced_sh，计算目标维度
    if forced_sh is not None:
        f_rest_dim = (forced_sh + 1) ** 2 * 3 - 3
    
    keys = ["x", "y", "z", "nx", "ny", "nz"]
    for i in range(f_dc_dim):
        keys.append(f"f_dc_{i}")
    for i in range(f_rest_dim):
        keys.append(f"f_rest_{i}")
    keys.append("opacity")
    keys.extend(["scale_0", "scale_1", "scale_2"])
    keys.extend(["rot_0", "rot_1", "rot_2", "rot_3"])
    
    return keys


def write_ply_header(f, num_points, keys):
    """写入PLY文件头"""
    header = f"""ply
format binary_little_endian 1.0
element vertex {num_points}
"""
    for key in keys:
        header += f"property float {key}\n"
    header += "end_header\n"
    
    f.write(header.encode('ascii'))


def process_batch(model, model_names, start_idx, end_idx, forced_sh):
    """处理一个批次的数据"""
    batch_data = []
    current_idx = 0
    
    for model_name in model_names:
        if model_name not in model["models"]:
            continue
            
        model_data = model["models"][model_name]
        num_points = model_data["_means"].shape[0]
        
        # 检查这个模型的数据是否在当前批次范围内
        if current_idx + num_points <= start_idx:
            current_idx += num_points
            continue
        if current_idx >= end_idx:
            break
            
        # 计算当前模型在当前批次中的范围
        model_start = max(0, start_idx - current_idx)
        model_end = min(num_points, end_idx - current_idx)
        
        if model_end > model_start:
            # 提取当前批次的数据
            xyz = model_data["_means"][model_start:model_end]
            features_dc = model_data["_features_dc"][model_start:model_end]
            features_rest = model_data["_features_rest"][model_start:model_end]
            opacity = model_data["_opacities"][model_start:model_end]
            scale = model_data["_scales"][model_start:model_end]
            rotation = model_data["_quats"][model_start:model_end]
            
            # 处理scale维度
            if scale.shape[1] == 2:
                scale = torch.cat([scale, torch.zeros((scale.shape[0], 1))], dim=-1)
            
            # 处理features_rest
            features_rest_transposed = features_rest.transpose(1, 2)
            
            # 如果指定了forced_sh，进行填充
            if forced_sh is not None:
                features_rest_transposed = fill_features_rest_torch(features_rest_transposed, forced_sh)
            
            features_rest_flat = features_rest_transposed.flatten(start_dim=1)
            # 转换为numpy并添加到批次
            batch_data.append({
                'xyz': xyz.numpy(),
                'features_dc': features_dc.numpy(),
                'features_rest': features_rest_flat.numpy(),
                'opacity': opacity.numpy(),
                'scale': scale.numpy(),
                'rotation': rotation.numpy()
            })
        
        current_idx += num_points
    
    return batch_data


def write_batch_to_ply(f, batch_data, dtype_full):
    """将批次数据写入PLY文件"""
    for data in batch_data:
        # 创建normals（全零）
        normals = np.zeros_like(data['xyz'])
        
        # 连接所有属性
        attributes = np.concatenate([
            data['xyz'], normals, data['features_dc'], 
            data['features_rest'], data['opacity'], 
            data['scale'], data['rotation']
        ], axis=1)
        
        # 创建结构化数组并写入
        elements = np.empty(attributes.shape[0], dtype=dtype_full)
        elements[:] = list(map(tuple, attributes))
        
        # 直接写入二进制数据
        elements.astype(dtype_full).tofile(f)


def fill_features_rest_torch(features_rest_transposed, forced_sh):
    """使用PyTorch填充features_rest到指定SH阶数"""
    target_features_dim = (forced_sh + 1) ** 2 - 1
    current_features_dim = features_rest_transposed.shape[2]
    
    if current_features_dim < target_features_dim:
        padding_dim = target_features_dim - current_features_dim
        padding = torch.zeros((features_rest_transposed.shape[0], 3, padding_dim))
        features_rest_transposed = torch.cat([features_rest_transposed, padding], dim=2)
    
    return features_rest_transposed


def fill_features_rest(f_rest, forced_sh):
    """使用NumPy填充features_rest到指定SH阶数（保持向后兼容）"""
    target_features_dim = (forced_sh + 1) ** 2 * 3 - 3
    current_features_dim = f_rest.shape[1]
    if current_features_dim < target_features_dim:
        padding_dim = target_features_dim - current_features_dim
        padding = np.zeros((f_rest.shape[0], padding_dim))
        f_rest = np.concatenate([f_rest, padding], axis=1)
    return f_rest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert DriveStudio model to PLY format")
    parser.add_argument("--checkpoint_path", type=str, required=True, help="Path to checkpoint file")
    parser.add_argument("--save_path", type=str, required=True, help="Path to save output PLY file")
    parser.add_argument(
        "--model_names",
        type=str,
        nargs="+",
        default=["Background", "Ground", "RigidNodes", "DeformableNodes"],
        help="List of model names to extract (default: Background Ground)",
    )
    parser.add_argument(
        "--forced_sh",
        type=int,
        default=None,
        help="Force the features_rest to have a specific SH order (default: None)",
    )

    args = parser.parse_args()

    convert_model_to_ply(checkpoint_path=args.checkpoint_path, save_path=args.save_path, model_names=args.model_names, forced_sh=args.forced_sh)
