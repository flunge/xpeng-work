<title>YED-RW2882m</title>

# YED-RW2882m

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/nofru4v3lo4zwqug  
> 路径: 产品用户手册 > 4G RTU > YED-RW2882m

# 简介

YED-RW2882m DTU是由银尔达（yinerda）推出的高性价的Cat1 RTU设备产品，适合设备控制，状态检测，传感器数据采集等通过4G网络与服务器的场景，特性如下

1. 支持7-36V供电，具有防插反功能,支持供电电压采集；
2. 工作环境为-35℃-75℃；
3. 支持1路RS232,2路RS485；
4. 支持1路RTC本地时钟；
5. 支持8路常开常闭3脚继电器输出(交流250V/10A ，直流28V/10A 继电器)；
6. 支持8路干接点输入检测，输入电压等于供电电压;
7. 支持2路ADC电流采集(0-20ma)，1路供电电压采集;
8. 支持硬件看门狗，运行稳定不死机;

9)支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、Websocket,阿里云IOT 、腾讯IOT、OneNet，华为IOT，电信云，涂鸦云、ThingsCloud等平台；

1. 支持标签logo定制服务；
2. 支持二次开发定制;

12)支持SSL证书加密TCPS/MQTTS/HTTPS 协议；

13)支持给用户设备进行固件升级。

# 硬件规格

## 硬件参数

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| 4G模块 | 网络标准 | Cat1 4G全网通，支持中国移动、联通、电信 |
| 网络频段 | LTE-FDD:B1/B3/B5/B8 LTE-TDD:B34/B38/B39/B40/B41 |  |
| 电源参数 |  | 7\~36V，10W电源，推荐7V以上电源，电源防插反 ,支持供电电压采集； |
| 工作环境  | 工作温度 | -35℃ \~+75℃ |
| 工作湿度 | 5%\~95%RH(无凝露) |  |
| 继电器 | 8路 | 250VAC 10A/28VDC 10A |
| 输入 | 8路 | 默认IN和COM导通触发输入 |
| RS232串口 | 1路 | 1200-460800；数据位:8 ；停止位：1、2；校验位：奇、偶、无校验 |
| RS485串口 | 2路 | 1200-230400；数据位:8 ；停止位：1、2；校验位：奇、偶、无校验 |
| 0\~20ma ADC | 2路 | 默认0-20ma采集，可以修改电阻采集电压或者其他参数 |
| 电源ADC | 1路 | 1路，与供电电源并联，只能采集供电电压 |
| 硬件看门狗 | 支持 | 外部硬件看门狗 |
| RTC | 支持 | 能正常设置和读取RTC时间 |
| 尺寸 |  |  |
| 安装方式 |  | M3螺丝安装 |

## 硬件资源介绍

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | VIN GND | 供电电源 | 7\~36V 电压，10W电源，推荐7V以上电压，电源防插反 ,支持供电电压采集； |
| 2 | 外置SIM卡 |  | 直插自弹卡槽，中卡 |
| 3 | 内置SIM卡 |  | 贴片卡 |
| 4 | 4G天线 |  | SMA接口 |
| 5 | NET |  | 系统指示灯 |
| 6 | AI1 AI2 GND | 模拟量采集 | AI接0\~20ma，电流采集 |
|  |  |  |  |
| RXD/TXD |  | RS232接口 |  |
| B1 A1 B2 A2 |  | RS485接口 |  |
| IN1-IN8 COM | 8路干接点输入 | 默认IN和COM导通触发输入 COM是高电平其电压等于设备供电电压 |  |
| 7 | RTC |  | RTC时钟 |
| 8 | Reload |  | 长按7秒，恢复出厂设置 |
| 9 | BOOT |  | 配合USB，进入BOOT升级模式 |
| 10 | USB |  | 固件升级和日志调试 |
| 11 | 继电器 | 8路 3PIN 继电器 | 250VAC 10A/28VDC 10A |

## 硬件尺寸

1. 外壳尺寸
2. PCB尺寸
3. 外壳孔位图

# LED状态描述

|  |  |  |
|-|-|-|
| 指示意义 | 现象 | 备注 |
| SIM卡不识别 | NET LED 5000ms亮 5000ms灭 |  |
| SIM卡正常，但注册不了网络 | NET LED 100ms闪烁 |  |
| 注册网络成功，但没连上服务器 | NET LED 500ms慢闪 | 没有任何通道链接服务器 |
| 成功连上服务器 | NET LED 1000ms慢闪 | 至少有一个通道链接服务器成功 |

# 测试硬件连接方法

## 使用普通串口工具测试

模块的VIN GND 接7\~36V,10W的电源(不能用USB转串口那种电脑USB供电，功率不足)；可以用RS232 TX接RX，RX接TX，GND 接GND；使用RS485是A接A，B接B；推荐使用银尔达的YED-UUART-211测试工具测试，方便供电和串口连接调试。

# DTU固件实例讲解

适用模组方案：Air780EP/Y100E

|  |  |  |
|-|-|-|
| 序号 | 网络协议 | 测试实例 |
| 1 | TCP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/wr3hgtr9gav7muvs) |
| 2 | TCP协议远程控制DTU资源 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/ucbd63lmggdxlls8) |
| 3 | UDP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sgoxuutg6gemmxvs) |
| 4 | HTTP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sqk72vapn8l56hy0) |
| 5 | MQTT协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/qqvrgz251f9tu1u1) |
| 6 | MQTT协议远程控制DTU资源 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/bfwt0kufgud2ahbz) |
| 7 | 定位 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/mgp5olalo7norg03) |
| 8 | WebSocket | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/lht1n1waqugwxbd0) |
| 9 | 移动物联网 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/tqpm82gznca3b1xb) |
| 10 | 电信Aiot-MQTT | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/wcvr7ba7ahgyas9s) |
| 11 | 华为IotDA | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/zyxif86xpi8okziu) |
| 12 | 新腾讯IOT Explorer | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/lepikshg8p42xn73) |
| 13 | 阿里IOT | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/dcvex15v33ly1i2b) |
| 14 | 涂鸦云 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/hqs5t0n3kmo34ag3) |
| 15 | ThingsCloud | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/mgdzgnp83ftq9xny) |
| 16 | 短信转发 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/gyeexzk1ct1s5ggb) |
| 17 | 升级设备(客户设备)固件实例 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sdaxhokk7vbdfhuh) |
| 18 | SSL有证书加密实例 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/egolpofpm3efac2e) |

# 银尔达IOT平台教程

|  |  |  |
|-|-|-|
| 序号 | 网络协议 | 测试实例 |
| 1 | IOT平台入门教程 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/mmtu92gx798qmo2n) |
| 2 | 八路远程开关示例 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/eap61d4xngi6hhi1) |
|  |  |  |