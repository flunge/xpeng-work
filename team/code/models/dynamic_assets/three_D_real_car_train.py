# automatically run the 3D real car pre process and training

import os
import shutil
import logging
import argparse
import datetime

import three_D_real_car_preprocess.three_D_RealCar_Toolkit.data_preprocess.utils.masked_image_generate as masked_image_generate

def run_cmd_and_log_out(cmd):
    logging.info(f"Running command: {cmd}")
    result = os.system(cmd)
    if result != 0:
        logging.error(f"Command failed with exit code {result}: {cmd}")
    return result


def pre_process(data_path, config_name, del_files):
    logging.info("[pre_process] Starting preprocessing for 3D real car data...")
    
    # data_path should has keyword: "3dgs_dynamic"
    if "3dgs_dynamic" not in data_path:
        logging.error("[pre_process] Data path must contain '3dgs_dynamic'.")
        return
    
    # dataset_name should be data_path's last directory name
    dataset_name = os.path.basename(data_path)
    dataset_parent_dir = os.path.dirname(data_path)

    code_base_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 
        "three_D_real_car_preprocess", 
        "three_D_RealCar_Toolkit", 
        "data_preprocess"
    )

    logging.info(f"[pre_process] Dataset name: {dataset_name}, Parent directory: {dataset_parent_dir}, Code base directory: {code_base_dir}")

    # # Run below code to rearrange dataset
    # cd DATASET_NAME
    # mkdir 3dscanner_origin
    # mv *.* 3dscanner_origin
    # check if 3dscanner_origin exists
    three_D_scanner_dir = os.path.join(data_path, '3dscanner_origin')
    if os.path.exists(three_D_scanner_dir):
        logging.info(f"[pre_process] 3D scanner origin directory {three_D_scanner_dir} already exists.")
    else:
        logging.info(f"[pre_process] 3D scanner origin directory {three_D_scanner_dir} does not exist, creating it...")
        if not os.path.exists(data_path):
            logging.error(f"[pre_process] Data path {data_path} does not exist.")
            return

        # create a 3dscanner_origin directory
        logging.info(f"[pre_process] Creating directory for 3D scanner origin data at {data_path}...")
        os.makedirs(three_D_scanner_dir, exist_ok=True)

        # move all files to 3dscanner_origin
        logging.info(f"[pre_process] Moving files to {three_D_scanner_dir}...")
        cmd = f"mv {data_path}/*.* {three_D_scanner_dir}"
        run_cmd_and_log_out(cmd)
    
    # /workspace/group_share/adc-sim/users/wangyl11/3dgs_dynamic/dataset/0-200_v2/2024_06_04_13_44_39/colmap_processed/pcd_rescale/sparse/0/points3D.ply
    final_result_file = os.path.join(data_path, "colmap_processed", "pcd_rescale", "sparse", "0", "points3D.ply")
    pre_process_finished = False
    if os.path.exists(final_result_file):
        pre_process_finished = True
        logging.info(f"[pre_process] Final result file {final_result_file} already exists, skip preprocessing.")

    # Run the preprocessing script - colmap process
    if not pre_process_finished:
        logging.info("[pre_process] Running the colmap script...")
        script_path = "./three_D_real_car_preprocess/three_D_RealCar_Toolkit/data_preprocess/bash/pipeline.sh"

        if not os.path.exists(script_path):
            logging.error(f"[pre_process] Preprocessing script {script_path} does not exist.")
            return
        
        logging.info(f"[pre_process] Executing [colmap] preprocessing script: {script_path} with dataset {dataset_name}...")
        yaml_exp_name = config_name if config_name else "demo"
        
        cmd = f"bash {script_path} {dataset_name} dataset {yaml_exp_name} {dataset_parent_dir} {code_base_dir}"
        run_cmd_and_log_out(cmd)

        # Run the preprocessing script - segmentation process
        # run "export HF_ENDPOINT=https://hf-mirror.com"
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        os.environ["HF_HOME"] = "/root/install/huggingface"
        logging.info("[pre_process] Set HF_ENDPOINT to https://hf-mirror.com")

        logging.info("[pre_process] Running the segmentation preprocessing script...")
        cmd = f"bash {script_path} {dataset_name} segmentation {yaml_exp_name} {dataset_parent_dir} {code_base_dir}"
        run_cmd_and_log_out(cmd)

        # Run the preprocessing script - pcd clean process
        logging.info("[pre_process] Running the pcd clean preprocessing script...")
        cmd = f"bash {script_path} {dataset_name} pcd_clean {yaml_exp_name} {dataset_parent_dir} {code_base_dir}"
        run_cmd_and_log_out(cmd)

        # Run the preprocessing script - pcd standard
        logging.info("[pre_process] Running the pcd standard preprocessing script...")
        cmd = f"bash {script_path} {dataset_name} pcd_standard {yaml_exp_name} {dataset_parent_dir} {code_base_dir}"
        run_cmd_and_log_out(cmd)

        # Run the preprocessing script - pcd rescale
        logging.info("[pre_process] Running the pcd rescale preprocessing script...")
        cmd = f"bash {script_path} {dataset_name} pcd_rescale {yaml_exp_name} {dataset_parent_dir} {code_base_dir}"
        run_cmd_and_log_out(cmd)

        # Run the preprocessing script - mask extract
        logging.info("[pre_process] Running the mask extract preprocessing script...")
        target_dir = os.path.join(data_path, "colmap_processed", "pcd_rescale")
        masked_dir = os.path.join(target_dir, "masked_images")
        if not os.path.exists(masked_dir):
            masked_image_generate.process_mask_images(target_dir)
        else:
            logging.info(f"[pre_process] Masked images already exist in {masked_dir}, skipping mask extraction.")

        logging.info("[pre_process] Preprocessing completed.")

        # tar.gz the processed data, in "colmap_processed"
        logging.info("[pre_process] Tarring the processed data...")
        tar_file_path = tar_processed_data(data_path)

        # upload the tar file to oss
        upload_tar_to_oss(dataset_name, tar_file_path, "colmap_processed")

        meta_file_path = os.path.join(target_dir, "sparse", "0", "meta.json")
        upload_meta_to_oss(dataset_name, meta_file_path, "colmap_processed")

        # delete colmap_processed but colmap_processed/pcd_rescale and delete the tar file
        if del_files:
            delete_colmap_processed(data_path, tar_file_path)

