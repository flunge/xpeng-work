<title>tag-3.0 PCB 设计（Vehicle Tag + UWB）</title>

# tag-3.0 PCB 设计（Vehicle Tag + UWB）

> 阶段三 UWB 预研落地板。在稳定基线 `tag-2.0`（LF 唤醒 + IMU + ESP-NOW）基础上，**新增 DWM3000 UWB 模组**做厘米级双向测距（TWR），成为可对固定锚点 `base-3.0` 定位的 UWB 标签，同时保留 tag-2.0 全部功能。
> 
> 设计依据：阶段三《UWB 开源方案调研》。芯片选 Qorvo DW3000 家族，此处用 **DWM3000 模组**（DW3110 + 38.4MHz 晶振 + 射频匹配 + 陶瓷天线，已调好）——对齐开源参考（Makerfabs / Cerdas），降射频风险；固件路径对齐 **br101/libdeca**（DW3000 原生 ESP-IDF，TWR 直出 cm）。

## 一、相对 tag-2.0 的改动

| 项目 | tag-2.0 | tag-3.0 |
|-|-|-|
| UWB | — | **+ U8 DWM3000**（SPI 与 IMU/Si3933 共总线，独立 CS/IRQ/RST/WAKEUP） |
| 板尺寸 | 30 × 32 mm | **25 × 40 mm**（紧凑双面布局：WROOM 正面上端 / DWM3000 背面下端） |
| USB-C | 通孔（GCT USB4085） | **SMD 顶置（GCT USB4105）**——本体留正面，仅 4× 1mm 屏蔽脚过孔，故 DWM3000 可贴其背面（腾出紧张的 25mm 板宽） |
| 新增器件 | — | U8 + R15（RSTn 上拉）+ R16（WAKEUP 下拉）+ C18/C19（UWB VDD 去耦）；另 LF 前端补 R17（CH1 125kHz 谐振腔阻尼 240k，与 L1‖C10 并联）；LF 升双通道再补 CH3：L2‖C20(110pF)‖R14(240k) on LF3P↔LFN；Si3933 DAT/CL_DAT 接入 IO47/IO42 |
| 天线布局 | WROOM-1 朝顶边 | WROOM-1 **正面上端** + DWM3000 **背面下端**（异端 **且** 异面 = 2.4G/6.5G 最大射频隔离） |
| 固定孔 | 4× M2 角孔 | **无**——无螺丝密封壳（Qi/磁吸充电，无开口，决策 E19）；板灌封/边缘夹持。两排模组占满 25mm 板宽，4mm M2 keep-out 环已放不下。 |
| 轮速霍尔（J4+R14） | 有（IO6） | **按规格移除** |
| 其余 | IMU/气压/充电/电量计/磁吸/干簧/RTC | **完全不变**（LF 已同步 tag-2.0：DAT/CL_DAT 接入 + 双通道天线） |

## 二、电源设计（开关 + 充放电 + 电源管理）

> 核心约束：**全密封无开口**（决策 E19，防水靠磁吸/无线充，无裸露 USB 开关）。故「开关」用磁控干簧、「充电」双路 OR（USB-C + 磁吸触点）、「放电/供电」经 LDO，「电量」由库仑计 I2C 读出。

**主链（两路输入 OR 汇于 VCHG，再一条直链到 +3V3，无交叉）：**

```text
USB-C VBUS ─[F1]─[TVS1⏚]─[D1]─┐
                              ├─► VCHG ─[U6 TP4056]─► VBAT ─[U5 LDO]─► +3V3 ─► 全系统
磁吸  VMAG ───────────[D2]─────┘                       │              (ESP32-S3/IMU/
                                                       └─► J2 电芯(PCM)  Si3933/BMP280/UWB)

```

**三条旁支（不进主链，单列）：**

