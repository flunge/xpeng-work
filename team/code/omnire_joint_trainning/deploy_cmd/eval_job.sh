task_prefix="drive_studio_eval"

ckpt=$1

if [ -z "${ckpt}" ]; then
    echo "need to set ckpt"
	exit 1
fi

workspace_path=$(echo $PWD | sed -E 's_(/workspace/[a-zA-Z0-9\_\.\-\@]+/).*_\1_')

function launch {
	fuyao deploy --site=fuyao_b1 \
		--queue=adc-sim \
		--job-name "$task_prefix" \
		--label "$task_prefix" \
	    --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:yangxh7-251209-0220 \
		--project=sim3dgs-sim \
		--gpus-per-node=1 \
		--nodes=1 \
		bash eval_cmd.sh $workspace_path $ckpt
}

launch
