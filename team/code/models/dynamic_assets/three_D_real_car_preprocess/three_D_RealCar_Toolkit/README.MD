## Preperation
```
# install colmap
apt-get install colmap

# install some python package
pip install colorama plyfile open3d kornia tqdm imageio imageio[ffmpeg] opencv-python

# other you need install GroudingDino and SAM
wget https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth && mv sam_vit_h_4b8939.pth resources/models/
pip install submodules/GroundingDINO
pip install supervision segment_anything
```

**Data**
```
# data path structure example: 
/path/raw_data/dataset_name/3dscanner_origin/xxxx(png or json)
# for example: /realcar3D/demo_data/raw_data/2024_04_11_11_31_27/3dscanner_origin

# Run below code to rearrange dataset
cd DATASET_NAME
mkdir 3dscanner_origin
mv *.* 3dscanner_origin
```

## Run
```
# for example, DATASET_NAME=2024_04_11_11_31_27, EXP_NAME=demo

# Preprocess progress: colmap -> segmentation -> pcd_clean -> pcd_standard -> pcd_rescale

# colmap: use colmap to extract camera intrinsics and extrinsics.
./bash/pipeline.sh DATASET_NAME dataset EXP_NAME

# segmentation: use SAM to extract alpha for car. Should be run after colmap.
./bash/pipeline.sh DATASET_NAME segmentation EXP_NAME

# pcd_clean: use alpha extracted by SAM to clean point cloud. Should be run after segmentation.
./bash/pipeline.sh DATASET_NAME pcd_clean EXP_NAME

# pcd_standard: use PCA to find possible standarized coordinates. CHECKING REQUIRED since may be wrong. Should be run after pcd_clean.
./bash/pipeline.sh DATASET_NAME pcd_standard EXP_NAME

# pcd_rescale: use PCA calculated by ARKit camera extrinsics to extract scales between colmap camera extrinsics and arkit's. Should be run after pcd_standard.
./bash/pipeline.sh DATASET_NAME pcd_rescale EXP_NAME

```

# 3DRealCar: An In-the-wild RGB-D Car Dataset with 360-degree Views
### [Project page](https://xiaobiaodu.github.io/3drealcar/) | [Paper](https://arxiv.org/html/2406.04875v1)

<img src="assets/teaser.png"/>


## Free Commercial Usage
**3DRealCar dataset is allowed commercial usage for free. The dataset license is Apache-2.0.** 

## 😮 Highlights
- Our 3DRealCar is the first large-scale 3D real car dataset containing both densely captured RGB-D images and point clouds.
-  This dataset is the first to provide 3D car parsing map annotations.


## 🚩 **Updates**

Welcome to **watch** 👀 this repository for the latest updates.


✅ **[2024.6.10]** : We have released our paper, 3DRealCar on [arXiv](https://arxiv.org/html/2406.04875v1).

✅ **[2024.6.10]** : Release [project page](https://xiaobiaodu.github.io/3drealcar/).

✅ **[2024.8.13]** : Code is realeased. 

✅ **[2024.8.15]** : We are releasing our dataset. You can download our dataset in the [project page](https://xiaobiaodu.github.io/3drealcar/). 

✅ **[2025.1.21]** : Release 3DRealCar dataset [download page](https://xiaobiaodu.github.io/3drealcar/download.html). 



## How to use

Please refer to our code [data_preprocess](data_preprocess)




## ✏️ Citation
If you find our paper and code useful in your research, please consider giving a star :star: and citation :pencil:.

```BibTeX
@article{du20243drealcar,
  title={3DRealCar: An In-the-wild RGB-D Car Dataset with 360-degree Views},
  author={Du, Xiaobiao and Sun, Haiyang and Wang, Shuyun and Wu, Zhuojie and Sheng, Hongwei and Ying, Jiaying and Lu, Ming and Zhu, Tianqing and Zhan, Kun and Yu, Xin},
  journal={arXiv preprint arXiv:2406.04875},
  year={2024}
}
```








[//]: # (## ✏️ Citation)

[//]: # (If you find our paper and code useful in your research, please consider giving a star :star: and citation :pencil:.)

[//]: # ()
[//]: # (```BibTeX)

[//]: # ()
[//]: # ()
[//]: # ()
[//]: # (```)

[//]: # (<!---->)