```text
① 软开关   SW1(干簧) ── VBAT→U5.CE 使能 ；R13(100k) CE下拉→断磁即关（不切主回路，关机仍可充）
② 电量计   U7(MAX17261) ── 跨 R12(10mΩ) 测流 + BATT 测压 → I2C 上报；REG 脚独立去耦 C13，不并 +3V3
③ 指示     TP4056 CHRG/STDBY → LED1/LED2 ；电量条 LED3 ← IO48(GPIO)，真实电量走 I2C
```

下面 2.1–2.4 按「开关 / 充电 / 放电供电 / 电量计」四块分述。

### 2.1 开关（磁控干簧，无开口）

- **SW1 = 干簧开关（REED, magnet-actuated）**：外部磁铁一贴即通/断，**壳体无需开孔**，满足 E19 防水。
- 干簧**门控 LDO 的 CE**（使能脚），**不切电池主回路**——所以「关机」时电芯仍可正常充电（充电路径独立于开关）。SW1 闭合→CE 拉到 VBAT（开机）；**R13(100k) 常态把 CE 下拉到 GND**（干簧断开即关机，无浮空）。

### 2.2 充电（双路 OR：USB-C + 磁吸）

- **入口保护**：USB-C VBUS 先过 **F1（500mA PPTC 自恢复保险丝）**，再由 **TVS1（SMAJ5.0CA 双向）**钳位浪涌/静电到 GND。
- **双路 OR**：USB-C 经 **D1（SS14 肖特基）**、磁吸触点 VMAG 经 **D2（SS14）**，二极管 OR 汇入充电输入轨 **VCHG**——任一路可充电、且互不倒灌（一路插着另一路不会被反向馈电）。
- **充电 IC = U6 TP4056-42（ESOP-8）**：单节锂电线性充电；**PROG=R1(1.2k)→约 1A** 充电电流；TEMP 接 GND（按 datasheet 关闭温控）；**CE(pin8) 拉高到 VCHG 使能**（datasheet：高=正常、低=禁用，不可浮空）；**CHRG/STDBY 两脚驱动 LED1/LED2** 指示充电/满电。
- **电芯 = J2 带保护板(PCM)锂电**：密封壳内不可换电芯，故选**内置过充/过放/过流保护**的成品电芯（决策 A2）。

### 2.3 放电 / 供电（LDO）

- **U5 = ME6211C33（SOT-23-5 LDO）**：VBAT → 稳定 **+3V3** 供全板（ESP32-S3 / IMU / Si3933 / BMP280 / DWM3000）。
- 输入 **C1(1µF/0805)** + 输出 **C2(1µF/0805)** 去耦；LDO 由 SW1 经 CE 门控（见 2.1），实现「磁控软开关」。
- **抗跌落 bulk：C15(100µF/1210)** 挂 +3V3——2.4G/UWB TX 瞬时可拉 200–350mA，大电容托住轨压，防「发射瞬间掉电复位」（决策 B3）。

### 2.4 电源管理 / 电量计（库仑计 I2C）

- **U7 = MAX17261（TDFN-14）库仑计**：跨 **低边采样电阻 R12(10mΩ)** 在 CSPL/CSN 之间测充放电电流并积分，BATT 脚测电芯电压，**I2C 上报剩余电量**（电量条 LED3 由 IO48 驱动、真实电量走 I2C 读）。
- 电池负极回流路径：**J2(-) → R12 → GND**，库仑计正是在这颗采样电阻上积分（没有 R12 就无法计量，决策 A1）。
- **REG 脚 = 库仑计内部稳压输出，独立本地去耦 C13(0.47µF，按 datasheet)，绝不并到系统 +3V3**（否则两个电源顶在一条网上打架）。
- **TH(pin1) 热敏输入接 VBAT**（datasheet「不用时接 BATT」，输入脚不可浮空）；**ALRT(pin12) 开漏告警脚未用**（电量走 I2C 轮询，无硬件告警线）→ 置 No-Connect（避免 KiCad ERC 开漏-电源输出误报）。
- 深睡策略：DWM3000 收发峰值 \~150mA，固件在测距间隙深睡，避免拖垮 LF 唤醒低功耗预算。

