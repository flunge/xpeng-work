<title>base-3.0 PCB 设计（UWB 锚点 / Anchor）</title>

# base-3.0 PCB 设计（UWB 锚点 / Anchor）

> 泵道 RTLS 的**固定 UWB 锚点/测距节点（阶段三 UWB 预研）**。精简版：**ESP32-S3 + DWM3000** 做双向测距（TWR）。全场部署 **≥3 个锚点**，各自对移动的 `tag-3.0` 测距，三角定位得到标签 cm 级位置。
> 
> 设计依据：阶段三《UWB 开源方案调研》。与 `tag-3.0` 用**同一 DWM3000 模组 + 同一套 UWB 接线**，故**固件可在标签/锚点间直接复用**（br101/libdeca DS-TWR，原生 ESP-IDF）。

## 一、锚点 = 标签砍到只剩必需

市电/USB 供电、固定不动，故砍掉全部标签专属硬件，只留锚点必需：

| 保留 | 砍掉（相对标签） |
|-|-|
| U1 ESP32-S3-WROOM-1（ESP-NOW 回传） | 电池 / TP4056 充电 / MAX17261 电量计 / 保护板 |
| U8 DWM3000（UWB TWR） | Si3933 LF 唤醒 + LF 天线（锚点常开无需唤醒） |
| U5 ME6211 3V3 LDO（USB 5V 供电） | ICM-42688 IMU / BMP280 气压 / 轮速（锚点不动） |
| J1 USB-C（供电+烧录） | 磁吸座 / 干簧开关（无需防水） |
| D1/F1/TVS1 电源入口防护 | 32.768kHz RTC 晶振 |
| LED1 电源 + LED2 UWB 活动 | 3 个标签状态 LED |

## 二、Datasheet ↔ 电路核对（2026-07，已按官方 datasheet 修复）

base-3.0 与 tag-3.0 共用同一 DWM3000 自建符号/封装，故 tag-3.0 上发现的 DWM3000 引脚号 + 封装几何错误**在本板一并修复**：

- **DWM3000 引脚号 + 封装几何双错（严重，已修）**：自建符号早期把 SPI 放在 pin3–6、虚构了 **VDDAON**（pin20）与 NC（21/22）。按 Qorvo DWM3000 Data Sheet Rev B（Figure 8 + Table 2）改正为 24 脚城堡孔真实分配：**SPI=17(CSn)/18(MOSI)/19(MISO)/20(CLK)、IRQ=22、电源 VDD1(5)+VDD3V3(6,7)、地 VSS=8/16/21/23/24**，无 VDDAON。**封装几何同样是错的**：原为 23.4×13.4 的「两排 12 脚」，与模组真实的 **13×22.7mm 倒 U 形城堡孔**（左列 1–8 / 底排 9–16 / 右列 17–24，陶瓷天线在顶部短边）完全不同——按旧封装打样模组根本装不上。已重画 land pattern（`gen_uwb.py`），并据此把 PCB 上 U8 由 rot270 改为 rot180（竖向模组，天线朝板底），QC R1–R5 复跑全 PASS。
- **防复发机器校验（新增）**：`gen_uwb.py` 内新增独立于工作引脚表的「datasheet 真值表」+ `assert_datasheet()` 断言，任何未来改动只要偏离 datasheet 引脚映射即 **PIN_QC FAIL 中断构建**（已做正向/负向自测），从机制上杜绝引脚号错误再次悄悄回归。
- 其余（ESP32-S3 供电/去耦、ME6211 引脚/去耦、USB-C CC/D± 22Ω、SS14/SMAJ 极性、指示 LED）核对**无误**——锚点电路是标签的子集，无标签专属器件（IMU/Si3933/电量计）需再核对。

## 三、状态

| 阶段 | 状态 |
|-|-|
| 原理图（netlist） | ✅ 0 error（SKiDL） |
| 原理图 ERC | ✅ 0 电气错误（仅良性库配置警告） |
| 原理图 PDF / BOM | ✅ 19 组器件 |
| 原理图布局 QC（SCH_QC） | ✅ PASS（26 器件，器件/文字/标签不溢框且互不重叠） |
| PCB 布局（30 器件，4 层，36×58） | ✅ QC R1–R5 全 PASS（焊盘在板内 / 无同面重叠 / 无非预期越界 / 无双面穿板冲突 / 无本体碰撞） |
| 3D 渲染（目视复核） | ✅ 顶面（WROOM + USB-C + DWM3000 竖向模组）/ 底面（LDO + 电源簇）——已复核，DWM3000 竖向落板内无越界 |
| PCB 布线 | ⏸️ 交用户在 KiCad GUI 完成（placement-only 交付） |

## 四、板

- **36 × 58 mm**，宽松布局（墙/杆安装，非可穿戴），4 层（F.Cu / GND / PWR / B.Cu）。
- **WROOM-1 天线悬顶边、DWM3000 UWB 天线（竖向模组短边）朝底边** → 最大隔离，2.4G ESP-NOW 与 6.5G UWB 互不 desense。
- USB-C 在右边缘（供电+烧录）。锚点常开：LDO CE 拉高常使能。

## 五、固件 pins.h（与 tag-3.0 完全相同的 UWB 映射）

```text
UWB (DWM3000):  CS=IO17  IRQ=IO18  RST=IO21  WAKEUP=IO38   （SPI: SCLK12/MOSI11/MISO13）
LED (UWB 活动): IO48

```

## 六、部署

最小可用 RTLS = **1 个 tag-3.0 + 3 个 base-3.0 锚点**（三角定位）。40×60m 泵道可增加锚点改善几何/覆盖。锚点经 ESP-NOW 把测距回传给基站 → 4G → 云。

## 七、PCB 3D 渲染

下方为顶面 / 底面 3D 渲染（36×58 布局）。顶面：WROOM-1（天线悬顶边）+ USB-C（右边缘）+ 指示 LED + DWM3000（**竖向 13×22.7 模组、rot180、天线短边朝板底**）；底面：ME6211 LDO + D1 + 电源入口防护/被动件 + DWM3000 城堡孔焊盘环，无重叠。

> ✅ DWM3000 焊盘编号↔功能映射与城堡孔 land pattern 已按 Qorvo Data Sheet Rev B（Figure 8/14）改正并落到自建封装；引脚真值已由 `gen_uwb.py` 的 `assert_datasheet()` 机器断言守护（偏离即中断构建）。投产前仍建议对照实物模组丝印做一次目视终检。

![base-3.0 顶面：WROOM-1 + USB-C + DWM3000 竖向模组（36×58）](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZjU4MDhkMjJmZTQxNmFkYTA3MDJhMDY5NTE4YTc2YjhfNTFiMWRiNTk1NWJkMTczN2ZkN2NmNDEwZjhjNzdiNjFfSUQ6NzY2Nzg1NDE0MjM5Njg2MTcxNV8xNzg1NzY5MjQxOjE3ODU3NzI4NDFfVjM)

![base-3.0 底面：LDO + 电源簇 + DWM3000 城堡孔焊盘环（36×58）](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=YzAxN2VhNzgwNmQwMTkxNjZmMWQ4MDU4ZDBiMzAzNjdfOWQyYWI5OTIyYTVkMTRjNGM4MTA1YjBkMDRkMTUzOTNfSUQ6NzY2Nzg1NDE1MzI2ODEyMDc2MV8xNzg1NzY5MjQxOjE3ODU3NzI4NDFfVjM)