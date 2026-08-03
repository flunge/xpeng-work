# difix ref图模式优化

## 当前问题

- 换车型以后部分3dgs渲染图中的几何位置被ref图中的位置带偏
- 多发生于3dgs渲染图效果不好的区域
- 原因：

  - ref 和 3DGS 越像 → cross-view attention softmax 越尖锐 → 每个 3DGS 的 token 几乎只 attend 到 ref 上对应那一根车道线 token → 直接复制 ref 的几何。
  - ref 和 3DGS 差很多时（如闭环仿真）→ 没有锐利的"对应点"→ attention 被迫弥散 → 只能借鉴全局风格/纹理 → 几何不会被注入。
  - 本质：这是个分布外问题（OOD），训练集里没有"高对齐 + 外参小差异" 的样本，导致 attention 在这种情况下的极尖锐行为没有被正则化过。
- 现象：

<figure view-type="Preview"><source name="video_cam2_origin_rgb.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MDA1M2M4M2Q3MjNlZTg0N2UyNWE3ZjBjYWM2MjhjN2NfZTI3ZWU4YzY4ODY4ZjY2ODFlYmUxMGE1NDliZGZjMjBfSUQ6NzY0MjI2OTM2OTk2MDA3NDE3MV8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="1088.000000" origin-width="3840.000000" size="92638994" token="Rc8QbSDRioFAqNxpVPqc2tmInft"/></figure>



## 短期解决措施

- ref图回到训练数据domain，即恢复类似训练数据分布，不用时间上完全对齐的图为ref图，而选择前后1秒的图作为ref图

<table><colgroup><col/><col/><col/><col/><col/></colgroup><tbody><tr><td></td><td>52712252</td><td>53028797</td><td>53132679</td><td>56912286</td></tr><tr><td>cam0</td><td></td><td></td><td></td><td><figure view-type="Preview"><source name="output0_minus1.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=Zjk2YzdmMjkyYjRjOWQ4MGJkMDRlNmI4NDgzNDhiNTdfMTc5NmMzNDI5NzRlM2NkYmIzNzVkYTQ4OGQ0OTBlNzRfSUQ6NzY0MjI3NTMyOTk5ODgxODI3M18xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="2400.000000" origin-width="3840.000000" size="30687115" token="H186b7vbUox91gxgEgdcnhqCnpD"/></figure></td></tr><tr><td>cam2</td><td><figure view-type="Preview"><source name="output_minus1.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MmI1OTBjMjhmZmIyMjk2NThkODU5MDU5MDNmNDgzZTRfYTUxNWE2YTQ1MGQ4YTljZTU5NGQ0NmJjZGUwM2M2ZmRfSUQ6NzY0MjI3MzkxOTA0NjY4MzgzNF8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="2400.000000" origin-width="3840.000000" size="67344854" token="HxYibrFz4oDlJ7x0XUbcEVgJnwf"/></figure></td><td><figure view-type="Preview"><source name="output_minus1.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MTBkZWQwMGM4ZDFkODAzMGUyMTBjMGM0NjlmYzVkMzJfNGY3MjljYWFiZDdjMzRmNjU4ZTBkNzRmNTlmMzg1MmFfSUQ6NzY0MjI3MzE3NjY0NjUwMzYxM18xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="2400.000000" origin-width="3840.000000" size="46828469" token="PHEvbYrR0oZ7p5xlgbYcUJmWnLf"/></figure></td><td><figure view-type="Preview"><source name="output_minus1.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZWQ1ZTUxYTlmZWU2OGQ4MzA3NmZiYzEwNGI4NTI4ODFfMDJkZWFkNGJiYmI2MjFmYTdjOWJjYzBkMTI2MzE5OTlfSUQ6NzY0MjI3MjUwNjYxNTQ5OTk4N18xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="2400.000000" origin-width="3840.000000" size="45848194" token="LBAXbdFLRoGMJdxhVMlcJcXYnPc"/></figure></td><td><figure view-type="Preview"><source name="output_minus1.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YjFiYmM3YTZmYmMyYmIyMzQwZjA0NWM5MWIxNDZlYWJfYjEwMjI2Yzk0Y2Q1MWE2NDU1Yjc4YTRmMGZkYTAwOGRfSUQ6NzY0MjI3Mjc5MTA4NzMzNjQwMF8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="2400.000000" origin-width="3840.000000" size="58878205" token="X6gdbSfTjoP0a1xZrh4cS6gWnPb"/></figure></td></tr><tr><td>cam3</td><td></td><td></td><td></td><td><figure view-type="Preview"><source name="output3_minus1.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OGNiMWNjZGQ3ZDZhNmU3YjA5ZDgzNDExYjc1Zjc2OGFfZWQ5YTliMTQ0OWYyNWZlOGE4ZTFkZmNhYzdlYzFhNzdfSUQ6NzY0MjI3NTE1Mzg2NzczODA2OF8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="1788.000000" origin-width="1936.000000" size="21276865" token="BZDubcNjAoTEYLx2SPkcsJIYn5b"/></figure></td></tr><tr><td>cam4</td><td></td><td></td><td></td><td><figure view-type="Preview"><source name="output4_minus1.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YmMxZjYxMzU5NjMwMWVjMmI2YmFhYjk1ZmJmNzlmZDBfZGUwMDhjZmE5YjQ4YTBkNjQ0ODY1OTM1Y2U0NzNjODRfSUQ6NzY0MjI3NTY1NzQ1NzcxNjE3NF8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="1788.000000" origin-width="1936.000000" size="21001669" token="T7l5bTpQGoj6uRxsAu7c5UQCnlJ"/></figure></td></tr><tr><td>cam5</td><td></td><td></td><td></td><td><figure view-type="Preview"><source name="output5_minus1.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MTY5ZmM4OGJmYzlmODMwM2Y0OGIxNzFkNGMyZjVmYTBfMmVhODhmMWEyYTFjNGU4NTQyMWIxNzZlY2E0ZGFkOGFfSUQ6NzY0MjI3NjI3NDI3OTA5MTM5MF8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="1788.000000" origin-width="1936.000000" size="20449239" token="JEOVbRtQ1ozqjlx6PwWckEkDnvc"/></figure></td></tr><tr><td>cam6</td><td></td><td></td><td></td><td><figure view-type="Preview"><source name="output6_minus1.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MjAyZjhhNjM2NDFjMjE3ZDQxZjA1OWU2M2NiYWVlMDVfMzFiOWI2NTIxNGQ4MTlhN2Q0MTQxMGU2MGE1YWRjMmRfSUQ6NzY0MjI3NjU4NTg1Mjg5ODI0NV8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="1788.000000" origin-width="1936.000000" size="20757891" token="FnFhbsBX4oLluXxOoZZcUQsYn9f"/></figure></td></tr><tr><td>cam7</td><td></td><td></td><td></td><td><figure view-type="Preview"><source name="output7_minus1.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NDJiYThkMjEzYjZmYjcxZjFjMjU5NzRhNWRkZjZhODJfZWE2NjEwNTYzZTNmNWM3NGQwZTgxNzZiZjc4NTViZThfSUQ6NzY0MjI3Njc4Mzc2OTE0NDUxN18xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="2400.000000" origin-width="3840.000000" size="31306601" token="REoKbmD70oKG81xO458cOqMmnAb"/></figure></td></tr></tbody></table>

