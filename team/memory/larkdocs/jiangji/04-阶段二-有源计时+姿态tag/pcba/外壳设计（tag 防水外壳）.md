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

![装配透视](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MzliYTYzYzJiMjllMDdmYTVmZjY4MThkNGQxYmNhMDZfODA0ZjVmNTIzZjY3NTgxYzdlMjQ0ZjBlNTMyMmE3ZjdfSUQ6NzY2MDg1NTI4NjYwOTA3MTI4M18xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM)

![侧视(咬合)](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=OGIzNTI1YzZmY2JlMGEzMWQyNmU3YzcxNWIzNGJkNmJfNWRmZDJkNDNiNDVmMDkzOGEyZjA5MWExZDM1ZDJkN2NfSUQ6NzY2MDg1NTI5MjUzMDcwNzYzNl8xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM)

![顶盖斜视(logo+孔位)](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YmIwMzI0MTQ4OWVhNGJlMWJkNzEwZTM5MTdmYmEyZDZfOWVkNTU2YjZiZDdiYzkzOTY0MjI4NTlhNjY2ZmY0NjVfSUQ6NzY2MDg1NTMwMDIxOTkxNTUwNF8xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM)

![底壳内部(立柱+电池仓)](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MTY3Yzg4NDkwMTc3YjFlZGI3ZGI1YTJhZjMxMmNmYjFfZGRhZWM5MTMyM2YyNDMzZjM5YTMzYWM5ZTE0MTQ1OTNfSUQ6NzY2MDg1NTMwODgzMDYwODYwNF8xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM)

![顶盖](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NmI0NzU5YTY1ODRkNTI4MTRjMTMxMGZiYjk3ODczZjlfYmUxYWQ3M2Q1YmZiY2YyNzQwNTg0ZmY0ZmJlZWUxMDRfSUQ6NzY2MDg1NTMxNTU5MTkyNDk4MV8xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM)

![底面(两条扎带通道+弧形saddle)](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MzVmMjhhYjY1MDk0YzY3M2VkNDVhY2RlYzdiNTA0MDFfNTA4ZDMzMmQxOTYzNGEyZjVkOGJhYWY1OTc0Mzg2MjBfSUQ6NzY2MDg1NTMyNTE4ODI5NTkyN18xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM)

<figure view-type="Card"><source name="tag_case_bottom.stl" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MTc5NDM2MjY4MmFmMjEzMGRjZGYxZjM0NGJiZDhjY2ZfMmE0NGYyMTE5NDI1Y2Y3NTkyMTRkYzY0ZGExZDgxMmNfSUQ6NzY2MDg1NTMzMTM3OTM2NzA5MF8xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM" mime="model/stl" size="630274" token="WQsQb0vsAo7dnbx6A6pczJAzn4d"/></figure>

<figure view-type="Card"><source name="tag_case_top.stl" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NTZmYWZkOTRhZDE3ZDE5MDQ1NzYwY2JlN2VjMmFjOGRfZWM3M2YxYjkwNDA4MzdmNDY0ZWVlYWNlYTE0ZGIzYmFfSUQ6NzY2MDg1NTM0MTIxODg5MzAzOV8xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM" mime="model/stl" size="606038" token="BaFybc2ksoDRspx9RLrc1xCZnqg"/></figure>

<figure view-type="Card"><source name="tag_case_preview.stl" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=NTNiNDlkY2MyYWQzNmYzODQ5YTYyZGJlYWRiNzcwNWVfZWY5YzZmYThmZmZmNzRlNmNlZmU4ZDY4NWVjN2FjNWNfSUQ6NzY2MDg1NTM0NjE3Mjc5MjAxOV8xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM" mime="model/stl" size="1205030" token="Vrr5bcUo7oElYPxW3jscGwxrnQh"/></figure>