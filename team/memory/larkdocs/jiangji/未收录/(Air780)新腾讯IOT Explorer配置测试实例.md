<title>(Air780)新腾讯IOT Explorer配置测试实例</title>

# (Air780)新腾讯IOT Explorer配置测试实例

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/lepikshg8p42xn73  
> 路径: DTU固件实例讲解 > (Air780)新腾讯IOT Explorer配置测试实例

目前只有Air780支持,固件版本等于大于V1.1.1



使用任何平台本质都是MQTT协议协议通讯，这个难点是搞清楚平台的通讯规则，理清楚订阅topic，发布topic和数据格式（物模型）。

DTU目前是解决了平台基本的连接和交互问题，根据教程连接平台后，在实际实现自己的业务上用不起来。这个本质的原因是不清楚平台如何使用，平台需要的topic和物模型数据格式不清楚导致的。所以基本步骤测试完成后就要研究平台的文档和询问平台的技术支持，清楚topic和数据格式后，在继续下一步结合银尔达的技术支持，让DTU按自己业务需求上传和解析数据。

# 一、使用需知(必看)

腾讯云发布公告，从2024年06月20日起，新注册物联网开发平台的用户需购买公共实例激活码才可使用公共实例，在此时间之前注册的用户并已开通公共实例的用户则不受影响。所以此链接方式只适合于2024年06月20日前注册账号的用户，此日期之后注册的账户，不再提供免费公共实例，需要在腾讯云付费购买。

# 二、工具简介

DTU配置平台:[https://dtu.yinerda.com](https://dtu.yinerda.com)

DTU测试平台:[http://test.yinerda.com](http://test.yinerda.com)

串口测试软件:"[YEDTestTools](https://yinerda.yuque.com/yt1fh6/4gdtu/rfvpd0gwbr6vhfb4)"软件,或者任意自己熟悉的串口调试软件。

USB转串口调试工具:"[YED-UUART-211](https://yinerda.yuque.com/yt1fh6/4gdtu/rfvpd0gwbr6vhfb4)"，集成电源，TTL，RS232，RS485专门为设备调试设计,或者任意自己熟悉的串口调试工具。

# 三、必要条件

**2.1、\*\*\*\*如果您是首次使用DTU配置平台，请先参考**[**《WEB配置入门教程》**](https://yinerda.yuque.com/yt1fh6/4gdtu/textbcabgx9evwvd)**进行操作，包括设备的添加、分组的创建以及设备在分组中的分配。随后，依据本页指南完成云平台的参数设置及建立连接。**

\*\*2.\*\*2、设备接上天线，插上卡，正常10W电源供电，NET LED 500ms或者1000ms闪烁一次，表示网络正常。

# 四、创建产品

进入连接:[https://cloud.tencent.com/product/iothub](https://cloud.tencent.com/product/iothub)。整体流程是创建产品，配置参数，更新参数，使用任务处理topic。

注意:腾讯IOT一型一密只能激活一次，激活后参数会保存到DTU flashe中，如果设备更换了产品信息，需要Reload按键清除设备里面保存的腾讯信息，否则连不上。

## 4.1、创建产品

开通IOT服务，新增实例。这里以公共实例为例，这个默认有10个设备可以连接。

产品品类根据实际选择，这里选其他行业，自定义产品，设备类型选择设备，通讯方式选择2G/3G/4G,数据协议选择透传。

## 4.2、开启动态注册

## 4.3、获取产品ID和产品密匙

## 4.4、获取topic主题

透传topic $thing/up/raw/3WKT1X0IQ5/${deviceName}和$thing/down/raw/3WKT1X0IQ5/${deviceName}

需要把${deviceName}换成${IMEI}自动替换。

订阅消息主题填写 $thing/down/raw/3WKT1X0IQ5/${IMEI}

发布消息主题填写 $thing/up/raw/3WKT1X0IQ5/${IMEI}

## 4.5、添加设备

设备调试，新建设备，使用IMEI在平台提前添加设备。

# 五、配置参数

## 5.1、根据产品配置参数

注意topic用\${IMEI}变量替代。

## 5.2、更新参数

配置完参数后，点击保存参数，断电重启设备，等待设备更新参数。

如果你只有一台设备，可以在分组里面，观察未更新设备数量，如果是0表示更新。

如果有多台设备，可以在设备列表里面查看，当“分组参数版本” 等于“设备参数版本”，表示参数更新了。

## 5.3、观察服务器连接情况

如果参数正确，自动激活设备，可以刷新页面。

## 5.4、服务器发送数据到串口

透传topic无法再调试界面下发数据，调用API可以发送数据。

## 5.5、串口透传数据到服务器

## 5.6、服务器远程控制设备

方法1：

使用透传topic，服务器调用API发送数据，可以发送config命令控制查询设备。

命令详情查看DTU命令手册:[https://yinerda.yuque.com/yt1fh6/4gdtu/zyngfvlgylqny15n](https://yinerda.yuque.com/yt1fh6/4gdtu/zyngfvlgylqny15n)

方法2:

使用透传topic，服务器调用API发送数据，可以使用任务的方式，解析服务器数据，控制设备查询设备。

使用任务控制继电器参考:[https://yinerda.yuque.com/yt1fh6/4gdtu/wzlywm8diivdv551](https://yinerda.yuque.com/yt1fh6/4gdtu/wzlywm8diivdv551)

复制任务到DTUWEB平台，更新参数，控制台发送{"cmd":"on1"}控制继电器，{"cmd":"off1"}关闭继电器1。

方法3:

使用物模型topic，必须配合任务才能控制和查询设备。

## 5.7、物模型透传topic任务示例

创建产品的时候数据协议选择物模型。

本任务实现是DTU透传topic名字+，+数据给串口。串口发送topic名字+，+数据指定topic给服务器。下面demo直接拷贝到任务就能用。MCU可以通过收到的topic名字处理解析数据,组织topic名字应答服务器。

topic中的deviceName就是模块的IMEI，可以通过config,get,imei获取。

物模型订阅topic例如:

$thing/down/property/LQEJHV8W9V/${IMEI};$thing/down/event/LQEJHV8W9V/${IMEI};$thing/down/action/LQEJHV8W9V/${IMEI}

数据上报的格式必须遵循平台物模型格式，本质就是json组织和topic组装，参考官方资料:

[https://cloud.tencent.com/document/product/1081/34916](https://cloud.tencent.com/document/product/1081/34916)

## 5.8、物模型自动解析数据任务示例

每个特定产品功能不一样，无法做标准的，可以联系销售定制解析过程。比如需要控制RTU的继电器或者周期采集数字量，模拟量或者解析Modbus数据自动上传等功能。

这些功能的本质是组装json格式数据，然后用对应的topic上传即可。