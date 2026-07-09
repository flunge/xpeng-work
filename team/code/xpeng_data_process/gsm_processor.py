import os
import sys
import time
from pathlib import Path

current_dir = os.path.dirname(__file__)
root_path = os.path.abspath(os.path.join(current_dir, ".."))
scube_root_path = os.path.abspath(os.path.join(current_dir, "scube"))

if root_path not in sys.path:
    sys.path.append(root_path)
if scube_root_path not in sys.path:
    sys.path.append(scube_root_path)

from xpeng_data_process.scube.gsm_inference import (
    get_parser,
    create_model_from_args,
    render_and_save_gsm,
)


class GSMProcessor:
    def __init__(self, cfg):
        self.clip_path = Path(cfg.clip_path)
        self.data_folder = self.clip_path.parent
        self.clip_id = cfg.clip_id
        self.output_folder = os.path.join(self.clip_path, "gsm_bkgd")
        os.makedirs(self.output_folder, exist_ok=True)

        self.hyper_arg = "none"
        self.ckpt_path = getattr(
            cfg,
            "gsm_ckpt_path",
            "/workspace/group_share/adc-sim/users/dsc/scube_gsm.ckpt",
        )
        self.val_starting_frame = getattr(cfg, "gsm_val_starting_frame", 100)
        self.skybox_resolution = getattr(cfg, "gsm_skybox_resolution", 768)
        self.input_frame_offsets = getattr(cfg, "gsm_input_frame_offsets", [0])
        self.sup_slect_ids = getattr(cfg, "gsm_sup_slect_ids", [0])
        self.sup_frame_offsets = getattr(cfg, "gsm_sup_frame_offsets", [0, 5, 10])

    def _build_known_args(self):
        parser = get_parser()
        # 与命令行 `python gsm_inference.py none ...` 保持一致：
        # 用字符串 "none" 占位 hyper，表示不额外加载第二份 yaml。
        known_args = parser.parse_args([self.hyper_arg])
        known_args.ckpt_path = self.ckpt_path
        known_args.infer_case_id = self.clip_id
        known_args.output_root = self.output_folder
        known_args.val_starting_frame = self.val_starting_frame
        known_args.skybox_resolution = self.skybox_resolution
        known_args.suffix = ""
        known_args.save_img_separately = False
        known_args.save_gs = True
        known_args.input_frame_offsets = self.input_frame_offsets
        return known_args

    def _get_img_reorder(self, dataset_kwargs):
        if len(dataset_kwargs["sup_slect_ids"]) == 3:
            return [1, 0, 2]
        if len(dataset_kwargs["sup_slect_ids"]) == 5:
            return [3, 1, 0, 2, 4]
        if len(dataset_kwargs["sup_slect_ids"]) == 1:
            return [0]
        raise NotImplementedError(
            f"Unsupported sup_slect_ids length: {len(dataset_kwargs['sup_slect_ids'])}"
        )

    def process(self):
        print("Process GSM", flush=True)

        known_args = self._build_known_args()
        saving_dir = Path(known_args.output_root)
        saving_dir.mkdir(parents=True, exist_ok=True)

        hparam_update = {
            "skybox_resolution": known_args.skybox_resolution,
            "skybox_forward_sky_only": True,
            "train_val_num_workers": 0,
            "root_data_folder": str(self.data_folder),
        }

        model_name = "gsm"
        # create_model_from_args 内部调用 parser.parse_args()，会读 sys.argv，需带上 hyper。
        _old_argv = sys.argv[:]
        try:
            sys.argv = [sys.argv[0], self.hyper_arg]
            net_model_gsm, _ = create_model_from_args(
                known_args.ckpt_path,
                model_name,
                get_parser(),
                hparam_update=hparam_update,
            )
        finally:
            sys.argv = _old_argv
        net_model_gsm.cuda()

        dataset_kwargs = net_model_gsm.hparams.test_kwargs
        dataset_kwargs["split"] = "test"
        dataset_kwargs["root_data_folder"] = str(self.data_folder)
        dataset_kwargs["online_data_folder"] = str(self.data_folder)
        dataset_kwargs["val_starting_frame"] = known_args.val_starting_frame
        dataset_kwargs["input_frame_offsets"] = known_args.input_frame_offsets
        dataset_kwargs["sup_slect_ids"] = self.sup_slect_ids
        dataset_kwargs["sup_frame_offsets"] = self.sup_frame_offsets
        dataset_kwargs["n_image_per_iter_sup"] = None

        img_reorder = self._get_img_reorder(dataset_kwargs)

        render_and_save_gsm(
            net_model_gsm,
            known_args,
            saving_dir,
            img_reorder,
            save_img_together=True,
            save_gaussians=True,
        )


if __name__ == "__main__":
    from settings.config import make_default_settings

    cfg = make_default_settings()
    cfg.clip_path = "/workspace/group_share/adc-sim/users/dsc/xpeng_ff_difix_sim/c-a9edc137-dfaf-3feb-a60f-02a35ad65785"
    cfg.clip_id = "c-a9edc137-dfaf-3feb-a60f-02a35ad65785"
    cfg.gsm_ckpt_path = "/workspace/group_share/adc-sim/users/dsc/scube_gsm.ckpt"

    gsm_process = GSMProcessor(cfg)
    gsm_process.process()
