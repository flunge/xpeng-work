# STEP 1: infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wugq1-251106-0747
# STEP 2: infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wugq1-251106-0807
# STEP 3: infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wugq1-251110-1914
# STEP 4: infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wugq1-251112-2222
# All necessary packages are saved in: /workspace/group_share/adc-sim/users/wugq1/new_torch_docker
From infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:peijh-260107-2302

ENV QT_QPA_PLATFORM=offscreen
ENV MAX_JOBS=1
ENV DEBIAN_FRONTEND=noninteractive
ENV TORCH_CUDA_ARCH_LIST="8.0"
ENV CUDA_ARCHITECTURES="80"
ENV TZ=Asia/Shanghai

RUN pip3 uninstall -y fuyao_inference && \
    pip3 install --no-cache --no-deps --trusted-host nexus-sre.xiaopeng.link -i http://nexus-sre.xiaopeng.link/repository/group-pypi/simple fuyao_inference

# 确保镜像内已安装 curl 和 lz4
RUN apt-get update && apt-get install -y curl lz4

# 下载、安装并清理
RUN curl -k -u "dataloader:pAy3qO2pfYee4#&9" -O http://artifactory-sre.xiaopeng.link/artifactory/xmotors-pipy/xdata-dataloader-3.3.89.tar.gz \
    && pip3 install xdata-dataloader-3.3.89.tar.gz \
    && rm xdata-dataloader-3.3.89.tar.gz

RUN pip3 uninstall -y setuptools && pip3 install --no-cache-dir setuptools==80.9.0

# 复制所有动态库文件
COPY camera_video_xp5_decoder_lib/*.so* /usr/local/lib/

RUN ldconfig


COPY camera_video_xp5_decoder_lib/camera_video_xp5_decoder /usr/local/bin/camera_video_xp5_decoder
RUN chmod +x /usr/local/bin/camera_video_xp5_decoder

ENV CAMERA_VIDEO_DECODER=/usr/local/bin/camera_video_xp5_decoder