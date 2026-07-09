cloudsim_scenario_id=$1
edited_3dgs_version=$2
output_dir=$3
# origin_dds_bucket=$4
# origin_dds_oss_dir=$5

if [ -z "${cloudsim_scenario_id}" ]; then
    echo "need to set cloudsim_scenario_id"
    exit 1
fi

if [ -z "${edited_3dgs_version}" ]; then
    echo "need to set edited_3dgs_version"
    exit 1
fi

task_prefix="harmonize_to_dds"
workspace_path="/workspace/wangyl11@xiaopeng.com"

curl https://gosspublic.alicdn.com/ossutil/install.sh | bash

oss_endpoint="http://oss-cn-wulanchabu-internal.aliyuncs.com"
output_tar_dir="${output_dir}/${edited_3dgs_version}/"
# run cmd to 
# download from oss://cloudsim-ci-sh/3dgs_scenario_engine/{edited_3dgs_version}/3dgs_model_edited.tgz
# ossutil -e http://oss-cn-wulanchabu-internal.aliyuncs.com -i OSS_ACCESS_KEY_ID_REDACTED -k OSS_ACCESS_KEY_SECRET_REDACTED -r --parallel 8 cp -f "oss://cloudsim-ci-sh/sim_engine/artificially_created_scenes/c-4155db0f-0930-3e4b-bda2-56555b893ee5/trained_model_202509031406/3dgs_model.tgz" ./
ossutil -e $oss_endpoint -i OSS_ACCESS_KEY_ID_REDACTED -k OSS_ACCESS_KEY_SECRET_REDACTED -r --parallel 8 cp -f "oss://cloudsim-ci-sh/3dgs_scenario_engine/${edited_3dgs_version}/3dgs_model_edited.tgz" "$output_tar_dir"

output_tar_path="${output_tar_dir}/3dgs_model_edited.tgz"

versioned_output_dir="${output_dir}/${edited_3dgs_version}"
mkdir -p "${versioned_output_dir}"

tar -xzf "$output_tar_path" -C "${versioned_output_dir}"

hf_home_path="$workspace_path/pretrain_model"
export TORCH_HOME="$workspace_path/torch_cache"
export HF_HOME=$hf_home_path

drivestudio_path="$workspace_path/workspace/sim_world/simworld/omnire_joint_trainning/src"
echo $drivestudio_path
cd $drivestudio_path

config="${versioned_output_dir}/configs/config_sim.yaml"

output_dir="$(dirname "$config")"
output_dir="$(dirname "$output_dir")"

export PYTHONPATH=$drivestudio_path

python scripts/render_harmonization.py --config $config --save_path $output_dir/simulator_render

# local dds dat dir
dds_dir="/root/origin_dds_dat_files/"

# remove existing .dat files folder
rm -rf "${dds_dir}"

# download oss all .dat files
# ossutil -e $oss_endpoint -i OSS_ACCESS_KEY_ID_REDACTED -k OSS_ACCESS_KEY_SECRET_REDACTED -r --parallel 8 cp -f -r "${origin_dds_bucket}/${origin_dds_oss_dir}/" "${dds_dir}"

dds_studio_path="$workspace_path/workspace/process_script/dds/dds_converter/convert/e2e_pytorch_job"
echo $dds_studio_path
cd $dds_studio_path

export PYTHONPATH=$dds_studio_path
pip install Msg_binder-0.0.1-py3-none-any.whl

export LD_LIBRARY_PATH="$workspace_path/workspace/process_script/dds/lib:$LD_LIBRARY_PATH"

dynamic_assets_path="$workspace_path/workspace/sim_world/simworld/models/dynamic_assets"
echo $dynamic_assets_path
cd $dynamic_assets_path

# upload dds dat files to oss
upload_dds_oss_dir="demo/aeb_test_dds/${edited_3dgs_version}/"

# /home/wangyl11/dev/sim_world_3dgs/simworld/models/dynamic_assets/scenario_edit/image_3dgs_to_dds.py
python ./scenario_edit/image_3dgs_to_dds.py --dat_dir "${dds_dir}" --base_dir $output_dir --mode "encode" --scenario_id "${cloudsim_scenario_id}"  --edited_3dgs_version ${edited_3dgs_version} --upload_dds_oss_dir "${upload_dds_oss_dir}"

# ossutil -e $oss_endpoint -i OSS_ACCESS_KEY_ID_REDACTED -k OSS_ACCESS_KEY_SECRET_REDACTED -r --parallel 8 cp -f -r "${dds_dir}" "${origin_dds_bucket}/${upload_dds_oss_dir}"

# upload all mp4 files in $output_dir/simulator_render to "oss://cloudsim-ci-sh/3dgs_scenario_engine/${edited_3dgs_version}/videos/"
ossutil -e $oss_endpoint -i OSS_ACCESS_KEY_ID_REDACTED -k OSS_ACCESS_KEY_SECRET_REDACTED -r --parallel 8 cp -f -r "${output_dir}/simulator_render/" "oss://cloudsim-ci-sh/3dgs_scenario_engine/${edited_3dgs_version}/videos/" --include "*.mp4"
ossutil -e $oss_endpoint -i OSS_ACCESS_KEY_ID_REDACTED -k OSS_ACCESS_KEY_SECRET_REDACTED -r --parallel 8 cp -f -r "${output_dir}/simulator_render/hevc_videos/" "oss://cloudsim-ci-sh/3dgs_scenario_engine/${edited_3dgs_version}/videos/hevc_videos/" --include "*.mp4"

rm -rf "${dds_dir}"

# modify scenario info to update dds path
# python ./scenario_edit/scenario_info_update.py --cloudsim_scenario_id ${cloudsim_scenario_id} --edited_3dgs_version ${edited_3dgs_version} --dds_oss_path ${upload_dds_oss_dir}

echo "Harmonization to DDS dat files process completed. scenario id: ${cloudsim_scenario_id}, edited_3dgs_version: ${edited_3dgs_version}, uploaded to oss dir: ${upload_dds_oss_dir}"