<title>UWB 开源方案调研（厘米级 / 低 BOM / 可继承 ESP32-S3 tag）</title>

# UWB 开源方案调研（厘米级 + 低 BOM + 可继承进 ESP32-S3 tag）

> 目标：为阶段五「UWB + 视觉全场建模」预研，找到能做到厘米级定位、BOM 成本可控（远低于市售 300+ 元/tag 成品）、且开源、可继承进现有 ESP32-S3（ESP-IDF/FreeRTOS）tag 系统的 UWB 工程。
> 
> ⚠️ 价格说明：调研时外网被屏蔽，芯片/模组单价为基于知识的**估算（非实时报价）**，量产前须自行到店/立创/淘宝核价。GitHub 的 stars / license / 更新日期经 API 核验，可信度高。

## 一、一句话结论

- **精度可行**：DW1000 / DW3000 系列 TWR（双向测距）在**视距 LOS + 天线延迟标定后**普遍做到 **5–10cm RMS**（多篇论文 + 多个开源项目实测一致）。**天线延迟标定是硬门槛**，不标定裸测差几十 cm。
- **成本可行**：裸 DW3110 芯片量产约 **¥30–50/颗**，加天线 + 晶振 + 被动件，**每 tag 的 UWB 增量 BOM ≈ ¥50–80**，远低于市售 300+/tag 成品。
- **最省力继承路径**：固件用 **br101/libdeca（DW3000，原生 ESP-IDF 5.1，LGPL-3.0，TWR 直接返回 cm）** 作为 TWR 内核，当 component 塞进现有工程；硬件抄 **Cerdas-UWB-Tracker（ESP32-S3 开源硬件，含原理图 / Gerber / BOM）** 的天线与布局；ESP-NOW 共存 + 自动天线标定参考 **Mertcagliyan/ESP32-DWM1000-Driver**。

## 二、芯片 / 模组选型对比（价格为估算）

| 器件 | 世代 / 标准 | 精度(LOS 标定后) | 接口 | 单价估算(¥) | 备注 |
|-|-|-|-|-|-|
| **Qorvo DW3110/DW3120**(裸芯) | DW3000, 802.15.4z | \~5–10cm | SPI≤38MHz | **30–50** | 最低 BOM；功耗约 DW1000 的 1/3；支持 ch5(6.5G)/ch9(8G)；量产首选 |
| **DWM3000 模组** | 内嵌 DW3110 | \~5–10cm | SPI | 100–140 | 免射频布局，小批量 / 打样首选 |
| **Ai-Thinker BU01**(国产, DW1000) | DW1000 | \~10cm | SPI | 60–90 | 国产低价，Cerdas 硬件用的就是它 |
| DWM1000 模组 | DW1000(legacy) | \~10cm | SPI | 60–120 | 老一代、功耗高、无 ch9；生态成熟 |
| NXP SR040/SR150 | 802.15.4z | \~cm | SPI | 100–200 | 偏手机 / 安全测距，SDK 有 NDA，开源 ESP32 支持薄，不推荐 |
| NoopLoop LinkTrack | 国产成品 RTLS | \~10cm | 串口 / 成品 | 200–400/节点 | 「买而非造」的对标，非 ESP32 原生，仅作基准 |

**结论**：量产走**裸 DW3110**；打样 / 小批量走 **DWM3000 模组**或直接买 Makerfabs 板验证。

## 三、开源工程对比（按「能否移植进 ESP-IDF」排序）

| 项目 | 芯片 | 平台 | TWR | License | 活跃 / 成熟 | 对本项目的价值 |
|-|-|-|-|-|-|-|
| **br101/libdeca** ⭐28 | DW3000 | **原生 ESP-IDF 5.1** | SS/DS-TWR，**返回 cm** | LGPL-3.0 | 2026-04 活跃 | 🥇固件 TWR 内核首选，纯 C 可主机验证，直接当 component |
| br101/dw3000-decadriver-source ⭐32 | DW3000 | 多平台 | 底层驱动 | **ISC**(宽松) | 2026-07 活跃 | libdeca 的底座，配套用 |
| **wjxway/DW1000_ESP32** ⭐6 | DW1000 | **ESP-IDF, 实测 S3** | DS-TWR | **MIT** | 2025-12 新 / 不成熟 | 🥈DW1000 路线的 ESP-IDF 唯一正解，支持与 IMU 共享 SPI，含 S3 CS 硅 bug 绕过；README 为 AI 生成需自验 |
| **geraicerdas/Cerdas-UWB-Tracker** ⭐53 | DW1000/BU01 | ESP32-S3(Arduino) | TWR+RTLS | CC-BY-SA(硬件) | 2025-05 | 🥇开源硬件参考：原理图 / Gerber / BOM 齐全，可直接抄 PCB；预留 BNO080 IMU + RTC 位 |
| **Mertcagliyan/ESP32-DWM1000-Driver** | DW1000 | ESP32(Arduino) | TWR + **自动天线标定 + ESP-NOW** | GPL-3.0 | 2026-02 新 | 🎯唯一同时解掉「自动天线标定 + ESP-NOW 共存」两个最难点；GPL 需注意 |
| Makerfabs-ESP32-UWB-DW3000 ⭐160 | DW3000 | ESP32(Arduino) | SS/DS-TWR, TDMA 多锚多标 | **无 license**❗ | 2026-07 活跃 | 生态最大、快速验证板；无许可证=法律风险，只作验证 / 参考 |
| kk9six/dw3000 ⭐31 | DW3000 | ESP32(PlatformIO) | 多锚 SS/DS-TWR + 最优调度 | 无 license❗ | 2025-07 | 多锚测距算法参考（泵道多锚布局有用） |
| F-Army/arduino-dw1000-ng ⭐133 | DW1000 | Arduino(ESP32=test) | TWR + 定位 + NLOS + 标定 API | **MIT** | 已归档 | 算法 / 标定参考，含 EEPROM 存标定 |
| realzoulou/esphome-uwb-dw3000 ⭐25 | DW3000 | ESPHome | DS-TWR + 三角定位 | **Apache-2.0** | 已归档 | 模块化封装干净，可抽取 ranging 模块 |
| thotro/arduino-dw1000 ⭐572 | DW1000 | Arduino | TWR(prototype) | Apache-2.0 | 2019 起停维护 | 所有 DW1000 方案的祖先，寄存器 / 算法源头 |
| foldedtoad/dwm3000 ⭐111 | DW3000 | **Zephyr(nRF/STM32)** | SS/DS-TWR + PDoA | GPL-3.0 | 2024-05 | 非 ESP32，Qorvo 官方 SDK 的干净移植，看 decadriver 用法 |

