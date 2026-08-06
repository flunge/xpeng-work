<title>YED-U724U（短信处理和网卡）</title>

# YED-U724U（短信处理和网卡）

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/ayk1abf7e0glf54i  
> 路径: 产品用户手册 > 4G网卡 > YED-U724U（短信处理和网卡）

# 简介

U724U 核心板是由银尔达（yinerda）基于合宙Air724模组推出的USB供电DTU 。小巧、稳定、可靠。能够把接收网络数据、短信自动发送到目标服务器，也可以用于做USB网卡。

特性如下:

1. 支持5V USB直插供电，USB接口；
2. 工作环境为-35℃-75℃；
3. 支持外部独立硬件看门狗，不死机；
4. 支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP等平台；
5. 支持标签logo定制服务；
6. 支持二次开发定制。

7)支持作为网卡；

8)支持移动、电信、联通手机卡发送短信；（U100U短信不支持电信卡）

9)支持USB做网卡（支持window,安卓,Linux系统）。

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
| TTL | 1路 | 产测串口，3.3V电平 |
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
| 1 | USB | 电源/USB | 5V USB供电接口，同时也是USB接口，用来下载程序或者调试日志。 |
| 2 | 4G天线 |  |  |
| 3 | BOOT按键 |  | 强制升级按键；按下按键，再上电设备，模组进入下模式 |
| 4 | Relaod |  | Reload 按键，按7秒恢复出厂设置 |
| 5 | TTL |  | 产测串口，放到外壳内部 |
| 6 | NET LED RDY LED |  | 设备状态指示灯 |
|  |  |  |  |
| 7 | SIM卡 |  | 大卡，插卡方向随卡槽上丝印插入 |

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

适适用模组方案：Air724UG/Air820UG

|  |  |  |
|-|-|-|
| 序号 | 网络协议 | 测试实例 |
| 1 | TCP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/wr3hgtr9gav7muvs) |
| 2 | UDP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sgoxuutg6gemmxvs) |
| 3 | HTTP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sqk72vapn8l56hy0) |
| 4 | MQTT协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/qqvrgz251f9tu1u1) |
| 5 | 短信处理教程 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/nrkyi5m375954zdt) |

# USB网卡使用教程

window系统下直接安装724驱动文件，就能自动识别4G网卡，然后自动上网。

Linux和安卓系统，参考教程:[https://doc.openluat.com/wiki/21?wiki_page_id=2010](https://doc.openluat.com/wiki/21?wiki_page_id=2010)

# Air724相关证书下载