# Dynamic Assets 动态资产模块
## 自动化预处理和训练脚本
``` shell
cd {your-workspace}/simworld/dynamic_assets/
python 3D_real_car_train.py --data_path {your-raw-3D-real-car-data}  --config_name {your-config}
```

已下载的3D real car数据集在fuyao位置: 
```
/workspace/group_share/adc-sim/users/wangyl11/3dgs_dynamic/dataset/
```

预训练配置文件位置: 
```
{your-workspace}/simworld/dynamic_assets/three_D_real_car_preprocess/three_D_RealCar_Toolkit/data_preprocess/resources/configs
```

## 3DRealCar data preprocess 资产点云数据预处理
将开源的3D Real Car数据集进行colmap，segmentation，clean，standard，rescale流水线处理

## gaussian-splatting 资产高斯训练
将pcd数据进行训练生成高斯球ply文件

## agent service 资产场景编辑
TBD