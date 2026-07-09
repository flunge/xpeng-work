FROM  infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:FuyaoSimSimengineLoop-0.0.27

ENV QT_QPA_PLATFORM=offscreen
ENV MAX_JOBS=1
ENV DEBIAN_FRONTEND=noninteractive
ENV TORCH_CUDA_ARCH_LIST="8.0 8.6 9.0+PTX"
ENV CUDA_ARCHITECTURES="90"
ENV TZ=Asia/Shanghai

COPY . /root/install
WORKDIR /root/install

# apt-get工具
RUN sed -i 's/archive.ubuntu.com/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        htop \
        zip \
        colmap \
        ffmpeg \
        iproute2 \
        net-tools \
        curl \
        vim \
        wget \
        libglm-dev libgl1-mesa-dev libglib2.0-0 \
        software-properties-common && \
    apt-get clean


# 安装 Python 3.10 和必要依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa -y \
    && apt-get install -y python3.10 python3.10-distutils python3.10-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 pip 和 setuptools
RUN apt-get update && \
    apt-get install -y python3.10 python3.10-distutils ca-certificates && \
    # 卸掉 Debian 自带的 pip、setuptools、wheel
    apt-get remove -y python3-pip python3-setuptools python3-wheel && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*
    
RUN apt-get update && python3.10 ./get-pip.py --no-index --find-links=./pips --no-setuptools --no-wheel && \
    python3.10 -m pip install ./wheel*.whl ./setuptools*.whl

# 设置 Python 3.10 为默认
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.10 1

# 安装各种依赖
RUN pip config --user set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --upgrade pip && \
    pip install  torchaudio torchmetrics && \
    apt-get install libsparsehash-dev && \
    pip install ./torchsparse-1.4.0 && \
    pip install ./gsplat && \
    pip install --ignore-installed -r ./requirements_new.txt && \
    pip uninstall numpy -y && \
    pip install scipy==1.12.0 numpy==1.24.0 && \
    pip install ./street_gaussians/submodules/diff-gaussian-rasterization && \
    pip install ./street_gaussians/submodules/simple-knn && \
    pip install ./street_gaussians/submodules/simple-waymo-open-dataset-reader && \
    pip install faiss-gpu oss2 nvitop ipykernel jupyterlab ninja && \
    pip install git+https://github.com/NVlabs/nvdiffrast.git && \
    pip install requests==2.25.1 && \
    pip install fuyao --extra-index-url http://nexus-wl.xiaopeng.link:8081/repository/ai_infra_pypi/simple
# RUN pip cache purge


ARG PIP_OPTIONS="-i https://mirrors.aliyun.com/pypi/simple --timeout 120"
RUN sed -i 's|archive.ubuntu.com|mirrors.aliyun.com|g' /etc/apt/sources.list && \
    sed -i 's|security.ubuntu.com|mirrors.aliyun.com|g' /etc/apt/sources.list

# 拷贝data-infra工具
COPY --from=infra-registry.cn-wulanchabu.cr.aliyuncs.com/data-infra/public:fuyao-base-1.9.7 /opt/data-infra /opt/data-infra
ENV PATH "${PATH}:/opt/data-infra"

# 设置工作目录和入口点
ENTRYPOINT ["tini", "-s", "--"]