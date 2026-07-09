import os
import yaml


def load_common_config(config_path_or_dict, pretrained_model_path):
    """
    Parse the config file and set default values.
    
    Args:
        config_path_or_dict: Either a path to config file (str) or a config dict
        pretrained_model_path: Path to pretrained models
    """
    if isinstance(config_path_or_dict, dict):
        config = config_path_or_dict
    else:
        config = yaml.safe_load(open(config_path_or_dict))

    # General configs
    config["ips"] = config.get("ips", False)
    config["trips_json"] = config.get("trips_json", os.path.join(config["exp_dir"], "merged_trips.json"))

    config["dump_clip_data"] = config.get("dump_clip_data", True)

    config["pretrained_model_path"] = pretrained_model_path
    config["netvlad_model_path"] = os.path.join(config["pretrained_model_path"], "VGG16-NetVLAD-Pitts30K.mat")
    config["dino_salad_model_path"] = os.path.join(config["pretrained_model_path"], "salad/dino_salad.ckpt")

    code_dir = os.path.dirname(os.path.abspath(__file__))
    config["vehicle_calibration_path"] = os.path.join(code_dir, "vehicle.yaml")

    config["sp_batch_size"] = config.get("sp_batch_size", 2)
    config["sp_workers"] = config.get("sp_workers", 4)
    return config