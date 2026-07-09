import torch
from nail_evolsplat.train.optimizers import Optimizers, AdamOptimizerConfig,ExponentialDecaySchedulerConfig

def obtain_config(yaml_info=None):
    mlp_conv_optimizer_lr = 0.0001
    scene_info = [
        # "c-0ecdc716-6fc6-31cc-bd7c-d4d92cdeaf58",
        "c-1e5aded3-883a-3fbe-ab66-e8e4f4dd2009",
        "c-856b3b8c-a180-37ea-b816-55668511f63f",
        "c-4b63c505-8820-32ad-8d64-116a8dbf6b3a",
        "c-a8d8a534-f95b-3b5e-9483-0365724aa10b",
        "c-c3d6ad95-8d56-3c23-92b5-b91535a45447",
        "c-ddfb861b-9cb3-3b8a-8bb6-644b1edf0777",
        "c-df92a958-1266-3ac1-9e3a-c5fc631e8809",
        "c-e41c1451-ec6e-3f24-937b-5a6822aab460",
    ]
    eval_scenes = [
        "c-0ecdc716-6fc6-31cc-bd7c-d4d92cdeaf58",
    ]
    root_data_folder = "/workspace/lvy10@xiaopeng.com/code/simworld/models/nail_evolsplat/train/root_data_folder"
    output_dir = "/workspace/lvy10@xiaopeng.com/code/simworld/models/nail_evolsplat/train/train_output_allscene_1205"
    num_iterations = 100
    delete_origin_data = False
    if yaml_info is not None:
        mlp_conv_optimizer_lr = yaml_info["mlp_conv_optimizer_lr"]
        scene_info = yaml_info["scene_info"]
        eval_scenes = yaml_info["eval_scenes"]
        root_data_folder = yaml_info["root_data_folder"]
        output_dir = yaml_info["output_dir"]
        num_iterations = yaml_info["num_iterations"]
        delete_origin_data = yaml_info["delete_origin_data"]

    config = {
        "scenes" : scene_info,
        "eval_scenes" : eval_scenes,
        "root_data_folder": root_data_folder,
        "output_dir" : output_dir,
        "num_iterations" : num_iterations,
        "delete_origin_data" : delete_origin_data,
        "weight_entropy_loss": 0.1,
        "ssim_lambda": 0.8,
        "device": "cuda",
        "optimizer_config" : {
            "sparse_conv": {
                "optimizer": AdamOptimizerConfig(lr=1*1e-3, eps=1e-15),
                "scheduler": ExponentialDecaySchedulerConfig(
                    lr_final=5e-7, max_steps=30000, warmup_steps=500, lr_pre_warmup=0
                ),
            },

            "mlp_conv": {
                "optimizer": AdamOptimizerConfig(lr=mlp_conv_optimizer_lr, eps=1e-15),
                "scheduler": ExponentialDecaySchedulerConfig(lr_final=0.0001,max_steps=30000),
            },

            "mlp_opacity": {
                "optimizer": AdamOptimizerConfig(lr=1*1e-3, eps=1e-15),
                "scheduler": ExponentialDecaySchedulerConfig(lr_final=0.0001,max_steps=30000),
            },

            "mlp_offset": {
                "optimizer": AdamOptimizerConfig(lr=1*1e-3, eps=1e-15),
                "scheduler": ExponentialDecaySchedulerConfig(lr_final=0.0001,max_steps=30000),
            },

            "gaussianDecoder": {
                "optimizer": AdamOptimizerConfig(lr=1*1e-3, eps=1e-15),
                "scheduler": ExponentialDecaySchedulerConfig(lr_final=0.0001,max_steps=30000),
            },
        }

    }
    return config

