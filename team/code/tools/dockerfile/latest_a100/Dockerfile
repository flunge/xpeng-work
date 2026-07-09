############# fuyao docker --push --site=fuyao_hk
From infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:shengby-250911-0358

ENV QT_QPA_PLATFORM=offscreen
ENV MAX_JOBS=1
ENV DEBIAN_FRONTEND=noninteractive
ENV LD_LIBRARY_PATH=/usr/local/cuda/compat:/usr/local/cuda/compat/lib:$LD_LIBRARY_PATH
ENV TZ=Asia/Shanghai

############# vision pipeline RoGS
COPY ./diff_gaussian_rasterization_depthalpha /tmp/diff_gaussian_rasterization_depthalpha
COPY ./diff_gaussian_rasterization_kitti /tmp/diff_gaussian_rasterization_kitti
COPY ./diff_gaussian_rasterization_nusc /tmp/diff_gaussian_rasterization_nusc

RUN cd /tmp/diff_gaussian_rasterization_depthalpha && python3 setup.py install
RUN cd /tmp/diff_gaussian_rasterization_kitti && python3 setup.py install
RUN cd /tmp/diff_gaussian_rasterization_nusc  && python3 setup.py install

RUN pip install -i https://mirrors.aliyun.com/pypi/simple scikit-spatial==9.0.1 pymeshlab==2021.10 pytorch-lightning==1.9.2

############# MVSNet
# cupy progressbar tensorboardX imagesize is required by mvsnet
RUN pip install cupy 
RUN pip install progressbar 
RUN pip install tensorboardX 
RUN pip install imagesize 

############# MVSA
RUN pip install antialiased-cnns loguru==0.7.2 rootpath

############# Feed-Forward
# 设置 pip 使用阿里云镜像, 避免 setup.py 去访问 pypi.org
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple && \
    pip config set install.trusted-host mirrors.aliyun.com
RUN pip install --upgrade typing-extensions
RUN apt-get install libsparsehash-dev
COPY ./torchsparse /tmp/torchsparse
RUN cd /tmp/torchsparse && \
    python setup.py install --single-version-externally-managed --record=record.txt

############# Sam3D
ENV TORCH_CUDA_ARCH_LIST="8.0 8.6 9.0+PTX"
ENV FORCE_CUDA=1
ENV PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple" 
ENV PIP_EXTRA_INDEX_URL="https://pypi.ngc.nvidia.com https://download.pytorch.org/whl/cu126"
ENV PIP_FIND_LINKS="https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.7.1_cu126.html"
RUN pip install \
    gradio==5.49.0 \
    kaolin==0.18.0 \
    seaborn==0.13.2 \
    utils3d \
    astor==0.8.1 \
    auto_gptq==0.7.1 \
    autoflake==2.3.1 \
    av==12.0.0 \
    dataclasses==0.6 \
    decord==0.6.0 \
    deprecation==2.1.0 \
    einops-exts==0.0.4 \
    fastavro==1.9.4 \
    fasteners==0.19 \
    ftfy==6.2.0 \
    hdfs==2.7.3 \
    hydra-submitit-launcher==1.2.0 \
    igraph==0.11.8 \
    imath==0.0.2 \
    jsonlines==4.0.0 \
    jsonpickle==3.0.4 \
    librosa==0.10.1 \
    lightning==2.3.3 \
    mosaicml-streaming==0.7.5 \
    objsize==0.7.0 \
    OpenEXR==3.3.3 \
    optimum==1.18.1 \
    optree==0.14.1 \
    panda3d-gltf==1.2.1 \
    pdoc3==0.10.0 \
    pip-system-certs==4.0 \
    point-cloud-utils==0.29.5 \
    polyscope==2.3.0 \
    pydot==1.4.2 \
    pymeshfix==0.17.0 \
    randomname==0.2.1 \
    rootutils==1.0.7 \
    sagemaker==2.242.0 \
    sentence-transformers==2.6.1 \
    simplejson==3.19.2 \
    usort==1.0.8.post1 \
    xatlas==0.0.9 \
    spconv-cu126==2.3.8 \
    flash_attn==2.8.0.post2 \
    "MoGe @ git+https://github.com/microsoft/MoGe.git@a8c37341bc0325ca99b9d57981cc3bb2bd3e255b"

RUN pip install huggingface_hub==0.25.2
RUN pip install cattrs==25.1.1

############# xpeng_raster
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

# install scube
RUN ${PYTHON} -m pip install -U "packaging>=22"
COPY ./openvdb /tmp/openvdb

ENV LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/usr/local/cuda/lib64:/usr/local/nvidia/lib64:${LD_LIBRARY_PATH}
RUN cd /tmp/openvdb/fvdb && ${PYTHON} -m pip install -v . --no-build-isolation --no-cache-dir --force-reinstall
RUN ${PYTHON} -m pip install python-pycg