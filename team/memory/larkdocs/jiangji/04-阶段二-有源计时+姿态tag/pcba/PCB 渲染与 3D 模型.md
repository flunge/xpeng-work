<title>PCB 渲染与 3D 模型（tag 车载板）</title>

# PCB 渲染与 3D 模型

自研车载 tag PCBA：**30×32mm 4 层板**（F.Cu 信号 / In1 GND 平面 / In2 +3V3 平面 / B.Cu 信号），52 器件双面布局，放置态（布线由后续在 KiCad GUI 完成）。

## 本轮修正（器件放置质量）

- 接口全部改**小型化真实连接器**：电池/轮速用 JST-SH 1.0mm，磁吸用小 SMD 焊盘（不再用大插针）
- **U6/U7 移出 USB-C 反面投影区**（消除双面焊盘冲突）
- **丝印清理**：隐藏 Value 文字、缩小参考标号，不再压焊盘
- **U7(TDFN-14) 补 3D 模型**（DFN-14 同尺寸替代），渲染不再空缺
- 渲染留边距，不再截断板边器件

## 正反面渲染图

（下方依次为 顶面 / 底面 3D 渲染）

## 3D 模型文件

STEP（工业标准，可测量/装配）与 VRML（带颜色预览）见文末附件。

![PCB 顶面（模组+接口+LED，接口已小型化）](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MTFhNzA2NjI5OTY1YTFjZDBlMjg3MDM1M2MxMzc0NmZfZmMzOTA2NDRjMjZiYWNmNTkxMzJjZThjNWIwOTExOWJfSUQ6NzY2MDg0OTcwMjMyMTI2MTgwOF8xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM)

![PCB 底面（U7 已渲染，U6/U7 避开 USB-C 反面）](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NThkOGM2NTdjNDRkYTY3YmU2NmFhZjIxNGQ1ZGY1M2JfY2U5ZjQ5YzQxMDUzMzA3ZjExOTgzZTBiYjE5MmQ3NThfSUQ6NzY2MDg0OTcxMjQ2Mjg3NTg0MV8xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM)

<figure view-type="Card"><source name="pumptrack-pcba.step" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OTA3NGY4M2FiNmIzMTE1MzRhZDFlOTViYWQ4OGNmMGRfYmZlMjQ5OGYxMzkxZGEzMzE4Yjg4ZWU2OTQ1MDJjMzRfSUQ6NzY2MDg0OTcyMTA1NzU5NDU3N18xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM" mime="model/step" size="3605244" token="RIDtb9EXWopaU5xBxw6ceAbQnuc"/></figure>

<figure view-type="Card"><source name="pumptrack-pcba.wrl" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZjVjMjYxNzIzYmNhYzcyOWJiMjE1NWE4ODQ5MjUyOWRfNTI1YWQyMzExMTIwZDNlNmQ1ZTlkYmJkZDRlZDU3OWVfSUQ6NzY2MDg0OTczMzcxMTYyOTU1MV8xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM" mime="model/vrml" size="3751337" token="HUqJbOhTHoK6pRxZk0tcXEhUnrt"/></figure>