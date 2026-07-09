# STEP 1: infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wugq1-251106-0747
# STEP 2: infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wugq1-251106-0807
# STEP 3: infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wugq1-251110-1914
# STEP 4: infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wugq1-251112-2222
# All necessary packages are saved in: /workspace/group_share/adc-sim/users/wugq1/new_torch_docker
From infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wugq1-251112-2222

ENV QT_QPA_PLATFORM=offscreen
ENV MAX_JOBS=1
ENV DEBIAN_FRONTEND=noninteractive
ENV TORCH_CUDA_ARCH_LIST="8.0"
ENV CUDA_ARCHITECTURES="80"
ENV TZ=Asia/Shanghai

RUN pip3 uninstall -y fuyao_inference && \
    pip3 install --no-cache --no-deps --trusted-host nexus-sre.xiaopeng.link -i http://nexus-sre.xiaopeng.link/repository/group-pypi/simple fuyao_inference

# for mvsa
RUN pip install -i https://mirrors.aliyun.com/pypi/simple antialiased-cnns loguru==0.7.2

##### xpeng_raster
ARG PYTHON=python3
RUN ${PYTHON} -m pip install --no-cache-dir --upgrade pip setuptools wheel ninja
WORKDIR /opt
COPY xpeng_raster /opt/xpeng_raster
WORKDIR /opt/xpeng_raster
# ------ Build and install xpeng_raster ------
RUN rm -rf build/ xpeng_raster/_C.*.so 2>/dev/null || true && \
    export MAX_JOBS="$(command -v nproc >/dev/null 2>&1 && nproc || echo 1)" && \
    ${PYTHON} setup.py build_ext --inplace && \
    ${PYTHON} -m pip install --no-cache-dir --no-build-isolation .
    

##################### Sam3D
COPY auto_gptq-0.7.1+cu128-cp312-cp312-linux_x86_64.whl  \
     kaolin-0.18.0-cp312-cp312-linux_x86_64.whl \
     point_cloud_utils-0.29.5-cp312-cp312-linux_x86_64.whl /opt/
WORKDIR /opt
ENV FORCE_CUDA=1
ENV PIP_INDEX_URL="https://mirrors.aliyun.com/pypi/simple" 
ENV PIP_EXTRA_INDEX_URL="https://pypi.ngc.nvidia.com https://download.pytorch.org/whl/cu128"
RUN pip install \
    warp-lang -i "https://mirrors.aliyun.com/pypi/simple" \
    gradio==5.49.0 \
    kaolin-0.18.0-cp312-cp312-linux_x86_64.whl \
    seaborn==0.13.2 \
    utils3d \
    astor==0.8.1 \
    auto_gptq-0.7.1+cu128-cp312-cp312-linux_x86_64.whl \
    autoflake==2.3.1 \
    dataclasses==0.6 \
    decord==0.6.0 \
    deprecation==2.1.0 \
    fastavro==1.9.4 \
    fasteners==0.19 \
    hdfs==2.7.3 \
    hydra-submitit-launcher==1.2.0 \
    igraph==0.11.8 \
    imath==0.0.2 \
    jsonlines==4.0.0 \
    einops-exts==0.0.4 \
    jsonpickle==3.0.4 \
    librosa==0.10.1 \
    lightning==2.3.3 \
    mosaicml-streaming==0.7.5 \
    objsize==0.7.0 \
    OpenEXR==3.3.3 \
    # optimum==1.18.1 \
    optree==0.14.1 \
    panda3d-gltf==1.2.1 \
    pdoc3==0.10.0 \
    point_cloud_utils-0.29.5-cp312-cp312-linux_x86_64.whl \
    polyscope==2.3.0 \
    pydot==1.4.2 \
    pymeshfix==0.17.0 \
    randomname==0.2.1 \
    rootutils==1.0.7 \
    # transformers==4.53.3
    sagemaker==2.242.0 \
    sentence-transformers==2.6.1 \
    simplejson==3.19.2 \
    usort==1.0.8.post1 \
    xatlas==0.0.9 \
    "MoGe @ git+https://github.com/microsoft/MoGe.git@a8c37341bc0325ca99b9d57981cc3bb2bd3e255b"
    
RUN pip install \
    spconv-cu128==2.3.8 -i "https://guest_xiaopeng:XiaoPeng1234@art-pub.eng.t-head.cn/artifactory/api/pypi/cu128_index/simple"

###################### scube
RUN python3 -m pip install -U "packaging>=22"

RUN ln -s $(which gcc) /usr/bin/gcc-11 && \
    ln -s $(which g++) /usr/bin/g++-11

ARG PYTHON=python3
COPY ./openvdb /tmp/openvdb
RUN cd /tmp/openvdb/fvdb && ${PYTHON} -m pip install -v . --no-build-isolation --no-cache-dir --force-reinstall
RUN ${PYTHON} -m pip install python-pycg