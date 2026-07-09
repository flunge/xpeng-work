job_name=$1
config_path=$2
output_path=$3
debug_frame=$4
debug_distance=$5
resume_ckpt=$6


root="/workspace/dusc@xiaopeng.com/code/simworld_bk/SCube_space/SCube"

rm local_git_sha*
rm upstream*

gpu_num=4

fuyao deploy --gpu-type=A100  --volume=adc-sim --queue=adc-sim --release\
             --site=fuyao_b1_prod2 --label $job_name \
             --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:dusc-260121-1905 \
             --project="adc-sim" --experiment "sim3dgs-sim" --gpus-per-node=$gpu_num --nodes=1 \
    bash run_scube_train.bash $job_name $root $config_path $output_path $gpu_num $debug_frame $debug_distance $resume_ckpt