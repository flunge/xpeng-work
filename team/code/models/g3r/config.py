import torch

def obtain_config(region_type):
    config = {
        "device": "cuda",
        "region": region_type,  # ground & bkgd
        "data_type": torch.float32,
        "lr": 1e-4,
        "save_img_step": 500,
        "save_img_id": 5,
        "evaluation_step": 2000,
        "num_points_train": 3000000,
        "epochs": 1000,
        "batch_size": 1,
        "num_workers": 0,
        "T_iterations": 5,
        "sample_camera_num": 300,
        "num_batch_views": 30,
        "num_src_views_train": 15,
        "lambda_mse": 1.0,
        "lambda_lpips": 0.01,
        "lambda_psnr": 0.001,
        "lambda_ssim": 0.01,
        "lambda_reg": 0.01,
        "reg_epsilon": 0.1,
        "scheduler_gamma": 0.99998,
        "warmup_steps": 50,
        "voxel_size": 0.04,
        "cam_names": ["cam0", "cam2", "cam3", "cam4", "cam5", "cam6"],
        "root_data_folder": "/workspace/dusc@xiaopeng.com/online_data/data",
        "validation_data_folder": "/workspace/group_share/adc-sim/users/yangxh7/datasets/fm_pose_crop/c-10ce0565-ffaf-378d-bd9c-845893333d1d",
    }

    if config['region'] == "ground":
        print("Groud Region Type")
        config["explicit_dim"] = 7
        config["latent_dim_only"] = 16
    elif config['region'] == "bkgd":
        print("Bkgd Region Type")
        config["explicit_dim"] = 11
        config["latent_dim_only"] = 24
    else:
        print("False Region Type")
    config['total_latent_dim'] = config['explicit_dim'] + config['latent_dim_only']
    return config

def modify_inference_config(config):
    config["cam_names"] = ["cam3", "cam4", "cam2", "cam0"]
    config["num_points_train"] = 15000000
    config["voxel_size"] = 0.02

    config["num_batch_views_cam02"] = 10
    config["num_batch_views_cam34"] = 25
    config["sample_camera_num"] = 50
    config["num_batch_views"] = 50
    return config