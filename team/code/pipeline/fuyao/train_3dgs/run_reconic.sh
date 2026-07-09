set -euo pipefail

workspace_path=$1
config=$2
clip_id=$3
cameras_id=$4
output_path=$5
priority=$6

# generative model need these env
hf_home_path="$workspace_path/pretrain_model"
export TORCH_HOME="$workspace_path/torch_cache"
export HF_HOME=$hf_home_path

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
legacy_root="$workspace_path/simworld"

if [[ -d "$legacy_root/omnire_joint_trainning/src" ]]; then
    simworld_root="$legacy_root"
else
    simworld_root="$repo_root"
fi

drivestudio_path="$simworld_root/omnire_joint_trainning/src"
echo "$drivestudio_path"
if [[ ! -d "$drivestudio_path" ]]; then
    echo "[ERROR] drivestudio path not found: $drivestudio_path"
    exit 1
fi
cd "$drivestudio_path"

# use low pri config if pri is low
if [[ "$priority" == "low" ]]; then
    config_dir="$(dirname "$config")"
    config_name="$(basename "$config")"
    new_config_name="low_pri_$config_name"
    cp "$config" "$config_dir/$new_config_name"
    sed -i "s|saveckpt_freq:.*|saveckpt_freq: 5000|" "$config_dir/$new_config_name"
    config="$config_dir/$new_config_name"
fi

# train step
export PYTHONPATH=$drivestudio_path:$simworld_root/models:$simworld_root/libs/xpeng_raster
HF_ENDPOINT=https://hf-mirror.com CUDA_VISIBLE_DEVICES=0 \
    python reconic/cli/train_cli.py \
    --config_file "$config" \
    --output_root "$output_path" \
    --project "$clip_id" \
    --run_name ${cameras_id}

output_dir=$output_path/$clip_id/${cameras_id}
if [ ! -f "$output_dir/trained_model/checkpoint_final.pth" ]; then
    exit
fi

# clean not used data to restore disk space
rm -rf "$output_dir/novel_view_data"
rm -rf "$output_dir/trained_model/checkpoint_20000.pth"
rm -rf "$output_dir/trained_model/checkpoint_40000.pth"
rm -rf "$output_dir/trained_model/checkpoint_60000.pth"
rm -rf "$output_dir/engine_checkpoint_final.pth"
rm -rf "$output_dir/vis_generative_engine_training"
rm -rf "$output_dir/videos"
rm -rf "$output_dir/metrics"
rm -rf "$output_dir/buffer_maps"

python scripts/convert_model_to_ply.py --checkpoint_path "$output_dir/trained_model/checkpoint_final.pth" --save_path "$output_dir/trained_model/output_pointcloud.ply"

# render step
output_cfg=$output_dir/configs/config_sim.yaml
python scripts/render_sim.py --config "$output_cfg" --save_path "$output_dir/simulator_render"

# video concate
cd "$output_dir/simulator_render"

ffmpeg -y -loglevel info -i video_cam0_origin_rgb.mp4 -i video_cam2_origin_rgb.mp4 -i video_cam3_origin_rgb.mp4 -i video_cam4_origin_rgb.mp4 -i video_cam5_origin_rgb.mp4 -i video_cam6_origin_rgb.mp4 -filter_complex "[0:v] crop=iw/2:ih:iw/2:0 [v0]; [1:v] crop=iw/2:ih:iw/2:0 [v1]; [2:v] crop=iw/2:ih:iw/2:0 [v2]; [3:v] crop=iw/2:ih:iw/2:0 [v3]; [4:v] crop=iw/2:ih:iw/2:0 [v4]; [5:v] crop=iw/2:ih:iw/2:0 [v5]; nullsrc=size=3840x1854 [base]; [base][v0] overlay=shortest=1:x=0:y=0 [tmp1]; [tmp1][v1] overlay=shortest=1:x=1920:y=0 [tmp2]; [tmp2][v2] overlay=shortest=1:x=0:y=1080 [tmp3]; [tmp3][v3] overlay=shortest=1:x=968:y=1080 [tmp4]; [tmp4][v4] overlay=shortest=1:x=1936:y=1080 [tmp5]; [tmp5][v5] overlay=shortest=1:x=2904:y=1080" -c:v libx264 -preset veryfast -crf 22 output_023456.mp4
ffmpeg -y -loglevel info -i video_cam0_sin_wave_rgb.mp4 -i video_cam2_sin_wave_rgb.mp4 -i video_cam3_sin_wave_rgb.mp4 -i video_cam4_sin_wave_rgb.mp4 -i video_cam5_sin_wave_rgb.mp4 -i video_cam6_sin_wave_rgb.mp4 -filter_complex "[0:v] crop=iw/2:ih:iw/2:0 [v0]; [1:v] crop=iw/2:ih:iw/2:0 [v1]; [2:v] crop=iw/2:ih:iw/2:0 [v2]; [3:v] crop=iw/2:ih:iw/2:0 [v3]; [4:v] crop=iw/2:ih:iw/2:0 [v4]; [5:v] crop=iw/2:ih:iw/2:0 [v5]; nullsrc=size=3840x1854 [base]; [base][v0] overlay=shortest=1:x=0:y=0 [tmp1]; [tmp1][v1] overlay=shortest=1:x=1920:y=0 [tmp2]; [tmp2][v2] overlay=shortest=1:x=0:y=1080 [tmp3]; [tmp3][v3] overlay=shortest=1:x=968:y=1080 [tmp4]; [tmp4][v4] overlay=shortest=1:x=1936:y=1080 [tmp5]; [tmp5][v5] overlay=shortest=1:x=2904:y=1080" -c:v libx264 -preset veryfast -crf 22 output_sin_wave_023456.mp4
ffmpeg -y -loglevel info -i video_cam0_origin_rgb.mp4 -i video_cam2_origin_rgb.mp4 -i video_cam3_origin_rgb.mp4 -i video_cam4_origin_rgb.mp4 -i video_cam5_origin_rgb.mp4 -i video_cam6_origin_rgb.mp4 -filter_complex "[0:v] crop=iw/2:ih:0:0 [v0]; [1:v] crop=iw/2:ih:0:0 [v1]; [2:v] crop=iw/2:ih:0:0 [v2]; [3:v] crop=iw/2:ih:0:0 [v3]; [4:v] crop=iw/2:ih:0:0 [v4]; [5:v] crop=iw/2:ih:0:0 [v5]; nullsrc=size=3840x1854 [base]; [base][v0] overlay=shortest=1:x=0:y=0 [tmp1]; [tmp1][v1] overlay=shortest=1:x=1920:y=0 [tmp2]; [tmp2][v2] overlay=shortest=1:x=0:y=1080 [tmp3]; [tmp3][v3] overlay=shortest=1:x=968:y=1080 [tmp4]; [tmp4][v4] overlay=shortest=1:x=1936:y=1080 [tmp5]; [tmp5][v5] overlay=shortest=1:x=2904:y=1080" -c:v libx264 -preset veryfast -crf 22 output_gt_023456.mp4