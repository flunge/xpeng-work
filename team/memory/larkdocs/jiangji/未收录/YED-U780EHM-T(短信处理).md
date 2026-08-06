<title>YED-U780EHM-T(短信处理)</title>

# YED-U780EHM-T(短信处理)

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/qvgngt59vp5wfz14  
> 路径: 产品用户手册 > 4G网卡 > YED-U780EHM-T(短信处理)

# 简介

U780EHM-T 核心板是由银尔达（yinerda）基于合宙Air780EHM模组推出的USB供电DTU 。小巧、稳定、可靠。能够把接收网络数据、短信自动发送到目标服务器。

特性如下:

1. 支持5V USB直插供电，USB转TTL接口；
2. 工作环境为-35℃-75℃；
3. 支持外部独立硬件看门狗，不死机；
4. 支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、Websocket,阿里云IOT 、腾讯IOT、OneNet，华为IOT，电信云，涂鸦云、ThingsCloud等平台；
5. 支持标签logo定制服务；
6. 支持二次开发定制；

7)支持SSL证书加密TCPS/MQTTS/HTTPS 协议；

8)短信支持移动、联通、电信。；

9)不支持USB上网。

# **硬件规格**

## 硬件参数

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| 4G模块 | 网络标准 | Cat1 4G全网通 |
| 网络频段 | LTE-FDD:B1/B3/B5/B8 LTE-TDD:B34/B38/B39/B40/B41 |  |
| 电源参数 |  | 5V USB供电 |
| 工作环境  | 工作温度 | -35℃ \~+75℃ |
| 工作湿度 | 5%\~95%RH(无凝露) |  |
| TTL | 1路 | USB 转TTL串口 |
| 尺寸 |  | 34\*87mm |
| 安装方式 |  | USB直插 |

## 4G 模块功耗参考

待机电流为 DTU 保持服务器网络连接，不发数据的时候的平均电流；5V 发送数据的电流平均约30ma计算；

|  |  |  |  |  |
|-|-|-|-|-|
| 编号 | 供电电压 | 关闭全部 LED | 待机电流(ma) | 备注 |
| 1 | 5V | N | 5.7\~8ma |  |
| 2 | 5V | Y | 5.1\~7ma |  |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | USB | 电源/usb to ttl | 5V USB供电接口，同时也是USB转TTL串口，可以用于电脑串口通讯 |
| 2 | V M P G | 程序下载和调试 | USB |
| 3 | BOOT |  | 强制升级，接到一起，再上电设备，模组进入下模式 |
| 4 | Relaod |  | Reload 接到一起，保持7秒恢复出厂设置 |
| 5 | 4G天线 |  | 板载天线 |
| 6 | NET LED RDY LED |  | 设备状态指示灯 |
|  |  |  |  |
| 7 | SIM卡 |  | 小卡，自弹卡槽 |

## 硬件尺寸

# NET LED 状态描述

|  |  |  |
|-|-|-|
| 指示意义 | 现象 | 备注 |
| SIM卡不识别 | NET LED 5000ms亮 5000ms灭 |  |
| SIM卡正常，但注册不了网络 | NET LED 100ms闪烁 |  |
| 注册网络成功，但没连上服务器 | NET LED 500ms慢闪 | 没有任何通道链接服务器 |
| 成功连上服务器 | NET LED 1000ms慢闪 | 至少有一个通道链接服务器成功 |

# 测试硬件连接方法

插卡方向

# DTU固件实例讲解

适用模组方案：Air780E/Air700/Y100E

|  |  |  |
|-|-|-|
| 序号 | 网络协议 | 测试实例 |
| 1 | TCP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/wr3hgtr9gav7muvs) |
| 2 | UDP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sgoxuutg6gemmxvs) |
| 3 | HTTP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sqk72vapn8l56hy0) |
| 4 | MQTT协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/qqvrgz251f9tu1u1) |
| 5 | 短信转发 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/gyeexzk1ct1s5ggb) |

# Y100E相关证书下载

|  |  |
|-|-|
| 序号 | 证书列表 |
| 1 |  |
| 2 |  |
| 3 |  |
| 4 |  |