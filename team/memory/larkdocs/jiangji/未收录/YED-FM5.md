<title>YED-FM5</title>

# YED-FM5

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/ucbo6ysuddh0dsqg  
> 路径: 产品用户手册 > 4G RTU > YED-FM5

# 简介

YED-FM5 RTU是由银尔达（yinerda）推出的高性价的远程控制器，适合设备控制，状态检测，传感器数据采集等通过4G网络与服务器通讯的场景，特性如下:

1. 支持3.3-4.2V锂电池供电，支持供电电压采集；
2. 支持5-18V太阳能充电（5V和12V太阳能板），支持充电电压采集；
3. 支持接触放电±8KV，空气放电±15KV；
4. 工作环境为-35℃\~75℃；
5. 支持 1 路电磁阀驱动,12V/1A；
6. 支持 2 路干接点信号输入检测；
7. 支持 1 路可控电源输出，12V/300ma；
8. 支持 1 路RS485；
9. 支持 2 路模拟量采集；
10. 支持 1 路RTC本地时钟；
11. 支持 1 路SPI flash，8M字节；
12. 支持硬件看门狗，运行稳定不死机；

13)支持银尔达DTU透传固件，支持TCP、UDP、MQTT、HTTP、Websocket,阿里云IOT 、腾讯IOT、OneNet，华为IOT，电信云，涂鸦云、ThingsCloud等平台；

1. 支持标签logo定制服务；
2. 支持二次开发定制;

16)支持SSL证书加密TCPS/MQTTS/HTTPS 协议；

# 硬件规格

## 硬件参数

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| 4G模块 | 网络标准 | Cat1 4G全网通，支持中国移动、联通、电信 |
| 网络频段 | LTE-FDD:B1/B3/B5/B8 LTE-TDD:B34/B38/B39/B40/B41 |  |
| 电源参数 |  | 3.3-4.2V电池供电 |
| 充电参数 |  | 5-12V 太阳能板充电，默认配5V/200ma 太阳能板 |
| 充电MPPT参数 |  | 5V挡是4.3V 12V挡是10.5V |
| 工作环境  | 工作温度 | -35℃ \~+75℃ |
| 工作湿度 | 5%\~95%RH(无凝露) |  |
| 电池阀控制 | 1路 | 12V 最大1A |
| 可控电源输出 | 1路 | 12V 最大300ma |
| 输入 | 2路 | 干接点输入 |
| 模拟量采集 | 2路 | 0-20ma采集 |
| RS485 | 1路 | 1200-230400；数据位:8 ；停止位：1、2；校验位：奇、偶、无校验 |
| 尺寸 |  | 174.5x140.5x43mm |
| 安装方式 |  | M3螺丝安装 |

## **硬件资源介绍**

|  |  |  |  |
|-|-|-|-|
| 编号 | 标识 | 功能 | 说明 |
| 1 | 负极 正极 | 供电电源 | 3.3-4.2V 锂电池 2.54接口 如果电池不够可以自己换更大的 |
| 2 | OFF ON | 电池开关 | 关闭后电池可以充电 关闭后设备不工作 |
| 3 | 充满 充电 | 充电指示灯 | 充电中，红色，充满，绿色 |
| 4 | 5V 光伏板 12V | 太阳能MPPT | 太阳能MPPT电压控制 太阳板支持5v 和12V 2个版本 5\~6V的 跳到5V挡 12V跳到12V 和5V都可以 |
| 5 | BOOT | BOOT按键 | 配合USB，进入BOOT模式升级固件 |
| 6 | Reload | Reload按键 | DTU固件，长按7秒，用来恢复出厂设置 |
| 7 | 4G天线 |  | IPEX1代 |
| 8 | VB DM DP GND | USB | 用来调试或者固件升级。 |
| 9 | NET | LED | 系统网络指示灯 |
| 10 | 贴片SIM卡 |  | 贴片SIM卡稳定，不松动，脱落，整个板子可以喷三防漆，缺点是不能更换卡 |
| 11 | VIN GND |  | 太阳能充电接口 VIN 正 GND负 5.3V 最大300ma 默认配100ma太阳能板 |
| 12 | OUT1 OUT2 |  | 控制电磁阀驱动，可以输出3个状态 12V GND ，GND 12V ,GND GND 12V 最大1A |
| 13 | VOUT GND |  | 12V可控电源输出,最大300ma （继电器输出ID是1，可控电源输出ID是2） |
| 14 | A B |  | RS485 |
| 15 | IN1 IN2 COM | 输入检测 | IN 和 COM 导通触发 |
| 16 | AI1 AI2 GND | 模拟量采集 | 0-20ma采集 |

