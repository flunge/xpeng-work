<title>BLE 蓝牙对接协议（App↔设备）</title>

# 车载设备 App 对接文档（BLE）— 用户端 + 管理员端

> **读者**：微信小程序开发同学。**分工**：板端 firmware 由固件侧负责；本文是**固件↔App 的协议契约**。  
> **场景**：儿童在泵道骑行，**家长持手机**。App 通过 **BLE** 与车载 tag（ESP32-S3）交互。  
> **配套固件**：`firmware/components/ble_calib/`。  
> **依据**：`/docs/algorithms/attitude-fusion.md`、`phase1-debug-validation.md`。  
> **协议版本**：`proto_ver = 9`（v5：`CMD_ADM_FS_DELETE`；v6：拉模式下载 `FS_OPEN`/`FS_READ_AT`；v7：`CMD_START_STATIC`(0x04) 静态标定，单姿态一次标 gyro+accel 零偏；v8：`ST_LF_DEBUG`(0x0F)+`CMD_STREAM_LFDEBUG`(0x36) LF 红绿灯+RSSI 调试面板；v9：`ST_LF_DEBUG` 追加 rssi2/rssi3/base_id/src——来自 CSM demo 板 GPIO18 串口的三通道 RSSI + 激励器 ID，App 按 len≥15 读取，旧固件补零兼容）。
> 
> ⚠️ **大文件下载只用拉模式（量产唯一可靠方案）**：手机 `FS_OPEN` 拿到 size，再循环 `FS_READ_AT(offset)` 一块一块要，固件**每个请求只回一个 notify**。这样 NimBLE mbuf 池任意时刻最多 1 个在飞、发完即回收，**与文件大小无关，永不耗尽**（push-stream 的 ST_FS_DATA 会撑爆 mbuf 池 → `os_memblock_get failed`，已弃用于二进制大文件，仅保留给小文本/日志）。  
> 流程：`[0x45]+name → ST_FS_OPEN[ok,u32 size]`；`[0x46]+u32 offset → ST_FS_CHUNK[u32 offset,u8 len,bytes]`，`len=0`=EOF。手机收到一块才请求下一块，天然支持进度条 + 每步超时重试。  
> **速度**：chunk 数据长度 = 协商 ATT MTU−3−6。固件 `ble_att_set_preferred_mtu(247)` + 小程序 `wx.setBLEMTU(247)` 把 MTU 抬高 → 单块从 14B(MTU23) 增到 \~176B+，往返次数降 \~12×（20KB 从 2 分钟→约 10 秒）。MTU 协商失败则自动退回 14B（仍可用，只是慢）。  
> **小程序取文件**：`.bin` 无法 `wx.openDocument` 预览；下载后用 `wx.shareFileMessage` 转发到「文件传输助手」，电脑微信收原始文件。

---

## 0. 数据分两路（先理解，决定一切设计）

| 路 | 通道 | 内容 | 特性 | 给谁 |
|-|-|-|-|-|
| **a) 低频观感流** | **BLE**（手机直连 tag） | 姿态/竖直速度/腾空/打卡，≤10fps | **尽力而为、每包自包含、丢了就丢** | 家长手机实时看、做特效 |
| **b) 全量权威数据** | **ESP-NOW → 基站 → 云 → AI** | 整圈完整遥测、成绩、发力分析 | 可靠、不丢、留存 | 教练端 / 学员端（经云推送） |

**关键判断（必须理解，否则 App 会做错预期）**：

- **骑行时 BLE 可用，但不可靠**。泵道是封闭小场地，家长几米\~几十米内 BLE 勉强够看个实时姿态；但小孩在动、人体遮挡 2.4GHz、车天线朝向变 → **必然有瞬断/丢包**。所以 BLE 流**只做观感**，App 要容忍丢包（每包自带 seq + 完整字段，丢了等下一包，不要做跨包重组）。
- **权威数据永远以云端（b 路）为准**。圈速、最高腾空、发力分析这些"成绩"绝不依赖 BLE 收全，由基站可靠上云后回推。
- App 同一时刻只连一台 tag（GATT 单连接）。

> 一句话：**BLE = 实时但易丢的"现场观感"；云 = 完整可靠的"成绩与分析"。** App 两套数据源都接，各司其职。

---

