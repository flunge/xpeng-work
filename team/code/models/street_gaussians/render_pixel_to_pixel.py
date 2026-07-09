import torch
import os
import torchvision
from tqdm import tqdm
from lib.models.street_gaussian_model import StreetGaussianModel
from lib.models.street_gaussian_renderer import StreetGaussianRenderer
from lib.datasets.dataset import Dataset
from lib.models.scene import Scene
from lib.utils.img_utils import visualize_depth_numpy
from lib.utils.general_utils import safe_state
from lib.config import cfg, args
from lib.visualizers.base_visualizer import BaseVisualizer as Visualizer
from lib.visualizers.street_gaussian_visualizer import StreetGaussianVisualizer
import time


def render_sets():
    cfg.render.save_image = True
    cfg.render.save_video = False

    with torch.no_grad():
        dataset = Dataset()
        gaussians = StreetGaussianModel(dataset.scene_info.metadata)
        scene = Scene(gaussians=gaussians, dataset=dataset)
        renderer = StreetGaussianRenderer()

        times = []
        if not cfg.eval.skip_train:
            save_dir = os.path.join(
                cfg.model_path, "train", "ours_{}".format(scene.loaded_iter)
            )
            visualizer = Visualizer(save_dir)
            cameras = scene.getTrainCameras()
            for idx, camera in enumerate(tqdm(cameras, desc="Rendering Training View")):

                torch.cuda.synchronize()
                start_time = time.time()
                result = renderer.render(camera, gaussians)

                torch.cuda.synchronize()
                end_time = time.time()
                times.append((end_time - start_time) * 1000)

                visualizer.visualize(result, camera)

        if not cfg.eval.skip_test:
            save_dir = os.path.join(
                cfg.model_path, "test", "ours_{}".format(scene.loaded_iter)
            )
            visualizer = Visualizer(save_dir)
            cameras = scene.getTestCameras()
            for idx, camera in enumerate(tqdm(cameras, desc="Rendering Testing View")):

                torch.cuda.synchronize()
                start_time = time.time()

                result = renderer.render(camera, gaussians)

                torch.cuda.synchronize()
                end_time = time.time()
                times.append((end_time - start_time) * 1000)

                visualizer.visualize(result, camera)

        print(times)
        print("average rendering time: ", sum(times[1:]) / len(times[1:]))


def render_trajectory():
    cfg.render.save_image = False
    cfg.render.save_video = True

    with torch.no_grad():
        dataset = Dataset()
        gaussians = StreetGaussianModel(dataset.scene_info.metadata)

        scene = Scene(gaussians=gaussians, dataset=dataset)
        renderer = StreetGaussianRenderer()

        dir_name = f"{args.prefix}_{scene.loaded_iter}"
        if args.camera_shifting > 0.01:
            dir_name += f"_shifting{args.camera_shifting:.1f}"

        save_dir = os.path.join(cfg.model_path, "trajectory", dir_name)
        visualizer = StreetGaussianVisualizer(save_dir)

        train_cameras = scene.getTrainCameras()
        test_cameras = scene.getTestCameras()
        cameras = train_cameras + test_cameras
        cameras = list(sorted(cameras, key=lambda x: x.id))

        if args.camera_shifting > 0.01:
            for camera in cameras:
                camera.T[0] += args.camera_shifting
                camera.set_extrinsic(camera.get_extrinsic())

        for idx, camera in enumerate(tqdm(cameras, desc="Rendering Trajectory")):
            result = renderer.render_all(camera, gaussians)
            visualizer.visualize(result, camera)

        visualizer.summarize()


def render_pix2pix_data(ckpt_dir, num_iter, output_dir):
    cfg.render.save_image = True
    cfg.render.save_video = False
    ckpt_path = os.path.join(ckpt_dir, f"iteration_{num_iter}.pth")
    if not os.path.exists(ckpt_path):
        print(f"{ckpt_path} not exists")
        return

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if args.camera_shifting > 0.01:
        output_dir_iter = os.path.join(output_dir, f"iter{num_iter}_shifting{args.camera_shifting:.1f}")
    else:
        output_dir_iter = os.path.join(output_dir, f"iter{num_iter}")

    os.makedirs(output_dir_iter, exist_ok=True)
    # if len(os.listdir(output_dir_iter)) >= 999:
    #     print(f"skip {output_dir_iter}")
    #     return

    with torch.no_grad():
        dataset = Dataset()
        gaussians = StreetGaussianModel(dataset.scene_info.metadata)
        scene = Scene(gaussians=gaussians, dataset=dataset, skip_resume=True)
        scene.gaussians.load_state_dict(torch.load(ckpt_path))
        renderer = StreetGaussianRenderer()

        cameras = scene.getTrainCameras()
        cameras = list(sorted(cameras, key=lambda x: x.id))

        if args.camera_shifting > 0.01:
            for camera in cameras:
                camera.T[0] += args.camera_shifting
                camera.set_extrinsic(camera.get_extrinsic())

        for camera in tqdm(cameras, desc=f"Rendering Trajectory Iter {num_iter}"):
            print("render pixtopix cam: {0}".format(camera))
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
            print("save image colored")
            torchvision.utils.save_image(
                depth_colored,
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_depth.png"),
            )
            print("save image rgb_background")
            torchvision.utils.save_image(
                result["rgb_background"],
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_background.png"),
            )
            print("save image rgb_object")
            torchvision.utils.save_image(
                result["rgb_object"],
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_object.png"),
            )
            print("save image acc_object")
            torchvision.utils.save_image(
                (result["acc_object"] > 0.8) * 255.0,
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_objMask.png"),
            )
            print("save image acc")
            torchvision.utils.save_image(
                ((1 - result["acc"]) > 0.8) * 255.0,
                os.path.join(output_dir_iter, f"{img_name}_{cam_type}_skyMask.png"),
            )

import threading
import sys
global stop_thread
def flush_stdout_thread():
    while not stop_thread:
        time.sleep(1000)
        print("flush stdout")
        sys.stdout.flush()

def render_pix2pix_thread(arg_ckpt_dir, arg_output_dir, arg_num_iter) :
    render_pix2pix_data(
        ckpt_dir=arg_ckpt_dir,
        output_dir=arg_output_dir,
        num_iter=arg_num_iter,
    )

if __name__ == "__main__":
    print("Rendering " + cfg.model_path)
    safe_state(cfg.eval.quiet)

    # print log prevent from being killed
    stop_thread = False
    flush_thread = threading.Thread(target=flush_stdout_thread)
    flush_thread.start()  # prevent fuyao from stoping the job if no print out

    print("render pix2pix iter: ", str(args.render_pix2pix_iter))

    cfg.mode = "pix2pix_data"
    
    render_pix2pix_data(
        ckpt_dir=os.path.join(cfg.model_path, "trained_model"),
        output_dir=os.path.join(args.output_path, "pix2pix_data"),
        num_iter=args.render_pix2pix_iter,
    )

    stop_thread = True
    flush_thread.join()