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

from g3r.inference import inference_g3r_interface
from download_file_from_oss2 import download_file_from_oss2


class G3RProcessor:
    def __init__(self, cfg):
        self.clip_path = Path(cfg.clip_path)
        self.save_path = os.path.join(self.clip_path, 'g3r_ground')
        os.makedirs(self.save_path, exist_ok=True)
        self.region_type = "ground"
        self.pth_path = os.path.join(self.clip_path, "g3r_ground.pth")

    def download_pth(self):
        t1 = time.time()
        if not os.path.exists(self.pth_path):
            download_file_from_oss2(self.pth_path, "sim_engine/g3r_pth/g3r_ground_0821.pth")
        t2 = time.time()
        print("[INFO] Download models/g3r pth time: ", t2 - t1)
        return

    def process_g3r(self):
        self.download_pth()
        inference_g3r_interface(self.region_type, self.pth_path, self.clip_path, self.save_path)
        return

if __name__ == '__main__':
    from settings.config import make_default_settings, make_case_specific_settings
    cfg = make_default_settings()
    cfg.clip_path = "/workspace/group_share/adc-sim/users/dsc/dynamic_data/c-1bcbb7c9-8772-3356-81a6-2c058bf98202"

    g3r_processer = G3RProcessor(cfg)
    g3r_processer.process_g3r()