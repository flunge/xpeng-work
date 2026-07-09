import re
import os
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # 用于非GUI环境

def parse_log_file(filename, target_metrics):
    """
    解析日志文件，提取指定指标的数据
    
    参数:
    filename: 日志文件名
    target_metrics: 要提取的指标列表
    
    返回:
    steps: 步数列表
    metrics_data: 字典，键为指标名，值为对应的数值列表
    """
    steps = []
    metrics_data = {metric: [] for metric in target_metrics}
    
    # 正则表达式模式
    step_pattern = r'\[(\d+)/\d+\]'
    
    with open(filename, 'r', encoding='utf-8') as file:
        for line in file:
            # 检查是否包含训练步数信息
            step_match = re.search(step_pattern, line)
            if not step_match:
                continue
                
            step = int(step_match.group(1))
            steps.append(step)
            
            # 提取每个目标指标的值
            for metric in target_metrics:
                # 构建匹配指标值的正则表达式
                metric_pattern = rf'{re.escape(metric)}:\s*([\d.]+)'
                metric_match = re.search(metric_pattern, line)
                
                if metric_match:
                    value = float(metric_match.group(1))
                    metrics_data[metric].append(value)
                else:
                    # 如果该行没有找到该指标，添加NaN
                    metrics_data[metric].append(float('nan'))
    
    return steps, metrics_data

def plot_individual_metrics(steps, metrics_data, output_dir='metrics_plots'):
    """
    为每个指标单独绘制折线图
    
    参数:
    steps: 步数列表
    metrics_data: 指标数据字典
    output_dir: 输出目录名
    """
    # 创建输出目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 为每个指标单独绘图
    for metric, values in metrics_data.items():
        # 过滤掉NaN值
        valid_indices = [i for i, v in enumerate(values) if not np.isnan(v)]
        if not valid_indices:
            print(f"警告: 指标 {metric} 没有有效数据，跳过绘制")
            continue
            
        valid_steps = [steps[i] for i in valid_indices]
        valid_values = [values[i] for i in valid_indices]
        
        # 创建新图形
        plt.figure(figsize=(10, 6))
        
        # 绘制折线图
        plt.plot(valid_steps, valid_values, linewidth=2, color='blue')
        
        # 设置标题和标签
        plt.xlabel('Training Steps', fontsize=12)
        
        # 根据指标类型设置Y轴标签
        if 'loss' in metric.lower():
            plt.ylabel('Loss Value', fontsize=12)
            # 对于loss，通常希望看到下降趋势，所以使用对数坐标可能更好
            if min(valid_values) > 0:  # 确保所有值都大于0
                plt.yscale('log')
        elif 'psnr' in metric.lower():
            plt.ylabel('PSNR (dB)', fontsize=12)
        elif 'lr' in metric.lower():
            plt.ylabel('Learning Rate', fontsize=12)
            plt.yscale('log')
        else:
            plt.ylabel('Metric Value', fontsize=12)
        
        # 设置标题
        title = metric.replace('_', ' ').replace('/', ' - ')
        plt.title(f'{title} Over Training Steps', fontsize=14, fontweight='bold')
        
        # 添加网格
        plt.grid(True, alpha=0.3)
        
        # 调整布局
        plt.tight_layout()
        
        # 生成安全的文件名
        safe_filename = metric.replace('/', '_').replace('#', '_')
        output_filename = os.path.join(output_dir, f'{safe_filename}.png')
        
        # 保存图片
        plt.savefig(output_filename, dpi=300, bbox_inches='tight')
        print(f"图表已保存为: {output_filename}")
        
        # 关闭图形以释放内存
        plt.close()