## 4G 模块功耗参考

测试环境说明:3.7V电池供电，信号28

|  |  |  |  |
|-|-|-|-|
| 工作模式 | 工作模式说明 | 平均电流 | 3.7V/5000mah电池预估使用时间 |
| 保持服务器网络连接 | 每2分钟发一次心跳包，打开串口，所有输出保持关闭 | 17ma | 理论可持续工作290小时 |

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

# 电池和太阳能板说明

3.8V 电压供电，3分钟通信一次，平均17ma。(RS485正常，模拟量正常，可控电源关闭)

配的5000ma电池，理论能用5000/17=294小时=12天左右。（如果加自己的传感器，另算）

板载太阳能板充电效率 5V 120ma左右(太阳好的时候)。理论太阳好充满时间是5000/（120-17）=48小时光照时间。

如果电池不够可以选择大的电池，如果充电效率不够，可以选择外置太阳能板，比如6\~12V的太阳能板，10W之类的。

评估使用时间时间和太阳能板功率要考虑安装地区的连续阴天的时间，板载太阳能板小，功率小。如果完全没太阳的时候基本 充不进去电。实际使用的时候 要考虑自己的传感器的用电，和连续阴天时间，建议考虑加大电池和外置的太阳能板。



# 设备安装说明

## 基本注意

1、太阳能板要能够长时间照到太阳的地方。

2、太阳能板上面的保护膜需要去掉。

3、太阳能板需要根据纬度对着太阳的轨迹，倾斜15\~30度，具体可以百度一下，保证出太阳能照到8小时以上最好。

## 朝向

太阳能板在北半球应朝向正南，安装倾斜角度通常参考当地纬度，这样能最大程度接收阳光，保证发电效率 。

正南方向是首选：在中国等北半球地区，太阳能板面向正南能接收最多的太阳直射光，发电量最高 。

允许有一定偏差：如果屋顶条件限制无法正南，偏向东南或西南 15°以内，发电量损失仅 1%～2%，基本无影响；偏差 30°以内损失约 4%～6%，也是可以接受的范围 。

尽量避免朝北：正北朝向会导致发电量损失 40%～50%，通常不建议安装 。

## 角度

参考当地纬度：最通用的法则是安装倾角等于当地纬度。例如北纬 30°的地区，面板倾斜 30°左右效果较好 。

不同地区有差异：

低纬度地区（如海南、广东）：推荐倾角 10°～15°，因为太阳高度角较高 。

中纬度地区（如上海、浙江）：推荐倾角 20°～25° 。

高纬度地区（如北京、内蒙古）：推荐倾角 30°～40°，北方地区甚至可达 45°，以应对较低的太阳高度 。

## 其他注意事项

防止互相遮挡：多块板子安装时，前后排间距至少要保留板子高度的 1.5 倍，避免前排影子挡住后排 。

避开周围障碍物：安装前要观察周围有没有高楼、大树，确保全天没有阴影遮挡，哪怕少量遮挡也会大幅降低发电效率 。

支架固定要稳：使用专用支架固定，特别是在台风多发区，要确保抗风能力，可调节角度的支架方便后期优化

# 测试硬件连接方法

## 使用普通串口工具测试

模块的VIN GND 接电池,10W的电源；推荐使用银尔达的YED-UUART-211测试工具测试，方便供电和串口连接调试。

# DTU固件实例讲解

适用模组方案：Air780EPM/Y100EPM

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

# 设备质检报告