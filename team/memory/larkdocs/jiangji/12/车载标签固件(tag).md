<title>车载标签固件设计（tag）</title>

# 车载标签固件设计（tag）

<callout emoji="💡">
ESP32-S3 车载标签固件。职责：IMU 1kHz 采集 → VQF+ESKF 融合出 odom；LF 唤醒中断锁过线微秒时间戳；ESP-NOW 上行；BLE 标定/遥测。**代码目录 tag/**。
</callout>

## 一、任务编排（FreeRTOS）

| 任务 | 核/优先级 | 频率 | 职责 |
|-|-|-|-|
| imu_task | 核1 / 6 | \~500Hz（实测 dt） | 读 IMU → 融合管线（标定→初始化→ESKF/VQF）→ 更新 odom |
| lf_task | 核1 / 7（最高） | 事件（唤醒中断） | 过线：中断锁微秒戳 → 读 RSSI + 标记过线 + 锚点重置 |
| baro_task | 核1 / 5 | \~25Hz | 气压高度 → ESKF 高度约束（大 R，仅压趋势） |
| uplink_task | 核0 / 5 | 事件+1Hz 心跳 | 组 odom 包 → ESP-NOW 发基站 |
| console/ble_tick | 核0 / 3-4 | 低频 | 串口标定命令 / BLE 服务 tick |
| dualimu_task | 核1 / 5 | 100Hz（调试） | 第二 IMU 对比采集（仅调试，探测到才启） |

## 二、核心流程伪代码

### 1 · LF 唤醒中断（计时核心，只锁戳+入队）

```c
// ISR：硬实时，只做两件事
void IRAM_ATTR on_lf_wake_isr():
    t_us = esp_timer_get_time()          // 微秒时间戳 = 权威过线时刻
    xQueueSendFromISR(lf_queue, {t_us})  // 入队，不做任何解算
// 铁律：时间戳在此锁存，发送异步；不用基站收包时刻
```

### 2 · IMU 融合主循环

```c
loop imu_task:
    s = imu_read()                       // 加计/陀螺/温度
    dt = now_us - prev_us; prev_us = now_us   // 用实测 dt（非固定 1ms）
    clamp(dt, 1e-4, 0.1)                  // 拒绝首帧/丢帧
    odom = pipeline.feed(s.acc, s.gyr, s.temp, dt)
    //  pipeline 内部：calib 校正 → (未初始化?静止初始化) → VQF 姿态 → ESKF 速度/位置
    telemetry.update(odom)
    if logger_active and (frame % 10 == 0):  // 100Hz 抽稀记录
        logger_put_imu(t_us, acc, gyr)
```

### 3 · 过线事件处理（lf_task）

```c
loop lf_task:
    evt = xQueueReceive(lf_queue)         // 收 ISR 锁的微秒戳
    rssi = si3933_read_rssi()
    base_id = decode_exciter_id()         // 起点/终点区分
    pipeline.anchor_reset(base_id)        // 每圈过线锚点重置，界定漂移
    mark_crossing(evt.t_us, base_id, rssi)
    notify(uplink_task)                   // 触发上行
```

## 三、关键设计点

- **dt 用实测值**：循环非精确 1kHz（约 2ms/500Hz），固定 1ms 会让姿态半速旋转（已修 bug），用两帧时间差夹逼
- **姿态前端 = VQF**：VQF 6 轴出姿态注入 ESKF 名义姿态，ESKF 保留速度/位置/气压/锚点
- **标定**：陀螺静态 + 加计六面 → 落 NVS，开机自动加载
- **飞行记录器**：原始 IMU 100Hz + 气压 + 解算 + LF 触发 → 日志文件，BLE 拉取
- **ISR 只锁时间戳 + 入队**，采集/解算/发送都在任务

## 四、分层与契约

分层：L0 线性代数 → L1 驱动(IMU/LF/气压/链路) → L2 估计(ESKF/标定/初始化/VQF) → L3 服务(BLE/日志/OTA) → L4 编排(主程序)。依赖只能自上而下。

跨边界契约（改动须同步对端+升版本）：BLE GATT 协议(对小程序) · ESP-NOW odom 包(对基站) · 标定 NVS 序列化(对已烧录设备) · OTA 线协议 · 固件版本号。

## 五、相关

算法细节见 [多传感器融合架构](https://fqmtvue07d8.feishu.cn/docx/Cd4DdtFFZolSPZxFNJScy4T6nwh)；协议见 [BLE 对接协议](https://fqmtvue07d8.feishu.cn/docx/FT93djQoKo1V7Ax3o0Fc93nen5c)。

## tag WiFi-OTA 升级方案（BLE 配网 + WiFi 直拉，与 ESP-NOW/IMU 解耦）

> 目标：把 tag 固件升级从 ESP-NOW 通道彻底移出，改走独立的 WiFi 旁路，避免与骑行数据（IMU odom / ESP-NOW 回传）争抢带宽。核心思想：**BLE 只传"钥匙"（WiFi 凭证 + 下载地址），2\~3MB 的固件本体走 tag 自己的 WiFi 直连云拉取（esp_https_ota，几秒完成）**。不推翻决策 17b（4G 主线）——骑行数据仍走 ESP-NOW，OTA 只是旁路。

### 一、为什么这样设计

tag 已具备的基础：**OTA 双分区**（ota_0/ota_1 各 3MB，partitions.csv）、**NimBLE 服务**（components/ble_calib，含 unlock/bind 安全上下文与 admin OTA 推流命令 0x50–0x52）、WiFi+BLE 固件栈。现有 BLE 推流 OTA 把整包 2\~3MB 经 BLE 逐包写，速度只有几 KB/s、要数分钟且占满 BLE。本方案改为 **BLE 下发几十字节凭证 + tag WiFi 直拉**，速度提升到 MB/s 级、且升级期零占用 ESP-NOW/IMU。

| 维度 | 现有 BLE 推流 OTA(0x50-52) | 本方案 WiFi 直拉 |
|-|-|-|
| 固件本体通道 | BLE 逐包推 2\~3MB | tag WiFi 直连云 COS |
| 速度 | 数分钟 | 几\~十几秒 |
| 占用 ESP-NOW/IMU | 否（占 BLE） | 零占用 |
| App 侧传输量 | 整个 bin | 仅 SSID/密码/URL（几十字节） |

### 二、完整流程（五步）

**① 管理端推送新版本（后台发布，非手动烧录）。**管理员在 App 管理端「发布固件」，云端 `tagFirmwares` 集合登记 `{ver, fileID, sha256, size, model, active}` 并标 active；用户端设备页查询到"有新固件 vX"即提示"发现新版本"。

**② 用户 BLE 连接设备。**小程序经现有 ble_calib 服务连接 tag，走 CMD_UNLOCK / 绑定校验（复用现成安全上下文）。

**③ BLE 下发 WiFi 凭证 + 触发（新增 BLE 命令）。**用户输入家中 WiFi 的 SSID/密码，小程序经新命令 `CMD_WIFI_OTA`（拟定 opcode 0x53）分包下发 `{ssid, password, ota_url（云端签发的带鉴权临时下载地址）, sha256}`。凭证在 unlock/bind 的加密上下文内传，不明文。

**④ tag 连 WiFi 直拉 bin（核心提速）。**tag 收命令 → esp_wifi STA 连用户 AP → `esp_https_ota(ota_url)` 从云 COS 直拉 → 写 ota_1 + SHA256 校验。全程 BLE 保持连接只用于报进度（新增 ST 状态：wifi连接中 / 下载 X% / 校验 / 完成 / 失败码）。

**⑤ 校验通过 → 重启进新固件 → 自检确认。**复用现有 A/B 双分区 + 失败自动回滚；成功后 BLE 报"更新完成"，tag 恢复正常。

### 三、三端改动清单

**tag 固件（主体）。**① ble_calib_proto.h 新增 `CMD_WIFI_OTA` opcode + 对应 ST 进度状态码；② ble_calib_svc 收命令、分包重组 SSID/password/url；③ 新模块 `wifi_ota`：esp_wifi STA 连 AP + esp_https_ota 拉取 + SHA 校验 + 重启（复用 ota_1 分区与回滚，及现有 project_name 机型校验防串刷）；④ 进度经 BLE ST 通知回传。

**云端。**① 新集合 `tagFirmwares`（ver/fileID/sha256/size/model/active，仿 baseFirmwares）；② 管理端「发布固件」接口（标 active、面向机型）；③ 用户端「查询新固件」接口（按机型+当前版本比对）；④ 签发 bin 的带鉴权临时下载 URL（COS 可出，tag WiFi 直拉）。

**小程序。**① 用户设备页「发现新版本」提示 + 更新入口；② BLE 配网 UI（输 WiFi SSID/密码 → BLE 下发 → OTA 进度条）；③ 管理端固件发布页（推送而非手动上传烧录）。

### 四、必须正视的难点

- **WiFi 凭证安全**：用户家 WiFi 密码经 BLE 传，必须在 unlock/bind 加密上下文内，禁止明文。
- **WiFi+BLE 射频共存**：ESP32-S3 需开 coexistence；**OTA 配网期 tag 本就空闲**——IMU logger 仅在场地 start 过点触发后才开启，配网升级不在骑行场景，无采集冲突（无需"暂停 IMU"）。
- **URL 可达性**：tag 连用户家 WiFi（公网出口）拉云 COS 的 https URL，需 URL 公网可访问 + 鉴权/时效。
- **机型匹配**：推送区分机型/硬件版本，复用固件头 project_name 校验，防止 base 固件误刷到 tag。
- **真机验证**：WiFi+BLE 共存、esp_https_ota 行为需真机实测，主机孪生只能覆盖协议编解码与状态机。

### 五、与既定决策的关系

不推翻决策 17b（4G 主线）：骑行数据仍走 ESP-NOW；OTA 走 WiFi 旁路正是解决"OTA 抢 IMU/ESP-NOW 带宽"的顾虑。是对决策 17c（tag OTA）的实现细化——从"ESP-NOW 分片"升级为"BLE 配网 + WiFi 直拉"，更快、更解耦。base(base-passive) 的 OTA 另见「基站固件」文档（DTU 原生 / gzip / ESP-NOW relay 三级方案），两者独立。