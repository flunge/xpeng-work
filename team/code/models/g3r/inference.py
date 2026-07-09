import os
import gc
import sys
import time
import torch
import random
import argparse
import numpy as np
from functools import reduce
from torchsparse import SparseTensor
from torch.utils.data import Dataset, DataLoader

current_dir = os.path.dirname(__file__)
root_path = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(root_path)

from g3r.config import obtain_config, modify_inference_config
from g3r.g3r_net import G3RReconstructor
from g3r.dataset import XpengDataset, sparse_scenes_collate
from g3r.utils.general_utils import get_ddim_schedule, get_cosine_schedule, NetMode, metric_evaluation
from g3r.utils.ply_utils import update_g3r_gaussians_with_count, save_vis_g3r_gaussians,\
    save_init_g3r_gaussians, convertG3RPly, average_g3r_gaussians, merge_g3r_gaussians, repair_gaussians


def inference_g3r(g3r_reconstructor, net_mode, cfg, source_data, log_folder):
    print("Start models/g3r inference", flush=True)
    use_g3r_avg = True
    if log_folder is not None:
        if not os.path.exists(log_folder):
            os.makedirs(log_folder, exist_ok=True)

    g3r_reconstructor.set_netmode(net_mode)
    dataset = XpengDataset(cfg, source_data, net_mode)
    input_points, coords, unquantized_points_info = dataset.get_points_info()
    total_points_num = input_points.shape[0]
    print("Total points num ", total_points_num)

    all_updated_id = set()
    cam_list = cfg["cam_names"]
    total_scene_gaussians = None
    update_id_counts = None
    total_cameras_info = {}
    camera_update_weight = {"cam3": 2.0, "cam4": 2.0, "cam5": 2.0, "cam6": 2.0, "cam2": 0.6, "cam0": 1.5}

    for cam_name in cam_list:
        print("Process Camera: ", cam_name)
        total_cameras_info[cam_name] = []
        dataset.get_xpeng_scene(cam_name)
        eval_loader = DataLoader(dataset, batch_size=cfg['batch_size'], shuffle=False, 
                                num_workers=cfg['num_workers'], collate_fn=sparse_scenes_collate)

        for batch_idx, batch in enumerate(eval_loader):
            cameras_info, valid_ids = batch["cameras_info"], batch["valid_ids"]
            total_cameras_info[cam_name].append(cameras_info)
            if use_g3r_avg:
                curr_update_id = np.unique(np.concatenate(valid_ids))
                points_num = curr_update_id.shape[0]
                if points_num > 700000:
                    curr_update_id = curr_update_id[np.random.choice(points_num, 700000, replace=False)]
                curr_update_id_set = set(curr_update_id)
                all_updated_id = all_updated_id | curr_update_id_set
            else:
                curr_update_id_set = set(np.unique(np.concatenate(valid_ids)))
                curr_update_id = np.array(list(curr_update_id_set - all_updated_id))
                if curr_update_id.shape[0] < 10:
                    continue
                all_updated_id = all_updated_id | curr_update_id_set
            print("Curr update length: ", curr_update_id.shape[0])

            curr_input_points = input_points[curr_update_id, :].to(cfg['device'])
            curr_coords = coords[curr_update_id, :].to(cfg['device'])
            data_length = len(cameras_info["timestamps"])
            view_ids = torch.arange(data_length)

            positions, rotations, priori_colors, priori_scales, S_t_detached = g3r_reconstructor.initialize_neural_gaussians(curr_input_points)
            gammas = get_cosine_schedule(cfg['T_iterations']).to(cfg['device'])
            for t_step in range(cfg['T_iterations']):
                print("Process Step: ", t_step, flush = True)
                grad_S_t = g3r_reconstructor.compute_gradient_feedback(S_t_detached, cameras_info, view_ids, positions, rotations, priori_colors, priori_scales)
                x_in = torch.cat([S_t_detached, grad_S_t], dim=-1)
                sparse_in = SparseTensor(feats=x_in, coords=curr_coords)
                update_list = g3r_reconstructor.g3r_net(sparse_in, torch.tensor([t_step], dtype=cfg["data_type"], device=cfg['device']))

                S_updated_feats = S_t_detached + gammas[t_step] * update_list[-1].feats
                current_gaussians = g3r_reconstructor.decoder(S_updated_feats, positions, rotations, priori_colors, priori_scales)
                S_t_detached = S_updated_feats.detach()
                gc.collect()
                torch.cuda.empty_cache()

            if use_g3r_avg:
                total_scene_gaussians, update_id_counts = update_g3r_gaussians_with_count(\
                    total_scene_gaussians, update_id_counts, current_gaussians, curr_update_id,\
                    total_points_num, camera_update_weight[cam_name])
            else:
                total_scene_gaussians = merge_g3r_gaussians(total_scene_gaussians, current_gaussians)

        del eval_loader
        gc.collect()
        torch.cuda.empty_cache()

    if use_g3r_avg:
        total_scene_gaussians = average_g3r_gaussians(total_scene_gaussians, update_id_counts)
    total_scene_gaussians = repair_gaussians(total_scene_gaussians, all_updated_id, input_points, unquantized_points_info)
    metric_output = metric_evaluation(total_cameras_info, total_scene_gaussians, log_folder)

    if log_folder is not None:
        record_metrics(metric_output, g3r_reconstructor.get_step, log_folder, net_mode)
        save_vis_g3r_gaussians(total_scene_gaussians, os.path.join(log_folder, "g3r_ground_vis.ply"))
        save_init_g3r_gaussians(total_scene_gaussians, os.path.join(log_folder, "g3r_ground.ply"))

    print("total scene gaussians number: ", total_scene_gaussians["means"].shape)
    del total_scene_gaussians, dataset, input_points, coords, g3r_reconstructor
    gc.collect()
    torch.cuda.empty_cache()
    return