def get_train_params_by_asset_type(asset_type):
    train_params = {
        "iterations": 7000,
        "sh_degree": 1,
        "densify_grad_threshold": 0.0004,
        "screen_size_threshold": 250,
        "extent_portion": 0.1
    }

    if asset_type == "VRU": 
        train_params["extent_portion"] = 0.05
    elif asset_type == "vehicle":
        # train_params["densify_grad_threshold"] = 0.0008
        train_params["screen_size_threshold"] = 1000
        train_params["extent_portion"] = 0.07

    return train_params

def train_gaussian_splatting(data_path, asset_type):
    script_path = "./gaussians_splatting/gaussian-splatting/train.py"
    if not os.path.exists(script_path):
        logging.error(f"[train_gaussian_splatting] Training script {script_path} does not exist.")
        return
    logging.info(f"[train_gaussian_splatting] Executing training script: {script_path} with data path {data_path}...")

    # colmap_processed/pcd_rescale
    processed_data_path = os.path.join(data_path, "colmap_processed", "pcd_rescale")
    if not os.path.exists(processed_data_path):
        logging.error(f"[train_gaussian_splatting] Processed data path {processed_data_path} does not exist.")
        return

    datetime_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(data_path, "trained_results", datetime_str)

    tar_path_dir = os.path.join(data_path, "trained_results")
    if os.path.exists(tar_path_dir):
        # check if tar_path_dir contains file that start with trained_, end with .tar.gz
        tar_files = [f for f in os.listdir(tar_path_dir) if f.startswith("trained_") and f.endswith(".tar.gz")]
        if tar_files:
            logging.warning(f"[train_gaussian_splatting] tar files found in {tar_path_dir}, train already done")
            return

    train_params = get_train_params_by_asset_type(asset_type)
    iterations = train_params.get("iterations", 7000)
    sh_degree = train_params.get("sh_degree", 1)
    densify_grad_threshold = train_params.get("densify_grad_threshold", 0.0004)
    screen_size_threshold = train_params.get("screen_size_threshold", 250)
    extent_portion = train_params.get("extent_portion", 0.1)

    # python train.py -s /workspace/group_share/adc-sim/users/wangyl11/3dgs_dynamic/dataset/HQ200/HQ200/2024_09_23_11_13_10_anonymous_tricycl/colmap_processed/pcd_rescale -i masked_images --iterations 7000 --sh_degree 1 --densify_grad_threshold 0.0002 --debug_from 6000
    cmd = f"python {script_path} \
        -s {processed_data_path} \
        -m {output_dir} \
        -i masked_images \
        --iterations {iterations} \
        --sh_degree {sh_degree} \
        --densify_grad_threshold {densify_grad_threshold} \
        --screen_size_threshold {screen_size_threshold} \
        --extent_portion {extent_portion} \
    "
    logging.info(f"[train_gaussian_splatting] Running command: {cmd}")
    run_cmd_and_log_out(cmd)

    logging.info("[train_gaussian_splatting] Training completed.")

    tar_file_path = tar_trained_results(output_dir)
    dataset_name = os.path.basename(data_path)
    if tar_file_path:
        logging.info(f"[train_gaussian_splatting] Tar file created at {tar_file_path}.")
        upload_tar_to_oss(dataset_name, tar_file_path, "trained_results")

        ply_file_path = os.path.join(output_dir, "point_cloud", f"iteration_{iterations}" , "point_cloud.ply")
        upload_ply_to_oss(dataset_name, ply_file_path, "trained_results")

        rendered_image_dir = os.path.join(output_dir, "rendered_images")
        upload_images_to_oss(dataset_name, rendered_image_dir, "trained_results")


