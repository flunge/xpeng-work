import os
import pickle
from datasets import Dataset, Image, Value
import argparse

sg_render_data_pkl_path="/workspace/zhangzy27@xiaopeng.com/sim4dmodel/lora_gaussian_render/generative_model_data/xh_new_data_1_10/render_pkl/c-0dae3b4a-34dc-33e3-ac2f-017dc4ec9e6c.pkl"
sg_render_data_root="/workspace/zhangzy27@xiaopeng.com/sim4dmodel/output/xh_new_data_1_10/exp_c-0dae3b4a-34dc-33e3-ac2f-017dc4ec9e6c/train/ours_100000"

def gen_render_meta_info(render_data_dir, data_dict):
    if not os.path.exists(render_data_dir):
        raise
    for cam_dir in os.listdir(render_data_dir):
        render_data_cam_dir = os.path.join(render_data_dir, cam_dir)
        if not os.path.exists(render_data_cam_dir):
            raise
        for filename in os.listdir(render_data_cam_dir):
            input_image_filename = os.path.join(render_data_cam_dir, filename)

            print("processing ", input_image_filename)

            if not os.path.exists(input_image_filename):
                raise FileExistsError(input_image_filename)
            print(input_image_filename)
            print(f"the Xiaopeng Vehicle of {cam_dir.upper()} camera view.")
            data_dict["input_image"].append(input_image_filename)
            data_dict["edit_prompt"].append(f"the Xiaopeng Vehicle of {cam_dir.upper()} camera view.")
    return data_dict

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--sg_render_data_pkl_path', required=True, type=str)
    parser.add_argument('--sg_render_data_root', required=True, type=str)
    args = parser.parse_args()

    data_dict = {
        "input_image": [],
        "edit_prompt": [],
    }

    output_pkl_file = args.sg_render_data_pkl_path
    data_dict = gen_render_meta_info(
        render_data_dir=args.sg_render_data_root,
        data_dict=data_dict,
    )
    
    with open(output_pkl_file, "wb") as f:
        pickle.dump(data_dict, f)