import os
import sys
import torch
from tqdm import tqdm

current_dir = os.path.dirname(__file__)
root_path = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.append(root_path)
from nail_evolsplat.model.model import load_model
from nail_evolsplat.data_manager import Datamanager

if __name__ == "__main__":
    ckpt_path = "/workspace/lvy10@xiaopeng.com/code/simworld/models/nail_evolsplat/train/root_data_folder/evolsplat.ckpt"

    # case_id = "c-904fedb5-6148-3db5-86d9-2679a3321e5a"
    # case_id = "c-69604306-b895-3973-bdea-3ef389607098"
    case_id = "c-0ecdc716-6fc6-31cc-bd7c-d4d92cdeaf58"
    root_data_folder = "/workspace/lvy10@xiaopeng.com/code/simworld/models/nail_evolsplat/train/root_data_folder"
    output_folder = os.path.join("/workspace/lvy10@xiaopeng.com/code/simworld/models/nail_evolsplat/train/infer", case_id)
    os.makedirs(output_folder, exist_ok=True)

    data_manager = Datamanager(case_id, root_data_folder, output_folder)
    data_length = data_manager.get_data_length()
    seed_points = data_manager.get_seed_points()

    model = load_model(ckpt_path=ckpt_path,train_mode=False)
    model.set_datas_init(data_length, seed_points, output_folder)
    model = model.to("cuda")
    model.eval()
    model.init_volume()

    for idx in tqdm(range(data_length)):
        camera, batch = data_manager.get_next_data(idx)
        model.get_outputs(camera, batch)