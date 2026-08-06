<title>YED-D724Y3</title>

# YED-D724Y3

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/ldgvzrmopnawy3lf  
> 路径: 产品用户手册 > 4G DTU > YED-D724Y3

# 简介

YED-D724Y3 是一款基于合宙Air724系列高性价比的Cat1 4G DTU。支持移动、电信、联通 全网通4G，可以方便集成到自己的设备系统中。主要特点如下:

1. 支持5\~36V宽电压供电,电源防插反；
2. 外壳防水等级IP66，防油、防水、防尘；
3. 信号强度指示LED，方便排查安装地方信号；
4. 工作环境为-35℃-75℃；
5. 支持1路RS485通讯；
6. 支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、阿里云IOT 、腾讯IOT；

**7) 支持标签logo定制服务；**

**8) 支持二次开发定制。**

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
| RS485串口 | 1路 | 1200-230400；数据位:8 ；停止位：1、2；校验位：奇、偶、无校验 |
| 信号指示 |  | 5颗信号强度指示灯 |
| 尺寸 |  | 107\*58\*40mm |
| 安装方式 |  | M3螺丝安装 |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | 4G天线 |  | SMA接口，兼容IPEX焊盘，可以选贴 |
| 2 | PWR |  | 电源指示灯 |
| 3 | NET |  | 系统指示灯 |
| 4 | RDY |  | 系统指示灯 |
| 5 | B A |  | RS485的A和B |
| 6 | VCC GND | 电源 | VCC电源正极，GND电源负极 5\~36V供电，10W电源，推荐12V电源供电 |
| 7 | 信号指示灯 |  | 5颗信号指示灯 |
| 8 | 固定孔 |  | 3MM孔径 |

## 硬件尺寸

## PCBA

## 使用注意事项

震动、运动、腐蚀、潮湿环境推荐贴片卡，如果是外置卡有 松动，氧化风险，建议打胶固定。

# LED状态描述

## NET和RDY LED描述

|  |  |  |
|-|-|-|
| 指示意义 | 现象 | 备注 |
| SIM卡不识别 | NET LED 和RDY/STA LED 5000ms亮 5000ms灭 |  |
| SIM卡正常，但注册不了网络 | NET LED 100ms闪烁,RDY/STA LED 熄灭 |  |
| 注册网络成功，但没连上服务器 | NET LED 500ms慢闪,RDY/STA LED熄灭 | 没有任何通道链接服务器 |
| 成功连上服务器 | NET LED 1000ms慢闪,RDY/STA LED常亮 | 至少有一个通道链接服务器成功 |

## 信号LED 描述

|  |  |  |
|-|-|-|
| LED点亮个数 | 信号强度范围 | 备注 |
| 5 | 26\~31 | 极强 |
| 4 | 21\~25 | 强 |
| 3 | 17\~20 | 一般 |
| 2 | 12\~16 | 差（不能稳定通信） |
| 1 | 6\~11 | 很差（不能稳定通信） |
| 0 | <6 | 不能通信 |



# 测试硬件连接方法

## 使用普通串口工具测试

模块的VIN GND 接5\~36V,10W的电源(不能用USB转串口那种电脑USB供电，功率不足)；RS48接口，A接A，B接B。推荐使用银尔达的YED-UUART-211测试工具测试，方便供电和串口连接调试。

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