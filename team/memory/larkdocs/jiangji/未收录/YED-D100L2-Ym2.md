<title>YED-D100L2-Ym2</title>

# YED-D100L2-Ym2

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/giky11g5yags6w8s  
> 路径: 产品用户手册 > 4G DTU > YED-D100L2-Ym2

# 简介

YED-D100L2-Ym2 DTU是由银尔达（yinerda）推出的高性价的低功耗DTU，适合设备控制，状态检测，传感器数据采集等通过4G网络与服务器通讯的场景，特性如下:

1. 支持3.3\~4.2供电；
2. 支持供电电压采集；
3. 工作环境为-35℃-75℃；
4. 支持超低功耗功能；
5. 支持1路供电电源升压后的12V可控输出（方便给外接传感器供电）；
6. 支持2路数字量输入（可以超低功耗休眠唤醒）；
7. 支持1路模拟量电压输入（0\~10V输入）；
8. 支持1路模拟量电流输入(0-20ma输入)；
9. 支持1路RS485，EN 软件反转；
10. 支持硬件看门狗，运行稳定不死机（可选贴，默认不贴）；
11. 支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、Websocket,阿里云IOT 、腾讯IOT、OneNet，华为IOT，电信云，涂鸦云、ThingsCloud等平台；
12. 支持标签logo定制服务；
13. 支持二次开发定制。

14)支持给用户设备进行固件升级。

注意YED-D100L2-Y与YED-D100L2-Ym2相同，前置是Air780EP方案，后置是Air780EPM方案。DTU用户使用方法一样。

# **硬件规格**

## 2.1、硬件参数

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| 4G模块 | 网络标准 | Cat1 4G全网通，支持中国移动、联通、电信 |
| 网络频段 | LTE-FDD:B1/B3/B5/B8 LTE-TDD:B34/B38/B39/B40/B41 |  |
| 电源参数 |  | 3.3\~4.2V，10W电源，推荐3.5V以上 |
| 工作环境  | 工作温度 | -35℃ \~+75℃ |
| 工作湿度 | 5%\~95%RH(无凝露) |  |
| RS485 | 1路 | 1200-230400；数据位:8、7；停止位：1、2；校验位：奇、偶、无校验 |
| 可控电源输出 | 1路 | 输出固定12V电压，最大电流1A |
| 数字量输入 | 2路 | 支持0\~16V高电平检测 |
| 模拟电压输入 | 1路 | 支持0-10V电压采集 |
| 模拟电流输入 | 1路 | 支持0-20ma采集 |
| 尺寸 |  | 86\*72\*20mm |
| 安装方式 |  | m3螺丝固定 |

## 4G 模块功耗参考

### 普通功耗说明

待机电流为 DTU 保持服务器网络连接，不发数据的时候的平均电流；3.8V 发送数据的电流平均约20ma计算；数据发送完成后大约 12 秒后会自动进入低功耗。

|  |  |  |  |  |
|-|-|-|-|-|
| 编号 | 供电电压 | 关闭全部 LED | 待机电流(ma) | 备注 |
| 1 | 3.3V | N | 12\~13ma |  |
| 2 | 3.8V | Y | 8\~8.6ma |  |
| 3 | 4.2V | N | 7.6\~8ma |  |

### 超低功耗说明

测试环境说明:3.8V电池供电，信号31

|  |  |  |  |
|-|-|-|-|
| 工作模式 | 工作模式说明 | 平均电流 | 3.7V/500mah电池预估使用时间 |
| 超低功耗休眠 | LED 关闭，设备不运行，不连接服务器，可以周期唤醒 | 59ua | 353天 |
| 保持服务器网络连接 | 关闭LED，3分钟发个心跳包 | 8ma | 62小时 |
| 超低功耗休眠10分钟周期唤醒工作 | 正常网络下，唤醒一次大约工作30秒 | 600ua | 833小时\~=34天 |
| 超低功耗休眠60分钟周期唤醒工作 | 正常网络下，唤醒一次大约工作30秒 | 190ua | 2631小时\~=110天 |

## **2.2、硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | VIN GND | 供电电源 | VIN表示电源正极，GND表示电源负极 3.3\~4.2V，10W，推荐3.5V以上 |
| VOUT | 可控电源输出 | 输出12V电压，最大电流1A |  |
| IN1 IN2 | 数字量输入 | 检测范围2\~16V，可以做超低功耗唤醒 |  |
| AIV |  | 0\~10V电压采集，可以切换电路采集电流 |  |
| AII |  | 0\~20ma电流采集，可以切换电路采集电压 |  |
| A/B |  | RS485,EN 硬件手动反转，最大波特率230400 |  |
| 2 | RST | 复位按键 | 在超低功耗的时候，下载程序方便 |
| 3 | VB DM DP GND | USB | 升级固件和调试日志 2.54mm间距USB排针，VB是+ GND是- 不能接反，否则会烧毁设备 |
| 4 | BOOT按键 |  | 强制升级按键；按下按键，再上电设备，模组进入下模式 |
| 5 | Relaod |  | Reload 按键，按7秒回复出厂设置 |
| 6 | 4G天线 |  | SMA接口，必须接 |
| 7 | NET LED |  | 设备状态指示灯 |
| 8 | 外置SIM卡 |  | 自弹中卡卡槽 |
| 9 | 内置SIM卡 |  | 贴片SIM卡 |

## 2.3、硬件尺寸

### 外壳尺寸

### PCB尺寸

## 2.4、PCBA

## 2.5、使用注意事项

震动、运动、腐蚀、潮湿环境推荐贴片卡，如果是外置卡有 松动，氧化风险，建议打胶固定

# NET LED 状态描述

|  |  |  |
|-|-|-|
| 指示意义 | 现象 | 备注 |
| SIM卡不识别 | NET LED 5000ms亮 5000ms灭 |  |
| SIM卡正常，但注册不了网络 | NET LED 100ms闪烁 |  |
| 注册网络成功，但没连上服务器 | NET LED 500ms慢闪 | 没有任何通道链接服务器 |
| 成功连上服务器 | NET LED 1000ms慢闪 | 至少有一个通道链接服务器成功 |

# 测试硬件连接方法

## 1、SIM卡插卡方向

## 2、使用普通串口工具测试

模块的VIN GND 接3.3\~4.2V供电，10W的电源(不能用USB转串口那种电脑USB供电，功率不足)，可以直接用锂电池供电或者稳压电源；RS485串口的A接A，B接B。推荐使用银尔达的YED-UUART-211测试工具测试，方便供电和串口连接调试。

# DTU固件实例讲解

适用模组方案：Air780E/Air700/Y100E/Air780EPM/ Y100EP

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

# YED-D100L2-Ym2与YED-D780L2-Y与YED-D100L2-Ym2区别

|  |  |  |  |  |
|-|-|-|-|-|
| 功能 | D100L2-Ym2 | D100L2-Ym | D780L2-Y | 备注 |
| 芯片方案 | Air780EPM/Y100EPM | Air780EPM/Y100EPM | Air780E |  |
| RS485方案 | RS485软件反转 | RS485硬件自动反转 | RS485软件翻转 | 解决有的设备设备翻转太快数据接收不全问题 |
| 12V 供电超低待机功耗 | 超低功耗59ua | 超低功耗59ua | 超低功耗8ua |  |