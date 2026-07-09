import os
import sys
import logging
import argparse
import datetime

import three_D_real_car_train as three_d_train

def write_error_log(data_dir, error_logs):
    """
    Write error logs to a file.
    """
    log_file = os.path.join(data_dir, "error_log.txt")
    with open(log_file, "a") as f:
        for error in error_logs:
            f.write(f"{datetime.datetime.now()} - {error}\n")

def batch_run_training(data_dir, config_name, asset_type, del_files):
    """
    Run the training process in batch mode.
    """
    logging.info(f"[batch_run_training] Running batch training with data directory: {data_dir}, config name: {config_name}, and asset type: {asset_type}")

    # get all sub dir in data_dir
    sub_dirs = [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))]
    logging.info(f"[batch_run_training] Found subdirectories size: {len(sub_dirs)}")

    skip_list = [
        "2024_06_30_14_36_20",
        "2024_06_30_14_46_25",
        "2024_07_01_15_42_20"
    ]

    for sub_dir in sub_dirs:
        sub_abs_dir = os.path.join(data_dir, sub_dir)
        logging.info(f"[batch_run_training] Processing subdirectory: {sub_abs_dir}")

        if sub_dir in skip_list:
            logging.info(f"[batch_run_training] Skipping {sub_abs_dir} as it is in the skip list.")
            continue

        # check sub_dir or sub_dir/3dscanner_origin contains frame_***.jpg
        three_d_origin_dir = os.path.join(sub_abs_dir, "3dscanner_origin")
        check_dir = sub_abs_dir
        if os.path.exists(three_d_origin_dir):
            check_dir = three_d_origin_dir

        # Check if the directory contains any frame_***.jpg files
        jpg_files = [f for f in os.listdir(check_dir) if f.endswith(".jpg") and "frame_" in f]
        if jpg_files:
            logging.info(f"[batch_run_training] Found {len(jpg_files)} frame images in {check_dir}")
        else:
            logging.warning(f"[batch_run_training] No frame images found in {check_dir}")
            continue

        # check if dir contain " " or "tricy" or "special", is so then skip
        if " " in sub_dir or "tricy" in sub_dir or "special" in sub_dir:
            logging.info(f"[batch_run_training] Skipping {sub_abs_dir} as it contains space or 'tricy' or 'special'.")
            continue

        try:
            three_d_train.pre_process(sub_abs_dir, config_name, del_files)
            # TODO: skip train first
            three_d_train.train_gaussian_splatting(sub_abs_dir, asset_type)

        except Exception as e:
            logging.error(f"[batch_run_training] Error occurred while processing {sub_abs_dir}: {e}")
            write_error_log(sub_abs_dir, [f"Error in {sub_abs_dir}: {str(e)}"])
            continue

def parse_args_builder():
    """
    Parse command line arguments for the script.
    """
    parser = argparse.ArgumentParser(description="Batch Run train process.")
    parser.add_argument("--data_dir", type=str, help="Path to the data directory.")
    parser.add_argument("--config_name", type=str, help="Name of the configuration file.")
    parser.add_argument("--asset_type", type=str, help="Type of the asset.")
    parser.add_argument("--del_files", type=bool, default=False, help="Delete intermediate files.")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args_builder()
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    
    # Log the start of the script
    logging.info("Starting the training process with the following parameters:")
    logging.info(f"Data Directory: {args.data_dir}")
    logging.info(f"Configuration Name: {args.config_name}")

    batch_run_training(args.data_dir, args.config_name, args.asset_type, args.del_files)

    logging.info("Training process completed.")