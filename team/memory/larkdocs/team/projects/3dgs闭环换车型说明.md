<title>3dgs闭环换车型说明</title>

<callout emoji="📌">
必须先确认要换车型的case有生产闭环scenario
</callout>

# 下载3dgs模型

以[89089621](https://cloudsim.xiaopeng.link/#/scenario/89089621)为例，下载3dgs模型并解压，找到calib.json

![图片展示的是3dgs闭环换车型文档中“复制scenario”步骤里，cloudsim接口修改字段的示例代码。代码中以红色框突出显示了“3dgs_config”部分，包含“oss_bucket”为“cloudsim-ci”等配置信息。该图片与上文提到的“可以考虑直接调cloudsim接口来修改”相呼应，直观呈现了通过cloudsim接口修改scenario时，需复制并修改的字段内容，帮助理解如何进行3dgs模型的闭环换车型操作。](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YjRmMDhiMjZmM2FkY2E1M2NiMWVjZThiZjVlODJlYzNfMDc1ZjYwMDU5OTdjMjZlMjc3N2Y2NDhkZmE1MWY0MThfSUQ6NzY2MDA3NTkwODI3MDkxODg3N18xNzg1NzU2Nzg0OjE3ODU3NjAzODRfVjM)

![这张图片展示的是文件目录结构，根目录为3dgs_datasets下的4030文件夹，该文件夹内包含名为model1的目录。在model1目录下，configs、images等多个子项中，calib.json文件被红色方框重点标注，该文件是下载3dgs模型并解压后需要找到的关键文件，对应文档中下载3dgs模型步骤里提及的calib.json内容。](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OGNkOTkzZjNiZTkzNmNlNmRhZGQzZDY0MDYzM2Q2OWFfZWZiZjhlM2YzZmZiMmMwOThlYWEzMDZhZjkzYTkwYTRfSUQ6NzY2MDA3NjUwMzIxMTk2OTc4MV8xNzg1NzU2Nzg0OjE3ODU3NjAzODRfVjM)

# 上传oss

```Plain Text
ossutil64 cp calib.json oss://cloudsim-ci-sh/multi_vehicle/calibration/d03-4030/calib.js
on
路径说明：oss://cloudsim-ci-sh/multi_vehicle/calibration/{车型}/calib.json
```

如果要换dds calibration，也需要把calibration.tar.lz4上传到oss



# 复制scenario

> 可以考虑直接调cloudsim接口来修改

![图片展示的是cloudsim平台中3DGS LogSimSuite的编辑界面。左侧为Base Info、Editable Info等信息板块，如ID、Difficulty Level、DDS Source等。右侧Functions板块有Request Permission、Core Scenario、Test Scenario等选项，下方是Edit History记录，显示了2026 - 07 - 07 12:13的更新操作。图片中红色箭头指向“vehicle_name”字段，提示其为可编辑字段，与上下文提到的复制scenario后修改vehicle_name字段以换车型的内容相关。](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MTc4M2QyOWVhMDhiZmMzMDlhZDc4ODA4OTI3ZTI5ZmVfZmZiYzdlMjg3NTIwZTgxZjU1OGFiY2I2ZjVlMzEzMDVfSUQ6NzY2MDA4MDU4NTU3OTM4Mzc1N18xNzg1NzU2Nzg0OjE3ODU3NjAzODRfVjM)

1. 先复制scenario
2. 跳转到复制好的scenario修改以下字段

- vehicle_name

一般这种换calibration的都是同车型，所以vehicle_name不改，否则需要改成新车型

- ddsDataSource.calibration

修改为需要替换车型的calibration。如果换整个车型，一般是根据第二步上传的calibataion填路径，如果需求是同车型换其他车的calibration，可以直接把其他车型的calibration复制到待换车型的dsDataSource.calibration

![图片展示了3DGS系统中待换车scenario和其它车的calibration信息。待换车scenario部分，有“dsDataSource”字段，其“calibration”值为“cloudsim_scenario/driving/2020-07-07/88659353/unknown - L1N8X7NTYB256507 - d85exslidc”。其它车的calibration部分，有“dsDataSource”字段，其“calibration”值为“cloudsim_scenario/driving/2020-07-07/88659353/unknown - L1N8X7NTYB256507 - d85exslidc - 3349823339999999999”。图片与上下文关系为，上下文提到若需求是同车型换其他车的calibration，可复制其他车型的calibration到待换车型的dsDataSource.calibration，此图展示了具体字段对应情况。](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YjkzMTQzNjMxZDY3NmM1MWM5ZmVlNjcyOWNlMjU1NTRfMjcyOTU4OWE4OGEwY2M1N2RjZmUwNTI0MDM5N2M3ZWJfSUQ6NzY2MDA3OTc1OTUwNzEzMTU5Ml8xNzg1NzU2Nzg0OjE3ODU3NjAzODRfVjM)

- 3dgs_config.multi_vehicle_calib

新增字段multi_vehicle_calib，对应刚刚上传到oss的calib.json

![这是一段代码配置内容，对应文档中3dgs闭环换车型的相关配置说明，核心内容为新增的`multi_vehicle_calib`字段，其路径值被红色边框标注为`multi_vehicle/calibration/d03-4030/calib.json`，该配置的旁侧标注有“不填bucket”的提示，此内容与文档中“新增字段multi_vehicle_calib，对应刚刚上传到oss的calib.json”的描述相契合，明确了该字段的具体配置要求。](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YmYzMTM3YjQxYjJjZWE4N2RjMGJmNjIyMjgxN2ZjZTFfZmRjMjk1NTY1N2M0ODFiNDgyZTU5ZWRiNTBjMDJhMTJfSUQ6NzY2MDA4MDIxNzY1NTExOTA1OV8xNzg1NzU2Nzg0OjE3ODU3NjAzODRfVjM)

> 注意:修改完一定要点confirm
> 
> 如果要调cloudsim api来完成，接口是：query->duplicate_scenario->update_scenario