<title>YED-RN111</title>

# YED-RN111

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/eom27yxnli703cr1  
> 路径: 产品用户手册 > 4G RTU > YED-RN111

# 简介

YED-RN111 RTU是由银尔达（yinerda）推出的高性价的远程控制器，适合设备控制，状态检测，传感器数据采集等通过4G网络与服务器通讯的场景，特性如下:

1. 支持7\~36V直流供电
2. 支持接触放电±8KV，空气放电±15KV；
3. 工作环境为-35℃-75℃；
4. 支持1路220VAC/10A，30VDC/10A 继电器；
5. 支持1路干节点输入；
6. 支持1路TTL串口；
7. 支持1路TTS播报接口；
8. 支持外置和贴片SIM卡；
9. 支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、阿里云IOT 、腾讯IOT；

**10) 支持标签logo定制服务；**

**11) 支持二次开发定制。**

# 硬件规格

## 硬件参数

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| 4G模块 | 网络标准 | Cat1 4G全网通，支持中国移动、联通、电信 |
| 网络频段 | LTE-FDD:B1/B3/B5/B8 LTE-TDD:B34/B38/B39/B40/B41 |  |
| 电源参数 |  | 7\~36V，10W电源，推荐7V以上电源 |
| 工作环境  | 工作温度 | -35℃ \~+75℃ |
| 工作湿度 | 5%\~95%RH(无凝露) |  |
| 继电器 | 1路 | 220VAC 10A/30VDC 10A |
| 输入 | 1路 | 干接点 |
| TTL串口参数 | 数量 | 1路 |
|  | 电平 | 兼容3.3V、5V串口电平 |
|  | 参数 | 1200-460800；数据位:8 ；停止位：1、2；校验位：奇、偶、无校验 |
| 喇叭 | 1路 | 直接驱动8欧2W喇叭，做TTS播报 |
| 尺寸 |  | 59\*45mm |
| 安装方式 |  | M3螺丝安装 |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | VIN GND | 供电电源 | VIN标识电源正极 GND标识电源负极 7\~36V 电压，10W电源，推荐7V以上电压 |
| IN COM | 干接点输入 | 干节点输入，IN和COM接通后触发输入，IN LED会常亮 |  |
| 2 | 4G天线 |  | SMA接口，兼容IPEX焊盘，可以选贴 |
| 3 | SPK+ SPK- | 喇叭口 | 喇叭口，可以直接驱动8欧2W喇叭 可以用于TTS播报，播放语音等 |
| RX TX GND | 串口 | TTL电平串口，已经做了电平转换，兼容3.3V和5V串口电平 |  |
| 4 | BOOT | BOOT按键 | 配合USB，进入BOOT模式升级固件 |
| 5 | Reload | Reload按键 | DTU固件，长按7秒，用来恢复出厂设置 |
| 6 | NET LED |  | 系统网络指示灯 |
| STA LED |  |  |  |
| IN LED |  | 干节点输入状态指示灯，IN与COM导通，常亮 |  |
| OUT LED |  | 继电器输出指示灯，继电器的COM与NO导通，常亮 |  |
| PWR LED |  | 电源LED，供电常亮 |  |
| 7 | 继电器 |  | 220V 交流/10A 或者30V直流/10A继电器 COM与NC（默认）或COM与NO导通 |
| 8 | 继电器接口 |  | COM是公共端 |
| 9 | USB |  | 用来调试或者固件升级。VBUS接USB的正，GND接GND，不能接错，否则会烧毁设备 |
| 10 | 贴片SIM卡 |  | 贴片SIM卡稳定，不松动，脱落，整个板子可以喷三防漆，缺点是不能跟换卡 |
| 11 | 外置SIM卡槽 |  | 外置中型、自弹SIM卡，缺口向外，芯片朝模组面 |

## 硬件尺寸

## PCB图

# LED状态描述

## NET和RDY/STA LED描述

|  |  |  |
|-|-|-|
| 指示意义 | 现象 | 备注 |
| SIM卡不识别 | NET LED 和RDY/STA LED 5000ms亮 5000ms灭 |  |
| SIM卡正常，但注册不了网络 | NET LED 100ms闪烁,RDY/STA LED 熄灭 |  |
| 注册网络成功，但没连上服务器 | NET LED 500ms慢闪,RDY/STA LED熄灭 | 没有任何通道链接服务器 |
| 成功连上服务器 | NET LED 1000ms慢闪,RDY/STA LED常亮 | 至少有一个通道链接服务器成功 |

# 测试硬件连接方法

## 使用普通串口工具测试

模块的VIN GND 接7\~36V,10W的电源(不能用USB转串口那种电脑USB供电，功率不足)；TX 接USB 串口的RX，RX接USB串口的TX，GND接USB串口的GND。推荐使用银尔达的YED-UUART-211测试工具测试，方便供电和串口连接调试。

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

# 相关认证证书

|  |  |
|-|-|
| 序号 | 证书列表 |
| 1 |  |
| 2 |  |
| 3 |  |
| 4 |  |