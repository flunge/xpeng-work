<title>(Air780)阿里IOT配置测试实例</title>

# (Air780)阿里IOT配置测试实例

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/dcvex15v33ly1i2b  
> 路径: DTU固件实例讲解 > (Air780)阿里IOT配置测试实例

目前只有Air780支持,固件版本等于大于V1.1.1



使用任何平台本质都是MQTT协议协议通讯，这个难点是搞清楚平台的通讯规则，理清楚订阅topic，发布topic和数据格式（物模型）。

DTU目前是解决了平台基本的连接和交互问题，根据教程连接平台后，在实际实现自己的业务上用不起来。这个本质的原因是不清楚平台如何使用，平台需要的topic和物模型数据格式不清楚导致的。所以基本步骤测试完成后就要研究平台的文档和询问平台的技术支持，清楚topic和数据格式后，在继续下一步结合银尔达的技术支持，让DTU按自己业务需求上传和解析数据。

# 一、工具简介

DTU配置平台:[https://dtu.yinerda.com](https://dtu.yinerda.com)

DTU测试平台:[http://test.yinerda.com](http://test.yinerda.com)

串口测试软件:"[YEDTestTools](https://yinerda.yuque.com/yt1fh6/4gdtu/rfvpd0gwbr6vhfb4)"软件,或者任意自己熟悉的串口调试软件。

USB转串口调试工具:"[YED-UUART-211](https://yinerda.yuque.com/yt1fh6/4gdtu/rfvpd0gwbr6vhfb4)"，集成电源，TTL，RS232，RS485专门为设备调试设计,或者任意自己熟悉的串口调试工具。

# 二、必要条件

**2.1、\*\*\*\*如果您是首次使用DTU配置平台，请先参考**[**《WEB配置入门教程》**](https://yinerda.yuque.com/yt1fh6/4gdtu/textbcabgx9evwvd)**进行操作，包括设备的添加、分组的创建以及设备在分组中的分配。随后，依据本页指南完成云平台的参数设置及建立连接。**

\*\*2.\*\*2、设备接上天线，插上卡，正常10W电源供电，NET LED 500ms或者1000ms闪烁一次，表示网络正常。

# 三、视频教程

# 四、图文教程-创建产品

进入连接:[https://iot.console.aliyun.com](https://iot.console.aliyun.com)。整体流程是创建产品，配置参数，更新参数，使用任务处理topic。

注意:阿里IOT一型一密只能激活一次，激活后参数会保存到DTU flash中，如果设备更换了产品信息，先删除阿里云平台的设备，然后再重新添加设备，然后DTU Reload按键清除设备里面保存的阿里信息，重新获取参数后，连接阿里云，否则连不上。

## 3.1、开通实例

实例里面能获取到实例ID

## 3.2、获取服务器地址信息

进入设备详情，查看开发配置，获取MQTT服务器地址信息

## 3.3、创建产品

所属品类选择自定义品类，节点类型选择直连设备，联网与数据选择蜂窝(2G/3G/4G/5G),数据格式选择透传/自定义。

## 3.4、获取Productkey 和ProductSecret参数

## 3.5、开启动态注册

## 3.6、获取topic主题



## 3.7、添加设备

设备，添加设备，使用IMEI在平台提前添加设备，这个可以用表格批量添加，销售出货的时候可以提供设备IMEI。

# 五、图文教程-配置参数

## 4.1、根据产品配置参数

注意topic用\${IMEI}变量替代，在topic类列表，自定义Topic中，

/hhu5CevgOpg/${deviceName}/user/get 和 /hhu5CevgOpg/${deviceName}/user/update

在DTU配置平台配置的实际参数，需要把${deviceName}换成${IMEI}，格式如下:

DTU订阅消息主题填: /hhu5CevgOpg/\${IMEI}/user/get

DTU发布消息主题填: /hhu5CevgOpg/\${IMEI}/user/update

## 4.2、更新参数

配置完参数后，点击保存参数，断电重启设备，等待设备更新参数。

如果你只有一台设备，可以在分组里面，观察未更新设备数量，如果是0表示更新。

如果有多台设备，可以在设备列表里面查看，当“分组参数版本” 等于“设备参数版本”，表示参数更新了。

## 4.3、观察服务器连接情况

如果参数正确，自动激活设备，可以刷新页面。

## 4.4、服务器发送数据到串口

设备列表，查看，进入设备详情，topic列表，可以看到设备订阅的topic，在这里发送调试数据。

注意控制台无法发送\r\n回车换行，所以无法调试config命令，需要调用阿里API发送才能发\r\n回车换行。

## 4.5、串口透传数据到服务器

在日志服务，里面可以观察到设备上报的数据。

## 4.6、服务器远程控制设备

方法1：

使用透传topic，服务器调用API发送数据，可以发送config命令控制查询设备。

命令详情查看DTU命令手册:[https://yinerda.yuque.com/yt1fh6/4gdtu/zyngfvlgylqny15n](https://yinerda.yuque.com/yt1fh6/4gdtu/zyngfvlgylqny15n)

方法2:

使用透传topic，服务器调用API发送数据，可以使用任务的方式，解析服务器数据，控制设备查询设备。

使用任务控制继电器参考:[https://yinerda.yuque.com/yt1fh6/4gdtu/wzlywm8diivdv551](https://yinerda.yuque.com/yt1fh6/4gdtu/wzlywm8diivdv551)

复制任务到DTUWEB平台，更新参数，控制台发送{"cmd":"on1"}控制继电器，{"cmd":"off1"}关闭继电器1。

方法3:

使用物模型topic，必须配合任务才能控制和查询设备。



## 4.7、物模型透传topic任务示例

创建产品的时候数据协议选择物模型。

本任务实现是DTU透传topic名字+，+数据给串口。串口发送topic名字+，+数据指定topic给服务器。下面demo直接拷贝到任务就能用。MCU可以通过收到的topic名字处理解析数据,组织topic名字应答服务器。

topic中的deviceName就是模块的IMEI，可以通过config,get,imei获取。

物模型订阅topic例如:

/sys/hhu5TCskhvy/${IMEI}/thing/event/property/post\_reply;/sys/hhu5TCskhvy/${IMEI}/thing/service/property/set;/sys/hhu5TCskhvy/${IMEI}/thing/event/+;/sys/hhu5TCskhvy/${IMEI}/thing/service/+

数据上报格式必须遵循平台物模型格式，本质就是json组织和topic组装，参考官方资料:

[https://help.aliyun.com/zh/iot/user-guide/what-is-topic?spm=a2c4g.11186623.0.0.57227e94XW0bDL#25c668097calq](https://help.aliyun.com/zh/iot/user-guide/what-is-topic?spm=a2c4g.11186623.0.0.57227e94XW0bDL#25c668097calq)

## 4.8、物模型自动解析数据任务示例

每个特定产品功能不一样，无法做标准的，可以联系销售定制解析过程。比如需要控制RTU的继电器或者周期采集数字量，模拟量或者解析Modbus数据自动上传等功能。

这些功能的本质是组装json格式数据，然后用对应的topic上传即可。