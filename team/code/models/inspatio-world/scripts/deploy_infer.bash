# 训练产出目录：留空 = run.sh 自动选 output/ 下最新的 config_used.yaml 所在目录
run_dir="/root/workspace/jinxr@xiaopeng.com/simworld_b/simworld/models/inspatio-world/output/lora_run/lora_20260617_195059"
max_videos="5"
 
gpu_num="1"       
node_num="1"

# directory of this script
script_dir_abs="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir_abs="$(cd "$script_dir_abs/.." && pwd)"
echo "script_dir: $script_dir_abs"
echo "project_dir: $project_dir_abs"

# config
TOTAL_PROCESSES=$(($gpu_num * $node_num))    
echo "TOTAL_PROCESSES: $TOTAL_PROCESSES"


fuyao deploy --gpu-type=A100  --volume=adc-sim --queue=adc-sim --release\
             --site=fuyao_b1_prod2 --label "inspatio_${config_name}_${main_process_port}" \
             --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wangyd13-260304-0349 \
             --project="adc-sim" --experiment "sim3dgs-sim" --gpus-per-node=$gpu_num --nodes=$node_num \
    bash -c "
        bash $script_dir_abs/run.sh --mode infer \
            --train_config $project_dir_abs/configs/${config_name}.yaml \
            --num_gpus $TOTAL_PROCESSES \
            --max_videos $max_videos \
            --run_dir $run_dir
    "

