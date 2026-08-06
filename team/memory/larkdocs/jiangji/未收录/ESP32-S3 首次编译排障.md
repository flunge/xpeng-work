<title>ESP32-S3 首次编译排障</title>

# ESP32-S3 首次编译排障记录（2026-06-26）

> 在 macOS（Apple Silicon）上用 ESP-IDF v5.4 从零编译 `firmware/base` 和 `firmware/tag`，  
> 记录所有实际遇到的错误、根本原因与修复方法，供后续复现环境时直接对照。

---

## 一、环境说明

| 项目 | 值 |
|-|-|
| OS | macOS（Apple Silicon / arm64） |
| ESP-IDF | v5.4（浅克隆 `--depth 1`） |
| ESP-IDF 路径 | `hardware/firmware/esp/esp-idf/` |
| 交叉编译器 | `xtensa-esp-elf` GCC 14.2.0（`~/.espressif/tools/`） |
| 目标芯片 | ESP32-S3 |
| Host Python | 3.14.5（系统 python3） |

---

## 二、完整编译命令（纯命令行）

每次打开新终端都要先激活 IDF 环境，然后进工程目录构建。

### 2.1 激活环境

```bash
# 每个新终端窗口都必须执行一次（VS Code 的 ESP-IDF Terminal 已自动激活）
source /你的工程路径/hardware/firmware/esp/esp-idf/export.sh

# 或如果是用官方扩展装的（默认路径）:
source ~/esp/esp-idf/export.sh

# 验收
idf.py --version   # 应输出 ESP-IDF v5.4.x
```

### 2.2 构建 base（基站）

```bash
cd hardware/firmware/base

# 首次：设置目标芯片（会生成 sdkconfig，后续不需要重复）
idf.py set-target esp32s3

# 编译（首次约 5~10 分钟）
idf.py build

# 完整一行（激活 + 编译，适合 CI / 脚本）
source /你的路径/hardware/firmware/esp/esp-idf/export.sh 2>/dev/null && \
  cd hardware/firmware/base && idf.py build
```

### 2.3 构建 tag（车载标签）

```bash
cd hardware/firmware/tag

idf.py set-target esp32s3   # 首次
idf.py build
```

### 2.4 清空重新构建（遇到 CMake 缓存错误时）

```bash
idf.py fullclean    # 删除 build/ 目录
idf.py build        # 重新配置 + 编译
```

### 2.5 烧录（硬件到货后）

```bash
# 查看串口
ls /dev/cu.*

# 烧录 + 串口监视（一键）
idf.py -p /dev/cu.usbserial-XXXX flash monitor

# 退出监视：Ctrl + ]
```

### 2.6 本工程实际验收结果

| 工程 | 固件大小 | 分区 | 剩余空间 |
|-|-|-|-|
| `base.bin` | 877 KB（`0xd7400`） | 最小 app 分区 | 43% free |
| `tag.bin` | 971 KB（`0xf2a70`） | 最小 app 分区（3MB×2 OTA） | 68% free |

---

## 三、遇到的实际错误与修复

### E1 — 子模块缺失（8 个）

**错误信息：**

```
CMake Error: submodule 'components/mbedtls/mbedtls' is not initialized
CMake Error: submodule 'components/esp_wifi/lib' is not initialized
... (共 8 个)
```

**原因：**`esp-idf` 用 `git clone --depth 1` 浅克隆，子模块的 `.git` 历史不完整，  
`git submodule update --init` 失败（`pathspec not matched`）。

**修复：**

```bash
# 大多数子模块可以让 IDF 自己初始化
cd hardware/firmware/esp/esp-idf
git submodule update --init --recursive  # 能下载的先下

# esp_wifi/lib 特殊：必须手动 clone 到正确位置
cd components/esp_wifi
git clone https://github.com/espressif/esp32-wifi-lib.git lib
cd lib
git checkout a29b11bf0fe019ca0ade5459714b0b2426dfe020  # 对应 release/v5.4 精确 commit
```

---

### E2 — `esp_now` 组件不存在（IDF v5.4 合并）

**错误信息：**

```
CMake Error: Component 'esp_now' is not found
```

**原因：** IDF v5.4 把 ESP-NOW 并入了 `esp_wifi`，不再有独立的 `esp_now` 组件；但  
`link/CMakeLists.txt` 和 `base/main/CMakeLists.txt` 的 `REQUIRES` 里仍列着 `esp_now`。

