import os
import yaml
import json
import shutil

import numpy as np
import shutil


def set_default_value(config, key, value):
    if key not in config:
        config[key] = value

def backward_support(config):
    """
    Support old version configs for backward compatibility.
    """
    ### Set mode to "recon" if using two-stage IPS
    if "mode" not in config or config["mode"] in ["two_stage", "end2end"]:
        config["mode"] = "recon"

    ### Use sfm trips as merged trips if only one trip passed sfm
    if not os.path.exists(os.path.join(config["exp_dir"], "merged_trips.json")) \
        and os.path.exists(os.path.join(config["exp_dir"], "sfm_trips.json")):
        shutil.copyfile(os.path.join(config["exp_dir"], "sfm_trips.json"), os.path.join(config["exp_dir"], "merged_trips.json"))

    ### data_cache_saving_dir changed since v1.4
    if config["dataset_name"] == "vision_bases_gt":
        config["data_cache_saving_dir"] = "/workspace/group_share/adc-perception-staticxnet/mapless_warmup_cache"

    return config

def add_avm_configs(config):
    code_dir = os.path.dirname(os.path.abspath(__file__))
    avm_config_path = os.path.join(code_dir, 'avm.yaml')
    avm_config = yaml.load(open(avm_config_path, 'r'), Loader=yaml.FullLoader)
    config['avm_cam_list'] = avm_config.get("avm_cam_list", ['cam9', 'cam10', 'cam11', 'cam12'])
    config['dummy_cam_list'] = avm_config.get('dummy_cam_list', {})
    # config["cam_list"] = config["cam_list"] + config['avm_cam_list']
    for item in config['avm_cam_list']:
        if item not in config['cam_list']:
            config['cam_list'].append(item)

    print("avm_cam_list: ", config['avm_cam_list'])
    print("cam_list: ", config['cam_list'])

    if config['dummy_cam_list'] and len(config['dummy_cam_list'].keys()) != 0:
        config["single_trip_sfm_cam_list"] = config["cam_list"] + list(config['dummy_cam_list'].keys())

    rome_cam_list_mode = config.get('rome_cam_list_mode', 1)   # 1-only avm; 2-only pinhole; 3-avm + pinhole
    assert rome_cam_list_mode in [1, 2, 3], f"fail to check rome_cam_list_mode: {rome_cam_list_mode}"
    if rome_cam_list_mode == 1:
        config["rome_cam_list"] = list(config['avm_cam_list'])
        config["ref_cam"] = "cam9"
    elif rome_cam_list_mode == 2:
        config["rome_cam_list"] = [cam_id for cam_id in config["cam_list"] if cam_id not in config['avm_cam_list']]
    else:
        config["rome_cam_list"] = list(config["cam_list"])

    return config

