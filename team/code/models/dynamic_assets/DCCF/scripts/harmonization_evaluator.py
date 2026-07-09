import argparse
import os, sys
from pathlib import Path
from logging import Logger
from typing import List, Optional

import torch
from albumentations import Resize, NoOp

current_dir = os.path.dirname(__file__) 
relative_path = os.path.join(current_dir, '..')
sys.path.extend([relative_path])
sys.path.insert(0, '.')

from iharm.data.hdataset import HDatasetUpsample
from iharm.data.transforms import HCompose, LongestMaxSizeIfLarger
from iharm.inference.predictor_upsample_hsl import PredictorUpsampleHSL
from iharm.inference.predictor_upsample_hsl_nobackbone import PredictorUpsampleHSLNoBackbone
from iharm.inference.evaluation import evaluate_dataset_upsample_hsl_refine
from iharm.inference.metrics import MetricsHub, MSE, fMSE, SSIM, PSNR, N, AvgPredictTime
from iharm.inference.utils import load_model, find_checkpoint
from iharm.mconfigs import ALL_MCONFIGS
from iharm.utils.exp import load_config_file
from iharm.utils.log import logger, add_new_file_output_to_logger


class HarmonizationEvaluator:
    # 静态属性：Resize策略映射，类级别共享
    RESIZE_STRATEGIES = {
        'None': NoOp(),
        'LimitLongest1024': LongestMaxSizeIfLarger(1024),
        'Fixed256': Resize(256, 256),
        'Fixed512': Resize(512, 512)
    }

    def __init__(self, model_type, checkpoint, gpu=0, config_path='./config.yml', version='v1', eval_prefix=''):
        """
        初始化和谐化评估器（耗时操作集中在这里）
        
        Args:
            model_type: 模型类型，必须是ALL_MCONFIGS中的键
            checkpoint: 检查点路径（相对或绝对路径）
            gpu: GPU设备ID
            config_path: 配置文件路径
            version: 模型版本，['v1', 'hsl', 'hsl_nobb']
            eval_prefix: 评估日志前缀
        """
        # 加载配置
        print("init config_path: ", config_path)
        self.cfg = load_config_file(config_path, return_edict=True)
        self.eval_prefix = eval_prefix
        self.version = version
        
        # 处理检查点路径
        self.cfg.MODELS_PATH = ''  # 保持原逻辑
        self.checkpoint_path = find_checkpoint(self.cfg.MODELS_PATH, checkpoint)
        
        # 配置日志
        self._setup_logger()
        
        # 初始化设备
        self.device = torch.device(f'cuda:{gpu}')
        
        # 加载模型（耗时操作）
        self.net = load_model(model_type, self.checkpoint_path, verbose=False)
        
        # 创建预测器（耗时操作）
        self.predictor = self._create_predictor(version)
        
        # 记录初始化信息
        logger.info(f"Evaluator initialized with model: {model_type}, checkpoint: {self.checkpoint_path}")

    def reset_cfg(self, config_path='./config.yml'):
        print("init config_path: ", config_path)
        self.cfg = load_config_file(config_path, return_edict=True)

    def _setup_logger(self):
        """设置日志输出"""
        log_dir = Path(self.cfg.EXPS_PATH) / 'evaluation_logs'
        log_prefix = f"{self.eval_prefix}{Path(self.checkpoint_path).stem}_" if self.eval_prefix else f"{Path(self.checkpoint_path).stem}_"
        add_new_file_output_to_logger(
            logs_path=log_dir,
            prefix=log_prefix,
            only_message=True
        )

    def _create_predictor(self, version):
        """创建预测器实例"""
        if version == 'hsl':
            return PredictorUpsampleHSL(self.net, self.device, with_flip=False)
        elif version == 'hsl_nobb':
            return PredictorUpsampleHSLNoBackbone(self.net, self.device, with_flip=False)
        else:  # v1及其他版本默认处理
            return PredictorUpsampleHSL(self.net, self.device, with_flip=False)

    def evaluate(self, datasets=None, resize_strategy='Fixed256', 
                 use_flip=False, vis_dir=None, res='HR'):
        """
        执行评估（轻量操作，可多次调用）
        
        Args:
            datasets: 数据集名称，逗号分隔
            resize_strategy:  resize策略，必须是RESIZE_STRATEGIES中的键
            use_flip: 是否使用水平翻转测试增强
            vis_dir: 可视化输出目录
            res: 评估分辨率，['HR', 'LR']
        
        Returns:
            总体评估指标
        """
        # 更新预测器的翻转配置（如果需要）
        self.predictor.with_flip = use_flip
        
        # 处理可视化目录
        if vis_dir and not os.path.exists(vis_dir):
            os.makedirs(vis_dir, exist_ok=True)
        
        # 解析数据集列表
        # datasets_names = datasets.split(',')
        datasets_metrics_low = []
        datasets_metrics_full = []
        
        # 准备全分辨率增强器
        aug_fullres = HCompose([Resize(768, 1024)]) if res == 'HR' else None

        # 逐个评估数据集
        for dataset_idx, dataset_name in enumerate(datasets):
            # 加载数据集
            dataset = HDatasetUpsample(
                self.cfg.get(f'{dataset_name.upper()}_PATH'),
                split='test',
                blur_target=False,
                augmentator_1=aug_fullres,
                augmentator_2=HCompose([Resize(256, 256)]),
                keep_background_prob=-1,
                use_hr=True,
            )
            
            # 初始化指标计算器
            metrics_low = MetricsHub([N(), MSE(), PSNR(), fMSE(), SSIM(), AvgPredictTime()], name=dataset_name)
            metrics_full = MetricsHub([N(), MSE(), PSNR(), fMSE(), SSIM(), AvgPredictTime()], name=dataset_name)
            
            # 执行评估
            evaluate_dataset_upsample_hsl_refine(
                dataset, self.predictor, metrics_low, metrics_full, visdir=vis_dir
            )
            
            datasets_metrics_low.append(metrics_low)
            datasets_metrics_full.append(metrics_full)
            
            # 输出单个数据集结果
            if dataset_idx == 0:
                logger.info(metrics_low.get_table_header())
            
            if res == 'LR':
                logger.info(metrics_low)
            else:
                logger.info(metrics_full)
        
        # 计算并返回总体指标
        if res == 'LR':
            overall_metrics = sum(datasets_metrics_low, MetricsHub([], 'Overall_low_res'))
        else:
            overall_metrics = sum(datasets_metrics_full, MetricsHub([], 'Overall_full_res'))
        
        logger.info('-' * len(str(overall_metrics)))
        logger.info(overall_metrics)
        return overall_metrics

    def display_smooth_plot(self, saved_dir):
        self.predictor.display_smooth_plot(saved_dir=saved_dir)

