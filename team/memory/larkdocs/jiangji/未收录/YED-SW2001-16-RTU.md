<title>YED-SW2001-16-RTU</title>

# YED-SW2001-16-RTU

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/gq1rkguzys32lgzu  
> 路径: 产品用户手册 > 4G RTU > YED-SW2001-16-RTU

# 简介

YED-SW2001-16 RTU版本适合设备控制，状态检测等通过4G网络与服务器通讯的场景，具体功能特点如下。

1. 支持220V电压供电；
2. 支持接触放电±8KV，空气放电±15KV；
3. 工作环境为-35℃\~75℃；
4. 支持1路继电器控制，继电器打开可以直接输出供电220V电压；
5. 支持1路内部输入，用于继电器输出检查，光耦默认为1，有220V输出为0；
6. 支持硬件看门狗，运行稳定不死机；

7)支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、Websocket,阿里云IOT 、腾讯IOT、OneNet，华为IOT，电信云，涂鸦云、ThingsCloud等平台；

1. 支持标签logo定制服务；
2. 支持二次开发定制;

10)支持SSL证书加密TCPS/MQTTS/HTTPS 协议；



# **产品规格**

## **硬件参数**

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| 4G模块 | 网络标准 | Cat1 4G全网通，支持中国移动、联通、电信 |
| 网络频段 | LTE-FDD:B1/B3/B5/B8 LTE-TDD:B34/B38/B39/B40/B41 |  |
| 电源参数 |  | 交流220V |
| 工作环境  | 工作温度 | -35℃ \~+75℃ |
| 工作湿度 | 5%\~95%RH(无凝露) |  |
| 输入 | 1路 | 继电器输出检测，默认为1，有220V输出为0 检查原理: 内部有一路光耦检查，有220V输出就导通，没有接不导通. |
| 输出 | 1路 | 继电器，打开输出220V |
| TTL | 1路 | 产测串口，3.3V电平 |
| 硬件看门狗 | 支持 | 外部硬件看门狗 |
| 尺寸 |  | 84\*40\*25mm |
| 安装方式 |  | 3mm螺丝定位孔 |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | 红 黑 | 供电电源 | 220V交流供电，红接火线 黑接零线 |
| 2 | 内置SIM卡 |  | 贴片卡 |
| 3 | 红 黑 | 继电器 | 打开输出供电电压，红为火线 黑为零线，最大16A (可以用输入1获取继电器状态，默认为1，有220V输出为0) |
| 4 | NET LED |  | 系统指示灯 |
| 5 | OUT LED |  | 继电器指示灯，继电器打开点亮 |
| 6 | VB DM DP GND |  | USB，VB正，GND负，固件升级或调试日志 |
| 7 | B EXT |  | BOOT按键，与USB配合用来升级 |
| 8 | G TX RX |  | TTL产测串口，3.3V电平 |
| 9 | 4G天线 |  |  |

## 硬件尺寸

PCB尺寸

外壳尺寸

# LED状态描述

|  |  |  |
|-|-|-|
| 指示意义 | 现象 | 备注 |
| SIM卡不识别 | NET LED 5000ms亮 5000ms灭 |  |
| SIM卡正常，但注册不了网络 | NET LED 100ms闪烁 |  |
| 注册网络成功，但没连上服务器 | NET LED 500ms慢闪 | 没有任何通道链接服务器 |
| 成功连上服务器 | NET LED 1000ms慢闪 | 至少有一个通道链接服务器成功 |

# 测试硬件连接方法

模块220V供电，用测试服务器测试。

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
| 2 | 一路远程开关示例 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/hq3o7id8k8gecva1) |
|  |  |  |