def load_config(config_path):
    """
    Parse the config file and set default values.
    """
    config = yaml.safe_load(open(config_path))

    config = backward_support(config)

    # General configs
    config["ips"] = config.get("ips", False)
    if config["mode"] == "recon":
        config["rome_output_dir"] = config.get("rome_output_dir", os.path.join(config["exp_dir"], "rome_output"))
        config["trips_json"] = config.get("trips_json", os.path.join(config["exp_dir"], "merged_trips.json"))
    elif config["mode"] == "reloc":
        config["reloc_dir"] = config.get("reloc_dir", os.path.join(config["exp_dir"], "reloc"))
        config["rome_output_dir"] = config.get("rome_output_dir", os.path.join(config["reloc_dir"], "rome_output"))
        config["trips_json"] = config.get("trips_json", os.path.join(config["reloc_dir"], "merged_trips.json"))
    else:
        raise ValueError(f"Unsupported mode: {config['mode']}")
    config["dump_clip_data"] = config.get("dump_clip_data", True)

    # Asset configs
    if os.path.exists("/recon_pretrained_models"):
        pretrained_model_path = "/recon_pretrained_models"
    elif os.path.exists("/workspace/group_share/adc-perception-staticxnet/recon_pretrained_models"):
        pretrained_model_path = "/workspace/group_share/adc-perception-staticxnet/recon_pretrained_models"
    else:
        raise Exception("Cannot find pretrained model path.")
    config["pretrained_model_path"] = config.get("pretrained_model_path", pretrained_model_path)
    config["superpoint_model_path"] = os.path.join(config["pretrained_model_path"], "superpoint_v1.pth")
    config["superglue_model_path"] = os.path.join(config["pretrained_model_path"], "superglue_outdoor.pth")
    config["netvlad_model_path"] = os.path.join(config["pretrained_model_path"], "VGG16-NetVLAD-Pitts30K.mat")
    config["dino_salad_model_path"] = os.path.join(config["pretrained_model_path"], "salad/dino_salad.ckpt")

    config['mask2former_single_gpu'] = config.get("mask2former_single_gpu", True)
    config["mask2former_deuque_limit"] = config.get("mask2former_deuque_limit", 10)
    config["mask2former_batch_size"] = config.get("mask2former_batch_size", 1)
    config["mask2former_model_path"] = os.path.join(config["pretrained_model_path"], "mask2former_mapillary_vistas_swin_L.pkl")
    code_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config["code_dir"] = code_dir
    config["mask2former_cfg_path"] = os.path.join(code_dir, "Mask2Former/maskformer2_swin_large_IN21k_384_bs16_300k.yaml")
    config["vehicle_calibration_path"] = os.path.join(code_dir, "configs/vehicle.yaml")
    config['log_multi_trip'] = config.get("log_multi_trip", True)
    config['image_match_model'] = config.get("image_match_model", "light_glue")
    config["light_glue_weights"] = os.path.join(config["pretrained_model_path"], "superpoint_lightglue_v0-1_arxiv.pth")
    config["cross_trip_image_match_model"] = config.get("cross_trip_image_match_model", "super_glue")
    config['adaptive_batch_size'] = config.get("adaptive_batch_size", False)

    config["sp_batch_size"] = config.get("sp_batch_size", 2)
    config["sp_workers"] = config.get("sp_workers", 4)

    # Colmap configs
    if not config["ips"] or "colmap_path" not in config:
        config["colmap_path"] = config.get("colmap_path", "/tmp/colmap/build/src/colmap/exe/colmap")
    config["use_mvs_supervise"] = config.get("use_mvs_supervise", True)
    config["colmap_ref_cam"] = config.get("colmap_ref_cam", "cam0")

    set_default_value(config, "colmap_config", {})
    colmap_config = config["colmap_config"]
    # colmap sfm configs
    set_default_value(colmap_config, "ceres_dense_backend_type", "LAPACK")
    set_default_value(colmap_config, "ceres_sparse_backend_type", "SUITE_SPARSE")
    set_default_value(colmap_config, "max_num_images_direct_sparse_solver", 50000)
    # colmap mvs configs
    set_default_value(colmap_config, "image_undistored_with_cuda", True)
    set_default_value(colmap_config, "patch_match_stereo_type", "ACMH")
    set_default_value(colmap_config, "num_patch_match_src_images", 8)
    set_default_value(colmap_config, "fusion_type", "ACMH")
    set_default_value(colmap_config, "fusion_num_consistent", 4)
    set_default_value(colmap_config, "fusion_num_neighbors", 20)

    # image retrival cfg
    config['retrieval_diff_cam_score_thre'] = config.get("retrieval_diff_cam_score_thre", 0.5)
    config['retrieval_same_cam_score_thre'] = config.get("retrieval_same_cam_score_thre", 0.5)
    config['retrieval_pair_max_dist'] = config.get("retrieval_pair_max_dist", 20)
    config['retrieval_nms_range'] = config.get("retrieval_nms_range", 5)
    config['retrieval_min_bev_overlap_area'] = config.get("retrieval_min_bev_overlap_area", 10)
    config['retrieval_max_pair_per_trip'] = config.get("retrieval_max_pair_per_trip", 100)
    config['retrieval_pair_downsample_distance'] = config.get("retrieval_pair_downsample_distance", 1.0)
    config['retrieval_skip_min_num'] = config.get("retrieval_skip_min_num", 3)

    config['min_roma_match_certainty'] = config.get('min_roma_match_certainty', 0.2)


    # image retrival with augment config
    if "image_retrival_cfg" not in config:
        config["image_retrival_cfg"] = dict()

    image_retrival_cfg = config["image_retrival_cfg"]
    image_retrival_cfg['use_augmented_image_retrival'] = image_retrival_cfg.get('use_augmented_image_retrival', False)
    image_retrival_cfg['augmented_cam_id'] = image_retrival_cfg.get('augmented_cam_id', 2)
    image_retrival_cfg['augmented_type_num'] = image_retrival_cfg.get('augmented_type_num', 3)
    image_retrival_cfg['score_increase_gap'] = image_retrival_cfg.get('score_increase_gap', 0.15)
    image_retrival_cfg['readjust_score'] = config["retrieval_diff_cam_score_thre"] + 0.01

    config["roma_min_cerntainty"] = config.get("roma_min_cerntainty", 0.2)


    # ROME configs
    config["only_save_final_epoch_result"] = config.get("only_save_final_epoch_result", True)
    config["save_rendered_image"] = config.get("save_rendered_image", False)
    config["grid_guassian_smoothing"] = config.get("grid_guassian_smoothing", True)
    config["draw_cam_traj_on_bev_image"] = config.get("draw_cam_traj_on_bev_image", False)
    config["training_crop_image_by_label"] = config.get("training_crop_image_by_label", True)
    config["use_auto_cut_center"] = config.get("use_auto_cut_center", True)
    config["cutoff_radius"] = config.get("cutoff_radius", 200.0)
    config["rome_downsample_distance_threshold"] = config.get("rome_downsample_distance_threshold", 0.0)
    config["rome_downsample_angle_threshold"] = config.get("rome_downsample_angle_threshold", 0.0)
    config["extrinsic_slice_interval"] = config.get("extrinsic_slice_interval", 30)
    config["mesh_z_scale"] = config.get("mesh_z_scale", 1.0)
    config["reuse_mesh_prior_z"] = config.get("reuse_mesh_prior_z", True)
    config["log_every_n_steps"] = config.get("log_every_n_steps", 10)
    config["est_plane_use_adaptive_offset"] = config.get("est_plane_use_adaptive_offset", False)
    config["est_plane_fixed_offset"] = config.get("est_plane_fixed_offset", 0.8)
    config["est_plane_adaptive_offset_ratio"] = config.get("est_plane_adaptive_offset_ratio", 0.05)
    set_default_value(config, "flatten_bev_curb_depth", True)

    # add avm configs
    config["use_avm_cam"] = config.get("use_avm_cam", False)
    if config["use_avm_cam"]:
        config = add_avm_configs(config)

    return config


if __name__ == "__main__":
    load_config("configs/recon.yaml")
    print(config)
