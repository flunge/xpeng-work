<title>(Air780)ThingsBoard Cloud配置测试实例 </title>

# (Air780)ThingsBoard Cloud配置测试实例

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/cy0bwk4vsgao7e2o  
> 路径: DTU固件实例讲解 > (Air780)ThingsBoard Cloud配置测试实例

目前只有Air780支持,固件版本等于大于V1.1.1



使用任何平台本质都是MQTT协议协议通讯，这个难点是搞清楚平台的通讯规则，理清楚订阅topic，发布topic和数据格式（物模型）。

DTU目前是解决了平台基本的连接和交互问题，根据教程连接平台后，在实际实现自己的业务上用不起来。这个本质的原因是不清楚平台如何使用，平台需要的topic和物模型数据格式不清楚导致的。所以基本步骤测试完成后就要研究平台的文档和询问平台的技术支持，清楚topic和数据格式后，在继续下一步结合银尔达的技术支持，让DTU按自己业务需求上传和解析数据。

# 一、工具简介

DTU配置平台:[https://dtu.yinerda.com](https://dtu.yinerda.com)

串口测试软件:"[YEDTestTools](https://yinerda.yuque.com/yt1fh6/4gdtu/rfvpd0gwbr6vhfb4)"软件,或者任意自己熟悉的串口调试软件。

USB转串口调试工具:"[YED-UUART-211](https://yinerda.yuque.com/yt1fh6/4gdtu/rfvpd0gwbr6vhfb4)"，集成电源，TTL，RS232，RS485专门为设备调试设计,或者任意自己熟悉的串口调试工具。

# 二、必要条件

**2.1、\*\*\*\*如果您是首次使用DTU配置平台，请先参考**[**《WEB配置入门教程》**](https://yinerda.yuque.com/yt1fh6/4gdtu/textbcabgx9evwvd)**进行操作，包括设备的添加、分组的创建以及设备在分组中的分配。随后，依据本页指南完成云平台的参数设置及建立连接。**

\*\*2.\*\*2、设备接上天线，插上卡，正常10W电源供电，NET LED 500ms或者1000ms闪烁一次，表示网络正常。

# 三、配置参数图文教程

**注意:文档的图片直接看比较模糊，点击图片，放大看。**

## 3.1、注册ThingsBoard账号

点击进入ThingsBoard平台，点击试用。

注册账号，可以使用QQ邮箱注册，并在邮箱中激活。

## 3.2、添加设备

登录到您的 ThingsBoard 实例并转到 “Entities” 部分的 “Devices” 页面，单击表格右上角的“+”图标，然后从下拉菜单中选择“添加新设备”。

输入设备名称，例如，“test”；点击钢笔图标，编辑配置文件。

下拉协议选择MQTT，这里给了三个topic，1号topic是设备遥测数据发布topic，2号topic是服务器属性下发topic，稍后需要填入DTU配置平台。点击“save”保存。

点击“Add”添加。

**mqtt.thingsboard.cloud** 是服务器地址 **1883**是端口号 这些是MQTT配置参数，需要填入DTU参数配置平台。

点击设备添加好的设备，点击“copy access token”可以复制用户名，此参数也需要填入DTU参数配置平台。

## 3.3、配置DTU参数

在“网络通道参数”界面根据ThingsBoard Cloud参数填写MQTT参数。

配置串口参数。

配置完参数后，点击保存参数，断电重启设备，等待设备更新参数。

如果你只有一台设备，可以在分组里面，观察未更新设备数量，如果是0表示更新。

如果有多台设备，可以在设备列表里面查看，当“分组参数版本” 等于“设备参数版本”，表示参数更新了。

## 3.4、数据上报

参数更新后，刷新页面，可以看到DTU成功连接到ThingsBoard Cloud，

点击设备，“点击check connectivity”。

打开串口测试工具，并连接串口发送遥测数据 {"temperature":29}

可以看到已发布的“temperature”数据

## 3.5、数据下发

点击设备进入详情，点击“Attributes”，选择“Shared attributes”，点击加号添加。

添加key为“out”，格式“string”，内容“open”，点击“Add”后会自动下发并显示下发记录。

在串口工具可以看到收到的json数据，键为out，内容为open。

# 四、注意事项

通过以上步骤就实现了设备与平台的对接和简单的数据交互流程。至于平台的深入使用请查询相关社区文档。

演示里面只设置了一个订阅和一个发布topic。当需要使用多topic订阅/发布数据的时候，需要配合任务实现多topic 数据的发送，可以找工程师询问或者参考demo[https://yinerda.yuque.com/yt1fh6/4gdtu/zr39kum9autnqd6k](https://yinerda.yuque.com/yt1fh6/4gdtu/zr39kum9autnqd6k)