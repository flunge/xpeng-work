import os
import gc
import sys
import math
import torch
import random
import argparse
import numpy as np
from tqdm import tqdm
from statistics import mean
from datetime import datetime
from torch.utils.data import Dataset, DataLoader

from config import obtain_config
from inference import inference_g3r
from g3r_net import G3RReconstructor
from dataset import XpengDataset, sparse_scenes_collate
from utils.downclip_utils import down_training_data
from utils.general_utils import get_ddim_schedule, get_cosine_schedule, NetMode
from utils.training_cases import training_cases

def train_g3r(log_folder, config, checkpoint = None):
    print("----- start models/g3r train -----, process region: ", config["region"], flush=True)
    existing_cases = os.listdir(config["root_data_folder"])
    g3r_reconstructor = G3RReconstructor(config, log_folder).to(config['device'])

    if checkpoint is not None:
        checkpoint = torch.load(checkpoint, map_location=config['device'])
        g3r_reconstructor.load_state_dict(checkpoint, strict=False)

    gammas = get_cosine_schedule(config['T_iterations']).to(config['device'])
    for epoch in range(config['epochs']):
        print("Epoch ", epoch, flush=True)
        g3r_reconstructor.train()

        epoch_loss_list = []
        epoch_psnr_list = []
        for case_id in training_cases:
            print("Curr case id: ", case_id)
            data_path = os.path.join(config["root_data_folder"], case_id)
            if case_id not in existing_cases:
                download_status = down_training_data(config["root_data_folder"], case_id)
                if not download_status:
                    print("Case Download False")
                    continue

            dataset = XpengDataset(config, data_path, NetMode.TRAIN)
            input_points, coords, unquantized_points_info = dataset.get_points_info()
            total_points_num = input_points.shape[0]
            print("Total points num ", total_points_num)

            for cam_name in config["cam_names"]:
                print("Process Camera: ", cam_name)
                dataset.get_xpeng_scene(cam_name)
                if dataset.data_length == 0:
                    continue
                train_loader = DataLoader(dataset, batch_size=config['batch_size'], shuffle=True, 
                                        num_workers=config['num_workers'], collate_fn=sparse_scenes_collate)

                for batch_idx, batch in enumerate(train_loader):
                    print("Global step: ", g3r_reconstructor.get_step, flush=True)
                    cameras_info, valid_ids = batch["cameras_info"], batch["valid_ids"]
                    valid_ids_arrays = [np.atleast_1d(arr) for arr in valid_ids]
                    update_id = np.unique(np.concatenate(valid_ids_arrays))
                    filter_points = input_points[update_id, :].to(config['device'])
                    filter_coords = coords[update_id, :].to(config['device'])

                    output_metrics = g3r_reconstructor(filter_points, filter_coords, cameras_info, gammas)
                    log_str = (f"loss mean: {output_metrics['loss_mean']:.4f} | "
                               f"loss last: {output_metrics['loss_last']:.4f} | "
                               f"lpips mean: {output_metrics['lpips_mean']:.4f} | "
                               f"lpips last: {output_metrics['lpips_last']:.4f} | "
                               f"psnr mean: {output_metrics['psnr_mean']:.4f} | "
                               f"psnr last: {output_metrics['psnr_last']:.4f}")

                    if not math.isinf(output_metrics['psnr_last']):
                        epoch_loss_list.append(output_metrics['loss_last'])
                        epoch_psnr_list.append(output_metrics['psnr_last'])
                    print(log_str, flush = True)

                    if g3r_reconstructor.get_step % config["evaluation_step"] == 0:
                        g3r_reconstructor.eval()
                        inference_g3r(g3r_reconstructor, NetMode.TRAIN, config, config["validation_data_folder"], os.path.join(log_folder, "eval"))
                        torch.save(g3r_reconstructor.state_dict(), os.path.join(log_folder, str(g3r_reconstructor.get_step) + '_step_model.pth'))
                        g3r_reconstructor.train()

                    del filter_points, filter_coords, output_metrics
                    gc.collect()
                    torch.cuda.empty_cache()

                del train_loader
                gc.collect()
                torch.cuda.empty_cache()

            os.system(f"rm -rf {data_path}")

        with open(os.path.join(log_folder, "epoch_loss.txt"), 'a', encoding='utf-8') as f:
            f.write(str(mean(epoch_loss_list)) + "\n")
        with open(os.path.join(log_folder, "epoch_psnr.txt"), 'a', encoding='utf-8') as f:
            f.write(str(mean(epoch_psnr_list)) + "\n")

        g3r_reconstructor.eval()
        torch.save(g3r_reconstructor.state_dict(), os.path.join(log_folder, str(epoch) + '_epoch_model.pth'))
        g3r_reconstructor.train()

if __name__ == "__main__":
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    torch.cuda.manual_seed_all(42)

    parser = argparse.ArgumentParser(description = "G3R Train Pipeline")
    parser.add_argument("--job_name", type=str, required=True)
    parser.add_argument("--region", type=str, required=True)
    parser.add_argument("--checkpoint", type=str, required=False)
    args = parser.parse_args()

    print("Folder prefix: ", args.job_name, flush=True)
    current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"{args.job_name}_{current_time}")
    os.makedirs(log_folder, exist_ok=True)

    config = obtain_config(args.region)
    train_g3r(log_folder, config, args.checkpoint)
