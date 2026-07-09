config_file=$1
job_name=$2

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
run_preproc="$repo_root/pipeline/fuyao/preprocess/run_preproc.bash"

fuyao deploy --gpu-type=A100 --volume=adc-sim --queue=adc-sim --release \
    --site fuyao_b1_prod2 --job-name "$job_name" --label "$job_name" \
    --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:dusc-260426-1918 \
    --project="adc-sim" --experiment "sim3dgs-sim" --gpus-per-node=1 --nodes=1 \
    bash "$run_preproc" "$config_file" "$job_name" "$repo_root"
