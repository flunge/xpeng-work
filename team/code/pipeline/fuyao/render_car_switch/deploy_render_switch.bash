config_file=$1
save_path=$2
new_calib_path=$3
new_img_timestamps_path=$4
job_name=$5
reference_png_dir=$6
clip=$7

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../../.." && pwd)"
render_sh="${script_dir}/render.sh"
echo "[COMMAND] REPO_ROOT=$repo_root bash $render_sh ..."


echo "--------------------------------"
# bash 0_render.sh $config_file $run_name $project_name $mode $output_folder
fuyao deploy --gpu-type=A100  --volume=adc-sim --queue=adc-sim --release\
    --site fuyao_b1_prod2 --job-name $job_name --label $job_name \
    --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:dusc-260426-1918 \
    --project="adc-sim" --experiment "sim3dgs-sim" --gpus-per-node=1 --nodes=1 \
    "export REPO_ROOT='${repo_root}'; bash '${render_sh}' $config_file $save_path $new_calib_path $new_img_timestamps_path $reference_png_dir $clip"



