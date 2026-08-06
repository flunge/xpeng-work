<title>YED-AS2D0-AIV</title>

# YED-AS2D0-AIV

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/ohc5taq7af81hxn4  
> 路径: 产品用户手册 > 4G RTU > YED-AS2D0-AIV

# 简介

YED-AS2D0-AIV RTU是由银尔达（yinerda）推出的高性价的远程控制器，适合设备控制，状态检测，传感器数据采集等通过4G网络与服务器通讯的场景，特性如下:

1. 支持宽输入电压范围7\~36V；
2. 支持接触放电±8KV，空气放电±15KV；
3. 工作环境为-35℃\~75℃；
4. 支持1路可控电源输出；
5. 支持2路模拟量输入采集（两个版本，可选电流或者电压采集）；
6. 支持1路ADC，可以直接采集供电电源电压；
7. 支持硬件看门狗，运行稳定不死机；

8)支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、Websocket,阿里云IOT 、腾讯IOT、OneNet，华为IOT，电信云，涂鸦云、ThingsCloud等平台；

1. 支持标签logo定制服务；
2. 支持二次开发定制;

11)支持SSL证书加密TCPS/MQTTS/HTTPS 协议；

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
| 可控电源输出 | 1路 | 输出供电电压，最大1A |
| 模拟量采集 | 2路 | 两路0-10V采集或者两路0-20ma采集 |
| TTL串口 | 1路 | 产测串口 |
| 尺寸 |  | 55.5\*43\*22.5mm |
| 安装方式 |  | M3螺丝安装 |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | VIN GND | 供电电源 | VIN标识电源正极 GND标识电源负极 7\~36V 电压，10W电源，推荐7V以上电压 |
| VO GND | 可控电源输出 | 输出供电电压，最大1A |  |
| AI1 AI2 GND | 模拟量采集 | 两路0-10V采集或者两路0-20ma采集 |  |
| 2 | USB |  | 用来调试或者固件升级。 |
| 3 | TTL串口 |  | 产测串口 |
| 4 | 4G天线 |  | SMA接口，兼容IPEX焊盘，可以选贴 |
| 5 | Reload | Reload按键 | DTU固件，长按7秒，用来恢复出厂设置 |
| 6 | BOOT | BOOT按键 | 配合USB，进入BOOT模式升级固件 |
| 7 | NET LED |  | 系统网络指示灯 |
| 8 | 贴片SIM卡 |  | 贴片SIM卡稳定，不松动，脱落，整个板子可以喷三防漆，缺点是不能跟换卡 |
| 9 | 外置SIM卡槽 |  | 外置中型、自弹SIM卡，缺口向外，芯片朝模组面 |

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

模块的VIN GND 接7\~36V,10W的电源(不能用USB转串口那种电脑USB供电，功率不足)；推荐使用银尔达的YED-UUART-211测试工具测试，方便供电和串口连接调试。

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
| 2 | 模拟电压采集示例 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/ry80ku4hrt7wi783) |
| 3 | 模拟电流采集示例 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/zg3o4dwterpe16mm) |