## 1. 几个硬件能力的明确结论（影响 App 功能设计）

| 你的设想 | 结论 | App 怎么做 |
|-|-|-|
| **NFC 打卡** | ❌ **ESP32-S3 无 NFC**。加 NFC 需外挂 PN532 芯片（不建议） | 打卡用下面三选一 |
| 打卡/签到替代方案 | ✅ ① **125kHz LF 过线门**（起/终点天然就是打卡点，tag 被唤醒即 ST_CHECKIN）；② **BLE 邻近**（连上+RSSI）；③ 小程序**扫二维码**（车上贴码 / 场地码） | LF 门为主（自动、准），二维码为辅（绑定/手动签到） |
| **身份绑定**（买了设备绑自己，别人看不到） | ✅ 固件支持 **owner_token 绑定**：绑定后非机主/非管理员**看不到遥测、不能标定** | 见第 5 节绑定流程 |
| **BLE 看实时位置 / 每圈轨迹** | 🟡 阶段一 **IMU 航位推算 + 每圈过线 reset** → 可画"单圈轨迹形状"，但**估算会漂**；竖直高度由 baro(BMP280) 约束较准。阶段二上 UWB→厘米级真值（包格式不变） | 展示姿态+腾空高度+**单圈轨迹**(标注估算)；收 flags bit3 清上圈重画 |
| **BLE OTA 固件升级** | ✅ 可行但慢（BLE 吞吐低，1\~2MB 要几分钟），**仅管理员近距用**；有基站/AP 时优先 WiFi OTA | 见第 7 节，管理员专属 |
| **管理员看 FS / 日志 / 调试** | ✅ 固件提供 FS 列表/读文件/拉日志命令（管理员级） | 见第 7 节 |

**其他建议补充的能力**（供你考虑，已在协议预留）：

- **设备信息卡**（ST_INFO）：tag_id、固件版本、绑定状态、运行时长——用户/管理员都能先查。
- **健康/漂移提醒**（ST_HEALTH）：标定漂了主动提示家长"建议重新标定"。
- **打卡圈次**（ST_CHECKIN 带 lap）：现场即时显示"第几圈、过起点/终点"。

---

## 2. 权限模型（三级，决定每个功能谁能用）

| 级别 | 如何获得 | 能做什么 |
|-|-|-|
| **LVL_NONE**（默认） | 刚连接 | 读 `ST_INFO`；**若本机已绑定**，只有机主 App 持 owner_token 才会被允许后续操作 |
| **LVL_USER** | 发 `CMD_UNLOCK`(magic "LABI") + 机主校验 | 标定、看姿态流、看遥测流、绑定/解绑、打卡 |
| **LVL_ADMIN** | 发 `CMD_UNLOCK_ADMIN`(16B 管理员主密钥) | USER 全部 + FS/日志/OTA/调试 |

**绑定与可见性规则**（机主隐私）：

- 设备**未绑定**：任何人可连、可绑定（先到先得）、可标定。
- 设备**已绑定**：仅**持有正确 owner_token 的 App**（机主）能 UNLOCK 到 USER 级看数据/标定；  
其他人连上只能看 `ST_INFO`（显示"已被绑定"），**看不到遥测/姿态**。
- **管理员**（持主密钥）可无视绑定，调试任意设备、可强制解绑。

> owner_token 由你的**云端账号体系**下发：用户购买设备→小程序登录→云端生成并下发 16B token，  
> 小程序首次绑定时写给设备（`CMD_BIND`），之后本地安全存储；换手机重新登录从云端取回。

---

## 3. GATT 协议总表（权威：`ble_calib_proto.h`）

### 3.1 UUID（128-bit）

| 角色 | UUID | 属性 |
|-|-|-|
| **Service** | `6c616269-0000-1000-8000-00805f9b34fb` | Primary |
| **CMD**（手机→设备） | `6c616201-0000-1000-8000-00805f9b34fb` | Write / WriteNoResponse |
| **STATUS**（设备→手机） | `6c616202-0000-1000-8000-00805f9b34fb` | Notify |

广播名 `tag-calib-01`（含编号区分多车）。**约束：每包 ≤20B（MTU=23），全部小端。**

### 3.2 CMD 命令（写 CMD 特征，首字节 = opcode）

