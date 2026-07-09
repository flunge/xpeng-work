import json
import os
import sys
from download_file_from_oss2 import download_file_from_oss2


def pre_processor(context: dict, **kwargs):
    # ================================= ips args ======================================
    print("[INFO] pre_processor")
    print("[INFO] context:")
    print(context)
    print("[INFO] kwargs:")
    print(kwargs)
    overwrite = str(kwargs.get('overwrite', False)).lower() == 'true' or int(kwargs.get('overwrite', True)) == 1
    images_root = kwargs.get('images_root', '/workspace/group_share/adc-sim/users/difix_train/images_origin')
    images_origin_stride = int(kwargs.get('images_origin_stride', 6))

    for item in context['records']:
        clip_id = item["clip_id"]
        images_origin_exist_in_oss = item["images_origin_exist_in_oss"]

        print(f"[INFO] processing clip {clip_id}")

        if images_origin_exist_in_oss:
            clip_src_path = f"{images_root}/{clip_id}"
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
