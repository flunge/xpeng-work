<title>YED-DG720Zm</title>

# YED-DG720Zm

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/wmpd5itfugwr661g  
> 路径: 产品用户手册 > 4G DTU > YED-DG720Zm

# 简介

YED-DG720Zm DTU是由银尔达（yinerda）推出的工业级的单RS232串口DTU 。小巧、稳定、可靠。适合设备控制，状态检测，传感器数据采集等通过4G网络与服务器通讯的场景，特性如下:

1. 支持直流5\~36V宽电压供电；
2. 支持标准35mm导轨安装和螺丝孔安装，外壳阻燃材料；
3. 支持接触放电±8KV，空气放电±15KV；
4. 工作环境为-35℃-75℃；
5. 支持1路RS232串口；
6. 支持供电电源电压采集；
7. 支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、Websocket,阿里云IOT 、腾讯IOT、OneNet，华为IOT，电信云，涂鸦云、ThingsCloud等平台；
8. 支持标签logo定制服务；
9. 支持二次开发定制。

13)支持SSL证书加密TCPS/MQTTS/HTTPS 协议；

14)支持给用户设备进行固件升级。

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
| RS232串口 | 1路 | 1200-460800；数据位:8、7 ；停止位：1、2；校验位：奇、偶、无校验 |
| 供电电压采集 | 1路 | 支持采集电压5\~36V供电电压 |
| SIM卡 | 2路 | 支持内置贴片SIM卡 外置弹簧SIM卡 |
| 尺寸 |  | 96\*26\*25mm |
| 安装方式 |  | 35mm导轨+M3螺丝安装 |
| 接线规格 |  | 0.1-0.5mm平方 |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | VIN GND | 供电电源 | VIN标识电源正极，GND 标识电源负极 5\~36V 电压，10W电源，推荐12V电压 支持供电电压采集 |
| TX/RX/GND |  | RS232串口 |  |
| 2 | PWR | 电源指示灯 | 供电正常常亮(注意只接USB也会昏暗的常亮，是没供电的) |
| NET |  | DTU状态指示灯，具体看系统指示功能描述 |  |
| RDY |  | DTU状态指示灯，具体看系统指示功能描述 |  |
| 3 | 天线 |  | SMA接口天线 |
| 4 | Reload | 恢复出厂设置按键 | 长按7秒，清除全部参数，恢复出厂设置 |
| 5 | SIM卡 |  | 自弹SIM卡，小卡。注意SIM卡方向缺口朝外 |
| 备注 | USB和BOOT按键在外壳内部，如果要调试任务，升级固件，二次开发，需要拆开外壳 |  |  |

## 硬件尺寸

## 使用注意事项

震动、运动、腐蚀、潮湿环境推荐贴片卡，如果是外置卡有 松动，氧化风险，建议打胶固定。

# LED状态描述

## NET和RDY LED描述

|  |  |  |
|-|-|-|
| 指示意义 | 现象 | 备注 |
| 供电正常 | PWR LED常亮 |  |
| SIM卡不识别 | NET LED 和RDY/STA LED 5000ms亮 5000ms灭 |  |
| SIM卡正常，但注册不了网络 | NET LED 100ms闪烁,RDY/STA LED 熄灭 |  |
| 注册网络成功，但没连上服务器 | NET LED 500ms慢闪,RDY/STA LED熄灭 | 没有任何通道链接服务器 |
| 成功连上服务器 | NET LED 1000ms慢闪,RDY/STA LED常亮 | 至少有一个通道链接服务器成功 |

# 测试硬件连接方法

## SIM卡安装方向

注意SIM卡的缺口方向和芯片方向

## 使用普通串口工具测试

模块的VIN GND 接5\~36V,10W的电源(不能用USB转串口那种电脑USB供电，功率不足)；RS232 TX接RX，RX接TX,GND接GND；推荐使用银尔达的YED-UUART-211测试工具测试，方便供电和串口连接调试。

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