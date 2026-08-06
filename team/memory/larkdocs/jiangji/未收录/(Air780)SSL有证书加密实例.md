<title>(Air780)SSL有证书加密实例</title>

# (Air780)SSL有证书加密实例

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/egolpofpm3efac2e  
> 路径: DTU固件实例讲解 > (Air780)SSL有证书加密实例

目前只有Air780支持,固件版本等于大于V1.1.12，证书版本只支持TLS1.2版本。

本例使用MQTT协议测试。还支持TCP，HTTP协议。与普通协议的区别就是多了证书的配置方法。

# 一、工具简介

DTU配置平台:[https://dtu.yinerda.com](https://dtu.yinerda.com)

DTU测试平台:[http://test.yinerda.com](http://test.yinerda.com)

串口测试软件:"[YEDTestTools](https://yinerda.yuque.com/yt1fh6/4gdtu/rfvpd0gwbr6vhfb4)"软件,或者任意自己熟悉的串口调试软件。

USB转串口调试工具:"[YED-UUART-211](https://yinerda.yuque.com/yt1fh6/4gdtu/rfvpd0gwbr6vhfb4)"，集成电源，TTL，RS232，RS485专门为设备调试设计,或者任意自己熟悉的串口调试工具。

# 二、必要条件

2.1、参考[《WEB配置入门教程》](https://yinerda.yuque.com/yt1fh6/4gdtu/textbcabgx9evwvd)，完成**添加设备，创建分组，分组里面分配设备。**

\*\*2.\*\*2、设备接上天线，插上卡，正常10W电源供电，NET LED 500ms或者1000ms闪烁一次，表示网络正常。

# 三、配置流程

其他配置和非加密MQTT一样填写即可，只是配置证书的地方有区别。

普通MQTT协议参考:[https://yinerda.yuque.com/yt1fh6/4gdtu/qqvrgz251f9tu1u1#](https://yinerda.yuque.com/yt1fh6/4gdtu/qqvrgz251f9tu1u1)

## 3.1、配置MQTT协议通道

配置自己的服务器信息，示例的服务器无效。

## 3.2、配置证书

证书版本只支持TLS1.2版本。根据自己服务器的需求，填写对应对应的证书，不是全部证书都必要。

用文本编辑器，打开证书文件后数据即可，拷贝的时候，注意不要多不要少，不要有空格等。

配置后重启更新参数即可，使用方法与普通MQTT协议一样使用。

# 四、注意事项

1、如果USB打开了日志，会输出配置的证书信息，调试的时候可以打开，后面记得关闭，避免证书泄露。

2、如果连接不正常可以先用MQTT.fx等电脑工具，使用证书连接一下自己的服务器看是否正常，如果正常后再用DTU测试。