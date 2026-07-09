config_file=$1
run_name=$2
project_name=$3
mode=$4
output_folder=$5
iter=$6
use_difix=$7

if [ -z "$mode" ]; then
    mode="render"
fi

if [ -z "$output_folder" ]; then
    output_folder="simulator_render"
fi

job_name="${mode}_${output_folder}_${project_name}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../../.." && pwd)"
render_sh="${script_dir}/render.sh"

echo "Deploying $mode"
echo "Config file: $config_file"
echo "Run name: $run_name"
echo "Project name: $project_name"
echo "Repo root: $repo_root"
echo "[COMMAND] REPO_ROOT=$repo_root bash $render_sh ..."

echo "--------------------------------"
fuyao deploy --gpu-type=A100 --volume=adc-sim --queue=adc-sim --release \
    --site fuyao_b1_prod2 --job-name "$job_name" --label "$job_name" \
    --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:dusc-260426-1918 \
    --project="adc-sim" --experiment "sim3dgs-sim" --gpus-per-node=1 --nodes=1 \
    "export REPO_ROOT='${repo_root}'; bash '${render_sh}' '${config_file}' '${run_name}' '${project_name}' '${mode}' '${output_folder}' '${iter}' '${use_difix}'"
