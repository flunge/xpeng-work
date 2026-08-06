<title>YED-D795W1</title>

# YED-D795W1

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/os555qo1hbusgfn8  
> 路径: 产品用户手册 > 4G DTU > YED-D795W1

# 简介

YED-D795W1适合设备控制，状态检测，传感器数据采集等通过4G网络与服务器通讯的场景，具体功能特点如下。

1. 支持宽输入电压范围5\~36V；
2. 支持接触放电±8KV，空气放电±15KV；
3. 工作环境为-35℃\~75℃；
4. 支持全球4G+2G频段；
5. 支持1路RS485；
6. 支持1路RS232；
7. 支持硬件看门狗，运行稳定不死机；

8)支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、阿里云IOT 、腾讯IOT；

**9)支持标签logo定制服务；**

**10)支持二次开发定制。**

# **硬件规格**

## **硬件参数**

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| 4G模块 | 网络标准 | Cat1 全球通 4G+2G |
| 网络频段 | LTE-FDD:B1/B2/B3/B4/B5/B7/B8/B12/B13/B17/B18/B19/B20/ B25/B26/B28/B66 LTE-TDD:B38/B40/B41 GSM:850/900/1800/1900 |  |
| 电源参数 |  | 5\~36V，10W电源，推荐5V以上电源 |
| 工作环境  | 工作温度 | -35℃ \~+75℃ |
| 工作湿度 | 5%\~95%RH(无凝露) |  |
| RS232串口 | 数量 | 1路 |
|  |  | 1200-460800；数据位:8 ；停止位：1、2；校验位：奇、偶、无校验 |
| RS485串口 | 数量 | 1路 |
|  |  | 1200-230400；数据位:8 ；停止位：1、2；校验位：奇、偶、无校验 |
| 尺寸 |  | 73\*88\*20mm |
| 安装方式 |  | M3螺丝安装 |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | V/G | 供电电源 | V标识电源正极(VIN) G标识电源负极(GND) 5\~36V 电压，10W电源，推荐5V以上电压 |
| RX/TX/GND |  | RS232 |  |
| A/B |  | RS485 |  |
| 2 | BOOT | BOOT按键 | 与USB配合，做固件升级 |
| 3 | Reload | Reload按键 | 长按7秒恢复出厂设置 |
| 4 | 4G天线 |  | SMA天线，兼容IPEX 1代 |
| 5 | USB |  | 用来下载程序或者调试日志 2.0mm排针VB是USB正极，GND是负极，不能接错否则会烧毁设备 |
| 6 | NET LED |  | 系统状态指示LED |
| 7 | 外置SIM卡 |  | 弹簧中卡，缺口朝外 |

## 硬件尺寸

PCB尺寸

外壳尺寸

## PCBA

## 使用注意事项

震动、运动、腐蚀、潮湿环境推荐贴片卡，如果是外置卡有 松动，氧化风险，建议打胶固定。

# LED状态描述

|  |  |  |
|-|-|-|
| 指示意义 | 现象 | 备注 |
| SIM卡不识别 | NET LED 5000ms亮 5000ms灭 |  |
| SIM卡正常，但注册不了网络 | NET LED 100ms闪烁 |  |
| 注册网络成功，但没连上服务器 | NET LED 500ms慢闪 | 没有任何通道链接服务器 |
| 成功连上服务器 | NET LED 1000ms慢闪 | 至少有一个通道链接服务器成功 |

# 测试硬件连接方法

## SIM卡安装方法

## 使用普通串口工具测试

模块的VIN GND 接5\~36V,10W的电源(不能用USB转串口那种电脑USB供电，功率不足)；RS232接口TX 接USB 串口的RX，RX接USB串口的TX，GND接USB串口的GND，或者RS485 A接A，B接B。推荐使用银尔达的YED-UUART-211测试工具测试，方便供电和串口连接调试。

# DTU固件实例讲解

适用模组方案：Air724UG/Air820UG

|  |  |  |
|-|-|-|
| 序号 | 网络协议 | 测试实例 |
| 1 | TCP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/wr3hgtr9gav7muvs) |
| 2 | UDP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sgoxuutg6gemmxvs) |
| 3 | HTTP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sqk72vapn8l56hy0) |
| 4 | MQTT协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/qqvrgz251f9tu1u1) |
| 5 | 阿里IOT配置 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/hycom1hedsr36ay2) |
| 6 | 定位配置测试实例 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/mgp5olalo7norg03) |