| op | 名称 | 级别 | payload |
|-|-|-|-|
| `0x00` | UNLOCK | →USER | 4B magic=`0x4C414249`("LABI",小端 `49 42 41 4C`) |
| `0x01` | START_GYRO | USER | u16 帧数(默认1000) |
| `0x02` | START_ACC6 | USER | u16 每面帧数(默认500) |
| `0x04` | START_STATIC | USER | u16 帧数(小程序传2000≈2s)；静态标定(方法A)：单姿态静止，一次标 gyro+accel 零偏 → ST_GYRO_RES + ST_ACC_RES；采集中若动了(陀螺RMS>0.06rad/s)→ ST_ERR(8) 要求重做 |
| `0x03` | FACE_READY | USER | — |
| `0x10` | SAVE | USER | — |
| `0x11` | LOAD | USER | — |
| `0x12` | ZUPT | USER | — |
| `0x20` | STREAM_POSE | USER | 1B on, 1B Hz(默认10) — 静止姿态流 |
| `0x21` | QUERY_HEALTH | USER | — |
| `0x30` | UNLOCK_ADMIN | →ADMIN | 16B 管理员主密钥 |
| `0x31` | BIND | USER/未绑 | 16B owner_token |
| `0x32` | UNBIND | 机主/ADMIN | 16B owner_token(机主自解需匹配；管理员可空) |
| `0x33` | QUERY_INFO | NONE | — |
| `0x34` | STREAM_TELE | USER | 1B on, 1B Hz(≤10) — 骑行遥测流 |
| `0x35` | CHECKIN | USER | — (调试手动打卡；正式走 LF 门) |
| `0x40` | ADM_FS_LIST | ADMIN | — |
| `0x41` | ADM_FS_READ | ADMIN | 路径字符串 |
| `0x42` | ADM_LOG_PULL | ADMIN | — (拉取真实运行日志环形缓冲) |
| `0x43` | ADM_SHELL | ADMIN | ASCII 命令行（help/free/tasks/uptime/info/fs/restart）→ 输出经 ST_FS_DATA 回传 |
| `0x50` | ADM_OTA_BEGIN | ADMIN | u32 总字节, u32 crc32 |
| `0x51` | ADM_OTA_DATA | ADMIN | u16 seq + 数据(≤18B) |
| `0x52` | ADM_OTA_END | ADMIN | — |
| `0xFF` | ABORT | any | — |

### 3.3 STATUS 通知（订阅 STATUS 特征，首字节 = type）

| type | 名称 | 布局 | 说明 |
|-|-|-|-|
| `0x00` | HELLO | `[00, unlocked(1), proto_ver(1)]` | UNLOCK 应答 |
| `0x01` | PROGRESS | `[01, mode, face, done(u16), total(u16), quality(u16)]` | 标定进度 |
| `0x02` | FACE_DONE | `[02, face, next_face]` | 该面采完 |
| `0x03` | GYRO_RES | `[03, f32 bg0[3]]` 13B | 陀螺零偏 |
| `0x04` | ACC_RES | `[04, f32 ba0[3]]` 13B | 加计零偏 |
| `0x05` | ACC_RES2 | `[05, f32 Sa_diag[3]]` 13B | 加计尺度 |
| `0x06` | SAVE_RES | `[06, ok, r]` | 保存结果 |
| `0x07` | LOAD_RES | `[07, ok, r]` | 加载结果 |
| `0x08` | POSE | `[08, i16 r,p,y(0.01°), flags]` 8B | 静止姿态；flags bit0=valid |
| `0x09` | HEALTH | `[09, flags, i16 gyr_drift(0.001rad/s), i16 acc_err(0.01m/s²), i8 temp]` 7B | 漂移检测 |
| `0x0A` | INFO | `[0A, u16 tag_id, u8 fw_major, u8 fw_minor, u8 bound, u32 uptime_s]` | 设备信息 |
| `0x0B` | BIND_RES | `[0B, ok, reason]` | 0ok 1已绑 2token错 3无权 |
| `0x0C` | TELE | 见 3.4 | 骑行遥测(低频,可丢) |
| `0x0D` | CHECKIN | `[0D, u32 t_us_lo, u8 point(起0/终1), u8 lap]` | 打卡(LF门触发也推) |
| `0x0E` | BARO | `[0E, i32 pressure_pa, i16 temp(0.01℃), i16 height(cm,相对开机点,+上), u8 valid]` | 气压计；**随姿态流(STREAM_POSE)一起推**，每个 POSE 后跟一个 BARO |
| `0x40` | ADM_AUTH | `[40, ok]` | 管理员鉴权结果 |
| `0x41` | FS_ENTRY | `[41, u32 size, name…(≤14B)]` | FS 条目；name 空=列举结束 |
| `0x42` | FS_DATA | `[42, u16 seq, bytes…(≤17B)]` | 文件/日志块；seq=0xFFFF=结束 |
| `0x43` | OTA_ACK | `[43, stage, u16 next_seq/result]` | stage:1begin 2data 3end |
| `0x7F` | ERR | `[7F, code]` | 1包格式 2未解锁 3未知命令 4无权限 5忙 6校验失败 |

