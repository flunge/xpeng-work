<title>Mac 环境配置指南</title>

# Mac 环境配置指南（VS Code + ESP-IDF）— 备用系统

> ⭐ **本项目主调试系统是 Windows**：完整流程（装环境+编译+烧录）见 **`Windows-setup-and-flashing.md`**。  
> 本 Mac 文档为**备用**（流程一致，仅路径/驱动不同）。  
> 在 **macOS** 上从零把 `firmware/tag` 和 `firmware/base` 两个工程**编译跑通**的完整步骤。  
> 编译**全程不需要硬件**；只有「烧录/串口监视」才需插板子（最后两章）。

---

## 0. 一句话路线

装 VS Code「Espressif IDF」扩展 → 用它一键装 ESP-IDF v5.4 工具链 → 分别打开 tag/base 文件夹 → 选 esp32s3 → 点 Build。**不需要 Arduino、不需要 PlatformIO。**

---

## 1. 前置检查（Mac 自带，基本都有）

打开「终端」(Terminal)，确认：

```bash
sw_vers                 # macOS 版本（11 Big Sur 以上都行）
uname -m                # arm64 = Apple Silicon(M系列)；x86_64 = Intel
git --version           # 没有会弹窗让你装 Xcode Command Line Tools，点装即可
python3 --version       # 3.8+，自带
```

> **Apple Silicon (M1/M2/M3/M4)**：ESP-IDF v5.4 原生支持，无需 Rosetta。  
> 若提示要 Xcode 命令行工具：`xcode-select --install`，弹窗点「安装」。

---

## 2. 装 VS Code + Espressif IDF 扩展

1. 没装 VS Code 的话：https://code.visualstudio.com → 下载 macOS 版 → 拖进「应用程序」。
2. VS Code 左侧扩展栏（`⌘⇧X`）搜 **`Espressif IDF`**（作者 **Espressif Systems**，认准官方）→ Install。

---

## 3. 用扩展装 ESP-IDF 工具链（核心，约 10\~20 分钟）

1. 命令面板 **`⌘⇧P`** → 输入并选 **`ESP-IDF: Configure ESP-IDF Extension`**。
2. 选 **EXPRESS**（最省心，自动下载并配置）。
3. **Select ESP-IDF version** → 选 **`v5.4 (release version)`**。
4. 下面几个路径**保持默认**即可：

   - IDF 安装目录：`~/esp/esp-idf`
   - 工具链/Python 目录：`~/.espressif`
5. 点 **Install** → 等待下载（约 1.5GB：工具链 + Python 虚拟环境 + 子模块）。

   - 进度在「ESP-IDF Setup」面板里实时显示。中途别关窗口。
6. 出现 **「All settings have been configured」/绿色对勾** = 成功。

> 网络慢/卡住：EXPRESS 默认走 GitHub。可在该界面把下载源切到 **Espressif 国内镜像**（dl.espressif.com/github_assets）重试。

### 验收

命令面板 → `ESP-IDF: Open ESP-IDF Terminal`（会自动激活环境）→ 终端里：

```bash
idf.py --version        # 期望: ESP-IDF v5.4.x
```

---

## 4. 打开工程（tag / base 各开一个窗口）⚠️ 关键

tag 和 base 是**两个独立的 IDF 工程**，**必须各自单独 Open Folder**：

1. `File → Open Folder…` → 选到 **`你的路径/firmware/base`**（注意：选 base **这一层**，里面要能看到 `CMakeLists.txt`）。
2. 再开一个新窗口（`⌘⇧N`）→ `Open Folder…` → 选 **`firmware/tag`**。

> 🚫 **不要直接打开 `firmware/` 根目录**——那里没有顶层 `CMakeLists.txt`，扩展会报「不是 IDF 工程」。

---

## 5. 选目标芯片 = esp32s3

每个工程窗口都要设一次：

- 底部状态栏点 **⚙️ 图标**（或命令面板 `ESP-IDF: Set Espressif Device Target`）→ 选 **`esp32s3`** → 再选 **`ESP32-S3 chip (via builtin USB-JTAG)`**。

