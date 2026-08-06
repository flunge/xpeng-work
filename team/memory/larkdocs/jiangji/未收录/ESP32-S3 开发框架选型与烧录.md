<title>ESP32-S3 开发框架选型与烧录</title>

# ESP32-S3 — 开发框架选型 & 烧录

> 回答三个诉求：1) 各类传感器怎么高效接进来；2) 在 VS Code 里开发；3) 烧录测试方便。

## 1. 调研结论（xiaozhi-esp32 / 飞书 wiki）

- **xiaozhi-esp32**（github.com/78/xiaozhi-esp32，27.6k★）是一个**基于 MCP 的 AI 语音聊天机器人**（Wi-Fi/4G + 离线唤醒 + ASR/LLM/TTS + OLED/LCD）。⚠️ **它不是传感/计时项目，不能作为我们计时固件的基座**，但有两点直接可借鉴：

  - **开发环境**：官方推荐 **Cursor 或 VS Code + ESP-IDF 插件（SDK ≥ 5.4）**，Linux 编译更快、驱动问题少。
  - **新手烧录**：提供**免环境的预编译固件**，直接刷即可（不用搭开发环境）。
- xiaozhi "bread-compact-wifi" 的成品合并 .bin 曾放在 `firmware/prebuilt/` 用于体验烧录链路，**现已删除**（第三方 AI 语音 demo，与本项目无关）。需要可到 xiaozhi 官方自取。
- 飞书 wiki（`rcn4qyi58ici.feishu.cn/wiki/…`）**需登录，无法爬取**。xiaozhi 自带的面包板教程在另一篇飞书《小智 AI 聊天机器人百科全书》。

## 2. 框架选型（本项目）

| 维度 | Arduino-ESP32 | **ESP-IDF (FreeRTOS)** | 折中：**PlatformIO(VSCode)** |
|-|-|-|-|
| 上手/接传感器 | ⭐ 库最多，IMU/LF 例程拿来即用（如 `icm42688.ino`） | 需自写/移植驱动 | 两种框架都支持，一个 IDE |
| 实时性/低功耗/中断 | 一般 | ⭐ ISR+任务+队列、esp_timer 微秒、ESP-NOW、低功耗最佳 | 取决于所选框架 |
| 我们的需求(ISR 锁时间戳、ESP-NOW、边缘解算) | 勉强 | ⭐ 最契合（项目规则 G 已定 ESP-IDF） | — |
| VSCode 开发 | PlatformIO/Arduino 插件 | ⭐ ESP-IDF 插件 | ⭐ 原生 |
| 烧录测试 | 一键 | 一键 | ⭐ 一键 Upload+Monitor |

**决策**：

- **桌面快速验证传感器** → **VS Code + PlatformIO（Arduino 框架）**：直接跑 `icm42688.ino` 验 IMU、试 Si3933，库多、最快出结果。
- **正式固件（车载 tag / 基站 base）** → **VS Code + ESP-IDF 插件**（与项目规则 G 一致：FreeRTOS、ISR 只锁时间戳+入队、ESP-NOW、Madgwick/Fusion）。
- PlatformIO 同时支持 Arduino 与 ESP-IDF（含 arduino-as-component），可一个 IDE 平滑过渡。**不要把固件建在 xiaozhi 工程上**，从空白 ESP-IDF 工程起。

## 3. 传感器怎么"高效接进来"（固件分层）

```
app（FreeRTOS 任务）
 ├─ imu_task      读 ICM42688(SPI+INT1) → Madgwick 姿态 → 腾空检测
 ├─ lf_task       Si3933 WAKE 中断锁时间戳(ISR) → 读向量/正文
 ├─ uplink_task   ESP-NOW 发 odom 状态量（不发原始 IMU）
 └─ common/drivers  imu(WHO_AM_I 自适配) / si3933(SPI 寄存器) / espnow
ISR 只做：锁存 esp_timer 微秒时间戳 + 入队；解算/发送都在任务（硬实时）
```

新增传感器 = 加一个 driver + 一个 task + 往 odom 结构体加字段，互不阻塞。

## 4. 烧录测试

### 4.1 烧我们自己的固件（ESP-IDF / PlatformIO）

- USB 连 ESP32-S3-DevKitC-1 → VSCode 里点 **Build → Flash → Monitor**（或 `idf.py flash monitor` / PlatformIO `Upload`+`Monitor`）。
- 串口 115200 看 log；崩溃有 backtrace。

### 4.2 （可选）烧第三方预编译 bin 体验烧录链路

- 工具：`esptool.py`，或网页版 **ESP Web Flasher**（Chrome，免安装）；merged bin 一般烧到 0x0。
- 注：早期仓库里放过一个 xiaozhi 面包板成品 bin 仅用于"验证板子/烧录链路"，**已删除**（与本项目业务无关，纯占空间）。要体验可自行到 xiaozhi 官方下载；正式开发直接用我们自己的 ESP-IDF 工程即可。

## 5. 安全提示

基站固件若开放 Wi-Fi/网络接口上云，务必加鉴权（设备密钥/TLS），不要裸开未认证端口。