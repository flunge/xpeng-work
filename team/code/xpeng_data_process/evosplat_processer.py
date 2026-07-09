import torch
from tqdm import tqdm

import os
import sys
import time
from pathlib import Path

current_dir = os.path.dirname(__file__)
root_path = os.path.abspath(os.path.join(current_dir, ".."))
_ucp_dir = os.path.join(root_path, "pipeline", "ucp")
_models_dir = os.path.join(root_path, "models")
for _p in (_ucp_dir, _models_dir, root_path):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import torch
from tqdm import tqdm
from nail_evolsplat.model.model import load_model
from nail_evolsplat.data_manager import Datamanager

from download_file_from_oss2 import download_file_from_oss2

class EvoSplatProcessor:
    def __init__(self, cfg):
        self.clip_path = Path(cfg.clip_path).parent
        self.clip_id = cfg.clip_id
        self.output_folder = os.path.join(self.clip_path,cfg.clip_id, 'evolsplat_bkgd')
        os.makedirs(self.output_folder, exist_ok=True)
        self.pth_path = os.path.join(self.clip_path, "evolsplat.ckpt")

    def download_pth(self):
        t1 = time.time()
        if not os.path.exists(self.pth_path):
            download_file_from_oss2(self.pth_path, "sim_engine/evolsplat_pth/step-000511830.ckpt")
        t2 = time.time()
        print("[INFO] Download models/g3r pth time: ", t2 - t1)
        return

    def process(self):
        print("Process EvolSplat", flush = True)
        self.download_pth()
        data_manager = Datamanager(self.clip_id, self.clip_path, self.output_folder)
        data_length = data_manager.get_data_length()
        seed_points = data_manager.get_seed_points()
        model = load_model(ckpt_path=self.pth_path,train_mode=False)
        model.set_datas_init(data_length, seed_points, self.output_folder)
        model = model.to("cuda")
        model.eval()
        model.init_volume()

        for idx in tqdm(range(data_length)):
            camera, batch = data_manager.get_next_data(idx)
            model.get_outputs(camera, batch)

if __name__ == "__main__":

    from settings.config import make_default_settings, make_case_specific_settings
    cfg = make_default_settings()
    cfg.clip_path = "/workspace/dusc@xiaopeng.com/online_data/data_lvyu/"
    cfg.clip_id = "c-0ecdc716-6fc6-31cc-bd7c-d4d92cdeaf58"
    evosplat_process = EvoSplatProcessor(cfg)
    evosplat_process.process()