- 仍然无法解决cam3等近距离栅栏高度问题
- 动态障碍物的车尾灯、行人动作等可能会丢失



## 长期解决措施（data augmentation）

- 优化训练数据重训

  - 目标：
  
    - 减少ref图几何的干扰
    - 去掉ref图车身的影响
  - 之前的渲染链路

  <whiteboard token="PyqZwv6N7hOGU9bZSa5c7xdanHc"></whiteboard>

  - 改造后渲染链路

  <whiteboard token="P0Hnw5Murh9xI3bJnJlcbvHKnXF"></whiteboard>

  - 改动点：
  
    - 渲染代码改造
    - 训练数据重新生成，需要不带mask的数据
    - Difix-ref模型改造，需要加入车身mask



## 版本管理

### 20260528 优化 - v1

- 加入了一些不同车型的图作为ref图进行训练，比例为（6：4）

<whiteboard token="LUcfwWcMchEwWcbEJbNc4gzdnFg"></whiteboard>

- 有改善

  - 但仍然有幻觉，部分也场景也很跳

  <grid><column width-ratio="0.500000"><figure view-type="Preview"><source name="output.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZWU2ZWYzMGIwODliOTFiMTFlNmU3NTYwMjc3YTZlOTFfZjQyZDA2MjFlOGE3MDQxYTBiNDQ4NTJiZTM4MTJkMzFfSUQ6NzY0NDg2NDgyMTUzMjE4MzQ5NV8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="2176.000000" origin-width="3840.000000" size="17666804" token="G4A2bqViHoHuUBxUkDJc9ECAnFO"/></figure></column><column width-ratio="0.500000"><figure view-type="Preview"><source name="output_compressed.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MTQ3ZjdlZDkzNWE1NDk3ZTM0YTkwM2I4ZjVjMDRiNzBfZWEwNGI3MzY4OGVkZjJhMTM3NGMxYzgzODA2ZDM2MjZfSUQ6NzY0NDg2NTEzMjAwMjg4ODkwNF8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" origin-height="2176.000000" origin-width="3840.000000" size="19251835" token="PUzyb7NoqoxlWWxwVzXc50wMnZf"/></figure></column></grid>

  - 但对于某些视角，如下面第二图，顶部栏杆那里怀疑是学到远处背景了，导致3dgs渲染的时候仍然还有部分原几何的渲染，difix加重了这个幻影

  ![图片展示了三个不同视角的图像，分别是未经perturb训练的test.png（左侧）、testref.png（中间）和testload.png（右侧）。左侧test.png图像显示了城市街道场景，有树木、护栏和远处建筑。中间testref.png图像与左侧类似，但护栏部分有不同。右侧testload.png图像中，护栏部分有明显变化，与中间图像相比，护栏颜色和细节有所不同。该图与上下文提到的使用pertube对40%原图增加扰动，以及对某些视角顶部栏杆怀疑学到远处背景导致3DGS渲染时仍有原几何渲染等问题相关。](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YmRhNWMwM2JlZDgwNjg1OWY2MjgxNGJmMzgxNjYyYTNfZmQwZjA1M2Y1MWFiNGJjMGY2YzJmNTZhYjYzNWRhYWJfSUQ6NzY0NDQwMjk5MjM4NDQyOTI1MF8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM)
