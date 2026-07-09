fuyao deploy --job-name render --label render \
    --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wugq1-241223-1944 \
    --project="sim3dgs-sim" --gpus-per-node=1 --nodes=1 \
    "source activate base;
    source activate street-gaussians-ns;
    strip --remove-section=.note.ABI-tag /usr/lib/x86_64-linux-gnu/libQt5Core.so.5;
    cd /workspace/yangxh7@xiaopeng.com/codes/3dgs/;
    python tools/scripts/render_oss_mode.py;"
