# DataEngine - Reconic

Currently, mostly modified from [DriveStudio](https://github.com/ziyc/drivestudio). Towards combined training and optimization of generative models and reconstruction models. DriveStudio README can be found [here](docs/drivestudio.md).

Refer to [Project Page](https://gigaai0118.feishu.cn/wiki/GsEzwwKbji9c6okRYJ8ckJj3nEg) for more details.

# Installation

```bash

# Clone the Reconic repo
git clone git@codeup.aliyun.com:645a08b9d983fb47ec1d5df2/DataEngine/Reconic.git

# Initialize
make init


# Set huggingface model cache path if needed
rm -rf ~/.cache/huggingface/hub
rm -rf ~/.cache/torch/hub
mkdir -p ~/.cache/huggingface/
mkdir -p ~/.cache/torch/
ln -s /shared_disk/models/huggingface ~/.cache/huggingface/hub
ln -s /shared_disk/models/torch/hub ~/.cache/torch/hub

```

## Usage

```bash

# Joint training
reconic-train \
    --config_file configs/joint_training_legacy/generative_streetgs_waymo_val065_3cams.yaml \
    --output_root output \
    --project generative_streetgs \
    --run_name waymo_val065_3cams

# Recon training
reconic-train \
    --config_file configs/joint_training_legacy/streetgs_waymo_val065_3cams.yaml \
    --output_root output \
    --project streetgs \
    --run_name waymo_val065_3cams


# Eval
reconic-eval \
    --resume_from output/generative_streetgs/waymo_val065_3cams/checkpoint_final.pth
```
