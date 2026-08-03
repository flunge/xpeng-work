# 星际骑遇（泵道计时）项目事实库（低频长条目，从全局热内存下沉）

> 2026-08-03 由 xai 全局 MEMORY 下沉至此：热内存只留指针，进该项目上下文才读本文件。
> 权威源=飞书文档（镜像：`team/memory/larkdocs/jiangji/`，检索用 docs_search / `doc_rag.py`）。
> 本文件是**读后的结构化摘要**，更新走【更新记忆】流程后同步修订。

## 技术主线
- **LF 唤醒 µs 级计时** + **ESKF/VQF 姿态融合**（倾角收敛 1.61°，已达公开 SOTA）+ **轮速杀手锏**（速度精度 0.112 m/s）
- tag 端只发 odom（位姿/速度），**不发原始数据流**，带宽敏感链路由 ESKF 紧耦合消化

## 阶段 1.5 无源计时（当前主力交付）
- **光电边沿锁定时刻（WHEN）** + **MA82 RFID 认人（WHO）**；RFID/RSSI 只负责身份，绝不参与计时
- ESP-NOW 双基站对时，实测精度 ~120 µs

## OTA 方案（tag）
- **BLE 下发 WiFi 凭证 + COS 地址 → 切 WiFi 直拉 COS 固件**；BLE 不承载固件本体
- ESP-IDF 原生 OTA 双分区 + SHA256/签名校验 + 自检失败自动回滚；只刷 app 分区保 NVS 标定数据

## UWB（阶段三定位）
- **DWM3000 + libdeca** 方案，8 锚点 / 40×60m 泵道
- 原生容量 4–5 标签 → 经 **LF 门控 + 低频校正 + 就近 4 锚 + TDMA** 四件套扩容到 **15–25 标签**
- 定位解算在 tag 端：DS-TWR 逐锚标量量测进 ESKF 紧耦合，厘米级 3D 实时定位

## PCB 交付边界
- tag-2.0 / tag-3.0 / base-3.0 **均 placement-only 交付**，布线留给用户 KiCad
- 有 `qc_datasheet_pins.py` 引脚门禁

## 外设参考
- `13-外设参考/银尔达4G DTU`：厂商手册 110 篇，**查询式使用，勿全读**（单次超 50K token 且信息密度低）

## 当前硬件/环境注意
- 本机无 ESP-IDF 工具链，固件未编译
- `tag/main/app_main.cpp` 的 `BASE_MAC`、base 的 `YOUR_WIFI`/`CHANGE-ME-BASE-KEY`/`example.com` 仍是占位，烧录前必须填真实值
- base-passive 计时铁律：光电边沿定 WHEN、RFID/RSSI 只认 WHO；DTU 下行 OTA chunk 保持 2048，勿调大
- pcba tag-2.0 目前是放置态