def plot_metric_groups(steps, metrics_data, output_dir='metrics_plots'):
    """
    将相关指标分组绘制在同一图表中
    
    参数:
    steps: 步数列表
    metrics_data: 指标数据字典
    output_dir: 输出目录名
    """
    # 创建输出目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 定义指标分组
    metric_groups = {
        'training_metrics': ['train_metrics/psnr'],
        'losses': [
            'losses/rgb_loss', 
            'losses/ssim_loss',
            'losses/sky_loss_opacity',
            'losses/depth_loss',
            'losses/affine_loss',
            'losses/Background_sharp_shape_reg',
            'losses/Ground_sharp_shape_reg',
            'losses/Ground_max_s_square',
            'losses/dynamic_opacity_loss'
        ],
        'learning_rates': [
            'train_stats/lr_Affine#all',
            'train_stats/lr_Background#sh_dc',
            'train_stats/lr_Background#sh_rest',
            'train_stats/lr_Background#scaling',
            'train_stats/lr_Background#rotation',
            'train_stats/lr_Background#xyz',
            'train_stats/lr_Background#opacity',
            'train_stats/lr_CamPose#all',
            'train_stats/lr_Ground#sh_dc',
            'train_stats/lr_Ground#sh_rest',
            'train_stats/lr_Ground#scaling',
            'train_stats/lr_Ground#rotation',
            'train_stats/lr_Ground#xyz',
            'train_stats/lr_Ground#opacity',
            'train_stats/lr_RigidNodes#sh_dc',
            'train_stats/lr_RigidNodes#sh_rest',
            'train_stats/lr_RigidNodes#scaling',
            'train_stats/lr_RigidNodes#rotation',
            'train_stats/lr_RigidNodes#xyz',
            'train_stats/lr_RigidNodes#opacity',
            'train_stats/lr_RigidNodes#appearance_features',
            'train_stats/lr_RigidNodes#appearance_embedding_model',
            'train_stats/lr_RigidNodes#ins_rotation',
            'train_stats/lr_RigidNodes#ins_translation',
            'train_stats/lr_Sky#all'
        ],
        'gaussian_numbers': [
            'train_stats/gaussian_num_Background',
            'train_stats/gaussian_num_RigidNodes',
            'train_stats/gaussian_num_Ground'
        ]
    }
    
    # 为每个分组绘制图表
    for group_name, metrics_in_group in metric_groups.items():
        # 检查分组中哪些指标实际存在于数据中
        existing_metrics = [metric for metric in metrics_in_group if metric in metrics_data and any(not np.isnan(v) for v in metrics_data[metric])]
        
        if not existing_metrics:
            continue
            
        plt.figure(figsize=(12, 8))
        
        # 为分组中的每个指标绘制线条
        for metric in existing_metrics:
            values = metrics_data[metric]
            valid_indices = [i for i, v in enumerate(values) if not np.isnan(v)]
            if valid_indices:
                valid_steps = [steps[i] for i in valid_indices]
                valid_values = [values[i] for i in valid_indices]
                # 简化标签显示
                label = metric.split('/')[-1].replace('_', ' ').replace('#', ' - ')
                plt.plot(valid_steps, valid_values, label=label, linewidth=2)
        
        plt.xlabel('Training Steps', fontsize=12)
        plt.ylabel('Value', fontsize=12)
        
        # 根据分组设置Y轴比例
        if group_name == 'learning_rates':
            plt.yscale('log')
        
        title = group_name.replace('_', ' ').title()
        plt.title(f'{title} Over Training Steps', fontsize=14, fontweight='bold')
        
        # 添加图例
        plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        
        # 保存图片
        output_filename = os.path.join(output_dir, f'{group_name}.png')
        plt.savefig(output_filename, dpi=300, bbox_inches='tight')
        print(f"分组图表已保存为: {output_filename}")
        
        # 关闭图形
        plt.close()

def main():
    # 指定要提取的指标（可以根据需要添加或删除）
    target_metrics = [
        'train_metrics/psnr',
        'losses/rgb_loss', 
        'losses/ssim_loss',
        'losses/sky_loss_opacity',
        'losses/depth_loss',
        'losses/affine_loss',
        'losses/Background_sharp_shape_reg',
        'losses/Ground_sharp_shape_reg',
        'losses/Ground_max_s_square',
        'losses/dynamic_opacity_loss',
        'train_stats/gaussian_num_Background',
        'train_stats/gaussian_num_RigidNodes',
        'train_stats/gaussian_num_Ground',
        'train_stats/lr_Affine#all',
        'train_stats/lr_Background#sh_dc',
        'train_stats/lr_Background#sh_rest',
        'train_stats/lr_Background#scaling',
        'train_stats/lr_Background#rotation',
        'train_stats/lr_Background#xyz',
        'train_stats/lr_Background#opacity',
        'train_stats/lr_CamPose#all',
        'train_stats/lr_Ground#sh_dc',
        'train_stats/lr_Ground#sh_rest',
        'train_stats/lr_Ground#scaling',
        'train_stats/lr_Ground#rotation',
        'train_stats/lr_Ground#xyz',
        'train_stats/lr_Ground#opacity',
        'train_stats/lr_RigidNodes#sh_dc',
        'train_stats/lr_RigidNodes#sh_rest',
        'train_stats/lr_RigidNodes#scaling',
        'train_stats/lr_RigidNodes#rotation',
        'train_stats/lr_RigidNodes#xyz',
        'train_stats/lr_RigidNodes#opacity',
        'train_stats/lr_RigidNodes#appearance_features',
        'train_stats/lr_RigidNodes#appearance_embedding_model',
        'train_stats/lr_RigidNodes#ins_rotation',
        'train_stats/lr_RigidNodes#ins_translation',
        'train_stats/lr_Sky#all'
    ]
    
    input_file = 'log.txt'
    output_dir = 'metrics_plots'
    
    try:
        # 解析日志文件
        steps, metrics_data = parse_log_file(input_file, target_metrics)
        
        if not steps:
            print("未找到有效的训练步数数据，请检查日志文件格式。")
            return
        
        # 检查哪些指标有数据
        found_metrics = [metric for metric in target_metrics if any(not np.isnan(v) for v in metrics_data[metric])]
        if not found_metrics:
            print("未找到任何指定的指标数据，请检查指标名称是否正确。")
            return
        
        print(f"成功解析 {len(steps)} 个训练步骤")
        print(f"找到 {len(found_metrics)} 个有数据的指标")
        
        # 为每个指标单独绘图
        plot_individual_metrics(steps, metrics_data, output_dir)
        
        # 可选：绘制分组图表
        plot_metric_groups(steps, metrics_data, output_dir)
        
        print(f"所有图表已保存到 {output_dir} 目录")
        
    except FileNotFoundError:
        print(f"错误: 找不到文件 {input_file}")
    except Exception as e:
        print(f"处理文件时发生错误: {e}")

if __name__ == "__main__":
    # 检查并导入必要的库
    try:
        import numpy as np
    except ImportError:
        print("错误: 需要安装numpy库，请运行: pip install numpy")
        exit(1)
    
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("错误: 需要安装matplotlib库，请运行: pip install matplotlib")
        exit(1)
    
    main()