def create_harmonization_evaluator(
    pretrain_path: str,
    datasets: List[str],
    cuda_device: int = 0,
    model_type_hr: str = "hrnet18s_v2p_idih256_upsample_hsl_refine_HR",
    model_type_lr: str = "hrnet18s_v2p_idih256_upsample_hsl_refine_LR",
    resize_strategy: str = "Fixed256",
    version: str = "hsl",
    config_path_hr: str = "config_test_HR.yml",
    config_path_lr: str = "config_test_LR.yml",
    vis_base_dir: Optional[str] = "./harmonization_exps_hr/images_",
    res: str = "HR",
):
    print("==============create_harmonization_evaluator=============")
    # 预训练模型路径
    pretrain_path = "/workspace/group_share/adc-sim/harmonizer/pretrained_models/dccf_idih_hrnet18s_v2p_HR_pretrain.pth"
    # if len(pretrain_path) == 0:
    #     pretrain_path = os.path.join(relative_path, "pretrained_models", "dccf_idih_hrnet18s_v2p_HR_pretrain.pth")
    print("dccf pretrain_path: ", pretrain_path)

    # 复制环境变量并设置CUDA可见设备
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(cuda_device)
    
    # 根据分辨率模式选择模型类型和配置文件
    if res == "HR":
        model_type = model_type_hr
        config_path = config_path_hr
    elif res == "LR":
        model_type = model_type_lr
        config_path = config_path_lr
    else:
        raise ValueError(f"不支持的res模式: {res}，请使用HR或LR")


    evaluator = HarmonizationEvaluator(
        model_type=model_type,
        checkpoint=pretrain_path,
        gpu=cuda_device,
        config_path=config_path,
        version=version,
        eval_prefix=vis_base_dir
    )
    return evaluator


# 命令行调用入口
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('model_type', choices=ALL_MCONFIGS.keys())
    parser.add_argument('checkpoint', type=str, help='Checkpoint path (relative or absolute)')
    parser.add_argument('--datasets', type=str, default='HFlickr,HDay2Night,HCOCO,HAdobe5k',
                        help='Comma-separated dataset names')
    parser.add_argument('--resize-strategy', type=str, choices=HarmonizationEvaluator.RESIZE_STRATEGIES.keys(),
                        default='Fixed256')
    parser.add_argument('--use-flip', action='store_true', default=False,
                        help='Use horizontal flip test-time augmentation')
    parser.add_argument('--gpu', type=str, default=0, help='GPU ID to use')
    parser.add_argument('--config-path', type=str, default='./config.yml', help='Path to config file')
    parser.add_argument('--eval-prefix', type=str, default='', help='Prefix for evaluation logs')
    parser.add_argument('--vis-dir', type=str, default=None, help='Visualization output directory')
    parser.add_argument('--version', type=str, default='v1', help='Model version [v1, hsl, hsl_nobb]')
    parser.add_argument('--res', type=str, default='HR', help='Evaluation resolution [HR, LR]')
    return parser.parse_args()


def main():
    args = parse_args()
    # 创建评估器实例（执行一次初始化）
    evaluator = HarmonizationEvaluator(
        model_type=args.model_type,
        checkpoint=args.checkpoint,
        gpu=args.gpu,
        config_path=args.config_path,
        version=args.version,
        eval_prefix=args.eval_prefix
    )
    # 执行评估（可多次调用）
    evaluator.evaluate(
        datasets=args.datasets,
        resize_strategy=args.resize_strategy,
        use_flip=args.use_flip,
        vis_dir=args.vis_dir,
        res=args.res
    )


if __name__ == '__main__':
    main()