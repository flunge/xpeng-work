<title>YED-UUART-211</title>

# YED-UUART-211

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/nggppiz5x1gi9fe5  
> 路径: 产品用户手册 > 调试工具 > YED-UUART-211

YED-UUART-211驱动下载:

使用视频教程:[https://www.bilibili.com/video/BV1cK1aBBEec](https://www.bilibili.com/video/BV1cK1aBBEec)

# 一、产品介绍





YED-UUART-211规格书 是一款基于CH344系列高性价比的串口调试工具。同时支持TTL串口，RS232，RS485。主要特点如下:

1. Type-c 接口；
2. 支持电源扩展输出；
3. 支持1路RS485；
4. 支持2路TTL串口，兼容3.3V和5V电平；
5. 支持1路RS232；

# 二、硬件介绍



|  |  |  |  |
|-|-|-|-|
| 编号 | 功能 |  | 详细说明 |
| 1 | DC电源座 |  | DC座与VCC GND电源接口直连，方便引出电源给调试设备供电 这个电源是给外部设备供电的，串口工具本身不需要供电 DC 座规格：直径5.5mm ，内径2.1mm |
| 2 | USB |  | Type-c接口 |
| 3 | 指示灯 | PWR | USB电源指示灯 |
| 485 | RS485指示灯，蓝色发数据，红色收数据 |  |  |
| TTL1 | TTL1串口指示灯，蓝色发数据，红色收数据 |  |  |
| TTL2 | TTL2串口指示灯，蓝色发数据，红色收数据 |  |  |
| 232 | RS232指示灯，蓝色发数据，红色收数据 |  |  |
| 4 | 接口 | VCC GND | 与DC 座直连，外部设备供电 比如DC座是12V，VCC就是12V |
| RS232 | 对应电脑驱动的D接口 |  |  |
| TTL2 | 对应电脑驱动的C接口 |  |  |
| TTL1 | 对应电脑驱动的B接口 |  |  |
| RS485 | 对应电脑驱动的A接口 |  |  |

# 三、安装驱动

下载驱动，，安装驱动“CH34XSER”后，type-C USB 接上电脑后，设备管理，显示如何下表示正常。

# 四、硬件规格

|  |  |  |
|-|-|-|
| 功能事项 |  | 详细说明 |
| RS485 |  | 最高波特率460800 |
| RS232 |  | 最高波特率460800 |
| TTL |  | 最高波特率921600 |
| 产品尺寸 |  |  |
| 工作温度 | 工作温度 | -35℃ \~+75℃ |
| 存储温度 | -40℃ \~+85℃ |  |

# 五、产品尺寸

支持35MM导轨安装

# 六、硬件连接示例

# 七、配合电脑串口软件工具使用

使用银尔达自主研发的“YEDTestTools.exe”测试工具，能方便你调试DTU或者其他串口功能。使用方法参考:

[https://yinerda.yuque.com/yt1fh6/4gdtu/tl1vaqdylayghdhz](https://yinerda.yuque.com/yt1fh6/4gdtu/tl1vaqdylayghdhz)