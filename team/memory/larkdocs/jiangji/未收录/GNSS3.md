<title>GNSS3</title>

# GNSS3

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/zb4rsxcipdkrgala  
> 路径: 产品用户手册 > 定位模块 > GNSS3

# 一、模组资料

GPS+BD双模定位模块资料

单BD定位模块资料

通用协议文档

# 二、使用方法

1、必须到在室外空旷地方才能使用，在窗边也不一定能够定位成功。

2、是纯硬件定位，只要给GPS上电，就会自动在串口输出定位信息，如果定位成功1PPS会闪烁。

3、定位成功的定位数据都是WGS-84坐标，不能直接用在地图上面定位，直接使用有偏差。按不同的地图纠偏使用。纠偏测试地址和方法: [http://old.openluat.com/GPS-Offset.html](http://old.openluat.com/GPS-Offset.html)

4、供电3.3\~5V ，电脑工具TX接RX，RX接TX，GND接GND，波特率9600，模组上电后就会自动输出定位信息到串口。

5、开发板用的是ZH1.25-5P的座子，线需要转接一下。

连接示意图：

串口数据示意图：