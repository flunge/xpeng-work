<title>外壳设计（tag 防水外壳 3D · cable-tie 绑扎）</title>

# 外壳设计 · tag 防水外壳（cable-tie 直绑）

3D 打印两件式外壳（星际骑遇），**35.2 × 37.2 × \~25mm**。参考实拍：设备用两根扎带直接绑在前叉管上。

## 安装：cable-tie 直绑（满足三要求）

- **防水**：底部 plinth 里两条**闭合横向扎带通道**（通道顶 5.5mm < 电池腔底 7.5mm，永不破入电池/PCB 腔），无开口防水不受影响
- **稳固不裂**：通道下 2.5mm 实体承张力 + 圆角过渡；底面**弧形 saddle** 贴合前叉圆管（防滚、分散夹紧力）
- **易制造**：两件式、免支撑（水平横孔 FDM 直打）；开模简单

## 其余防水（延续）

磁吸充电（盲孔+薄膜）、LED 导光（薄壁透光）、干簧管开关（磁控零开孔）、USB 调试可堵槽。

## 容纳

30×32mm PCB（4×M2 立柱）+ **802530 电池（600mAh，25×30×8mm，二选一选定）**。

## 多视角渲染

（依次：装配透视 / 侧视 / 顶盖斜视 / 底壳内部 / 顶盖 / 底面-看扎带通道+saddle）

## 3D 模型文件

底壳 / 顶盖 / 装配预览 STL 见文末附件（单位 mm，可直接切片）。

![装配透视](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZWRhZWRiOWI5MzM4YWM5NTViYTU2ZTdlOWQ3YjY3NjVfNGEwMjMyYzhlMTE3ODA0ZDRkOWQ1NWNiOTgzZTBmZWFfSUQ6NzY2MDg1NTI4NjYwOTA3MTI4M18xNzg1NzQwMjkyOjE3ODU3NDM4OTJfVjM)

![侧视(咬合)](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MDYyNGY2NzIyMWIxNDQzODA5N2YzNDEyMzJhMDJiMjFfYjIzMTZkMTZlMjljYjhmY2RjYmVjNTE5YjVjNmY1ZDdfSUQ6NzY2MDg1NTI5MjUzMDcwNzYzNl8xNzg1NzQwMjkyOjE3ODU3NDM4OTJfVjM)

![顶盖斜视(logo+孔位)](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZGY4MmI3NTQxMjBmN2ViNWRkNDk2NTM0Mjg0MGI1ZTNfMmMzZDg5MmQ1N2Y0MjU4MDUzYzIwNmQ2Yjg0OGQ1YzlfSUQ6NzY2MDg1NTMwMDIxOTkxNTUwNF8xNzg1NzQwMjkyOjE3ODU3NDM4OTJfVjM)

![底壳内部(立柱+电池仓)](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZmY5Njk5ZTc2MDZmZGIxZTQyM2Y3ZGQyZGFjNDM1NzNfYTRmNDVlMmQ2ZjRmNTk4NTljZDhjOTAyOTg4MjVlNmRfSUQ6NzY2MDg1NTMwODgzMDYwODYwNF8xNzg1NzQwMjkyOjE3ODU3NDM4OTJfVjM)

![顶盖](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YWYxZTQwMTRkNmE2ZDMzYTIxMzcyOWQ5MzUxZjQzYmFfYjAyNjgwYTUzMWI4YWNiNTUyZGRjYmQzMWZjMGNlNTZfSUQ6NzY2MDg1NTMxNTU5MTkyNDk4MV8xNzg1NzQwMjkyOjE3ODU3NDM4OTJfVjM)

![底面(两条扎带通道+弧形saddle)](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YTUxMDk2MDBkYzhhNDAxZTQ0NzFlNzYxOWQ0MGUwMzNfNzZhMTgxODI2MmEzMThjOGNiODc1MzM2ODBhYjdkNjJfSUQ6NzY2MDg1NTMyNTE4ODI5NTkyN18xNzg1NzQwMjkyOjE3ODU3NDM4OTJfVjM)

<figure view-type="Card"><source name="tag_case_bottom.stl" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MGZkOWEwYWNkY2NlZmUzYjM1ODYzYTNjNDY3OTk1YWFfYWY4ZTMxZTE4MjA0NzM5NWQyMDc0YjdjNzJmNThjMDZfSUQ6NzY2MDg1NTMzMTM3OTM2NzA5MF8xNzg1NzQwMjkyOjE3ODU3NDM4OTJfVjM" mime="model/stl" size="630274" token="WQsQb0vsAo7dnbx6A6pczJAzn4d"/></figure>

<figure view-type="Card"><source name="tag_case_top.stl" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MTc0MDkzMWFhMDNmZDkwN2Q4ZDRlYWY2YmZlODk1NmRfOTkxODBiM2U2NzA0ZThjZGExMzJmYWZhNzM3MWE2OTVfSUQ6NzY2MDg1NTM0MTIxODg5MzAzOV8xNzg1NzQwMjkyOjE3ODU3NDM4OTJfVjM" mime="model/stl" size="606038" token="BaFybc2ksoDRspx9RLrc1xCZnqg"/></figure>

<figure view-type="Card"><source name="tag_case_preview.stl" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OWY0MzI3OWIzOGM2NDAwM2IxYzMwMmVhMTAzZDYxNjRfZTZhZDFlYzRmYTNhMWZlOWI5ZGY3MzA5NDA1YjQ3YzBfSUQ6NzY2MDg1NTM0NjE3Mjc5MjAxOV8xNzg1NzQwMjkyOjE3ODU3NDM4OTJfVjM" mime="model/stl" size="1205030" token="Vrr5bcUo7oElYPxW3jscGwxrnQh"/></figure>