**修复（两处）：**

`firmware/components/link/CMakeLists.txt`：

```cmake
# 改前：REQUIRES esp_wifi esp_now nvs_flash esp_netif esp_event
# 改后：
REQUIRES esp_wifi nvs_flash esp_netif esp_event
```

`firmware/base/main/CMakeLists.txt`：

```cmake
# 改前：REQUIRES link esp_wifi esp_now esp_http_client esp_timer nvs_flash esp_netif esp_event
# 改后：
REQUIRES link esp_wifi esp_http_client esp_timer nvs_flash esp_netif esp_event
```

---

### E3 — GCC 14 + newlib：`cstdlib` 符号冲突

**错误信息：**

```
error: '__gnu_cxx::lldiv_t' has not been declared
In file included from calib_store.hpp:
  #include <cstdlib>
```

**原因：** GCC 14.2.0 的 `<cstdlib>` 尝试从 `__gnu_cxx` 命名空间引入 `lldiv_t` 等符号，  
但 ESP-IDF 自带的 newlib 不提供这些符号，产生冲突。只要 `<cstdlib>` 是在 ESP-IDF  
自己的 C++ 兼容头（`esp_cxx_compat.h`）之前首先被 include，冲突就能规避。

**修复：**

`firmware/components/calib/include/calib_store.hpp` 顶部第一行加：

```cpp
#include <cstdlib>   // 必须最先 include，绕开 GCC14+newlib 符号冲突
#include "imu_calib.hpp"
// ...
```

---

### E4 — `uint32_t` 用 `%u` 格式符报错

**错误信息：**

```
firmware/base/main/app_main.c:65:50: error: format '%u' expects argument of type 'unsigned int',
  but argument ... has type 'uint32_t' {aka 'long unsigned int'} [-Werror=format=]
```

**原因：** 在 ESP32-S3 的 xtensa 工具链中 `uint32_t = long unsigned int`，与 `%u`（期望 `unsigned int`）类型不匹配，`-Werror=format=` 把警告升为错误。

**修复：**

`firmware/base/main/app_main.c`：

```c
// 顶部加
#include <inttypes.h>

// 改格式串
// 改前：ESP_LOGI(TAG, "收 %u 上云 %u", seq, cross_pattern);
// 改后：
ESP_LOGI(TAG, "收 %" PRIu32 " 上云 %" PRIu32, seq, cross_pattern);
```

---

### E5 — `kGravity` 未声明

**错误信息：**

```
firmware/components/calib/imu_calib.cpp:xxx: error: 'kGravity' was not declared in this scope
```

**原因：**`kGravity = 9.80665f` 只在 `eskf.hpp` 里定义，但 `imu_calib.cpp` 没包含  
`eskf.hpp`，只包含了 `imu_calib.hpp`。

**修复：**

`firmware/components/calib/imu_calib.cpp`（在 `#include <cmath>` 之后加）：

```cpp
#include <cmath>
static constexpr float kGravity = 9.80665f;
```

---

### E6 — `estimator` 组件缺少 `init` 依赖

**错误信息：**

```
fatal error: init_static.hpp: No such file or directory
  #include "init_static.hpp"
```

**原因：**`estimator/include/fusion_pipeline.hpp` 包含了 `init_static.hpp`（来自 `init`  
组件），但 `estimator/CMakeLists.txt` 的 `REQUIRES` 没有声明 `init`。

**修复：**

`firmware/components/estimator/CMakeLists.txt`：

```cmake
# 改前：idf_component_register(INCLUDE_DIRS "include")
# 改后：
idf_component_register(INCLUDE_DIRS "include" REQUIRES init)
```

---

### E7 — `ble_calib` 进入 base 构建但 base 没有 BLE

**错误信息：**

```
fatal error: nimble/nimble_port.h: No such file or directory
```

（出现在 base 构建时，因为 base 没有开 BLE，NimBLE 头不存在）

**原因：**`firmware/components/ble_calib` 被 `EXTRA_COMPONENT_DIRS` 自动扫入，  
base 工程不需要 BLE 标定服务。

**修复：**

`firmware/base/CMakeLists.txt`（在 `project()` 之前加）：

```cmake
set(EXCLUDE_COMPONENTS "ble_calib")  # base 不需要 BLE 标定服务
```