## 四、继承进现有 ESP32-S3 tag 的集成路径与坑

1. **天线延迟标定（必做，决定 cm）**：Makerfabs 出厂 OTP 是空的，不标定差几十 cm，标定后残差几 cm；\~0.5cm/LSB。→ 抄 Mertcagliyan / Cerdas 的自动标定脚本（对已知固定距离做反馈扫描）。
2. **DS-TWR 优于 SS-TWR**：双边测距抵消 tag/anchor 时钟偏移，**无需时钟同步**即达 cm——正好契合现有「标签端本地锁存」思路（决策 A2），UWB 这条链不需要基站间授时。
3. **两套射频要物理隔离**：UWB(3.5–6.5GHz) 与 ESP-NOW(2.4G) 是独立前端，**必须独立 UWB 天线**，PCB 上拉开距离防 desense。
4. **独立晶振**：DW3000 要自己的稳定 \~38.4MHz XTAL，与 ESP32 时钟分开。
5. **SPI 与 ICM-42688 共总线**：给 DW3000 **独立 CS + 独立 IRQ GPIO**，用 ESP-IDF 线程安全 spi_master 多设备模式。wjxway 已验证与 IMU 共总线，并带 **ESP32-S3 的 CS 硅 bug 绕过**（手动 GPIO 控 CS）——关键坑。
6. **功耗**：DW3000 收发峰值 \~150mA，**必须在测距间隙深睡**，否则毁掉 LF 唤醒的低功耗预算（DW3000 \~DW1000 的 1/3 功耗，选它）。
7. **ISR 模式契合**：UWB IRQ 驱动 RX → task notification → dwt_isr()，正好复用现有「ISR 只锁存 + 入队」模式（决策 G28）；但 TWR_PROCESSING_DELAY 两端必须一致、ISR 里别打日志。
8. **定位需 ≥4 节点**：1 tag + 3 anchor 才能三角定位——这是**固定基础设施的 BOM 乘数，每个 tag 只需 1 颗 UWB**。泵道场景 TWR 比 TDOA 更稳（TDOA 省 tag 功耗但要锚点间紧同步，对多径 / 几何更敏感）。

## 五、推荐低 BOM 组合 + 预估单价

| 角色 | 方案 | 估算成本 |
|-|-|-|
| **tag 端 UWB 增量**(量产) | 裸 DW3110 + UWB 天线 + 38.4M 晶振 + 被动件 | **¥50–80/tag** |
| tag 端(打样 / 小批量) | DWM3000 模组 | ¥100–140/tag |
| **固定锚点** ×3–4 | DWM3000 模组或 Makerfabs 板(市电供电) | ¥100–280/个 ×3\~4 |
| **固件内核** | libdeca(DW3000, ESP-IDF native, LGPL) 当 component + Qorvo dwt_uwb_driver(ISC) | 开源 |
| **硬件参考** | 抄 Cerdas-UWB-Tracker 天线 / 布局，借 Mertcagliyan 的自动标定 + ESP-NOW | 开源 |

**对比市售 300+/tag：自研 tag 增量 ¥50–80，远低于目标。** 锚点是一次性场地投入，可摊薄。

**License 提醒**：出货产品优先 **libdeca(LGPL, 保持独立 component 可满足) / wjxway(MIT, 全宽松) / Qorvo dwt_uwb_driver(ISC)**；Makerfabs、kk9six **无许可证不可直接进产品**（只能验证 / 学习）；Mertcagliyan 是 GPL-3.0（传染性，谨慎）。

## 六、下一步（阶段五落地建议）

1. 先买 1\~2 块 Makerfabs ESP32-UWB-DW3000 板，用 libdeca 跑通 DS-TWR、验证标定后 cm 精度。
2. 在现有 tag 工程中以 component 形式接入 libdeca，验证 UWB 与 IMU 共 SPI、与 ESP-NOW 共存、深睡功耗。
3. 抄 Cerdas 硬件的 UWB 射频 / 天线部分，合并进自研 tag PCB（独立天线 + 独立晶振）。
4. 泵道多锚布局（≥3 锚点）+ 每圈锚点校正，把 UWB 位置喂进 ESKF 做全场轨迹重建。