`mode`:0空闲 1陀螺 2六面。`face`:0\~5=+X/-X/+Y/-Y/+Z/-Z 朝上。  
`HEALTH.flags`:bit0陀螺漂 bit1加计漂 bit2温度远离；`&0x03 != 0` ⇒ 建议重标。

### 3.4 ST_TELE 骑行遥测布局（20B=MTU 上限，每包自包含、可丢）

```
[0C, seq(u16), roll(i16,0.01°), pitch(i16), yaw(i16),
 vz(i16,0.01m/s), height_mm(u16), air_ms(u16), flags(u8),
 px(i16,cm), py(i16,cm)]
flags: bit0=valid bit1=腾空中 bit2=过线刚发生 bit3=本圈位置已reset
```

> **每圈一条轨迹（px,py）**：阶段一用 **IMU 航位推算**（ESKF 名义态积分位置）得水平位置，  
> **每次过线门(LF) reset 归零**（flags bit3），把单圈漂移限制在一圈内——足够画"这一圈的轨迹形状"。  
> ⚠️ 阶段一无 UWB，px/py 是**估算值、单圈内会漂**（直道尚可、长时间累积变形），App 标注"轨迹为估算"。  
> 阶段二上 UWB 后，固件用 `update_uwb_range` 把 px/py 修正为**厘米级真值**，**包格式不变**（向后兼容）。  
> App 收到 bit3=1 即开始画新一圈轨迹（清空上一圈点集）。

---

## 4. 用户端（家长 App）功能与时序

### 4.1 连接 + 设备信息 + 解锁

```
openBluetoothAdapter → startDiscovery(services:[Service UUID])
→ 找到 tag-calib-* → createBLEConnection → 取 CMD/STATUS 特征
→ notifyBLECharacteristicValueChange(STATUS, true)        // 订阅
→ 写 [0x33] QUERY_INFO → 收 ST_INFO（显示 tag_id/固件/绑定状态）
→ 若 bound 且本机是机主：写 UNLOCK（见下）；若未绑定：引导绑定
```

UNLOCK：`[0x00, 0x49,0x42,0x41,0x4C]` → 收 `HELLO(unlocked=1)`。

> magic = `0x4C414249`("LABI")，小端字节序列 `49 42 41 4C`。

### 4.2 实时姿态（静止/慢速观感）

```
写 [0x20, 0x01, 0x0A]  STREAM_POSE on 10Hz → 持续收 POSE
→ roll/pitch/yaw = i16/100 (度)，flags bit0=有效
→ 驱动 3D 模型 / 地平仪。离开页面写 [0x20,0,0] 关闭省电
```

### 4.3 骑行实时观感流（家长看小孩骑行）

```
写 [0x34, 0x01, 0x0A]  STREAM_TELE on 10Hz → 持续收 TELE(可丢)
→ 每包: seq/姿态/vz/height_mm/air_ms/flags（自包含）
→ App 做特效：腾空(flags bit1)放烟花、过线(bit2)弹圈速、倾角驱动赛车倾斜动画…
→ ⚠️ 丢包正常：按 seq 跳变判断，不插值过头；成绩以云端为准
```

> **设计要点**：TELE 是"尽力而为"。App 应在断连/久无包时显示"信号弱"，而非卡死；  
> 真实成绩、完整轨迹从**云端 b 路**拉取展示。

