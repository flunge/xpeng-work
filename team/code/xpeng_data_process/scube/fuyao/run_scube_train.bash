job_name=$1
root=$2
config_path=$3
output_path=$4
gpu_num=$5
debug_frame=$6
debug_distance=$7
resume_ckpt=$8

cd $root
echo "build scube env..."
ln -s /workspace/dusc@xiaopeng.com/conda_env/scube /opt/conda/envs/scube

source activate base
source activate scube
strip --remove-section=.note.ABI-tag /usr/lib/x86_64-linux-gnu/libQt5Core.so.5

export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda:/usr/local/cuda/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64

if echo "$job_name" | grep -iq "gsm"; then
    echo "Detected 'gsm' in job_name, removing system CUDA and /usr/lib/x86_64-linux-gnu paths from LD_LIBRARY_PATH"
    export LD_LIBRARY_PATH=$(echo $LD_LIBRARY_PATH | sed -e 's|/usr/local/cuda[^:]*:||g' -e 's|/usr/lib/x86_64-linux-gnu[^:]*:||g')
else
    echo "No 'gsm' in job_name, keeping original LD_LIBRARY_PATH with system paths"
fi

if echo "$job_name" | grep -iq "diffusion"; then
    echo "Detected 'diffusion' in job_name, removing system CUDA and /usr/lib/x86_64-linux-gnu paths from LD_LIBRARY_PATH"
    export LD_LIBRARY_PATH=$(echo $LD_LIBRARY_PATH | sed -e 's|/usr/local/cuda[^:]*:||g' -e 's|/usr/lib/x86_64-linux-gnu[^:]*:||g')
else
    echo "No 'diffusion' in job_name, keeping original LD_LIBRARY_PATH with system paths"
fi

python train.py $config_path --max_epochs 100 --gpus $gpu_num --eval_interval 1 --output_dir $output_path --debug_frame $debug_frame --debug_distance $debug_distance --resume_from_ckpt $resume_ckpt