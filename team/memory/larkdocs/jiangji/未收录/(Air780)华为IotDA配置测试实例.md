<title>(Air780)华为IotDA配置测试实例</title>

# (Air780)华为IotDA配置测试实例

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/zyxif86xpi8okziu  
> 路径: DTU固件实例讲解 > (Air780)华为IotDA配置测试实例

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

# 三、创建产品获取参数

进入连接:[https://www.huaweicloud.com](https://www.huaweicloud.com)。平台必须配合任务使用。因为平台下发的命令必须按规则应答平台，否则平台会认为命令下发失败，推送异常提醒给业务平台。

整体流程是创建实例，创建产品，添加设备，配置参数，更新参数，使用任务处理topic。

## 3.1、开通实例

开通设备接入IoTDA服务，选择服务器区域，创建实例。在实例里面获取服务器地址和端口，实例ID，应用接入HTTPS地址，区域到时影响到IAM的服务器地址和IAM账号的项目ID和项目选择。

## 3.2、创建产品

据需求选择，协议类型MQTT，数据格式，JSON，设备类型选择自定义，设备类型任意，测试。

## 3.3、获取产品ID

## 3.4、空间资源APPID

## 3.5、获取IAM服务器地址

IAM服务器地址与账号区域有对应。选择连接:[https://support.huaweicloud.com/api-iam/iam_01_0004.html](https://support.huaweicloud.com/api-iam/iam_01_0004.html)

## 3.6、创建IAM账号

IAM账号是用来自动创建设备用的，注意这个号码的权限限制，不能过大。这个账号信息需要保密，在DTU账号里面设置参数密码，防止别人从串口里面读出IAM账号信息。

创建IAM账号，首先主账号，开通IAM账号。然后换成IAM账号登录，然后获取IAM账户信息。

## 3.7、获取IAM账号信息

创建IAM账号后用IAM账号登录，账号信息，我的凭证，获取IAM用户名，账号名，项目，项目ID。项目和项目ID，与账号区域有对应。

## 3.8、topic介绍说明

产品详情，topic管理里面，有个系统预制topic，这里我们使用透传的topic即可。

$oc/devices/{device\_id}/sys/messages/up 和 $oc/devices/{device_id}/sys/messages/down 中把{device_id}用\${IMEI}替代。

发布消息主题 $oc/devices/${IMEI}/sys/messages/up

订阅消息主题 $oc/devices/${IMEI}/sys/messages/down

# 四、配置参数

## 4.1、根据产品配置参数

拷贝参数的时候，注意不要检查是否有空格，如果有要去掉。IAM 账户密码注意保密，可以在基本参数里面设置密码，防止被串口读出参数泄密。

## 4.2、更新参数

配置完参数后，点击保存参数，断电重启设备，等待设备更新参数。

如果你只有一台设备，可以在分组里面，观察未更新设备数量，如果是0表示更新。

如果有多台设备，可以在设备列表里面查看，当“分组参数版本” 等于“设备参数版本”，表示参数更新了。

## 4.3、观察服务器连接情况

如果参数正确，在设备，所有设备，就能看到DTU自动注册的设备，设备使用IMEI注册的。

## 4.4、服务器发送数据到串口

如果是纯透传topic，无法在控制平台发测试命令，需要调用API才能下发数据。如果使用物模型可以下发命令。

## 4.5、串口透传数据到服务器

DTU收到的任何数据，都会透传给服务器。包括HEX数据，只是平台会显示乱码。用API可以解析。

进入设备列表，点击 调试，调试设备

选择调试设备

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

本任务实现是DTU透传topic名字+，+数据给串口。串口发送topic名字+，+数据指定topic给服务器。下面demo直接拷贝到任务就能用。MCU可以通过收到的topic名字处理解析数据,组织topic名字应答服务器。

topic中的device id就是模块的IMEI，可以通过config,get,imei获取。

配置参数的时候，有ID的topic支持+通配符，接收所有的数据。比如:

$oc/devices/${IMEI}/sys/messages/down;$oc/devices/${IMEI}/sys/commands/+;$oc/devices/${IMEI}/sys/properties/set/+;$oc/devices/${IMEI}/sys/properties/get/+;$oc/devices/${IMEI}/sys/shadow/get/response/+;$oc/devices/${IMEI}/sys/events/down

数据上报的格式必须遵循平台物模型格式，本质就是json组织和topic组装，参考官方资料:

[https://support.huaweicloud.com/devg-iothub/iot_02_2200.html](https://support.huaweicloud.com/devg-iothub/iot_02_2200.html)



## 4.8、物模型自动解析数据任务示例

每个特定产品功能不一样，无法做标准的，可以联系销售定制解析过程。比如需要控制RTU的继电器或者周期采集数字量，模拟量或者解析Modbus数据自动上传等功能。

这些功能的本质是组装json格式数据，然后用对应的topic上传即可。