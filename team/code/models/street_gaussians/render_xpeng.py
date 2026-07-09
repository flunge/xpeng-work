import torch 
import os
import json
import time
import torchvision
from tqdm import tqdm
from lib.models.street_gaussian_model import StreetGaussianModel 
from lib.models.street_gaussian_renderer import StreetGaussianRenderer
from lib.datasets.dataset import Dataset
from lib.models.scene import Scene
from lib.utils.img_utils import visualize_depth_numpy
from lib.utils.general_utils import safe_state
from lib.config import cfg, args
from lib.visualizers.xpeng_visualizer import XpengVisualizer


def render_xpeng():
    
    with torch.no_grad():
        dataset = Dataset()        
        gaussians = StreetGaussianModel(dataset.scene_info.metadata)

        scene = Scene(gaussians=gaussians, dataset=dataset)
        renderer = StreetGaussianRenderer()
        
        save_dir = os.path.join(cfg.model_path, 'origin', "iter_{}".format(scene.loaded_iter))
        visualizer = XpengVisualizer(save_dir)
        
        train_cameras = scene.getTrainCameras()
        test_cameras = scene.getTestCameras()
        cameras = train_cameras + test_cameras
        cameras = list(sorted(cameras, key=lambda x: x.id))

        for idx, camera in enumerate(tqdm(cameras, desc="Rendering Trajectory")):
            result = renderer.render_all(camera, gaussians)  
            visualizer.visualize(result, camera)
            print(f"Rendering {idx}/{len(cameras)} images done", flush=True)

        visualizer.summarize()
            

def render_pix2pix_data(ckpt_dir, num_iter, output_dir, camera_shifting=0.0):
    cfg.render.save_image = True
    cfg.render.save_video = False
    ckpt_path = os.path.join(ckpt_dir, f"iteration_{num_iter}.pth")
    if not os.path.exists(ckpt_path):
        print(f"{ckpt_path} not exists")
        return

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    output_dir_iter = os.path.join(output_dir, f"iter{num_iter}")

    os.makedirs(output_dir_iter, exist_ok=True)
    if len(os.listdir(output_dir_iter)) >= 999:
        print(f"skip {output_dir_iter}")
        return

    with torch.no_grad():
        dataset = Dataset()
        gaussians = StreetGaussianModel(dataset.scene_info.metadata)
        scene = Scene(gaussians=gaussians, dataset=dataset, skip_resume=True)
        scene.gaussians.load_state_dict(torch.load(ckpt_path))
        renderer = StreetGaussianRenderer()

        cameras = scene.getTrainCameras()
        cameras = list(sorted(cameras, key=lambda x: x.id))

        if camera_shifting > 0.01:
            for camera in cameras:
                camera.T[0] += camera_shifting
                camera.set_extrinsic(camera.get_extrinsic())

        for camera in tqdm(cameras, desc=f"Rendering Trajectory Iter {num_iter}"):
            result = renderer.render_all(camera, gaussians)
            img_name = camera.image_name
            cam_type = camera.meta["cam"]
            torchvision.utils.save_image(
                result["rgb"],
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_rgb.png"),
            )
            depth_colored = visualize_depth_numpy(result["depth"].cpu().numpy().squeeze(0))[0]
            depth_colored = depth_colored[..., [2, 1, 0]] / 255.
            depth_colored = torch.from_numpy(depth_colored).permute(2, 0, 1).float()
            torchvision.utils.save_image(
                depth_colored,
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_depth.png"),
            )
            torchvision.utils.save_image(
                result["rgb_background"],
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_background.png"),
            )
            torchvision.utils.save_image(
                result["rgb_object"],
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_object.png"),
            )
            torchvision.utils.save_image(
                (result["acc_object"] > 0.8) * 255.0,
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_objMask.png"),
            )
            torchvision.utils.save_image(
                ((1 - result["acc"]) > 0.8) * 255.0,
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_skyMask.png"),
            )


if __name__ == "__main__":
    if cfg.mode == "pix2pix_data":
        print("Generating training data " + cfg.model_path)
        num_iter = cfg.train_xpeng.iterations_ground
        render_pix2pix_data(
            os.path.join(cfg.model_path, "trained_model"), 
            num_iter,
            os.path.join(cfg.model_path, "pix2pix_data"),
        )
    else:
        cfg.mode = "render"
        cfg.loaded_iter = -1
        print("Rendering " + cfg.model_path)
        safe_state(cfg.eval.quiet)
        render_xpeng()
        print("Done")