def upload_ply_to_oss(dataset_name, ply_file_path, process_name):
    """
    Upload the ply file to OSS.
    """
    if not os.path.exists(ply_file_path):
        logging.error(f"[upload_ply_to_oss] PLY file {ply_file_path} does not exist.")
        return

    oss_path = f"3dgs_dynamic/{dataset_name}/{process_name}/point_cloud_{dataset_name}.ply"
    upload_file_to_oss(ply_file_path, oss_path)
    logging.info(f"[upload_ply_to_oss] Successfully uploaded {ply_file_path} to OSS at {oss_path}.")

def upload_images_to_oss(dataset_name, image_dir, process_name):
    """
    Upload all images in the specified directory to OSS.
    """
    if not os.path.exists(image_dir):
        logging.error(f"[upload_images_to_oss] Image directory {image_dir} does not exist.")
        return

    oss_path = f"3dgs_dynamic/{dataset_name}/{process_name}/rendered_images/"
    for image_file in os.listdir(image_dir):
        if image_file.endswith(".png") or image_file.endswith(".jpg"):
            file_path = os.path.join(image_dir, image_file)
            upload_file_to_oss(file_path, oss_path + image_file)
            logging.info(f"[upload_images_to_oss] Successfully uploaded {file_path} to OSS at {oss_path + image_file}.")
    
    logging.info(f"[upload_images_to_oss] All images uploaded to OSS at {oss_path}.")


def tar_trained_results(output_dir):
    """
    Tar the trained results in trained_results directory.
    """
    if not os.path.exists(output_dir):
        logging.error(f"[tar_trained_results] Trained results directory {output_dir} does not exist.")
        return None

    tar_file_name = f"trained_{os.path.basename(output_dir)}.tar.gz"
    tar_file_path = os.path.join(os.path.dirname(output_dir), tar_file_name)
    if os.path.exists(tar_file_path):
        logging.info(f"[tar_trained_results] Tar file {tar_file_path} already exists, skipping tar creation.")
    else:
        logging.info(f"[tar_trained_results] Creating tar file {tar_file_path}...")
        cmd = f"tar -czf {tar_file_path} -C {os.path.dirname(output_dir)} {os.path.basename(output_dir)}"
        run_cmd_and_log_out(cmd)

    return tar_file_path

