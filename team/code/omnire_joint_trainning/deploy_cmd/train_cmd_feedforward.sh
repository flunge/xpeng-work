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

drivestudio_path="$workspace_path/code/simworld/omnire_joint_trainning/src"
echo $drivestudio_path
cd $drivestudio_path

# use low pri config if pri is low
if [[ "$priority" == "low" ]]; then
    config_dir="$(dirname "$config")"
    config_name="$(basename "$config")"
    new_config_name="low_pri_$config_name"
    cp $config $config_dir/$new_config_name
    sed -i "s|saveckpt_freq:.*|saveckpt_freq: 5000|" $config_dir/$new_config_name
    config=$config_dir/$new_config_name
fi

output_dir=$output_path/$clip_id/${cameras_id}

# render step
echo "==================Start Render=================="
python scripts/render_sim_feedforward.py --config_file $config --output_root $output_path --project $clip_id --run_name ${cameras_id}

# video concate
cd $output_dir/simulator_render

ffmpeg -y -loglevel info -i video_cam0_origin_rgb.mp4 -i video_cam2_origin_rgb.mp4 -i video_cam3_origin_rgb.mp4 -i video_cam4_origin_rgb.mp4 -i video_cam5_origin_rgb.mp4 -i video_cam6_origin_rgb.mp4 -filter_complex "[0:v] crop=iw/2:ih:iw/2:0 [v0]; [1:v] crop=iw/2:ih:iw/2:0 [v1]; [2:v] crop=iw/2:ih:iw/2:0 [v2]; [3:v] crop=iw/2:ih:iw/2:0 [v3]; [4:v] crop=iw/2:ih:iw/2:0 [v4]; [5:v] crop=iw/2:ih:iw/2:0 [v5]; nullsrc=size=3840x1854 [base]; [base][v0] overlay=shortest=1:x=0:y=0 [tmp1]; [tmp1][v1] overlay=shortest=1:x=1920:y=0 [tmp2]; [tmp2][v2] overlay=shortest=1:x=0:y=1080 [tmp3]; [tmp3][v3] overlay=shortest=1:x=968:y=1080 [tmp4]; [tmp4][v4] overlay=shortest=1:x=1936:y=1080 [tmp5]; [tmp5][v5] overlay=shortest=1:x=2904:y=1080" -c:v libx264 -preset veryfast -crf 22 output_023456.mp4
ffmpeg -y -loglevel info -i video_cam0_sin_wave_rgb.mp4 -i video_cam2_sin_wave_rgb.mp4 -i video_cam3_sin_wave_rgb.mp4 -i video_cam4_sin_wave_rgb.mp4 -i video_cam5_sin_wave_rgb.mp4 -i video_cam6_sin_wave_rgb.mp4 -filter_complex "[0:v] crop=iw/2:ih:iw/2:0 [v0]; [1:v] crop=iw/2:ih:iw/2:0 [v1]; [2:v] crop=iw/2:ih:iw/2:0 [v2]; [3:v] crop=iw/2:ih:iw/2:0 [v3]; [4:v] crop=iw/2:ih:iw/2:0 [v4]; [5:v] crop=iw/2:ih:iw/2:0 [v5]; nullsrc=size=3840x1854 [base]; [base][v0] overlay=shortest=1:x=0:y=0 [tmp1]; [tmp1][v1] overlay=shortest=1:x=1920:y=0 [tmp2]; [tmp2][v2] overlay=shortest=1:x=0:y=1080 [tmp3]; [tmp3][v3] overlay=shortest=1:x=968:y=1080 [tmp4]; [tmp4][v4] overlay=shortest=1:x=1936:y=1080 [tmp5]; [tmp5][v5] overlay=shortest=1:x=2904:y=1080" -c:v libx264 -preset veryfast -crf 22 output_sin_wave_023456.mp4
ffmpeg -y -loglevel info -i video_cam0_origin_rgb.mp4 -i video_cam2_origin_rgb.mp4 -i video_cam3_origin_rgb.mp4 -i video_cam4_origin_rgb.mp4 -i video_cam5_origin_rgb.mp4 -i video_cam6_origin_rgb.mp4 -filter_complex "[0:v] crop=iw/2:ih:0:0 [v0]; [1:v] crop=iw/2:ih:0:0 [v1]; [2:v] crop=iw/2:ih:0:0 [v2]; [3:v] crop=iw/2:ih:0:0 [v3]; [4:v] crop=iw/2:ih:0:0 [v4]; [5:v] crop=iw/2:ih:0:0 [v5]; nullsrc=size=3840x1854 [base]; [base][v0] overlay=shortest=1:x=0:y=0 [tmp1]; [tmp1][v1] overlay=shortest=1:x=1920:y=0 [tmp2]; [tmp2][v2] overlay=shortest=1:x=0:y=1080 [tmp3]; [tmp3][v3] overlay=shortest=1:x=968:y=1080 [tmp4]; [tmp4][v4] overlay=shortest=1:x=1936:y=1080 [tmp5]; [tmp5][v5] overlay=shortest=1:x=2904:y=1080" -c:v libx264 -preset veryfast -crf 22 output_gt_023456.mp4