### 4.4 标定（向导式，复用上一版逻辑）

- 静态(方法A,推荐)：`[0x04, u16帧]` → 设备任意姿态静止 → PROGRESS → GYRO_RES + ACC_RES → `[0x10]`SAVE。一次同时标 gyro+accel 零偏(只去重力分量,无需知朝向;不解尺度,尺度用六面)。修掉 |a|≠g 的零偏，缓解速度积分漂移。
- 陀螺：`[0x01, u16帧]` → PROGRESS → GYRO_RES → `[0x10]`SAVE。
- 六面：`[0x02, u16帧]` → 循环(提示朝向→稳定够→`[0x03]`FACE_READY→PROGRESS→FACE_DONE)×6 → ACC_RES/ACC_RES2 → SAVE。
- quality(PROGRESS) 做"稳定度条"，够稳才允许采集。
- 收到 HEALTH `flags&0x03` → 弹"建议重新标定"。

### 4.5 打卡 / 签到

- **自动（推荐）**：tag 经 LF 起/终点门被唤醒 → 设备推 `ST_CHECKIN(point,lap)` → App 即时显示"第 N 圈 过起点/终点"。
- **手动（辅助）**：小程序扫场地二维码 → 调你的云端签到 API（与 BLE 无关）。
- **不要用 NFC**（无硬件）。

### 4.6 身份绑定

```
未绑定设备：用户登录小程序 → 云端发 16B owner_token →
  写 [0x31] + token (BIND) → 收 BIND_RES(ok=1) → 本地+云端记录绑定关系
机主换机：重新登录从云端取回 token → UNLOCK 时设备校验 → 正常使用
解绑：写 [0x32] + token (UNBIND)
```

绑定后他人连接只能看 ST_INFO，无法 UNLOCK 看数据（设备端强制）。

---

## 5. 管理员端（你的后台/调试 App）

> 需先 `CMD_UNLOCK_ADMIN` + 16B 主密钥（出厂烧录进设备 NVS，云端管理员账号持有）。  
> 收 `ST_ADM_AUTH(ok=1)` 后解锁以下能力。

### 5.1 设备清单 / 在线状态

- "当前挂载的设备" = 你的**云端**维护的在线表（基站上报 + BLE 扫描）。
- 单机现场：小程序 BLE 扫描周边所有 `tag-calib-*`，列出 tag_id/RSSI/绑定状态（来自广播 + ST_INFO）。

### 5.2 文件系统 / 日志（调试）

```
写 [0x40] ADM_FS_LIST → 逐条收 ST_FS_ENTRY(size,name)，空 name=结束 → 列出 FS
写 [0x41]+"readme.txt" ADM_FS_READ → 分块收 ST_FS_DATA(seq,bytes)，seq=0xFFFF=结束（SPIFFS 扁平：传裸文件名，不带 '/'）
写 [0x42] ADM_LOG_PULL → 经 ST_FS_DATA 回传真实运行日志：固件 log_ring 组件用 esp_log_set_vprintf 把 ESP_LOGx 旁路进 4KB RAM 环形缓冲（UART 输出不受影响），拉取即得真实 启动/BLE/FS 全过程日志
```

### 5.3 交互式终端 Shell（调试）

```
写 [0x43]+"free"   ADM_SHELL → 经 ST_FS_DATA 回传命令输出文本（seq=0xFFFF=结束）
内置命令：help/free(堆)/tasks(任务数)/uptime/info(芯片+IDF+固件)/fs(SPIFFS用量)/restart(重启)
日志：log(提示)/log start/log stop/log status —— 控制飞行记录器(flightlog.bin)
```

> 输出复用 ST_FS_DATA 文本流，小程序终端按 `_dataSink` 区分「读文件 / 拉日志 / 终端」三类回包。

### 5.4 飞行记录器 Flight Recorder（原始数据日志）

