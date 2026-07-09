import argparse
import os
import torch
import yaml
import json
import shutil
# pytorch-lightning
from pytorch_lightning import Trainer
from pytorch_lightning import seed_everything
from pytorch_lightning.loggers import TensorBoardLogger
from pytorch_lightning.callbacks import ModelCheckpoint
import torch.distributed as dist
from .rome_net import RomeNet
import numpy as np
from .configs.parser import load_config
from pytorch_lightning.strategies import DDPStrategy
import cv2
cv2.setNumThreads(0)
cv2.ocl.setUseOpenCL(False)


class EpochModelCheckpoint(ModelCheckpoint):
    def on_train_epoch_end(self, trainer, pl_module) -> None:
        """save a checkpoint at after every epoch"""
        file_path = os.path.join(self.dirpath, self.filename + ".ckpt")
        self._save_checkpoint(trainer, file_path)


def train(world_size, configs):
    rome_net = RomeNet(configs)
    seed_everything(configs['rand_seed'])
    np.random.seed(configs["rand_seed"])
    logger = TensorBoardLogger(os.path.join(configs['rome_output_dir'], "tb_logs"))
    checkpoint_callback = EpochModelCheckpoint(dirpath=configs['rome_output_dir'], filename='checkpoint', save_on_train_epoch_end=True)
    print(f"Start RoMe Training, with world size: {world_size}, batch_size = {configs['batch_size']}")
    trainer = Trainer(default_root_dir=configs['rome_output_dir'],
                        max_epochs=configs['epochs'],
                        callbacks=[checkpoint_callback],
                        enable_progress_bar=True,
                        devices=world_size,
                        num_nodes=1,
                        strategy=DDPStrategy(find_unused_parameters=False),
                        accelerator="gpu",
                        limit_val_batches=0,
                        num_sanity_val_steps=0,
                        logger=logger)

    trainer.fit(rome_net)

def main(config):
    os.environ["NCCL_DEBUG"] = "ERROR"
    # print("python path = ", os.environ["PYTHONPATH"])
    os.makedirs(config["rome_output_dir"], exist_ok=True)

    # use_mvs_supervise = config.get("use_mvs_supervise", False)
    # if use_mvs_supervise:
    #     try:
    #         status_json = os.path.join(config["exp_dir"], "exp_status.json")
    #         status = json.load(open(status_json, "r"))
    #         if not status["mvs"]["finished"]:
    #             raise Exception("MVS is not finished. Stop training.")
    #     except:
    #         raise Exception("MVS is not finished. Stop training.")

    world_size = torch.cuda.device_count()
    train(world_size, config)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default="configs/recon.yaml")
    parser.add_argument('--local_rank', type=int, default=0)
    args = parser.parse_args()
    config = load_config(args.config)

    main(config)


