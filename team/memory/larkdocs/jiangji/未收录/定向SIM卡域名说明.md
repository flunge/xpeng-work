<title>定向SIM卡域名说明</title>

# 定向SIM卡域名说明

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/hy2l0bsfxh03yfkr  
> 路径: DTU通用入门教程 > 定向SIM卡域名说明

目前银尔达的SIM卡都不是定向卡，可以连接任意的服务器，只有自己购买的卡可能是定向卡。

表现是网络状态正常，但是无论如何都无法连接服务器，换手机卡就能连上。

如果你使用的定向卡，需要添加DTU用到的域名信息，SIM卡才能访问配置服务器。把下列数据提交到SIM卡供应商即可，供应商给您添加到白名单即可。

银尔达提供的SIM卡，都是普通卡，不需要添加这些域名。

|  |  |  |  |  |
|-|-|-|-|-|
| 域名 | 端口 | 协议 | 作用 | 是否必须 |
| dtu.yinerda.com | 91 | HTTP | WEB参数配置 | 是 |
| dtu.yinerda.com | 81 | HTTP | 升级固件文件服务器 | 否 |
| iot.openluat.com | 80 | HTTP | DTU自身固件升级平台 | 否 |
| bs.openluat.com | 80 | HTTP | WIFI/基站定位平台，基站定位需要 | 否 |
| download.openluat.com | 80 | HTTP | AGPS星历下载平台，GPS定位需要 | 否 |
| cn.pool.ntp.org | 123 | UDP | NTP网络时间同步 | 否 |
| edu.ntp.org.cn | 123 | UDP | NTP网络时间同步 | 否 |
| cn.ntp.org.cn | 123 | UDP | NTP网络时间同步 | 否 |