def delete_colmap_processed(data_path, tar_file_path):
    """
    Delete the colmap_processed directory except for pcd_rescale.
    """
    colmap_processed_dir = os.path.join(data_path, "colmap_processed")
    if not os.path.exists(colmap_processed_dir):
        logging.error(f"[delete_colmap_processed] Colmap processed directory {colmap_processed_dir} does not exist.")
        return
    
    for item in os.listdir(colmap_processed_dir):
        item_path = os.path.join(colmap_processed_dir, item)
        if item != "pcd_rescale":
            if os.path.isdir(item_path):
                logging.info(f"[delete_colmap_processed] Deleting directory {item_path}...")
                # remove recursively
                shutil.rmtree(item_path)
            else:
                logging.info(f"[delete_colmap_processed] Deleting file {item_path}...")
                os.remove(item_path)
    
    logging.info(f"[delete_colmap_processed] Deleted all files in {colmap_processed_dir} except for pcd_rescale.")

    # delete the tar file if it exists
    if os.path.exists(tar_file_path):
        logging.info(f"[delete_colmap_processed] Deleting tar file {tar_file_path}...")
        os.remove(tar_file_path)
    
    logging.info("[delete_colmap_processed] Successfully deleted unnecessary files in colmap_processed.")


def tar_processed_data(data_path):
    """
    Tar the processed data in colmap_processed directory.
    """
    colmap_processed_dir = os.path.join(data_path, "colmap_processed")
    if not os.path.exists(colmap_processed_dir):
        logging.error(f"[tar_process] Colmap processed directory {colmap_processed_dir} does not exist.")
        return None
    
    tar_file_name = f"{os.path.basename(data_path)}_colmap_processed.tar.gz"
    tar_file_path = os.path.join(data_path, tar_file_name)
    if os.path.exists(tar_file_path):
        logging.info(f"[tar_process] Tar file {tar_file_path} already exists, skipping tar creation.")
    else:
        logging.info(f"[tar_process] Creating tar file {tar_file_path}...")
        cmd = f"tar -czf {tar_file_path} -C {data_path} colmap_processed"
        run_cmd_and_log_out(cmd)
    
    return tar_file_path

def upload_meta_to_oss(dataset_name, meta_file_path, process_name):
    """
    Upload the meta file to OSS.
    """
    if not os.path.exists(meta_file_path):
        logging.error(f"[upload_meta_to_oss] Meta file {meta_file_path} does not exist.")
        return

    oss_path = f"3dgs_dynamic/{dataset_name}/{process_name}/meta.json"
    upload_file_to_oss(meta_file_path, oss_path)
    logging.info(f"[upload_meta_to_oss] Successfully uploaded {meta_file_path} to OSS at {oss_path}.")


def upload_tar_to_oss(dataset_name, tar_file_path, process_name):
    if not os.path.exists(tar_file_path):
        logging.error(f"[upload_tar_to_oss] Tar file {tar_file_path} does not exist.")
        return

    """
    Upload the tar file to OSS.
    """
    oss_path = f"3dgs_dynamic/{dataset_name}/{process_name}/{os.path.basename(tar_file_path)}"
    upload_file_to_oss(tar_file_path, oss_path)
    logging.info(f"[upload_tar_to_oss] Successfully uploaded {tar_file_path} to OSS at {oss_path}.")

def upload_file_to_oss(file_path, oss_path):
    """
    Upload a single file to OSS.
    """
    oss_bucket = "cloudsim-ci-sh"
    oss_endpoint = "http://oss-cn-wulanchabu-internal.aliyuncs.com"
    access_key_id = os.environ.get("OSS_ACCESS_KEY_ID", "")
    access_key_secret = os.environ.get("OSS_ACCESS_KEY_SECRET", "")

    cmd = f"ossutil -e {oss_endpoint} -i {access_key_id} -k {access_key_secret} -r --parallel 8 cp -f {file_path} oss://{oss_bucket}/{oss_path}"
    logging.info(f"[upload_file_to_oss] Uploading {file_path} to OSS at {oss_path}...")
    run_cmd_and_log_out(cmd)
    
    logging.info(f"[upload_file_to_oss] Successfully uploaded {file_path} to OSS at {oss_path}.")

def parse_args_builder():
    """
    Parse command line arguments for the script.
    """
    parser = argparse.ArgumentParser(description="Preprocess 3D data and upload to OSS.")
    parser.add_argument("--data_path", type=str, help="Path to the data directory.")
    parser.add_argument("--config_name", type=str, help="Name of the configuration file.")
    parser.add_argument("--asset_type", type=str, help="Type of the asset.")
    parser.add_argument("--del_files", type=bool, default=False, help="Delete intermediate files.")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args_builder()

    data_path = args.data_path
    config_name = args.config_name
    asset_type = args.asset_type
    del_files = args.del_files

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    pre_process(data_path, config_name, del_files)

    train_gaussian_splatting(data_path, asset_type)