### 2.5 关键器件（电源部分）

| 位号 | 器件 | 作用 |
|-|-|-|
| F1 | 500mA PPTC（1206） | USB VBUS 过流自恢复保险 |
| TVS1 | SMAJ5.0CA（SMA） | VBUS 浪涌/ESD 双向钳位 |
| D1 / D2 | SS14 肖特基（SOD-123） | USB-C / 磁吸双路 OR 入 VCHG，防倒灌 |
| U6 | TP4056-42（ESOP-8） | 单节锂电线性充电（\~1A） |
| R1 | 1.2kΩ | TP4056 PROG 设定充电电流 |
| SW1 | 干簧开关（REED） | 磁控门控 LDO CE（无开口开关） |
| R13 | 100kΩ | CE 下拉（干簧断=关机） |
| U5 | ME6211C33（SOT-23-5） | 3.3V LDO 主供电 |
| C15 | 100µF（1210） | +3V3 抗跌落 bulk（TX 突发） |
| U7 | MAX17261（TDFN-14） | I2C 库仑计电量估算 |
| R12 | 10mΩ | 库仑计低边电流采样 |
| J2 / J3 | 带保护电芯 / 磁吸触点 | 电源输入（放电 / 磁吸充电） |

## 三、设计评审反馈（2026-07，全部接受，无需改原理图）

- **IO19/IO20 = USB D-/D+**——作原生 USB-C（下载 + 充电）线，正确用法，未复用为 GPIO。✓
- **PSRAM IO35/36/37 未使用**——WROOM-1 内部 PSRAM 引脚，正确留空。✓
- **RXD0/TXD0（UART0）未引出**——调试走 USB-CDC；可接受的取舍（若 CDC 失效则无 UART 兜底）。✓

## 三·补、Datasheet ↔ 电路核对（2026-07，已按官方 datasheet 修复）

逐个器件官方 datasheet 与网表核对，发现并修复以下问题（datasheet 已归档飞书 `pcba` 文件夹）：

