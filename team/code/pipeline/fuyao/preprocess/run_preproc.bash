config=$1
job_name=$2
root=$3

workspace_path=$(echo $root | sed -E 's_(/workspace/[a-zA-Z0-9\_\.\-\@]+/).*_\1_')
cd $root

echo "========================================================================"
echo "PWD="$PWD
echo "root="$root
echo "workspace_path="$workspace_path
echo "========================================================================"


mkdir -p $workspace_path/logs/preprocess_logs/

export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda:/usr/local/cuda/lib:/usr/local/cuda/lib64:/usr/local/nvidia/lib:/usr/local/nvidia/lib64
echo $LD_LIBRARY_PATH
# Create a timestamp in YYMMDDHHmmSS format
timestamp=$(date +"%y%m%d%H%M%S")

python xpeng_data_process/main.py --config $config | tee "${workspace_path}/logs/preprocess_logs/log_${job_name}_${timestamp}.txt"