底栏会显示 `esp32s3`。

---

## 6. 编译（不插硬件就能做）

工程窗口里，点底部状态栏 **🔨（Build）图标**，或命令面板 `ESP-IDF: Build your project`。

- 首次 build 会自动套用本工程预置的 `sdkconfig.defaults` 生成 `sdkconfig`（tag 已含 BLE/共存/分区，base 已含 HTTPS/大分区，**无需手动 menuconfig**）。
- 成功标志：终端末尾出现

  ```
  Project build complete. To flash, run: idf.py flash
  ...
  tag.bin binary size 0x...  (xx% of partition)
  ```

### 推荐顺序

1. 先编 **base**（纯 C，依赖少，最快验证环境 OK）。
2. 再编 **tag**（C++17 + BLE + 多传感器，体积大）。

两个都出 `Project build complete` = **「编译落地」目标达成，此时仍未用到任何硬件**。

> 命令行等价（在 `ESP-IDF Terminal` 里）：`idf.py set-target esp32s3`（仅首次）→ `idf.py build`。

---

## 7. 编译报错怎么办

把终端里**第一条**`error:` 贴给灵犀逐条解。常见对照见 `build-preflight-phase1.md` 的「预期问题 & 解法」表（T1~~T10 / B1~~B4）。多数已在 sdkconfig/CMakeLists 预置，正常应能直接编过。

---

## 8.（硬件到货后）烧录 & 串口监视

1. USB-C 线把 ESP32-S3-DevKitC-1 接 Mac（用板上标 **USB** 的口，不是 UART 口也行，S3 有内置 USB-JTAG）。
2. 确认串口：

   ```bash
   ls /dev/cu.*
   # 期望看到 /dev/cu.usbmodem* 或 /dev/cu.usbserial-*
   ```

   - 看不到口：多半缺驱动。板子用 CP2102 → 装 **CP210x VCP Driver**；用 CH340 → 装 **CH34x** 驱动（官网下载，装后重启）。
3. 底栏 **🔌 图标** 选刚才的 `/dev/cu.*` 端口。
4. 烧录：底栏 **⚡（Flash）**，首次烧录方式选 **UART**。
5. 看日志：底栏 **🖥（Monitor）**；退出按 **`Ctrl + ]`**。
6. 一步到位：底栏 **🔥（Build + Flash + Monitor）**。

### 期望串口输出（tag）

```
车载 tag 启动(ESKF), TAG_ID=1
IMU WHO_AM_I=0x44 ...         ← 0x44=ICM-42686 / 0x47=ICM-42688
保持静止以完成 ESKF 初始化...
INIT→RUNNING                  ← 静止约 200ms 后
```

---

## 9. 常见坑速查

| 现象 | 原因 / 解法 |
|-|-|
| 扩展装到一半卡死 | 网络问题；重跑 Configure，下载源切 Espressif 国内镜像 |
| 「不是 IDF 工程」 | 打开了 `firmware/` 根目录；应分别开 `firmware/tag`、`firmware/base` |
| build 找不到 components | 顶层 `CMakeLists.txt` 的 `set(EXTRA_COMPONENT_DIRS ../components)` 须在 `project()` 之前（本工程已正确） |
| `/dev/cu.*` 看不到板子 | 装 CP210x / CH34x 驱动；换条**数据**USB-C 线（有些线只供电） |
| Flash 报 permission denied | 该端口被别的程序占用（关掉其他串口工具/Arduino IDE）；或拔插重选端口 |
| 同时装了 PlatformIO 还冲突 | 别两个扩展一起用；本工程用官方「Espressif IDF」即可 |

---

## 10. 换到 Windows 时

工程文件不用改，重复 §2\~§6（扩展、版本、Open Folder、Build 都一样）。差异仅：

- 安装路径在 `%USERPROFILE%\esp\`、`%USERPROFILE%\.espressif\`。
- 串口是 `COMx`（设备管理器查），不是 `/dev/cu.*`。
- 命令行用 `install.bat` / `export.bat`，建议在开始菜单的「ESP-IDF 5.4 PowerShell」里跑。