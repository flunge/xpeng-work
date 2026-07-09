import os
import pickle
from datasets import Dataset, Image, Value
import argparse

def gen_multi_meta_info(train_pkl_for_lora_path, render_data_dir, ground_truth_dir, data_dict_o):
    # for render_data_dir, ground_truth_dir in zip(render_data_dirs, ground_truth_dirs):
    data_dict_null = {
        "input_image": [],
        "edit_prompt": [],
        "edited_image": [],
    }
    data_dict = gen_meta_info(render_data_dir, ground_truth_dir, data_dict_null)
    data_name = os.path.basename(ground_truth_dir)
    output_pkl_file = os.path.join(train_pkl_for_lora_path, data_name + ".pkl")
    print(ground_truth_dir)
    with open(output_pkl_file, "wb") as f:
        pickle.dump(data_dict, f)
    return data_dict_o

def gen_meta_info(render_data_dir, ground_truth_dir, data_dict):
    for num_iter in range(1000, 30500, 1000):
        if num_iter % 3 == 0:
            continue
        iteration_dir = f"iter{num_iter}"
        render_data_dir_per_iter = os.path.join(render_data_dir, "pix2pix_data", iteration_dir)
        if not os.path.exists(render_data_dir_per_iter):
            print("{0} not exist".format(render_data_dir_per_iter))
            continue
        for filename in os.listdir(render_data_dir_per_iter):
            img_name, _ = os.path.splitext(filename)
            ts, cam_type, img_type = img_name.split("_")
            if img_type != "rgb":
                continue

            input_image_filename = os.path.join(render_data_dir_per_iter, f"{ts}_{cam_type}_rgb.png")
            edited_image_filename = os.path.join(ground_truth_dir, "images", cam_type, f"{ts}.png")
            if not os.path.exists(input_image_filename):
                raise FileExistsError(input_image_filename)
            if not os.path.exists(edited_image_filename):
                raise FileExistsError(edited_image_filename)

            print("processing ", input_image_filename, " gt ", edited_image_filename)

            data_dict["input_image"].append(input_image_filename)
            data_dict["edit_prompt"].append(f"the Xiaopeng Vehicle of {cam_type.upper()} camera view.")
            data_dict["edited_image"].append(edited_image_filename)

    return data_dict


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--train_pkl_for_lora_path', required=True, type=str)
    parser.add_argument('--clip_output_roots', required=True, type=str)
    parser.add_argument('--ground_truth_roots', required=True, type=str)
    args = parser.parse_args()

    data_dict = {
        "input_image": [],
        "edit_prompt": [],
        "edited_image": [],
    }
    
    data_dict = gen_multi_meta_info(
        train_pkl_for_lora_path=args.train_pkl_for_lora_path,
        render_data_dir=args.clip_output_roots,
        ground_truth_dir=args.ground_truth_roots,
        data_dict_o=data_dict,
    )
