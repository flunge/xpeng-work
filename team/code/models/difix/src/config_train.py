"""
训练配置加载：从 YAML 读取训练参数。
"""
import os
import sys
import shutil
import argparse


def step_to_num_images(step, train_batch_size, gradient_accumulation_steps, num_processes):
    """
    根据 ckpt 的 global_step 与训练配置，计算该 step 时模型已见过的图片张数。

    公式：num_images = step × train_batch_size × gradient_accumulation_steps × num_processes
    （每 1 个 global_step 对应一次参数更新，每次更新会累积 global_batch_size 张图）

    例：step=36000, train_batch_size=2, gradient_accumulation_steps=2, num_processes=4
        -> 36000 * 2 * 2 * 4 = 576000 张图
    """
    return step * train_batch_size * gradient_accumulation_steps * num_processes


# 训练参数默认值（YAML 中未写的项用此补全）
CONFIG_DEFAULTS = {
    "image_height": 576,
    "image_width": 1024,
    "use_ref_img": False,
    # ref 图几何扰动 (反对齐增广), 仅在 use_ref_img=True 时生效
    # ref_perturb_prob > 0 即开启, 默认 0 不触发
    "ref_perturb_prob": 0.0,
    "ref_perturb_amp": 10.0,
    "ref_perturb_repr_depth": 15.0,
    # ref 局部 mask: 仅在 use_ref_img=True 时生效;
    # 开启后读取数据 JSON 中的 "ref_mask" 字段(PNG 路径), 像素>127 = attn1 屏蔽该区域
    "use_ref_mask": False,
    "enable_dual_resolution_bucket": False,
    "bucket_16_9_height": 576,
    "bucket_16_9_width": 1024,
    "bucket_5_4_height": 768,
    "bucket_5_4_width": 960,
    "lora_rank_vae": 4,
    "timestep": 199,
    "overwrite_prompt": None,
    "lambda_lpips": 1.0,
    "lambda_l2": 10.0,
    "lambda_gram": 0.1,
    "gram_loss_warmup_steps": 2000,
    "dataset_path": None,
    "eval_freq": 0,
    "num_samples_eval": 1,
    "viz_freq": 100,
    "output_dir": None,
    "seed": None,
    "train_batch_size": 4,
    "num_training_epochs": 1,
    "checkpointing_epoch": 1,
    "gradient_accumulation_steps": 1,
    "max_steps_per_epoch": 4000,
    "gradient_checkpointing": False,
    "learning_rate": 5e-6,
    "lr_scheduler": "constant",
    "lr_warmup_steps": 500,
    "lr_num_cycles": 1,
    "lr_power": 1.0,
    "dataloader_num_workers": 0,
    "adam_beta1": 0.9,
    "adam_beta2": 0.999,
    "adam_weight_decay": 1e-2,
    "adam_epsilon": 1e-08,
    "max_grad_norm": 1.0,
    "allow_tf32": False,
    "report_to": "tensorboard",
    "mixed_precision": None,
    "enable_xformers_memory_efficient_attention": False,
    "set_grads_to_none": False,
    "resume": None,
}


def load_config(path):
    """加载 YAML 配置，返回 dict。"""
    try:
        import yaml
    except ImportError:
        raise ImportError("需要安装 PyYAML: pip install pyyaml")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg if cfg else {}


def parse_config_args():
    """解析命令行 --config <path>，从 YAML 加载全部训练参数，返回 argparse.Namespace。"""
    if len(sys.argv) >= 3 and sys.argv[1] == "--config":
        config_path = sys.argv[2]
    else:
        print("用法: python train_difix.py --config <path_to.yaml>")
        print("示例: python train_difix.py --config configs/overfit.yaml")
        sys.exit(1)
    if not os.path.isfile(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    cfg = load_config(config_path)
    # 去掉 YAML 里的非训练字段，只保留训练参数
    allowed = set(CONFIG_DEFAULTS)
    cfg = {k: v for k, v in cfg.items() if k in allowed and v is not None}
    merged = {**CONFIG_DEFAULTS, **cfg}
    if merged["output_dir"] is None or merged["dataset_path"] is None:
        raise ValueError("config 中必须提供 output_dir 和 dataset_path")
    # 由 output_dir 最后一级目录、dataset_path 文件名（无后缀）自动设置
    merged["tracker_project_name"] = os.path.basename(os.path.normpath(merged["output_dir"]))
    merged["tracker_run_name"] = os.path.splitext(os.path.basename(merged["dataset_path"]))[0]
    # 将当前配置文件复制到输出目录备份
    out_dir = merged["output_dir"]
    os.makedirs(out_dir, exist_ok=True)
    shutil.copy2(config_path, os.path.join(out_dir, os.path.basename(config_path)))
    args = argparse.Namespace(**merged)
    args._config_path = config_path  # 供 train 保存 ckpt 时复制 yaml 到 ckpt 目录
    return args


def save_checkpoint_for_epoch(
    accelerator,
    net_difix,
    optimizer,
    args,
    epoch_idx,
    current_global_step,
    lr_scheduler=None,
    is_final=False,
):
    """保存 checkpoint（model.pkl、config.json、train_config.yaml）到 ckpt 目录。"""
    from model import save_ckpt
    from utils_difix import save_config

    if not accelerator.is_main_process:
        return
    if is_final:
        ckpt_dir = os.path.join(args.output_dir, "checkpoints")
    else:
        ckpt_dir = os.path.join(
            args.output_dir, f"checkpoints_epoch_{epoch_idx:04d}_step_{current_global_step}"
        )
    os.makedirs(ckpt_dir, exist_ok=True)
    save_ckpt(
        accelerator.unwrap_model(net_difix),
        optimizer,
        outf=os.path.join(ckpt_dir, "model.pkl"),
        for_inference=True,
        epoch=epoch_idx,
        global_step=current_global_step,
        lr_scheduler=lr_scheduler,
    )
    save_config(ckpt_dir, args)
    # 将训练用 YAML 配置复制到 ckpt 目录（含固定名 train_config.yaml 供 fixer 等读取）
    # 优先用启动时已备份到 output_dir 的 yaml，避免训练过程中用户移动/删除原文件
    config_path = getattr(args, "_config_path", None)
    if config_path:
        backup_in_output = os.path.join(args.output_dir, os.path.basename(config_path))
        source_yaml = backup_in_output if os.path.isfile(backup_in_output) else config_path
        if os.path.isfile(source_yaml):
            shutil.copy2(source_yaml, os.path.join(ckpt_dir, os.path.basename(config_path)))
            shutil.copy2(source_yaml, os.path.join(ckpt_dir, "train_config.yaml"))