---

### E8 — `ble_calib_svc.cpp`：`s_advertising` 未声明

**错误信息：**

```
firmware/components/ble_calib/ble_calib_svc.cpp:xxx: error: 's_advertising' was not declared in this scope
```

**原因：** 代码中直接使用了 `s_advertising` 变量但忘记声明。

**修复：**

`firmware/components/ble_calib/ble_calib_svc.cpp`（与其他 `static` 变量放在一起加）：

```cpp
static uint8_t s_face       = 0;
static uint8_t s_advertising = 0;  // 广播中标志（补加）
```

---

### E9 — NimBLE struct 部分初始化 / 缩进警告升为错误

**错误信息：**

```
error: missing initializer for member 'ble_gatt_chr_def::flags' [-Werror=missing-field-initializers]
error: this 'if' clause does not guard... [-Werror=misleading-indentation]
```

**原因：**`ble_gatt_chr_def` 结构体字段用指定初始化器（`.uuid = ...`），未初始化的  
字段触发 `-Wmissing-field-initializers`。同时 NimBLE 内部宏展开后有缩进问题。

**修复：**

`firmware/components/ble_calib/CMakeLists.txt`：

```cmake
set_source_files_properties(ble_calib_svc.cpp PROPERTIES
    COMPILE_OPTIONS "-std=gnu++17;-Wno-missing-field-initializers;-Wno-misleading-indentation"
)
```

同时调整 `ble_gatt_chr_def` 初始化顺序，`.flags` 放在 `.val_handle` 之前（匹配结构体声明顺序）。见 E13。

---

### E13 — 指定初始化器顺序与声明顺序不符（C++）

**错误信息：**

```
components/ble_calib/ble_calib_svc.cpp:232:9
error: designator order for field 'ble_gatt_chr_def::flags' does not match declaration order in 'ble_gatt_chr_def'
```

**原因：** C++（不同于 C）要求 designated initializer 的书写顺序必须与结构体声明顺序一致。  
NimBLE 的 `ble_gatt_chr_def` 里 `flags` 声明在 `val_handle` 之前，但代码把 `.val_handle` 写在了 `.flags` 前面。  
（E9 的 `-Wno-missing-field-initializers` 只压住"缺字段"告警，**压不住顺序错误**——这是两个独立问题，两步都要做。）

**修复：**`firmware/components/ble_calib/ble_calib_svc.cpp` 第二个特征改为 `.flags` 在前：

```cpp
{ .uuid = &STAT_UUID.u, .access_cb = stat_access,
  .flags = BLE_GATT_CHR_F_NOTIFY, .val_handle = &s_stat_val_handle },
```

---

### E10 — UUID 宏双重嵌套大括号

**错误信息：**

```
error: too many initializers for 'ble_uuid128_t'
```

**原因：**`ble_calib_proto.h` 里 UUID 宏定义带了外层 `{}`：

```c
#define BLE_CALIB_SVC_UUID128  { 0xfb,0x34,...}  // 错误：C++ 里展开成 {{ ... }}
```

在 C++ 里用 `BLE_UUID128_INIT(BLE_CALIB_SVC_UUID128)` 时变成了双重嵌套。

**修复：**

`firmware/components/ble_calib/include/ble_calib_proto.h`（去掉外层大括号）：

```c
#define BLE_CALIB_SVC_UUID128  0xfb,0x34,0x9b,0x5f,0x80,0x00,0x00,0x80,0x00,0x10,0x00,0x00,0x00,0x62,0x61,0x6c
#define BLE_CALIB_CMD_UUID128  0xfb,0x34,0x9b,0x5f,0x80,0x00,0x00,0x80,0x00,0x10,0x00,0x00,0x01,0x62,0x61,0x6c
#define BLE_CALIB_STAT_UUID128 0xfb,0x34,0x9b,0x5f,0x80,0x00,0x00,0x80,0x00,0x10,0x00,0x00,0x02,0x62,0x61,0x6c
```

---

### E11 — `calib_nvs_*` 函数不可见（include 顺序问题）

**错误信息：**

```
error: 'calib_nvs_load' was not declared in this scope
```

**原因：**`ble_calib_svc.cpp` 中 `#include "calib_store.hpp"` 被误放在了文件中间  
（namespace 块内），导致声明对后续代码不可见。

