workspace_path=$1
ckpt=$2

hf_home_path="$workspace_path/pretrain_model"

export TORCH_HOME="$workspace_path/torch_cache"
export HF_HOME=$hf_home_path

drivestudio_path="$workspace_path/code/simworld/omnire_joint_trainning/src"

echo $drivestudio_path
cd $drivestudio_path
pip install --upgrade packaging
pip install -e .

# CUDA_VISIBLE_DEVICES=0 reconic-eval \
#     --resume_from $ckpt
CUDA_VISIBLE_DEVICES=0 PYTHONPATH=$drivestudio_path \
    python reconic/cli/eval_cli.py \
    --load_from $ckpt