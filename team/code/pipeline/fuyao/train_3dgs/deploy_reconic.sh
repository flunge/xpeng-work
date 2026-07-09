task_prefix="drivestudio_train"

config=$1
clip_id=$2
cameras_id=$3
output_path=$4
priority=$5

if [ -z "${config}" ]; then
    echo "need to set config"
	exit 1
fi
if [ -z "${clip_id}" ]; then
    echo "need to set clip_id"
	exit 1
fi
if [ -z "${cameras_id}" ]; then
    echo "need to set cameras_id"
	exit 1
fi
if [ -z "${output_path}" ]; then
    echo "need to set output_path"
	exit 1
fi
if [ -z "${priority}" ]; then
    priority="normal"
fi

workspace_path=$(echo $PWD | sed -E 's_(/workspace/[^/]+/).*_\1_')
repo_root="$PWD"
run_reconic_path="$repo_root/pipeline/fuyao/train_3dgs/run_reconic.sh"

function launch {
	# 	--site=fuyao_b1 --queue=adc-perception-globalization \
	fuyao deploy --job-name "${task_prefix}_${clip_id}" \
	--label "${task_prefix}_${clip_id}" \
	--docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:dusc-260426-1918 \
	--project=adc-sim \
	--experiment=sim3dgs-sim \
	--gpus-per-node=1 \
	--nodes=1 \
	--volume=adc-sim \
	--site=fuyao_b1_prod2 \
	--queue=adc-sim \
	--ignore-artifact-size \
	--priority=$priority \
	bash "$run_reconic_path" "$workspace_path" "$config" "$clip_id" "$cameras_id" "$output_path" "$priority"

	echo "bash command: $run_reconic_path $workspace_path $config $clip_id $cameras_id $output_path $priority"
}

launch