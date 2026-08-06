<title>YED-D700Am</title>

# YED-D700Am

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/rf73u7apzkbneaub  
> 路径: 产品用户手册 > 4G DTU > YED-D700Am

# 简介

YED-D700Am (基于Air780EPM)DTU是由银尔达（yinerda）推出的工业级的4G Cat1 DTU 。小巧、稳定、可靠。适合设备控制，状态检测，传感器数据采集等通过4G网络与服务器通讯的场景，特性如下:

1. 支持直流5\~36V宽电压供电，支持电源防接反；
2. 支持接触放电±8KV，空气放电±15KV；
3. 工作环境为-35℃-75℃；
4. 支持1路TTL 串口，兼容3.3V电平和5V电平；
5. 支持1路RS232；
6. 支持1路RS485；
7. 支持1路ADC采集供电电压；
8. 支持外置和贴片SIM卡；
9. 支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、Websocket,阿里云IOT 、腾讯IOT、OneNet，华为IOT，电信云，涂鸦云、ThingsCloud等平台；
10. 支持标签logo定制服务；
11. 支持二次开发定制。

12)支持SSL证书加密TCPS/MQTTS/HTTPS 协议；

13)支持给用户设备进行固件升级。

# **硬件规格**

## **硬件参数**

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| 4G模块 | 网络标准 | Cat1 4G全网通，支持中国移动、联通、电信 |
| 网络频段 | LTE-FDD:B1/B3/B5/B8 LTE-TDD:B34/B38/B39/B40/B41 |  |
| 电源参数 |  | 5\~36V，10W电源，推荐5V以上电源 自带1路ADC采集供电电压 |
| 工作环境  | 工作温度 | -35℃ \~+75℃ |
| 工作湿度 | 5%\~95%RH(无凝露) |  |
| TTL串口 | 1路 | 兼容3.3V、5V串口电平 1200-460800；数据位:7、8 ；停止位：1、2；校验位：奇、偶、无校验 |
| RS232串口 | 1路 | 1200-460800；数据位:7、8 ；停止位：1、2；校验位：奇、偶、无校验 |
| RS485串口 | 1路 | 1200-230400；数据位:7、8 ；停止位：1、2；校验位：奇、偶、无校验 |
| ADC | 1路 | 只支持供电电压采集 |
| 尺寸 |  | 86\*72\*20mm |
| 安装方式 |  | M3螺丝安装 |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1     | VIN/GND | 电源 | VIN电源正极，GND电源负极 范围5\~36V，功率10W电源 自带1路ADC采集供电电压 |
| RX/TX RS232 |  | RS232串口 |  |
| RX/TX TTL |  | TTL 串口，兼容3.3V电平和5V电平 |  |
| GND |  | 负极 |  |
| A/B | RS485 | RS485串口 |  |
| 2 | NET |  | NET LED 系统状态指示灯 |
| 3 | 外置SIM卡 |  | 自弹SIM卡，中卡，方向缺口朝外 默认自带贴片esim卡 |
| 4 | Reload |  | 长按7秒，恢复出厂设置 |
| 5 | 4G天线 |  | SMA接口天线 |

注意：USB和BOOT放到内部，如果需要二次开发和日志调试，需要成拆外壳。

## 硬件尺寸

1. 外壳尺寸
2. PCB尺寸

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

## SIM卡安装方向

## 使用普通串口工具测试

模块的VIN GND 接5\~36V,10W的电源(不能用USB转串口那种电脑USB供电，功率不足)；TTL串口 TX 接USB 串口的RX，RX接USB串口的TX，GND接USB串口的GND；RS232 TX 接USB 串口的RX，RX接USB串口的TX，GND接USB串口的GND；RS485 A接A，B接B；注意RS232和TTL串口不要接错，会导致损坏串口。

推荐使用银尔达的YED-UUART-211测试工具测试，方便供电和串口连接调试。

# DTU固件实例讲解

适用模组方案：Air780E/Air700/Y100E

|  |  |  |
|-|-|-|
| 序号 | 网络协议 | 测试实例 |
| 1 | TCP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/wr3hgtr9gav7muvs) |
| 2 | UDP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sgoxuutg6gemmxvs) |
| 3 | HTTP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sqk72vapn8l56hy0) |
| 4 | MQTT协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/qqvrgz251f9tu1u1) |
| 5 | 定位 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/mgp5olalo7norg03) |
| 6 | WebSocket | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/lht1n1waqugwxbd0) |
| 7 | 移动物联网 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/tqpm82gznca3b1xb) |
| 8 | 电信Aiot-MQTT | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/wcvr7ba7ahgyas9s) |
| 9 | 华为IotDA | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/zyxif86xpi8okziu) |
| 10 | 新腾讯IOT Explorer | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/lepikshg8p42xn73) |
| 11 | 阿里IOT | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/dcvex15v33ly1i2b) |
| 12 | 涂鸦云 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/hqs5t0n3kmo34ag3) |
| 13 | ThingsCloud | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/mgdzgnp83ftq9xny) |
| 14 | 短信转发 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/gyeexzk1ct1s5ggb) |
| 15 | 升级设备(客户设备)固件实例 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sdaxhokk7vbdfhuh) |
| 16 | SSL有证书加密实例 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/egolpofpm3efac2e) |

# 银尔达IOT平台教程

|  |  |  |
|-|-|-|
| 序号 | 网络协议 | 测试实例 |
| 1 | IOT平台入门教程 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/mmtu92gx798qmo2n) |
| 2 | 串口透传指令控制 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/dxeh9dmw2cr0sxxg) |
| 3 | Modbus温湿度传感器 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/ll641owofubt0msq) |

# 认证证书

|  |  |
|-|-|
| 序号 | 证书列表 |
| 1 |  |
| 2 |  |

# YED-D700Ap与YED-D700Am区别

|  |  |  |  |
|-|-|-|-|
| 功能 | D700Ap | D700Am | 备注 |
| 芯片方案 | Air780EP/Y100EP | Air780EPM | EPM内存更大 |
| 网络通道数 | 2路 | 4路 |  |