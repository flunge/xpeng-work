<title>13、以太网WIFI融合网络配置命令</title>

# 13、以太网WIFI融合网络配置命令

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/cnvsp9t30g8nianb  
> 路径: DTU指令手册 > 13、以太网WIFI融合网络配置命令

本文档记录的目前Air8000支持。可以实现4G，以太网，WIFI同时使用。

# 一、以太网参数

## 1、获取以太网MAC命令-emac

|  |  |  |
|-|-|-|
| 功能 | 获取以太网mac |  |
| 查询参数 | 无 |  |
| 返回参数 | mac |  |
| 查询实例 | config,get,emac\r\n \r\nconfig,emac,ok,DC3262611006\r\n |  |

## 2、获取以太网网线连接状态命令-elink

|  |  |  |
|-|-|-|
| 功能 | 获取以太网网线连接状态 |  |
| 查询参数 | 无 |  |
| 返回参数 | 0:网线没连接 1:网线连接 |  |
| 查询实例 | config,get,elink\r\n \r\nconfig,elink,ok,1\r\n |  |

## 3、设置以太网IP命令-eip

|  |  |  |
|-|-|-|
| 功能 | 设置以太网IP |  |
| 设置参数 | 参数 | 描述 |
|  | 是否打开dhcp | 0:关闭 1:打开 |
|  | 静态IP | dhcp设置为0填写静态IP dhcp设置为1填写全0“0.0.0.0”   |
|  | 掩码 |  |
|  | 网关 |  |
| 设置实例 | config,set,eip,1,"0.0.0.0","0.0.0.0","0.0.0.0"\r\n \r\nconfig,eip,ok\r\n config,set,eip,0,"192.168.1.200","255.255.255.0","192.168.1.1"\r\n \r\nconfig,eip,ok\r\n |  |
| 查询参数 | 无 |  |
| 返回参数 | 和设置参数一样 |  |
| 查询实例 | config,get,eip\r\n \r\nconfig,eip,ok,1,192.168.31.52,255.255.255.0,192.168.31.1\r\n |  |

# 二、WIFI参数

## 1、获取WIFI STATION MAC命令-wsmac

|  |  |  |
|-|-|-|
| 功能 | 获取WIIFI STATION mac |  |
| 查询参数 | 无 |  |
| 返回参数 | mac |  |
| 查询实例 | config,get,wsmac\r\n \r\nconfig,wsmac,ok,DC3262611006\r\n |  |

## 2、获取WIFI STATION 是否连接路由器命令-wslink

|  |  |  |
|-|-|-|
| 功能 | 获取WIFI STATION 是否连接路由器状态 |  |
| 查询参数 | 无 |  |
| 返回参数 | 0:没连接 1:连接 |  |
| 查询实例 | config,get,wslink\r\n \r\nconfig,wslink,ok,1\r\n |  |

## 3、获取WIFI STATION IP命令-wsip

|  |  |  |
|-|-|-|
| 功能 | 获取WIFI STATION IP 开启DHCP后，只有连接路由器了才有IP |  |
| 查询参数 | 无 |  |
| 返回参数 | DCHP | 0:关闭 1:打开 |
|  | 静态IP | 字符串 |
|  | 掩码 | 字符串 |
|  | 网关 | 字符串 |
| 查询实例 | config,get,wsip\r\n \r\nconfig,wsip,ok,1,192.168.31.231,255.255.255.0,192.168.31.1\r\n |  |

## 4、获取WIFI AP MAC命令-wamac

|  |  |  |
|-|-|-|
| 功能 | 获取WIIFI AP mac |  |
| 查询参数 | 无 |  |
| 返回参数 | mac |  |
| 查询实例 | config,get,wamac\r\n \r\nconfig,wamac,ok,DC3262611006\r\n |  |

## 5、获取WIFI AP 是否生成命令-walink

|  |  |  |
|-|-|-|
| 功能 | 获取WIFI AP 是否生成状态 |  |
| 查询参数 | 无 |  |
| 返回参数 | 0:没生成 1:生成 |  |
| 查询实例 | config,get,walink\r\n \r\nconfig,walink,ok,1\r\n |  |

## 3、设置WIFI参数连接参数是-wifiinfo

