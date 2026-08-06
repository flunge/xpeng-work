<title>原理图（tag 车载板 Schematic）</title>

# 原理图 · tag 车载板

52 器件，ERC 0 error。8 个功能块：MCU(ESP32-S3+32.768k RTC) / IMU(ICM-42688) / LF WAKE(Si3933) / BARO(BMP280) / USB-C / POWER(充电+开关+LDO+电量计) / BATT+IND+I2C / 磁吸充电+轮速。

- 充电：磁吸触点(防水无开口) + USB-C(调试) 双路 OR
- 开关：干簧管(磁控，壳体零开孔)
- 电量计：MAX17261 + R_sense 采样
- 连接器：电池/轮速 JST-SH 1.0mm，磁吸小 SMD 焊盘

## Datasheet ↔ 电路核对（2026-07，已按官方 datasheet 修复）

逐个器件官方 datasheet 与网表核对，发现并修复以下问题（datasheet 已归档飞书 `pcba` 文件夹）：

- **Si3933 全 16 脚引脚号错位（严重，已修）**：自建符号早期按 AS3933 猜测（LCA/LCB/LCC/VREG/CLK_GEN…），与 Si3933 官方 datasheet（Rev 1.1，table 3-1 / figure 3-1）完全不符。已按官方逐脚改正为 **1=CS 2=SCL 3=SDI 4=SDO 5=VCC 6=GND 7=LF3P 8=LF2P 9=LF1P 10=LFN 11=XIN 12=XOUT 13=VSS 14=WAKE 15=DAT 16=CL_DAT**；并按应用电路把时钟源改为内部 RC（XIN→VCC、XOUT 悬空）。原先虚构的 VREG 脚已删除。
- **Si3933 唤醒电报读出脚 DAT/CL_DAT 必须接 MCU（严重，已修）**：核对 datasheet 方框图（fig 2-1）+ 供应商标签参考固件后确认——解码后的唤醒电报**只能**经 DAT(pin15)+CL_DAT(pin16) 输出，SPI/SDO 只能读配置/RSSI 寄存器、**读不到电报内容**。而起点/终点线圈判别（决策 A3）依赖读取不同唤醒码，故 DAT/CL_DAT 原先悬空是设计缺陷。已接入 ESP32 **DAT→IO47、CL_DAT→IO42**（均为空闲脚，避开 strapping/USB-JTAG/PSRAM），并同步 firmware `pins.h`（PIN_SI_DAT / PIN_SI_CL_DAT）。
- **LF 前端改双通道天线（CH1+CH3，已改）**：由单通道升级为两路正交线圈（datasheet 支持 1-3 通道；供应商标签参考工程 `Si3933_PCB_V1.3` 正是 L1+L2 两颗 7.2mH + 240K 阻尼的双通道，固件 R0=0xd6 启用 ch1+ch3），近似消除朝向依赖。CH1=LF1P↔LFN（L1=7.2mH ‖ C10=110pF ‖ R15=240k），CH3=LF3P↔LFN（L2=7.2mH ‖ C18=110pF ‖ R16=240k），共用 LFN 回流；LF2P 保持不用。
- **LF 线圈封装纠正（已修）**：核对供应商参考工程发现，7.2mH 125kHz 天线线圈是绕线/模压 SMD 电感，参考板用**专用大体积线圈封装**；而本设计早前误给 L1/L2 套了 `C_0805`（贴片电容焊盘），线圈根本焊不上去。已改为电感封装 `Inductor_SMD:L_1812_4532Metric`，最终封装需按实际选型线圈匹配（同参考做法）。
- **IMU 引脚号错位（严重，已修）**：自建符号早期把 SPI 的 CS/SCLK/MOSI 放在 pin10/12/13，与 ICM-42688-P 官方引脚分配表（DS-000347）及模组参考原理图不符——正确为 **CS=12、SCL/SCLK=13、SDA/SDIO/SDI(MOSI)=14**。网表按脚名连线，脚号错会导致 SPI 焊到错误焊盘、板子不工作。已改 `gen_symbols.py`。
- **IMU pin7(RESV) 必接 GND（已修）**：datasheet 明确 pin7「Connect to GND」（非可选），原先浮空 → 已接 GND。
- **TP4056 CE(pin8) 浮空（已修）**：使能脚不可浮空 → 拉高到 VCHG（有电源即使能充电）。
- **MAX17261 TH(pin1) 浮空（已修）**：热敏输入 → 按 datasheet「不用时接 BATT」接 VBAT。
- **MAX17261 REG 去耦电容值（已修）**：datasheet 规定 0.47µF，原用 1µF → 改 C13=0.47µF。
- **ICM pin7(RESV) 必接 GND（tag 车载板同步修复）**：datasheet DS-000347 明确 pin7「Connect to GND」（其余 RESV 脚可悬空，唯 pin7 强制），原 tag-2.0 遗漏为悬空 → 已接 GND。
- **防复发机器校验（升级为跨板 datasheet 引脚门禁）**：新增 `qc_datasheet_pins.py`，把每颗关键 IC「哪些脚 datasheet 强制接 GND / 必接电源轨 / 不许悬空」编码成独立真值表，**三块板（tag-2.0 / tag-3.0 / base-3.0）每次构建自动校验**，任一脚偏离即 **DS_PIN_QC FAIL 中断构建**（已做正向/负向自测：故意断开 ICM pin7 立即被拦）。此前「修复只进了某一块板、其余板悄悄漂移」的问题（本轮实测 tag-2.0 曾漏改 CE/TH/C13/RESV7 四处）从机制上根除。原自建符号的 `assert_datasheet()` 保留。
- 其余（ME6211 引脚/去耦、BMP280 I2C 地址接法、ESP32-S3 供电/去耦、USB-C CC/D± 22Ω、SS14/SMAJ 极性）核对**无误**。

完整原理图见下方 PDF 附件。

![tag 车载板 原理图（KiCad 9 导出）](https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=ZDMwMzBiYjE1YWNiNmEzYmZkYWUxODZkZGU0ODRjMjdfYjI0OGUxY2Y5MWRlNTgxOGFjYTRiNDE4NjcxZTRkMmVfSUQ6NzY2NzkyMDk3NzQxNTYwNTQ1N18xNzg1NzY5MjQwOjE3ODU3NzI4NDBfVjM)