**修复：**

把 `#include "calib_store.hpp"` 移到文件顶部（与其他 includes 放在一起）：

```cpp
#include "ble_calib_codec.hpp"
#include "calib_store.hpp"      // ← 移到这里
// 删掉文件中间那个重复的 include
```

---

### E12 — `BLE_TOKEN_LEN` 在 `app_main.cpp` 中未声明

**错误信息：**

```
firmware/tag/main/app_main.cpp:88:31: error: 'BLE_TOKEN_LEN' was not declared in this scope
  88 | static uint8_t s_owner_token[BLE_TOKEN_LEN] = {0};
```

**原因：**`BLE_TOKEN_LEN` 定义在 `ble_calib_proto.h`，但 `ble_calib_svc.hpp`（被  
`app_main.cpp` 包含的头文件）没有传递地包含 `ble_calib_proto.h`。

**修复：**

`firmware/components/ble_calib/include/ble_calib_svc.hpp`：

```cpp
#include "fusion_pipeline.hpp"
#include "calib_session.hpp"
#include "imu_calib.hpp"
#include "ble_calib_proto.h"    // ← 补加，暴露 BLE_TOKEN_LEN 等常量
```

---

## 四、修改文件汇总

| 文件 | 修改内容 |
|-|-|
| `components/link/CMakeLists.txt` | 删 `esp_now`（已合并入 `esp_wifi`） |
| `base/main/CMakeLists.txt` | 删 `esp_now` |
| `base/CMakeLists.txt` | 加 `EXCLUDE_COMPONENTS "ble_calib"` |
| `base/main/app_main.c` | 加 `<inttypes.h>`，`%u` 改 `PRIu32` |
| `components/calib/include/calib_store.hpp` | 顶部加 `#include <cstdlib>`（GCC14 兼容） |
| `components/calib/imu_calib.cpp` | 补 `kGravity = 9.80665f` 常量定义 |
| `components/estimator/CMakeLists.txt` | 加 `REQUIRES init` |
| `components/ble_calib/CMakeLists.txt` | 加 `-Wno-missing-field-initializers` 等编译选项 |
| `components/ble_calib/ble_calib_svc.cpp` | 补 `s_advertising` 声明；移动 `calib_store.hpp` include；修复 `ble_gatt_chr_def` 字段顺序 |
| `components/ble_calib/include/ble_calib_proto.h` | UUID 宏去掉外层 `{}` |
| `components/ble_calib/include/ble_calib_svc.hpp` | 加 `#include "ble_calib_proto.h"` |

---

## 五、环境特殊处理（浅克隆 esp_wifi/lib）

IDF 以浅克隆方式存储，`esp_wifi/lib` 无法通过 `git submodule update` 下载。

**一次性处理命令（后续换机器需重做）：**

```bash
# 进入 esp_wifi 组件目录
cd hardware/firmware/esp/esp-idf/components/esp_wifi

# 手动 clone wifi 库（branch 对应 IDF v5.4）
git clone https://github.com/espressif/esp32-wifi-lib.git lib

# 切到 IDF v5.4 对应的精确 commit（必须与 IDF 版本匹配，不能用 HEAD）
cd lib
git checkout a29b11bf0fe019ca0ade5459714b0b2426dfe020
```

> **原因说明：**`esp32-wifi-lib` 包含预编译的 `.a` 静态库（`esp32s3/libcore.a`、`libespnow.a` 等），不包含在 IDF 主仓。浅克隆下 `git submodule` 命令无法跟踪到 blob，需手动处理。换 IDF 版本时对应的 commit hash 需重新查。

---

## 六、常见误区

| 误区 | 正确做法 |
|-|-|
| 把 `firmware/` 根目录作为工程打开 | 必须分别打开 `firmware/tag` 和 `firmware/base` |
| 新终端直接 `idf.py build` | 必须先 `source export.sh` 激活环境 |
| 修改完组件后不 fullclean | 大多数情况增量构建即可，但遇到 CMake 缓存错误时 `idf.py fullclean` |
| 给 base 工程开 BLE menuconfig | base 不需要 BLE，开了会拉进 NimBLE 导致编译失败 |
| UUID 宏包外层 `{}` | C++ 中 `BLE_UUID128_INIT(MACRO)` 会变成双重嵌套，宏只写字节列表不包大括号 |