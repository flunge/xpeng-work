tracker_run_name=$1
if [ -z "${tracker_run_name}" ]; then
    echo "need to set tracker_run_name"
    exit 1
fi
# fuyao deploy --gpu-type=A100  --volume=adc-sim --queue=adc-sim --release\
#              --site=fuyao_b1_prod2 --label $tracker_run_name \
#              --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wangyd13-260304-0349 \
#              --project="adc-sim" --experiment "sim3dgs-sim" --gpus-per-node=1 --nodes=1 \
#     bash fixer_train.bash $tracker_run_name

function launch {
    fuyao deploy --site=fuyao_b1_prod2 --queue=adc-sim-mig \
        --label "${tracker_run_name}" \
		--docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wangyd13-260304-0349 \
        --project=sim3dgs-sim \
        --gpu-type=mig --gpu-slice=1of2  \
        --volume=adc-sim \
        --priority=normal \
        --experiment sim3dgs-sim \
        --project="adc-sim" \
        bash "fixer_train.bash" "${tracker_run_name}"
}

launch