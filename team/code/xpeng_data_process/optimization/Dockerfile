From infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:lianged-250724-0301

ENV MAX_JOBS=1
ENV LD_LIBRARY_PATH=/usr/local/cuda/compat:/usr/local/cuda/compat/lib:$LD_LIBRARY_PATH

RUN pip config --user set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --upgrade pip

RUN pip install -i https://nexus-wl-internal.xiaopeng.link/repository/ai_infra_pypi_group/simple open3d==0.18.0 plyfile==1.1.2 numba==0.59.0  opencv-contrib-python==4.11.0.86 easydict

COPY ./diff-surfel-rasterization /root/diff-surfel-rasterization
COPY ./camopt /root/camopt

RUN cd /root/diff-surfel-rasterization && python3 setup.py install

RUN apt-get install -y libsuitesparse-dev
RUN cd /root/camopt && pip install -r requirements_campose.txt
RUN cd /root/camopt && pip install .
RUN pip install torch-scatter -f https://data.pyg.org/whl/torch-2.7.1+cu126.html

# install fuyao
RUN pip3 install fuyao \
    -i http://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com \
    --extra-index-url http://nexus-wl.xiaopeng.link:8081/repository/ai_infra_pypi/simple --trusted-host nexus-wl.xiaopeng.link

# notebook env
RUN sed -i 's|archive.ubuntu.com|mirrors.aliyun.com|g' /etc/apt/sources.list && \
    sed -i 's|security.ubuntu.com|mirrors.aliyun.com|g' /etc/apt/sources.list
RUN pip install jupyterlab
COPY --from=infra-registry.cn-wulanchabu.cr.aliyuncs.com/data-infra/public:fuyao-base-1.9.7 /opt/data-infra /opt/data-infra
ENV PATH="${PATH}:/opt/data-infra"
ENTRYPOINT ["tini", "-s", "--"]