job_name=$1
root=$2
region=$3
checkpoint=$4

cd $root
echo "build models/g3r env..."
ln -s /workspace/dusc@xiaopeng.com/envs/g3r_env /root/anaconda3/envs/g3r_env

source activate base
source activate g3r_env
strip --remove-section=.note.ABI-tag /usr/lib/x86_64-linux-gnu/libQt5Core.so.5

export LD_LIBRARY_PATH=/usr/local/cuda/compat:/usr/local/cuda/compat/lib:${LD_LIBRARY_PATH}

python train_g3r.py --job_name $job_name --region $region --checkpoint $checkpoint