```
log start        → 固件开始把 原始IMU(100Hz,17B/条) + baro(25Hz) + 解算结果(50Hz) 写入 /spiffs/flightlog.bin
log stop <epoch> → 停止 + 归档为 f<8位hex epoch>.bin（epoch=手机墙上时间秒，标签无 RTC，下发命名）；不带 epoch 则只停不改名
log status       → 当前 ON/off + 字节数
删除：写 [0x44 CMD_ADM_FS_DELETE]+"fXXXXXXXX.bin" → 收 ST_FS_DELETED[ok,rc]（专用 op；不走 shell "log rm"，否则 "log rm "+13字符文件名=21B 超 20B 写 MTU → 文件名被截断 .bin→.bi → 删除失败 rc=-2）
下载：写 [0x41]+"fXXXXXXXX.bin" ADM_FS_READ → 分块 ST_FS_DATA 回传 → 小程序拼为二进制文件保存
> ⚠️ **文件名必须 ≤14B**：ST_FS_ENTRY 的 name 字段受 MTU 限死在 ≤14 字节。`f`+8位hex(32位epoch)+`.bin`=13 字符正好放下；十进制 `flog-<epoch>.bin`(19B) 会被 fs_list 截断 → 下载/删除失败。小程序把 hex 解析回时间显示。
> 多份录制并存：每次 log stop <epoch> 归档一份；小程序文件列表显示可读时间 + 删除按钮。
```

**二进制格式**(小端)：头 32B `magic "LIKLOG1\0", u16 ver,tag_id,imu_hz,baro_hz,result_hz, u64 t0_us`；  
记录(type-tagged，t_ms 为相对开始毫秒)：

- `0x01` IMU(17B)：u8 type,u32 t_ms, i16 ax,ay,az,gx,gy,gz —— acc=g×1000, gyr=rad/s×400
- `0x02` BARO(13B)：u8 type,u32 t_ms, f32 pressure_pa, i16 temp(0.01℃), i16 height(cm)
- `0x03` RESULT(24B)：u8 type,u32 t_ms, i16 roll,pitch,yaw(rad×5729.578=cdeg), i16 vx,vy,vz(m/s×1000), i16 px,py,pz(cm), u8 flags

**容量**：`storage` SPIFFS 分区由 1MB 扩至 **9.6MB**（16MB flash 尾部空闲区，partitions.csv）。100Hz 约 **3.2 KB/s → 约 50 分钟**。

> ⚠️ 改了分区表，**烧录需整片擦除一次**（`idf.py erase-flash` 或下载工具勾全擦），否则旧 SPIFFS 偏移不匹配。  
> ⚠️ 9MB 文件经 BLE(17B/包) 下载很慢，仅适合**短时段诊断采集**；长时段/量产应走 USB 或后续大包 MTU。  
> 传文件方向：当前协议提供**设备→App 读取**（看 log/标定文件）。App→设备写文件可后续加（与 OTA 同机制）。

### 5.3 BLE OTA 固件升级

```
1. 写 [0x50]+u32 总字节+u32 crc32  (OTA_BEGIN) → 收 OTA_ACK(stage=1, result=0 就绪)
2. 循环：写 [0x51]+u16 seq+数据(≤18B) (OTA_DATA)
        → 设备写 OTA 分区；每若干包回 OTA_ACK(stage=2, next_seq=期望序号) 做流控/重传
3. 写 [0x52] (OTA_END) → 设备校验 crc32 → 正确则切分区+重启 → OTA_ACK(stage=3,result=0)
```

**OTA_ACK 的 result 码**（stage=1 begin 失败 / stage=3 end 的 u16 字段；stage=2 data 时该字段是「期望的下一个 seq」用于流控/重传）：  
`0`=OK `1`=无可用OTA分区 `2`=固件超出分区 `3`=esp_ota_begin失败 `4`=写入失败 `5`=乱序块 `6`=crc不符 `7`=校验/切分区失败。

> 流控约定：每个 OTA_DATA 后设备回 `OTA_ACK(stage=2, next_seq)`。App 应**按 next_seq 续传**；收到的 next_seq 若小于已发，说明设备要求重传该 seq。

**性能预期**：BLE 有效吞吐约 5~~20 KB/s，1MB 固件约 1~~3 分钟。**仅近距、管理员用**。  
**实现状态**：✅ 已实现（`esp_ota_*` + 双分区 `ota_0/ota_1`，见 `partitions.csv`）；设备端流式校验 crc32，END 时比对总长+crc 才切分区重启。仍需真机 BLE 栈验证。  
**密封标签的唯一升级通道就是 BLE**（无 USB 开口、不连 AP）；WiFi OTA 仅用于基站，不做在标签上。  
**安全**：OTA 必须 ADMIN 级；设备校验固件 crc32 + 可选签名；失败回滚（ESP-IDF 双 OTA 分区天然支持）。

