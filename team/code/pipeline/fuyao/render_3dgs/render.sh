#!/usr/bin/env bash
config_file=$1
run_name=$2
project_name=$3
mode=$4
output_folder=$5
iter=$6
use_difix=$7

save_root="$(dirname "$(dirname "$(dirname "$(dirname "$config_file")")")")"

if [ -z "$output_folder" ]; then
    output_folder="simulator_render"
fi

if [ "$mode" == "render_evaluate" ]; then
    run_name="${run_name}"
fi

echo "Rendering $mode"
echo "Config file: $config_file"
echo "Project name: $project_name"
echo "Run name: $run_name"
echo "Save root: $save_root"
echo "Repo root: $REPO_ROOT" # 环境变量，通过 deploy_render.bash 中设置


export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda:/usr/local/cuda/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
echo "LD_LIBRARY_PATH: $LD_LIBRARY_PATH"

if [ -n "$use_difix" ]; then
    export USE_DIFIX_TENSORRT="true"
    export SCENE_IDX=$project_name
    export CKPT="/workspace/group_share/adc-sim/users/cloudsim/difix/ckpt_finetuned/default_trt"
    export TORCH_HOME="/workspace/group_share/adc-sim/users/cloudsim/torch_cache"
    export HF_HOME="/workspace/group_share/adc-sim/users/cloudsim/pretrain_model"
    echo "USE_DIFIX enabled, set SCENE_IDX to $project_name and CKPT to $CKPT"
fi

reconic_src="${REPO_ROOT}/omnire_joint_trainning/src"
export PYTHONPATH="${reconic_src}:${REPO_ROOT}/models"
echo "repo_root=${REPO_ROOT}"
echo "reconic_src=${reconic_src}"
cd "${reconic_src}"

output_dir="${save_root}/${project_name}/${run_name}/${output_folder}"
iter_args=()
case "${iter}" in
    ""|0|-1|None|none|null|NULL)
        ;;
    *)
        iter_args=(--iter "${iter}")
        ;;
esac
python scripts/render_sim.py --mode "${mode}" --config "${config_file}" --save_path "${output_dir}" --sim "${iter_args[@]}"

mkdir -p "${output_dir}"
cd "${output_dir}"

if [ "$mode" == "novel" ]; then
    ffmpeg -y -loglevel info -i video_cam0_novel_rgb.mp4 -i video_cam2_novel_rgb.mp4 -i video_cam3_novel_rgb.mp4 -i video_cam4_novel_rgb.mp4 -i video_cam5_novel_rgb.mp4 -i video_cam6_novel_rgb.mp4 -filter_complex "[0:v] crop=iw/2:ih:iw/2:0 [v0]; [1:v] crop=iw/2:ih:iw/2:0 [v1]; [2:v] crop=iw/2:ih:iw/2:0 [v2]; [3:v] crop=iw/2:ih:iw/2:0 [v3]; [4:v] crop=iw/2:ih:iw/2:0 [v4]; [5:v] crop=iw/2:ih:iw/2:0 [v5]; nullsrc=size=3840x1854 [base]; [base][v0] overlay=shortest=1:x=0:y=0 [tmp1]; [tmp1][v1] overlay=shortest=1:x=1920:y=0 [tmp2]; [tmp2][v2] overlay=shortest=1:x=0:y=1080 [tmp3]; [tmp3][v3] overlay=shortest=1:x=968:y=1080 [tmp4]; [tmp4][v4] overlay=shortest=1:x=1936:y=1080 [tmp5]; [tmp5][v5] overlay=shortest=1:x=2904:y=1080" -c:v libx264 -preset veryfast -crf 22 output_novel_023456.mp4
else
    ffmpeg -y -loglevel info -i video_cam0_origin_rgb.mp4 -i video_cam2_origin_rgb.mp4 -i video_cam3_origin_rgb.mp4 -i video_cam4_origin_rgb.mp4 -i video_cam5_origin_rgb.mp4 -i video_cam6_origin_rgb.mp4 -filter_complex "[0:v] crop=iw/2:ih:iw/2:0 [v0]; [1:v] crop=iw/2:ih:iw/2:0 [v1]; [2:v] crop=iw/2:ih:iw/2:0 [v2]; [3:v] crop=iw/2:ih:iw/2:0 [v3]; [4:v] crop=iw/2:ih:iw/2:0 [v4]; [5:v] crop=iw/2:ih:iw/2:0 [v5]; nullsrc=size=3840x1854 [base]; [base][v0] overlay=shortest=1:x=0:y=0 [tmp1]; [tmp1][v1] overlay=shortest=1:x=1920:y=0 [tmp2]; [tmp2][v2] overlay=shortest=1:x=0:y=1080 [tmp3]; [tmp3][v3] overlay=shortest=1:x=968:y=1080 [tmp4]; [tmp4][v4] overlay=shortest=1:x=1936:y=1080 [tmp5]; [tmp5][v5] overlay=shortest=1:x=2904:y=1080" -c:v libx264 -preset veryfast -crf 22 output_023456.mp4
fi