- **v1版本最佳配置还是新模型 + -1秒的ref图**



### 20260529 优化 - v2

- 计划使用pertube来对40%的原图继续增加扰动，如图：

<figure view-type="Preview"><source name="cam2_perturb_amp10.0.mp4" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MTA5MDg5ZGE0MjgwMTUzOTI2OThkNGQxMWE1MjFiMDlfOWNiMjVjMWY4OTg2NjI3ZWQ2MDFiMTNiN2Y3YzI1YmRfSUQ6NzY0NDg2NjA3NzUzNzM0MDYzN18xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM" mime="video/mp4" size="33038508" token="VHFKbgSOxoDpTWxwPGFcNnvwn4G"/></figure>



### 20260601 优化 - v3

- Difix-ref模型改造完成，新车型车身mask不会被Diffusion修复回原车型

<grid>
<column width-ratio="0.333333">
![图片展示了Difix-ref模型改造后的效果对比。画面中，左侧为原始图像，右侧为改造后的图像。改造后，新车型车身mask不会被Diffusion修复回原车型，如图中红色车辆和白色车辆的车身轮廓在右侧图像中保持不变，与左侧图像有明显差异。该图片与上下文紧密相关，直观呈现了Difix-ref模型改造完成后的效果，验证了其改造成果。](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZWY2MzczYjdmNmE5NzgyOWFjM2Y5YzM5ZWIxYWM1ZTRfZDg2OWIyMGQwY2YyN2QyMDNkNTg2MmVkYjVjOGE2NjBfSUQ6NzY0NjM0MTI0Njk4MjcwNDA1OV8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM)
</column>
<column width-ratio="0.333333">
![图片展示了Difix-ref模型改造后的效果对比。画面中，一辆黑色汽车停在路边，周围有树木和栏杆。上半部分是未改造前的图像，下半部分是改造后的图像。改造后，新车型车身mask不会被Diffusion修复回原车型，车身轮廓更加清晰，与背景的树木、栏杆等元素融合得更好，整体画面更自然。该图片与上下文提到的Difix-ref模型改造完成，新车型车身mask不会被Diffusion修复回原车型的内容相呼应。](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MWVkOWI3Mjc2MWUyZjdkODA2YTkyMjE5MGQxMDJkMWNfNGU4MzM1ODUyZmYxMzNkYjIyMDg2NmVjY2FhODNjMDdfSUQ6NzY0NjM0MTc3NTE4Mjk5MDI2Nl8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM)
</column>
<column width-ratio="0.333333">
![图片展示了Difix-ref模型改造后的效果对比。画面分为 addCriterion图片展示了Difix-ref模型改造后的的对比。图片中包含四张图片，上方两张为原始图片，下方两张为改造后图片。上方两张图片中 addCriterion图片展示了Difix-ref模型改造后的效果对比。画面](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ODNmNjg2YjY5MWJjY2NmYmE3M2VhMDk5ZmI3NDE0MDlfNjMzZTU5MTgzYjQ0ODFiN2RjMGQwYzFmNGJlZTYyYWJfSUQ6NzY0NjM0ODc4MTc3MjU3MzY2OF8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM)
</column>
</grid>

![图片展示了Difix-ref模型改造后的效果对比。画面中呈现了四张图片，均为城市街道场景，包含树木、建筑、车辆等元素。左上角图片为原始图像，右上角图片为Difix-ref模型改造后的图像，左下角图片为Difix模型改造后的图像，右下角图片为Difix-ref模型改造前的图像。改造后，新车型车身mask不会被Diffusion修复回原车型，解决了之前存在的问题，与上下文提到的模型改造完成及效果相关。](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZGM4NDRkMmY4NWMwZTQ2OWQ5OWFlODk0MjQ3OGIyZTVfNTc5YjU4MThhYzBiZTE5YzliMTExZGRkZmIxZGEwMzNfSUQ6NzY0NjM0MjEzODI4NDczOTUzNl8xNzg1NzU2NzgzOjE3ODU3NjAzODNfVjM)