---

## 6. 解析示例（小程序 JS 伪代码，关键新增包）

```js
function onStatus(buffer) {
  const dv = new DataView(buffer); const t = dv.getUint8(0);
  switch (t) {
    case 0x0A: { // INFO
      const tagId = dv.getUint16(1, true);
      const fw = `${dv.getUint8(3)}.${dv.getUint8(4)}`;
      const bound = dv.getUint8(5);
      const uptime = dv.getUint32(6, true);
      break; }
    case 0x0C: { // TELE（可丢，按 seq 处理）
      const seq = dv.getUint16(1, true);
      const roll = dv.getInt16(3, true)/100, pitch = dv.getInt16(5, true)/100, yaw = dv.getInt16(7, true)/100;
      const vz = dv.getInt16(9, true)/100;
      const heightMm = dv.getUint16(11, true), airMs = dv.getUint16(13, true);
      const flags = dv.getUint8(15);   // bit0 valid,bit1 air,bit2 cross,bit3 pos_reset
      const px = dv.getInt16(16, true)/100, py = dv.getInt16(18, true)/100;  // 米
      if (flags & 0x08) startNewLapTrajectory();   // 过线 reset → 清上一圈轨迹
      renderRide(seq, {roll,pitch,yaw,vz,heightMm,airMs,flags,px,py});
      break; }
    case 0x0D: { // CHECKIN
      const point = dv.getUint8(5), lap = dv.getUint8(6);
      showCheckin(point, lap);
      break; }
    case 0x0B: { // BIND_RES
      const ok = dv.getUint8(1), reason = dv.getUint8(2); break; }
  }
}
// 绑定：CMD_BIND(0x31) + 16B token
function bind(tokenBytes /* Uint8Array(16) */) {
  const b = new Uint8Array(17); b[0]=0x31; b.set(tokenBytes,1);
  wx.writeBLECharacteristicValue({ /*…*/ value: b.buffer });
}
```

---

## 7. 安全要点（务必落实）

- **owner_token / 管理员主密钥由云端管理**，App 不硬编码；token 16B 随机，设备端常数时间比较。
- 已绑定设备**强制鉴权**：非机主拿不到遥测/姿态/标定（设备端拒绝，不只是 App 隐藏）。
- 标定/绑定/OTA 都需对应权限级；OTA 校验 crc32(+建议签名) 并支持回滚。
- 断连后设备**自动降回 LVL_NONE**、关闭所有流。
- BLE 仅近距观感+管理；**成绩与隐私数据以云端账号体系为准**。

---

## 8. 联调清单（硬件到货后）

| ✓ | 项 |
|-|-|
| ☐ | 扫描连接 + QUERY_INFO 显示 tag_id/固件/绑定状态 |
| ☐ | 绑定：未绑→BIND ok→他人连接只能看 INFO、UNLOCK 被拒 |
| ☐ | 标定全流程（陀螺/六面）+ SAVE/LOAD + HEALTH 漂移提醒 |
| ☐ | STREAM_POSE 静止姿态实时跟随 |
| ☐ | STREAM_TELE 骑行流：移动中收包、容忍丢包、seq 跳变处理 |
| ☐ | LF 过线 → 收 ST_CHECKIN（与基站记录对齐） |
| ☐ | 管理员：UNLOCK_ADMIN → FS_LIST/FS_READ/LOG_PULL（日志为真实环形缓冲，含启动/BLE/FS 全过程） |
| ☐ | 管理员：终端 ADM_SHELL free/tasks/info/fs/restart 各回显正确 |
| ☐ | 管理员：BLE OTA 小固件升级 + 重启 + 回滚验证 |
| ☐ | iOS / Android 各验（MTU、字节序、断连重连、后台保活） |

> ⚠️ **固件侧 BLE 栈(NimBLE) + FS/OTA 命令当前未经真机验证**（开发环境无工具链）；  
> 协议**编解码逻辑已用主机孪生验证**。  
> 真机首次联调以本协议表为准，双方对齐；FS/OTA 的分块流控细节可能在真机调试时微调（会同步更新本文）。