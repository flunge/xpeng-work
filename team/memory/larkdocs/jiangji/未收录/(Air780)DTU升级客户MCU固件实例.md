<title>(Air780)DTU升级客户MCU固件实例</title>

# (Air780)DTU升级客户MCU固件实例

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/sdaxhokk7vbdfhuh  
> 路径: DTU固件实例讲解 > (Air780)DTU升级客户MCU固件实例

目前只有Air780支持,固件版本等于大于V1.1.12。

注意DTU对设备进行固件升级，本质是用HTTP协议，分包从服务器下载文件，然后他通过串口透传个客户设备，客户设备通过拼接数据包的方式进行文件拼接、校验，然后在做自己的升级逻辑。

DTU并不保证设备升级固件是否完成，只是最大限度保证按顺序把文件下载下来。

# 一、工具简介

DTU配置平台:[https://dtu.yinerda.com](https://dtu.yinerda.com)

DTU测试平台:[http://test.yinerda.com](http://test.yinerda.com)

串口测试软件:"[YEDTestTools](https://yinerda.yuque.com/yt1fh6/4gdtu/rfvpd0gwbr6vhfb4)"软件,或者任意自己熟悉的串口调试软件。

USB转串口调试工具:"[YED-UUART-211](https://yinerda.yuque.com/yt1fh6/4gdtu/rfvpd0gwbr6vhfb4)"，集成电源，TTL，RS232，RS485专门为设备调试设计,或者任意自己熟悉的串口调试工具。

# 二、必要条件

2.1、参考[《WEB配置入门教程》](https://yinerda.yuque.com/yt1fh6/4gdtu/textbcabgx9evwvd)，完成**添加设备，创建分组，分组里面分配设备。**

\*\*2.\*\*2、设备接上天线，插上卡，正常10W电源供电，NET LED 500ms或者1000ms闪烁一次，表示网络正常。

# 三、配置流程

配置前，先看一下以下2个链接,理解流程和功能:

DTU升级客户MCU固件参数配置说明:

[https://yinerda.yuque.com/yt1fh6/4gdtu/gsccog81mv0hpii7#OfWeH](https://yinerda.yuque.com/yt1fh6/4gdtu/gsccog81mv0hpii7#OfWeH)

MCU需要执行的DTU透传固件升级客户固件命令(重点了解升级注意事项):

[https://yinerda.yuque.com/yt1fh6/4gdtu/py7g1e2x5rh7tma1](https://yinerda.yuque.com/yt1fh6/4gdtu/py7g1e2x5rh7tma1)

## 3.1、上传升级文件

银尔达DTU配置平台，支持升级固件文件管理，其中文件ID,是配置参数需要的。当然可以用自己的HTTP文件服务器，需要支持标准的断点续传功能即可,点击复制文件ID可以复制ID。

上传文件的文件名称，文件版本可以自定义，方便自己管理文件。

## 3.2、配置升级参数

文件版本号，是自定义的字符串，最好和上传的文件版本一样，方便管理。需要升级的设备可以通过upcheck命令读取，用于判断是否需要升级。

文件下载路径，如果文件获取方式是文件ID，就填写3.1步骤里面获取到的文件ID。如果选择下载url就填写自己的文件下载路径即可。

数据识别码，如果选择无，升级文件是纯透传的；如果选择有，数据格式是固定格式的"UPFILE:"+"文件总长度:"+"当前长度:"+"本报包长度:"+数据 用来方便计算文件是否下载完成。

配置完参数后，保存参数，重启设备更新参数。

## 3.3、使用串口工具测试下载

命令说明参考:[https://yinerda.yuque.com/yt1fh6/4gdtu/py7g1e2x5rh7tma1#](https://yinerda.yuque.com/yt1fh6/4gdtu/py7g1e2x5rh7tma1)

测试的时候使用串口工具测试，观察一下数据流程，然后再把相应的命令集成到自己的设备里面即可。

使用步骤，先使用upcheck命令 查询需要升级的版本，如果需要升级在执行upin命令。

执行upcheck命令，获取需要升级的版本，如果没配置会返回error

执行upin命令，开始进行固件升级

这个是最后一个升级包

升级结束后，返回了upsta状态命令，如果升级成功返回0，如果失败，参考命令的错误码

# 四、注意事项

下载的分包大小，请求间隔，根据实际情况去测试调试。

upin命令的返回与文件请求实际时间至少间隔3秒。

文件升级包数据与upsta命令，程序里面是间隔6秒。但是由于串口发送数据需要时间，如果串口分包过大，可能导致这个状态与数据包粘连后传送出来所以分包与串口波特率有关系，按理论9600波特率最大包是9600/11\*5约等于4K。