- **IMU 引脚号错位（严重，已修）**：自建符号原把 SPI 的 CS/SCLK/MOSI 放在 pin10/12/13，与 ICM-4268x 官方引脚分配表（DS-000347，与 -42686-P 引脚兼容）及模组参考原理图不符——正确为 **CS=12、SCL/SCLK=13、SDA/SDIO/SDI(MOSI)=14**。网表按脚名连线，脚号错会导致 SPI 焊到错误焊盘、板子不工作。已改 `gen_symbols.py`。
- **IMU pin7(RESV) 必接 GND（已修）**：datasheet 明确 pin7「Connect to GND」（非可选），原先浮空 → 已接 GND。
- **TP4056 CE(pin8) 浮空（已修）**：使能脚不可浮空 → 拉高到 VCHG（有电源即使能充电）。
- **MAX17261 TH(pin1) 浮空（已修）**：热敏输入 → 按 datasheet「不用时接 BATT」接 VBAT。
- **MAX17261 REG 去耦电容值（已修）**：datasheet 规定 0.47µF，原用 1µF → 改 C13=0.47µF。
- **Si3933 全 16 脚引脚号错位（严重，已修）**：自建符号早期按 AS3933 猜测（LCA/LCB/LCC/VREG/CLK_GEN…），与 Si3933 官方 datasheet（Rev 1.1，table 3-1 / figure 3-1）完全不符。已按官方逐脚改正为 **1=CS 2=SCL 3=SDI 4=SDO 5=VCC 6=GND 7=LF3P 8=LF2P 9=LF1P 10=LFN 11=XIN 12=XOUT 13=VSS 14=WAKE 15=DAT 16=CL_DAT**；并按应用电路把时钟源改为内部 RC（XIN→VCC、XOUT 悬空）。原先虚构的 VREG 脚已删除。
- **Si3933 唤醒电报读出脚 DAT/CL_DAT 必须接 MCU（严重，已修）**：核对 datasheet 方框图（fig 2-1）+ 供应商标签参考固件后确认——解码后的唤醒电报**只能**经 DAT(pin15)+CL_DAT(pin16) 输出，SPI/SDO 只能读配置/RSSI 寄存器、**读不到电报内容**。起点/终点线圈判别（决策 A3）依赖读取不同唤醒码，故原先悬空是设计缺陷。已接入 ESP32 **DAT→IO47、CL_DAT→IO42**（均为空闲脚，避开 strapping/USB-JTAG/PSRAM），并同步 firmware `pins.h`。
- **LF 前端改双通道天线（CH1+CH3，已改）**：由单通道升级为两路正交线圈（datasheet 支持 1-3 通道；供应商标签参考工程 `Si3933_PCB_V1.3` 正是 L1+L2 两颗 7.2mH + 240K 阻尼的双通道，固件 R0=0xd6 启用 ch1+ch3），近似消除朝向依赖。CH1=LF1P↔LFN（L1=7.2mH ‖ C10=110pF ‖ R17=240k），CH3=LF3P↔LFN（L2=7.2mH ‖ C20=110pF ‖ R14=240k），共用 LFN 回流；LF2P 保持不用。
- **LF 线圈封装纠正（已修）**：核对供应商参考工程发现，7.2mH 125kHz 天线线圈是绕线/模压 SMD 电感，参考板用**专用大体积线圈封装**；而本设计早前误给 L1/L2 套了 `C_0805`（贴片电容焊盘），线圈焊不上去。已改为电感封装 `Inductor_SMD:L_1812_4532Metric`，最终封装需按实际选型线圈匹配（同参考做法）。
- **DWM3000 引脚号 + 封装几何双错（严重，已修）**：自建符号早期把 SPI 放在 pin3–6、虚构了 **VDDAON**（pin20）与 NC（21/22）。按 Qorvo DWM3000 Data Sheet Rev B（Figure 8 + Table 2）改正为 24 脚城堡孔真实分配：**SPI=17(CSn)/18(MOSI)/19(MISO)/20(CLK)、IRQ=22、电源 VDD1(5)+VDD3V3(6,7)、地 VSS=8/16/21/23/24**，无 VDDAON。**封装几何同样是错的**：原为 23.4×13.4 的「两排 12 脚」，与模组真实的 **13×22.7mm 倒 U 形城堡孔**（左列 1–8 / 底排 9–16 / 右列 17–24，陶瓷天线在顶部短边）完全不同——按旧封装打样模组根本装不上。已重画 land pattern（`gen_uwb.py`），并据此把 PCB 上 U8 由 rot90 改为 rot180（竖向模组，天线朝板底），tag-3.0 与 base-3.0 两板 QC R1–R5 复跑全 PASS。
- **防复发机器校验（新增）**：`gen_symbols.py` / `gen_uwb.py` 内新增独立于工作引脚表的「datasheet 真值表」+ `assert_datasheet()` 断言，任何未来改动只要偏离 datasheet 引脚映射即 **PIN_QC FAIL 中断构建**（已做正向/负向自测），从机制上杜绝上述引脚号错误再次悄悄回归。
- 其余（ME6211 引脚/去耦、BMP280 I2C 地址接法、ESP32-S3 供电/去耦、USB-C CC/D± 22Ω、SS14/SMAJ 极性）核对**无误**。**base-3.0（市电锚点）同样内置 DWM3000，故上述 DWM3000 引脚号 + 封装修复已一并应用；其独有的电源/接口部分核对无误。**

## 四、状态

