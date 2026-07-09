# 训练配置名：overfit（过拟合）| train_full_dataset（全量）
config_name="train_v6"
gpu_num="8"
node_num="8"
main_process_port="29501"

fuyao deploy --gpu-type=A100  --volume=adc-sim --queue=adc-sim --release\
             --site=fuyao_b1_prod2 --label "difix_${config_name}_${main_process_port}" \
             --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:yangxh7-251209-0220 \
             --project="adc-sim" --experiment "sim3dgs-sim" --gpus-per-node=$gpu_num --nodes=$node_num \
    bash /workspace/yangxh7@xiaopeng.com/codes/3dgs/models/difix/deploy/run_train_difix_ngpu.sh "$gpu_num" "$node_num" "$main_process_port" "$config_name"
