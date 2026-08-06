<title>Windows 开发与烧录指南</title>

# Windows 开发与烧录指南（主文档）— ESP32-S3-DevKitC-1 / 芯路城 N16R8

> ⭐ **Windows 是本项目的主调试系统。** 本文是 Windows 上**从零到烧录成功**的主文档：  
> 装环境 → 装驱动 → 编译 → 烧录 → 看串口，含这块板的硬件细节（双 USB 口、CH340、一键下载）。  
> Mac 用户见 `Mac-environment-setup.md`（备用）；编译报错见 `ESP32-first-build-troubleshooting.md`。

---

## 0. 这块板的硬件要点（先认板）

| 项 | 说明 |
|-|-|
| 主控 | ESP32-S3-WROOM-1-**N16R8**（16MB Flash + 8MB OPI PSRAM，板载天线） |
| 串口芯片 | **CH340**（USB 转 UART），板载 **一键下载电路**（无需手动按 BOOT/RST 进下载模式） |
| USB 口 | ⚠️ 板上有**两个 USB（Type-C）口**：①**CH340/UART 口**（烧录走这个）②ESP32-S3 **原生 USB** 口。烧录优先用 **CH340 口** |
| 供电 | 你用 **MB-102 面包板电源**供模块；开发板可单独 USB 供电（调试期最简） |
| 下载模式 | 板载 ISP 一键下载，**正常不用手动操作**；万一失败再手动（见 §6） |

> 板子原理图：`design/ESP32-S3-devboard/schematic/`；厂商资料页：芯路城 id/61。

---

## 1. 装 CH340 驱动（Windows 必做，否则认不到串口）

1. 厂商提供 `CH340驱动.zip`（资料页内）；或官网 WCH 下载 `CH341SER.EXE`。
2. 运行 → 点「安装」→ 完成。
3. **插上开发板的 CH340 USB 口** → 打开**设备管理器 → 端口(COM 和 LPT)** → 应看到  
**`USB-SERIAL CH340 (COMx)`**（x 是数字，记住这个 COM 号）。

   - 看不到 → 驱动没装好 / 换条**数据线**（有些线只供电不传数据）/ 换 USB 口。

---

## 2. 装开发环境（VS Code + ESP-IDF，Windows）

1. 装 **VS Code**（https://code.visualstudio.com，Windows 版）。
2. VS Code 扩展栏（`Ctrl+Shift+X`）搜 **「Espressif IDF」**（作者 Espressif Systems）→ Install。
3. 命令面板 **`Ctrl+Shift+P`** → **`ESP-IDF: Configure ESP-IDF Extension`** → 选 **EXPRESS** → 版本选 **v5.4** → 路径保持默认（装到 `%USERPROFILE%\esp\` + `%USERPROFILE%\.espressif\`）→ Install。
4. 下载约 1.5GB，等「All settings have been configured」。
5. ⚠️ Windows 特有：

   - 安装路径**别带中文/空格**（默认 `%USERPROFILE%` 一般 OK，若用户名是中文则换装到 `C:\esp\`）。
   - 若公司电脑有杀软/防火墙拦下载，切到 Espressif 国内镜像重试。
   - 验收：命令面板 `ESP-IDF: Open ESP-IDF Terminal` → 终端跑 `idf.py --version` → 显示 v5.4.x。

---

## 3. 打开工程 + 选芯片/串口

1. VS Code → `File → Open Folder` → 选 **`firmware/tag`**（车载标签）或 **`firmware/base`**（基站）。  
⚠️ 各自独立工程，分别打开，**不要开 `firmware/` 根目录**。
2. 底栏 **⚙️** 选目标芯片 → **`esp32s3`**。
3. 底栏 **🔌** 选串口 → 选 **§1 记下的 `COMx`（CH340 那个）**。

---

## 4. 烧录（GUI 一键，推荐）

底栏从左到右的图标：🔌端口 ⚙️芯片 🔨build ⚡flash 🖥monitor 🔥(build+flash+monitor)。

**最简：点 🔥（Build + Flash + Monitor 一键）**

- 首次会先编译（几分钟），然后自动烧录，再打开串口监视。
- 烧录方式问选 **UART**（走 CH340）。

**或分步：**

1. 🔨 Build（编译，首次 \~几分钟）
2. ⚡ Flash（烧录，\~10-30 秒）
3. 🖥 Monitor（看串口输出）

**命令行等价**（命令面板 `ESP-IDF: Open ESP-IDF Terminal` 里）：

```powershell
idf.py set-target esp32s3      # 仅首次
idf.py -p COMx build flash monitor
```

（把 `COMx` 换成你的实际 COM 号）

---

## 5. 烧录成功的标志（串口 Monitor 输出）

烧录完会自动重启运行，Monitor 里应看到（**tag 工程**）：

```
tag boot (ESKF), TAG_ID=1
loaded IMU calibration from NVS   (或 no NVS calibration record...)
IMU WHO_AM_I=0x47    ← 0x47=ICM42688 / 0x44=ICM42686（接了 IMU 才有）
保持静止... INIT→RUNNING
```

**base 工程**：

```
base station boot
本机 MAC=xx:xx:... → 填到 tag 的 BASE_MAC
```

> 退出 Monitor：**`Ctrl + ]`**。

---

## 6. 烧录失败排查（Windows 常见）

| 现象 | 原因 / 解法 |
|-|-|
| 设备管理器无 COM 口 | CH340 驱动没装 / 数据线只供电 / 插了原生 USB 口而非 CH340 口 → 装驱动、换线、换口 |
| Flash 报 `Failed to connect` / `No serial data` | 选错 COM 口；或一键下载没生效 → **手动进下载模式**：按住 **BOOT** 不放 → 按一下 **RST/EN** → 松开 BOOT → 重试 Flash |
| `Permission denied` / 端口被占用 | 关掉别的串口工具（Arduino IDE / 串口助手 / 另一个 Monitor）→ 重选端口 |
| 烧录中途断开 | 换**短的优质数据线**；避开 USB Hub 直插电脑 |
| 烧进去但串口乱码 | Monitor 波特率应为 **115200**（默认）；或固件 LOG 波特率不符 |
| 编译报错（还没到烧录） | 见 `ESP32-first-build-troubleshooting.md`（E1\~E13） |

---

## 7. 完整流程速查

```
装 CH340 驱动 → 设备管理器确认 COMx
   ↓
VS Code 打开 firmware/tag（或 base）
   ↓
⚙️ esp32s3   🔌 选 COMx
   ↓
🔥 一键 Build+Flash+Monitor
   ↓
串口看到 "tag boot (ESKF)" + WHO_AM_I → 成功
```

> ⚠️ 供电注意：调试烧录期，开发板可单独用 USB（CH340 口）供电即可；模块由 MB-102 面包板电源供（见 `wiring-modules-to-esp32.md`）。**别让 USB 和 MB-102 同时硬怼开发板的 5V**（二选一，避免倒灌）。