| 阶段 | 状态 |
|-|-|
| 原理图（netlist 全连线） | ✅ 0 error（SKiDL） |
| 原理图 ERC | ✅ 0 电气错误（其余为良性库配置/PWR_FLAG 警告，与 tag-2.0 同级） |
| 原理图 PDF / BOM | ✅ 35 组器件 |
| PCB 布局（55 器件，双面，4 层，25×40） | ✅ QC R1–R5 全 PASS（焊盘在板内 / 无同面重叠 / 无非预期越界 / 无双面穿板冲突 / 无本体碰撞） |
| 3D 渲染（目视复核） | ✅ 顶面（WROOM + SMD USB-C + LED）/ 底面（DWM3000 + 传感/电源簇）——已复核，无重叠，两面利用率高 |
| PCB 布线 | ⏸️ 交用户在 KiCad GUI 完成（placement-only 交付，同 tag-2.0） |

## 五、UWB 集成要点（源自调研的「集成路径与坑」）

1. **SPI 共总线、独立 CS+IRQ。**DWM3000 挂现有 SPI（SCLK IO12 / MOSI IO11 / MISO IO13），独立 **CS=IO17**；**IRQ=IO18** 专用中断脚；SPIMISO 符号设为三态，共享 MISO 总线 ERC 干净。
2. **RST 上拉 / WAKEUP 下拉。**R15(10k) 保持 RSTn 高（不被复位），R16(100k) WAKEUP 常低。**RST=IO21，WAKEUP=IO38**，均非 strapping 脚（避开 0/3/45/46、USB 19/20、PSRAM 35-37、IMU2_CS=IO7）。
3. **射频隔离。**UWB(6.5GHz) 与 ESP-NOW(2.4GHz) 独立前端，两模组天线放**板子两端**互不 desense；DWM3000 自带天线 + 晶振，PCB 上无需另加射频电路。
4. **功耗/深睡。**DWM3000 收发峰值 \~150mA，固件须在测距间隙深睡，避免拖垮 LF 唤醒低功耗预算（选 DW3000 正因其功耗约 DW1000 的 1/3）。
5. **天线延迟标定（固件层，非 PCB）。**cm 精度需逐颗标定天线延迟（模组 OTP 出厂为空），固件对已知距离做反馈标定。

## 六、固件 pins.h 需新增

```text
UWB (DWM3000):  CS=IO17  IRQ=IO18  RST=IO21  WAKEUP=IO38   （SPI 共用 SCLK12/MOSI11/MISO13）
```

## 七、PCB 3D 渲染

下方为顶面 / 底面 3D 渲染（25×40 双面布局）。顶面：WROOM-1（天线 keep-out 悬顶边）+ SMD USB-C（右侧边）+ D1 与 LED1/2/3；底面：DWM3000（**竖向 13×22.7 模组、rot180、天线短边朝板底**）+ 传感器簇（IMU/Si3933/气压）+ 电源 IC + 全部被动件，无重叠。

> ✅ DWM3000 焊盘编号↔功能映射与城堡孔 land pattern 已按 Qorvo Data Sheet Rev B（Figure 8/14）改正并落到自建封装；引脚真值已由 `gen_uwb.py` 的 `assert_datasheet()` 机器断言守护（偏离即中断构建）。投产前仍建议对照实物模组丝印做一次目视终检。

![tag-3.0 顶面：WROOM-1 + SMD USB-C + LED（25×40）](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZTlhYjg1YWM4MTJiNWYxOGNhODBmYzAzMmE3NzU4NjZfYTRhNTZmOTk0YzEzZTM5ODU5YzdkNDE3NTU5NTkwM2ZfSUQ6NzY2NzkyMDkxNzYwNzE3MzMyOV8xNzg1NzY5MjQxOjE3ODU3NzI4NDFfVjM)

![tag-3.0 底面：DWM3000 + 传感/电源簇（25×40）](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=MDcwYTRjZDM3M2QxM2Q4ODVmZGYwN2FmZDZlMDNkZjVfOGM1NmM0NDBiNTIxZWQ2ZGYxNjM0N2M5YmM3MjBhOTlfSUQ6NzY2NzkyMDkyNTI0MDkwNTAwMl8xNzg1NzY5MjQxOjE3ODU3NzI4NDFfVjM)