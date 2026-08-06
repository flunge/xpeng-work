<title>YED-GX2001v-16-RTU</title>

# YED-GX2001v-16-RTU

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/eanhupcgy3dixv53  
> 路径: 产品用户手册 > 4G RTU > YED-GX2001v-16-RTU

# 简介

YED-GX2001v-16 RTU版本适合设备控制，状态检测等通过4G网络与服务器通讯的场景，具体功能特点如下。

1. 支持220V电压供电；
2. 支持接触放电±8KV，空气放电±15KV；
3. 工作环境为-35℃\~75℃；
4. 支持1路干节点输入检测；
5. 支持1路270VAC/16A继电器控制；

6)支持1路SPK，可以直接驱动4欧3W喇叭，进行TTS播报；

1. 支持硬件看门狗，运行稳定不死机；

8)支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、Websocket,阿里云IOT 、腾讯IOT、OneNet，华为IOT，电信云，涂鸦云、ThingsCloud等平台；

1. 支持标签logo定制服务；
2. 支持二次开发定制;

11)支持SSL证书加密TCPS/MQTTS/HTTPS 协议；



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
| 输入 | 1路 | 低电平输入检测 |
| 输出 | 1路 | 继电器，270VAC 16A/28VDC 16A |
| 硬件看门狗 | 支持 | 外部硬件看门狗 |
| 尺寸 |  | 77\*48\*32mm |
| 安装方式 |  | 35mm导轨+螺丝定位孔 |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | L N | 供电电源 | 220V交流供电，L接火线 N接零线 |
| 2 | SPK+ SPK- | 喇叭 | 可以直接驱动4欧3W喇叭，可以TTS播报 |
| 3 | IN GND | 输入检测 | 默认IN和COM导通，触发 |
| 4 | NO COM | 2PIN继电器 | 270VAC 16A/28VDC 16A |
| 5 | NET LED |  | 系统指示灯 |
| 6 | BOOT |  | 与USB配合用来升级 |
| 7 | Reload |  | 长按7秒，恢复出厂设置 |
| 8 | 4G天线 |  | SMA接口 |
| 9 | USB |  | 固件升级或调试日志 |
| 10 | TTL串口 |  | 产测串口，3.3V电平 |
| 11 | 内置SIM卡 |  | 贴片卡 |
| 12 | 外置SIM卡 |  | 直插自弹卡槽，小卡 |

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
| 19 | TTS播报教程 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/egolpofpm3efac2e) |

# 银尔达IOT平台教程

|  |  |  |
|-|-|-|
| 序号 | 网络协议 | 测试实例 |
| 1 | IOT平台入门教程 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/mmtu92gx798qmo2n) |
| 2 | 一路远程开关示例 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/hq3o7id8k8gecva1) |
|  |  |  |