def record_metrics(metric_output, train_step, log_folder, net_mode):
    log_str = f'Evaluation at step {train_step} | PSNR: {metric_output["total_psnr"]} | LPIPS: {metric_output["total_lpips"]}'
    print(log_str, flush=True)
    with open(os.path.join(log_folder, "eval_metrics.txt"), 'a', encoding='utf-8') as f:
        if net_mode == NetMode.TRAIN:
            f.write(f"Step {train_step} | ")
        elif net_mode == NetMode.INFERENCE:
            f.write(f"Inference | ")
        for key, value in metric_output.items():
            f.write(f"{key}: {value:.4f} ")
        f.write("\n")

def print_memory_usage(step_name=""):
    allocated = torch.cuda.memory_allocated() / 1024**2
    reserved = torch.cuda.memory_reserved() / 1024**2
    print(f"[{step_name}] Allocated: {allocated:.2f} MB, Reserved: {reserved:.2f} MB")

def inference_g3r_interface(region_type, model_pth, source_data, log_folder = None):
    cfg = obtain_config(region_type)
    cfg = modify_inference_config(cfg)

    g3r_reconstructor = G3RReconstructor(cfg, log_folder).to(cfg['device'])
    checkpoint = torch.load(model_pth, map_location=cfg['device'])
    g3r_reconstructor.load_state_dict(checkpoint, strict=False)
    inference_g3r(g3r_reconstructor, NetMode.INFERENCE, cfg, source_data, log_folder)
    return

if __name__ == "__main__":
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    torch.cuda.manual_seed_all(42)

    import argparse
    parser = argparse.ArgumentParser(description="Fuyao Production Training Script")
    parser.add_argument("--clip_id", type=str, help="Clip ID for training")
    args = parser.parse_args()
    source_path = f"/workspace/dusc@xiaopeng.com/datasets/tmp/{args.clip_id}/"
    model_path = os.path.join(source_path, "g3r_ground")
    region_type = "ground"
    model_pth = "/workspace/dusc@xiaopeng.com/g3r_pth/g3r_ground.pth"

    time1 = time.time()
    inference_g3r_interface(region_type, model_pth, source_path, model_path)
    time2 = time.time()
    print("models/g3r inference time: ", time2 - time1)
