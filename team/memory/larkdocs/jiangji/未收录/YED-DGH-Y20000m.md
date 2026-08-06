<title>YED-DGH-Y20000m</title>

# YED-DGH-Y20000m

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/sgc9u94h4kugnrl1  
> 路径: 产品用户手册 > 4G DTU > YED-DGH-Y20000m

# 简介

YED-DGH-Y20000m DTU版本适合设备控制，状态检测等通过4G网络与服务器通讯的场景，具体功能特点如下。

1. 支持3.3-4.2V电池供电，标配5000mah锂电池，支持开关；
2. 支持5\~12V 1.5A 充电，建议用5\~8V电压充电；
3. 支持接触放电±8KV，空气放电±15KV；
4. 工作环境为-35℃\~75℃；
5. 支持1路RS485串口；
6. 支持1路12V 1A可控电源输出；
7. 支持硬件看门狗，运行稳定不死机（可选贴，默认不贴）；

8)支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、Websocket,阿里云IOT 、腾讯IOT、OneNet，华为IOT，电信云，涂鸦云、ThingsCloud等平台；

1. 支持标签logo定制服务；
2. 支持二次开发定制;

11)支持SSL证书加密TCPS/MQTTS/HTTPS 协议；

12)标配IP64防水防尘外壳；

# **产品规格**

## **硬件参数**

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| 4G模块 | 网络标准 | Cat1 4G全网通，支持中国移动、联通、电信 |
| 网络频段 | LTE-FDD:B1/B3/B5/B8 LTE-TDD:B34/B38/B39/B40/B41 |  |
| 电源参数 |  | 3.3-4.2V电池供电 |
| 充电参数 |  | 5-12V 1.5A充电 建议用5\~8V电压充电 |
| 工作环境  | 工作温度 | -35℃ \~+75℃ |
| 工作湿度 | 5%\~95%RH(无凝露) |  |
| RS485 | 1路 | 1200-230400；数据位:8 ；停止位：1、2；校验位：奇、偶、无校验 |
| 电源输出 | 1路 | 12V 1A可控电源输出 |
| 硬件看门狗 | 支持 | 外部硬件看门狗（选贴，默认不贴） |
| 尺寸 |  | 35\*75mm |
| 安装方式 |  | 3mm螺丝定位孔 |

## 4G 模块功耗参考

### 普通功耗说明

待机电流为 DTU 保持服务器网络连接，不发数据的时候的平均电流；3.8V 发送数据的电流平均约22ma计算；数据发送完成后大约 12 秒后会自动进入低功耗。

|  |  |  |  |  |
|-|-|-|-|-|
| 编号 | 供电电压 | 关闭全部 LED | 待机电流(ma) | 备注 |
| 1 | 3.3V | N | 7.8\~8.8ma |  |
| 2 | 3.8V | Y | 7.4\~8.4ma |  |
| 3 | 4.2V | N | 7.2\~8.1ma |  |

### 超低功耗说明

测试环境说明:3.8V供电，信号28

|  |  |  |  |
|-|-|-|-|
| 工作模式 | 工作模式说明 | 平均电流 | 3.7V/5000mah电池预估使用时间 |
| 超低功耗休眠 | LED 关闭，设备不运行，不连接服务器，可以周期唤醒 | 46ua | 104160小时\~=4340天 |
| 保持服务器网络连接 | 关闭LED，3分钟发个心跳包 | 3ma | 1660小时 |
| 超低功耗休眠10分钟周期唤醒工作 | 正常网络下，唤醒一次大约工作30秒 | 550ua | 9090小时\~=370天 |
| 超低功耗休眠60分钟周期唤醒工作 | 正常网络下，唤醒一次大约工作30秒 | 180ua | 27770小时\~=1150天 |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | BAT GND | 供电电源 | 3.3-4.2V 5000mah锂电池 |
| 2 | KEY | 电池开关 | 控制电池开关 |
| 3 | VIN GND | 充电电源 | 5-12v 1.5A快充 建议用5\~8V电压充电 |
| 4 | 绿色 红色 | 充电指示灯 | 电池充满电 绿灯亮 电池未充满 红灯亮 |
| 5 | NET |  | 系统指示灯 |
| 6 | 贴片卡 |  | 贴片SIM卡 |
| 7 | 12V A B GND | 可控电源输出 RS485串口 | 12V/GND 为可控电源输出正/负 最大 12V 1A （可控电源输出ID为1） A/B RS485接口 |
| 8 | GND DP DM VB |  | 固件升级和日志调试 |
| 9 | BOOT |  | 配合USB，进入BOOT升级模式 |
| 10 | Reload |  | 长按7秒，恢复出厂设置 |
| 11 | 4G天线 |  | 4G天线，ipex1代 |

## 硬件尺寸

PCB尺寸

外壳尺寸

电源接口为DC5.5\*2.1 座子

# LED状态描述

|  |  |  |
|-|-|-|
| 指示意义 | 现象 | 备注 |
| SIM卡不识别 | NET LED 5000ms亮 5000ms灭 |  |
| SIM卡正常，但注册不了网络 | NET LED 100ms闪烁 |  |
| 注册网络成功，但没连上服务器 | NET LED 500ms慢闪 | 没有任何通道链接服务器 |
| 成功连上服务器 | NET LED 1000ms慢闪 | 至少有一个通道链接服务器成功 |

# 测试硬件连接方法

设备采用内置电池供电，按下开关即可启动。进行RS485通信时，需将设备的A端与USB转串口模块的A端对应连接，B端同理对接。建议选用银尔达YED-UUART-211测试工具，该工具集成供电与串口调试功能，可有效提升测试效率。

# DTU固件实例讲解

适用模组方案： Air780E/Air700/Y100E/Air780EPM/Y100EP

|  |  |  |
|-|-|-|
| 序号 | 网络协议 | 测试实例 |
| 1 | TCP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/wr3hgtr9gav7muvs) |
| 2 | TCP协议远程控制DTU资源 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/ucbd63lmggdxlls8) |
| 3 | UDP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sgoxuutg6gemmxvs) |
| 4 | HTTP协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/sqk72vapn8l56hy0) |
| 5 | MQTT协议 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/qqvrgz251f9tu1u1) |
| 6 | MQTT协议远程控制DTU资源 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/4gdtu/bfwt0kufgud2ahbzhttps://yinerda.yuque.com/yt1fh6/4gdtu/bfwt0kufgud2ahbz) |
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
| 2 | 串口透传指令控制 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/dxeh9dmw2cr0sxxg) |
| 3 | Modbus温湿度传感器 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/ll641owofubt0msq) |