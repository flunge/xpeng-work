<title>GNSS1-P</title>

# GNSS1-P

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/esi8auhc4n43qxlu  
> 路径: 产品用户手册 > 定位模块 > GNSS1-P

# 一、简介

YED-GNSS1-P DTU是由银尔达（yinerda）推出的高性价的带GPS/北斗定位+4G Cat1通信的DTU，适合设备控制，状态检测，传感器数据采集等通过4G网络与服务器通讯的场景，特性如下:

1. 支持8\~90V供电，支持电源防接反；
2. 工作环境为-35℃-75℃；
3. 支持1路高电平输入，检测3\~90V高电平输入；
4. 支持1路NPN输出，最高支持24V电压输出；
5. 支持1路GPS或单北斗定位；
6. 支持基站定位/WIFI定位(大陆)；
7. 支持AGNSS辅助定位，加快定位速度；
8. 支持1路ADC，采集供电电压；
9. 支持运动震动检测；

10)支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、Websocket,阿里云IOT 、腾讯IOT、OneNet，华为IOT，电信云，涂鸦云、ThingsCloud等平台；

1. 支持标签logo定制服务；
2. 支持二次开发定制;

13)支持SSL证书加密TCPS/MQTTS/HTTPS 协议；

# **二、硬件规格**

## **硬件参数**

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| 4G模块 | 网络标准 | Cat1 4G全网通，支持中国移动、联通、电信 |
| 网络频段 | LTE-FDD:B1/B3/B5/B8 LTE-TDD:B34/B38/B39/B40/B41 |  |
| 电源参数 |  | 8\~90V，10W电源，推荐10V以上电源 |
| 工作环境  | 工作温度 | -35℃ \~+75℃ |
| 工作湿度 | 5%\~95%RH(无凝露) |  |
| 定位 | 支持 | ATGM336H-5NR32 GPS模块或ATGM336H-6N22单北斗芯片 基站定位+WIFI定位(大陆） |
| 连接线接口规格 |  | SM2.54 4PIN |
| 数字量输入 | 1路 | 高电平输入检查，检测3-90V高电平信号 |
| 数字量输出 | 1路 | NPN输出，最高控制输出24V电压 |
| 震动检测 | 支持 |  |
| 供电电压采集 | 支持 | 8\~90V功能电压采集 |
| 尺寸 |  | 76\*26\*14mm |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | VIN NGD | 供电电源 | VIN表示正极，GND表示负极 8\~90V，10W电源 |
| IN |  | 3\~90V高电平检测输入 |  |
| OUT |  | NPN输出，支持最高24V电压控制 |  |
| 2 | 4G天线 |  |  |
| 3 | GPS天线 |  | 无源陶瓷天线 |
| 4 | USB | USB | 固件升级或者调试 |
| 5 | 1PPS LED |  | GPS定位状态灯，定位成功常亮 |
| 6 | NET LED |  | 系统指示灯 |
| 7 | 外置SIM卡 |  | 自弹小卡 |
| 8 | GPS模块 |  | ATGM336H-5NR32 GPS模块或ATGM336H-6N22单北斗芯片 |
| 9 | Reload |  | 与GND短路7秒恢复出厂设置 |
| 10 | BOOT VDD |  | BOOT，2点短接，配合USB，进入升级模式 |
| 11 | GND TXD RXD |  | TTL串口，3.3V电平，用来产测 |

## 硬件尺寸

## 2.GPS参数

### ATGM336H-5NR32 GPS模块参数

|  |  |  |  |
|-|-|-|-|
| 编号 | 项目 | 性能 | 备注 |
| 1 | 定位模式 | BDS/GPS/GLONASS/GALILEO/QZSS/SBAS |  |
| 2 | 跟踪通道数 | 三通道射频，支持全星座 BDS、GPS 和 GLONASS 同时接收 |  |
| 3 | 灵敏度 | 冷启动捕获灵敏度-148dBm 热启动捕获灵敏度-156dBm 跟踪灵敏度-162dBm 重捕获灵敏度 -160dbm |  |
| 4 | 数据更新频率 | 1Hz |  |
| 5 | 定位精度 | <2.5m（CEP50） |  |
| 6 | 测速精度 | 0.1m/s |  |
| 7 | 冷启动时间 | ≤35s |  |
| 8 | 热启动时间 | <1s |  |
| 9 | 重捕时间 | <1s |  |
| 10 | 典型功耗 | 26 mA | 3.3V 供电 |
| 11 | 天线 | 支持 3.3V 有源天线和无缘天线 |  |

### ATGM336H-6N22单北斗芯片参数

|  |  |  |  |
|-|-|-|-|
| 编号 | 项目 | 性能 | 备注 |
| 1 | 定位模式 | BDS：B1I+B1C | 北斗2，北斗3 |
| 2 | 灵敏度 | 冷启动捕获灵敏度-148dBm 热启动捕获灵敏度-156dBm 跟踪灵敏度-162dBm 重捕获灵敏度 -160dbm |  |
| 3 | 数据更新频率 | 1Hz |  |
| 4 | 定位精度 | <2.0m（CEP50） |  |
| 5 | 测速精度 | 0.1m/s |  |
| 6 | 冷启动时间 | ≤23s |  |
| 7 | 热启动时间 | ≤1s |  |
| 8 | 重捕时间 | ≤1s |  |
| 9 | 待机典型功耗 | <10uA | 3.3V 供电 |
| 10 | 连续运行典型功耗 | 42 mA | 3.3V 供电 |
| 11 | 天线 | 支持 3.3V 有源天线和无缘天线 |  |

## 4G 模块功耗参考

### 普通功耗说明

待机电流为 DTU 保持服务器网络连接，不发数据的时候的平均电流；12V 发送数据的电流平均约8ma计算；数据发送完成后大约 12 秒后会自动进入低功耗。如果 GPS 运行，叠加 GPS 功耗，参考 GPS 版本功耗。

|  |  |  |  |  |
|-|-|-|-|-|
| 编号 | 供电电压 | 关闭全部 LED | 待机电流(ma) | 备注 |
| 1 | 12V | N | 2.7\~2.9ma |  |
| 2 | 12V | Y | 2.6\~2.8ma |  |

### 超低功耗说明

测试环境说明:供电12V，信号30

|  |  |  |
|-|-|-|
| 工作模式 | 工作模式说明 | 平均电流 |
| 超低功耗休眠 | LED 关闭，设备不运行，不连接服务器，可以周期唤醒 | 465ua |
| 保持服务器网络连接 | 关闭LED，3分钟发个心跳包 | 5ma |
| 超低功耗休眠10分钟周期唤醒工作 | 10分钟自动唤醒，定位一次，上传GPS信息和基站信息 正常网络下，唤醒一次大约工作50秒 | 1.3ma |
| 超低功耗休眠60分钟周期唤醒工作 | 60分钟自动唤醒，定位一次，上传GPS信息和基站信息 正常网络下，唤醒一次大约工作50秒 | 600ua |

## 输入IN的原理说明

当IN悬空或者输入低电平的时候，内部GPIO为高电平。当IN输入高电平的时候，内部GPIO为低电平。



## 输出OUT的原理说明

这个是一个NPN输出。实际使用的时候如右图，OUT接负载的负极，负载的正极接负载的电源。当OUT为高电平的时候，负载通电，当OUT悬空或者低电平的时候，负载断电。

## 使用注意事项

震动、运动环境推荐贴片卡，如果是外置卡有 松动风险，建议打胶固定。



GPS必须放到室外空旷的地方官才能定位，室内无法定位，具体原理可以百度一下。

GPS的数据是WG84坐标，要用到需要转换成使用地图的坐标系，具体方法可以百度自己用的地图的坐标系。



基站定位免费的有频率限制，不支持WIFI定位。如果要求高，建议用付费定位。

基站定位不管是付费还是免费，都可能无法定位，这个是数据库是全面导致的，比如基站信息没再服务器内就无法定位。

# 三、NET LED 状态描述

|  |  |  |
|-|-|-|
| 指示意义 | 现象 | 备注 |
| SIM卡不识别 | NET LED 5000ms闪烁 |  |
| SIM卡正常，但注册不了网络 | NET LED 100ms闪烁 |  |
| 注册网络成功，但没连上服务器 | NET LED 500ms慢闪 | 没有任何通道链接服务器 |
| 成功连上服务器 | NET LED 1000ms慢闪 | 至少有一个通道链接服务器成功 |

# 四、测试硬件连接方法

## SIM卡插卡方向

## 工具测试

模块的VIN GND 接8\~90V,10W的电源(不能用USB转串口那种电脑USB供电，功率不足)；然后通过测试服务器看数据。GPS设备需要放到室外，才能定位。

# 五、DTU固件实例讲解

适用模组方案： Air780E/Air700/Y100E/Air780EPM/Y100EP

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

# 六、银尔达IOT平台教程

|  |  |  |
|-|-|-|
| 序号 | 网络协议 | 测试实例 |
| 1 | IOT平台入门教程 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/mmtu92gx798qmo2n) |
| 2 | 串口透传指令控制 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/dxeh9dmw2cr0sxxg) |
| 3 | Modbus温湿度传感器 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/ll641owofubt0msq) |
| 4 | 常供电定位器 | [【点击查看教程】](https://yinerda.yuque.com/yt1fh6/iot/ga0ozgryxzex0kpd) |