|  |  |  |
|-|-|-|
| 功能 | 设置WIFI参数 包括WIFI的模式，WIFI热点，WIFI STATION |  |
| 设置参数 | 参数 | 描述 |
|  | WIFI模式 | 0:STATION模式 1:AP模式 2:STATION和AP模式 |
|  | AP WIFI名字 | 支持中文，utf-8 |
|  | AP WIFI密码 |  |
|  | AP 网关 |  |
|  | AP 掩码 | 255.255.255.0 |
|  | Ap 通道 | 1-13 |
|  | AP 是否隐藏 | 0:不隐藏 1:隐藏 |
|  | AP 最大连接客户端数 | 1-4 |
|  | STATION WIFI名字 |  |
|  | STATION WIFI密码 |  |
|  | AP MAC地址 |  |
|  | STATION DHCP | 0:不开开启 1:开启 开启后，后面的IP，掩码，网关，不开启的时候需要设置,IP，掩码，网关 |
|  | STATION IP地址 |  |
|  | STATION 掩码 |  |
|  | STATION 网关 |  |
| 设置实例 | config,set,wifiinfo,0,,,,,0,0,0,yedyftest,yed1234567890,,1,,,\r\n \r\nconfig,wifiinfo,ok\r\n | 设置WIFI模式信息只SATIONM模式,DHCP |
|  | config,set,wifiinfo,0,,,,,0,0,0,银尔达AP路由器,123456,,0,192.168.1.1,255.255.255.0,192.168.1.1\r\n | 设置WIFI模式信息只SATIONM模式,固定IP |
|  | config,set,wifiinfo,1,银尔达设备生成AP,12345678,192.168.1.1,255.255.255.0,6,0,4,,,,0,,,\r\n | 设置WIFI模式信息只AP模式 |
|  | config,set,wifiinfo,2,银尔达设备生成AP,12345678,192.168.1.1,255.255.255.0,6,0,4,yedyftest,yed1234567890,,1,,,\r\n | 设置WIF摸信息STATION+AP模式，DHCP IP |
| 查询参数 | 无 |  |
| 返回参数 | 和设置参数一样 |  |
| 查询实例 | config,get,wifiinfo\r\n \r\nconfig,wifiinfo,ok,2,银尔达设备生成AP,12345678,192.168.1.1,255.255.255.0,6,0,4,yedyftest,yed1234567890,,1,,,\r\n |  |

# 三、设置网络通道网卡

## 1、设置网络通道网卡命令-nic

|  |  |  |
|-|-|-|
| 功能 | 设置通道网卡类型 不设置，不去启动，默认是4g |  |
| 设置参数 | 参数 | 描述 |
|  | 通道1网卡 | 0：4G网络 1：以太网 2：WIFI STATION 3：WIFI AP |
|  | 通道2网卡 |  |
|  | 通道3网卡 |  |
|  | 通道4网卡 |  |
|  | 通道5网卡 |  |
|  | 通道6网卡 |  |
|  | 通道7网卡 |  |
|  | 通道8网卡 |  |
|  | 网关 |  |
| 设置实例 | config,set,nic,0,1,2,3,0,0,0,0\r\n \r\nconfig,nic,ok\r\n | 设置多通道网卡选择,4G，以太网,WIFI STATION,WIFI AP |
| 查询参数 | 无 |  |
| 返回参数 | 和设置参数一样 |  |
| 查询实例 | config,get,nic\r\n \r\nconfig,nic,ok,0,1,2,3,0,0,0,0\r\n |  |



# 四、Ping命令-ping

|  |  |  |
|-|-|-|
| 功能 | 设置Ping命令 |  |
| 设置参数 | 参数 | 描述 |
|  | 目标地址 | 支持域名和IP |
|  | 地址类型 | 0:IP 1:域名 |
|  | 网卡 | 4G：4G ETH：以太网 WIFIS：WIFI STATION WIFIA：WIFI AP |
| 返回值 | 参数 |  |
|  | 时间 | 单位ms |
|  | 目标IP |  |
| 实例 | config,set,ping,www.baidu.com,1,4G\r\n \r\nconfig,ping,ok,91,111.45.11.5\r\n | 请求域名，4G |
|  | config,set,ping,118.195.188.216,0,ETH\r\n \r\nconfig,ping,ok,70,118.195.188.216\r\n | 请求IP，以太网 |
|  | config,set,ping,www.baidu.com,1,WIFIA\r\n \r\nconfig,ping,error,2\r\n | 网络不通，不可达，返回2 |