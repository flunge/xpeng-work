<title>YED-G724W</title>

# YED-G724W

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/pom7gbbqt8sghaw3  
> 路径: 产品用户手册 > 4G DTU > YED-G724W

# 简介

YED-G724W 是一款基于合宙Air724系列高性价比的Cat1 4G DTU。支持移动、电信、联通 全网通4G，可以方便集成到自己的设备系统中。主要特点如下:

1)支持5\~36V宽电压供电；

2)支持-35℃\~75℃工作环境温度；

3)支持5\~95%RH湿度工作环境；

4)支持接触放电±8KV,空气放电±15KV；

5)支持1路RS232串口；

6)支持1路RS485串口；

1. 支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、阿里云IOT 、腾讯IOT；

**8) 支持标签logo定制服务；**

**9) 支持二次开发定制。**

# **硬件规格**

## **硬件参数**

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| 4G模块 | 网络标准 | Cat1 4G全网通，支持中国移动、联通、电信 |
| 网络频段 | LTE-FDD:B1/B3/B5/B8 LTE-TDD:B34/B38/B39/B40/B41 |  |
| 电源参数 |  | 5\~36V，10W电源，推荐12V电源 |
| 工作环境  | 工作温度 | -35℃ \~+75℃ |
| 工作湿度 | 5%\~95%RH(无凝露) |  |
| RS232串口 | 1路 | 1200-460800；数据位:8 ；停止位：1、2；校验位：奇、偶、无校验 |
| RS485串口 | 1路 | 1200-230400；数据位:8 ；停止位：1、2；校验位：奇、偶、无校验 |
| 尺寸 |  | 90\*84\*26mm |
| 安装方式 |  | M3螺丝安装 |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | 4G天线 |  | SMA接口 |
| 2 | USB |  | mico usb 固件升级或日志调试 |
| 3 | SIM卡 |  | 自锁SIM卡 |
| 4 | DC IN | 供电电源 | DC电源座，5\~36V，10W电源，推荐12v电压 |
| 5 | DC IN | 供电电源 | +表示电源正极，-表示电源负极 5\~36V 电压，10W电源，推荐12V电压 |
| 6 | RS232 |  | DB9 RS232串口 2脚 RX ,3脚 TX ,5脚 GND |
| 7 | Reload |  | 长按7秒，恢复出厂设置 |
| 8 | RS485 |  | RS485 5.08接口 |

## PCBA

# LED状态描述

|  |  |  |
|-|-|-|
| 指示意义 | 现象 | 备注 |
| SIM卡不识别 | NET LED 和RDY/STA LED 5000ms亮 5000ms灭 |  |
| SIM卡正常，但注册不了网络 | NET LED 100ms闪烁,RDY/STA LED 熄灭 |  |
| 注册网络成功，但没连上服务器 | NET LED 500ms慢闪,RDY/STA LED熄灭 | 没有任何通道链接服务器 |
| 成功连上服务器 | NET LED 1000ms慢闪,RDY/STA LED常亮 | 至少有一个通道链接服务器成功 |

# 测试硬件连接方法

## 1、使用普通串口工具测试

模块的VIN GND 接5\~36V,10W的电源(不能用USB转串口那种电脑USB供电，功率不足)；RS232的TX 接USB 串口的RX，RX接USB串口的TX，GND接USB串口的GND；RS485的A接A，B接B。推荐使用银尔达的YED-UUART-211测试工具测试，方便供电和串口连接调试。

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