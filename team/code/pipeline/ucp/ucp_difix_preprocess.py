import json
import os
import sys
from download_file_from_oss2 import download_file_from_oss2


def pre_processor(context: dict, **kwargs):
    # ================================= ips args ======================================
    print("SKIP pre_processor")
    print("[INFO] pre_processor")
    print("[INFO] context:")
    print(context)
    print("[INFO] kwargs:")
    print(kwargs)
    return


def gpu_processor(context: dict, **kwargs):
    print(f"[GPU] ================================== GPU processor ==================================")
    overwrite = str(kwargs.get('overwrite', False)).lower() == 'true' or int(kwargs.get('overwrite', True)) == 1
    render_stride = int(kwargs.get('render_stride', 6))
    images_origin_stride = int(kwargs.get('images_origin_stride', 6))

    # 将所需路径添加到 sys.path
    simworld_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    omnire_path = os.path.join(simworld_path, 'omnire_joint_trainning', 'src')
    sys.path.extend([omnire_path, simworld_path])
    
    from reconic.simulator.reconic_simulator import ReconicSimulator
    from scripts.render_sim import render_sim
    
    print(f"[GPU] context:")
    print(context)
    print(f"[GPU] kwargs:")
    print(kwargs)
    print(f"[GPU] ================================== GPU processor ==================================")
    
    for item in context['records']:
        clip_id = item["clip_id"]
        model_version = item["model_version"]
        images_origin_exist_in_oss = item["images_origin_exist_in_oss"]

        print(f"[INFO] processing clip {clip_id}")

        if images_origin_exist_in_oss:
            clip_src_path = f"/workspace/group_share/adc-sim/users/cloudsim/images_origin/{clip_id}"
            target_images_path = f"{clip_src_path}/images_origin"
            if not os.path.exists(target_images_path) or overwrite:
                print(f"[INFO] images_origin for clip {clip_id} not exists, downloading from oss")
                os.makedirs(clip_src_path, exist_ok=True)
                images_origin_key = f"sim_engine/datasets/{clip_id}/images_origin/images_origin.tgz"
                download_file_from_oss2(
                    os.path.join(clip_src_path, "images_origin.tgz"),
                    images_origin_key, 
                    show_progress=False
                )
                os.system(f"cd {clip_src_path}; tar xf {os.path.join(clip_src_path, 'images_origin.tgz')}")
                os.system(f"mv {clip_src_path}/model1 {clip_src_path}/images_origin")
                os.system(f"rm {os.path.join(clip_src_path, 'images_origin.tgz')}")
                print(f"[INFO] images_origin for clip {clip_id} downloaded from oss")
                # delete images_origin by the stride
                if images_origin_stride > 1 and os.path.exists(os.path.join(clip_src_path, 'images_origin')):
                    for cam in os.listdir(os.path.join(clip_src_path, 'images_origin')):
                        cam_folder = os.path.join(clip_src_path, 'images_origin', cam)
                        image_names = [x for x in os.listdir(cam_folder) if x.endswith('.png')]
                        sorted_image_names = sorted(image_names, key=lambda x: int(x.split('.')[0]))
                        kept_image_names = sorted_image_names[::images_origin_stride]
                        kept_set = set(kept_image_names)
                        del_paths = [os.path.join(cam_folder, name) for name in sorted_image_names if name not in kept_set]
                        cmd = "rm " + " ".join(f"'{p}'" for p in del_paths)
                        os.system(cmd)
                        print(f"[INFO] deleted {len(del_paths)} images for cam {cam}, total {len(sorted_image_names)} images")
            else:
                print(f"[INFO] images_origin already exists: {target_images_path}")
        
        # download model and render model from oss
        train_data_path = f"/workspace/group_share/adc-sim/users/cloudsim/difix/train_data/{clip_id}"
        target_render_path = os.path.join(train_data_path, model_version, "simulator_render")
        if not os.path.exists(target_render_path):
            train_data_tar = os.path.join(train_data_path, f"3dgs_model_{model_version}.tgz")
            os.makedirs(train_data_path, exist_ok=True)
            download_file_from_oss2(
                train_data_tar, 
                os.path.join("sim_engine/ips_output_reconic", clip_id, model_version, f"3dgs_model.tgz"),
                show_progress=False
            )
            
            os.system(f"cd {train_data_path}; tar xf {train_data_tar}")
            os.system(f"cd {train_data_path}; mv model1 {model_version}")
            os.system(f"rm {train_data_tar}")
        
            config_file = os.path.join(train_data_path, model_version, "configs/config_sim.yaml")
            
            simulator = ReconicSimulator(config_file, cp_simulation=False)
            rendered_timestamps = simulator.timestamps_origin[::render_stride]
            rendered_cameras = simulator.cameras
            egoposes_shifted = simulator.egoposes_anchored_origin
            
            render_sim(simulator, rendered_timestamps, rendered_cameras, egoposes_shifted, 
                    name="origin", save_img=True, save_video=False,
                    save_path=target_render_path, full_mode=False)
            print(f"[INFO] render clip {clip_id} model {model_version} done")
            ckpt_path = os.path.join(train_data_path, model_version, "trained_model", "checkpoint_final.pth")
            segs_path = os.path.join(train_data_path, model_version, "segs")
            ply_path = os.path.join(train_data_path, model_version, "input_ply")
            os.system(f"rm -rf {ckpt_path}")
            os.system(f"rm -rf {segs_path}")
            os.system(f"rm -rf {ply_path}")
        else:
            print(f"[INFO] render already exists: {target_render_path}")

        # check if images_origin and render files are identical for this clip
        src_images_path = f"/workspace/group_share/adc-sim/users/cloudsim/images_origin/{clip_id}/images_origin/cam0"
        src_render_path = f"/workspace/group_share/adc-sim/users/cloudsim/difix/train_data/{clip_id}/{model_version}/simulator_render/redistort_rgb/cam0"
        if os.path.exists(src_images_path) and os.path.exists(src_render_path):
            src_images_files = [x for x in os.listdir(src_images_path) if x.endswith('.png')]
            src_render_files = [x for x in os.listdir(src_render_path) if x.endswith('.png')]
            if len(src_images_files) != len(src_render_files):
                print(f"[INFO] images_origin and render files are not identical for clip {clip_id}")
                continue
            # use set to check how manyfile names are identical (file numbers may be not the same)
            src_images_files_set = set(src_images_files)
            src_render_files_set = set(src_render_files)
            identical_count = len(src_images_files_set & src_render_files_set)
            print(f"[INFO] {identical_count} / {len(src_images_files)} file names are identical")
        else:
            print(f"[INFO] images_origin or render files are not exist for clip {clip_id}")
                