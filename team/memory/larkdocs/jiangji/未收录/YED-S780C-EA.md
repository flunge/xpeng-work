<title>YED-S780C-EA</title>

# YED-S780C-EA

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/fr18goqtsgxygc7y  
> 路径: 产品用户手册 > 4G DTU > YED-S780C-EA

# 简介

YED-S780C-EA DTU是由银尔达（yinerda）推出的工业级的单TTL串口DTU 。小巧、稳定、可靠。适合设备控制，状态检测，传感器数据采集等通过4G网络与服务器通讯的场景，特性如下:

1. 支持直流5\~36V宽电压供电；
2. 支持标准35mm导轨安装和螺丝孔安装，外壳阻燃材料；
3. 支持接触放电±8KV，空气放电±15KV；
4. 工作环境为-35℃-75℃；
5. 支持1路TTL 串口，兼容3.3V电平和5V电平；
6. 支持本地信号强度指示；
7. 支持1路ADC模拟量，输入检查电压5\~30V；
8. 支持1路数字量输入，触发电压1\~30V；
9. 支持欧洲/香港/韩国/泰国/印度/澳大利亚Cat1 4G频段;
10. 支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、Websocket,阿里云IOT 、腾讯IOT、OneNet，华为IOT，电信云，涂鸦云、ThingsCloud等平台；
11. 支持自动轮询功能；
12. 支持标签logo定制服务；
13. 支持二次开发定制。

14)支持SSL证书加密TCPS/MQTTS/HTTPS 协议；

15)支持给用户设备进行固件升级。

# **硬件规格**

## 硬件参数

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| 4G模块 | 网络标准 | Cat1 4G 欧洲/香港/韩国/泰国/印度/澳大利亚 |
| 网络频段 | LTE-FDD：B1/B3/B5/B7/B8/B28(A/B) |  |
| 电源参数 |  | 5\~36V，10W电源，推荐12V电压 |
| 工作环境  | 工作温度 | -35℃ \~+75℃ |
| 工作湿度 | 5%\~95%RH(无凝露) |  |
| TTL串口 | 1路 | 兼容3.3V电平和5V电平 1200-460800；数据位:8、7 ；停止位：1、2；校验位：奇、偶、无校验 |
| 数字量输入 | 1路 | 支持2\~36V高电平检测 |
| 模拟电压输入 | 1路 | 支持0-36V电压采集 |
| RST | 1路 | 支持3.3\~36V 高电平复位 |
| 尺寸 |  | 71\*43\*23mm |
| 安装方式 |  | 35mm导轨+m3螺丝固定 |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | + - | 供电电源 | +标识电源正极 -标识电源负极 5\~36V 电压，10W电源，推荐12V电源 |
| RX/TX | TTL 串口 | 兼容3.3V电平和5V电平 |  |
| ADC | 模拟电压采集 | 外部输入范围0\~36V，一般用于检查精度要求不高的场景，比如检查电池电压 |  |
| IN | 数字量输入 | 外部输入范围0\~1V为低电平，2\~36V是高电平 |  |
| RST | 复位管脚 | 高电平复位。支持3.3\~36V 电压 |  |
| 2 | USB | Mico USB | 用于下载程序、调试设备，不供电 |
| 3 | PWR | 电源指示灯 | 供电正常常亮(注意只接USB也会昏暗的常亮，是没供电的) |
| NET |  | DTU状态指示灯，具体看系统指示功能描述 |  |
| RDY |  | DTU状态指示灯，具体看系统指示功能描述 |  |
| 4 | 信号灯 |  | 3颗信号强度指示灯，具体看信号强度等级说明 |
| 5 | 天线 |  | SMA接口天线 |
| 6 | Reload | 恢复出厂设置按键 | 长按7秒，清除全部参数，恢复出厂设置 |
| 7 | BOOT |  | 配合USB，进入强制升级模式，用于升级固件 |
| 8 | SIM卡 |  | 自弹SIM卡，中卡。注意SIM卡方向缺口朝外 |

## 硬件尺寸

1. 外壳尺寸
2. PCB尺寸

正面尺寸图

背面尺寸图

## PCBA

## 使用注意事项

震动、运动、腐蚀、潮湿环境推荐贴片卡，如果是外置卡有 松动，氧化风险，建议打胶固定。

# LED状态描述

## NET和RDY LED描述

|  |  |  |
|-|-|-|
| 指示意义 | 现象 | 备注 |
| SIM卡不识别 | NET LED 和RDY/STA LED 5000ms亮 5000ms灭 |  |
| SIM卡正常，但注册不了网络 | NET LED 100ms闪烁,RDY/STA LED 熄灭 |  |
| 注册网络成功，但没连上服务器 | NET LED 500ms慢闪,RDY/STA LED熄灭 | 没有任何通道链接服务器 |
| 成功连上服务器 | NET LED 1000ms慢闪,RDY/STA LED常亮 | 至少有一个通道链接服务器成功 |

## 信号LED 描述

|  |  |  |
|-|-|-|
| LED点亮个数 | 信号强度范围 | 备注 |
| 3 | 24\~31 | 极强（正常通信） |
| 2 | 17\~23 | 强（正常通信） |
| 1 | 13\~16 | 一般（能通信，可能不稳定） |
| 0 | <12 | 不能通信或者不稳定 |

# 测试硬件连接方法

## 1、SIM卡插卡方向

## 2、使用普通串口工具测试

模块的VIN GND 接5\~36V,10W的电源(不能用USB转串口那种电脑USB供电，功率不足)；TTL 串口TX 接USB 串口的RX，RX接USB串口的TX，GND接USB串口的GND。推荐使用银尔达的YED-UUART-211测试工具测试，方便供电和串口连接调试。

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