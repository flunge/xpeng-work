job_name=$1
region=$2
checkpoint=$3

root="$(dirname "$(realpath "$0")")/.."

rm local_git_sha*
rm upstream*

fuyao deploy --volume=adc-sim --queue=adc-sim --release --site=fuyao_b1 --job-name $job_name --label $job_name \
    --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:yangxh7-240919-2046 \
    --project="sim3dgs-sim" --gpus-per-node=1 --nodes=1 \
    bash run_g3r_train.bash $job_name $root $region $checkpoint
