<title>ESP-NOW 链路协议 · Tag → Base</title>

<callout emoji="📌">
本文是 ESP-NOW 上行包的**唯一权威定义**。改动须同步 base 端并升版本（见 firmware/ARCHITECTURE.md 契约清单）。BLE 协议见同目录《BLE 蓝牙对接协议（App↔设备）》。
</callout>

# 一、odom_packet_t（32B，packed）

定义于 `firmware/components/link/include/espnow_link.h`，tag 类型为 `espnow_link_send()`，base 端经 `on_espnow_recv()` 解码。

| 字段 | 类型 | 含义 |
|-|-|-|
| seq | u32 | 序列号，base 侧用来去重 / 判断丢包 |
| tag_id | u16 | tag / 车辆 ID |
| flags | u16 | bit0=过线事件，bit1=腾空完成 |
| t_us | u64 | 事件 μs 时间戳（**tag 端本地锁存**，base 仅透传） |
| cross_pattern | u32 | 过线点位向量（起点/终点） |
| roll / pitch / yaw_cdeg | s16 ×3 | 姿态，单位 0.01° |
| air_ms | u16 | 最近腾空时长 ms |
| height_mm | u16 | 最近跳跃高度 mm |

# 二、base 侧规则

- 长度不匹配 `sizeof(odom_packet_t) = 32B` 时直接丢包。
- **去重 / 乱序丢包**: `(int32)(seq - last_seq) <= 0` 丢弃；序号缺口记 `gap_lost`；32 位回绕安全。
- 收到 50 次包报一次链路统计（收 / 去重 / 丢包率）。

# 三、改动契约

- 改动须同步 base（espnow_link.h 双侧共用）、移动端若要消费也要配套。
- 版本号走 `fw_version.h`；多车型通讯之前先升版本。
- 更宏观的固件总图见 12-软件设计，UWB 版本与阶段三 PCB 见 05。