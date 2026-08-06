<title>合宙AT固件超低功耗方法</title>

# 合宙AT固件超低功耗方法

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/kakaiw295gf0krwh  
> 路径: 合宙模组系列AT固件使用方法 > 合宙AT固件超低功耗方法

# 一、官方资料

模组厂家官方超低功耗实现方法:[https://doc.openluat.com/wiki/50?wiki_page_id=4917](https://doc.openluat.com/wiki/50?wiki_page_id=4917)

# 二、固件需求

不是所有的固件都支持超低功耗，需要下载对应的固件:[https://doc.openluat.com/article/4922#](https://doc.openluat.com/article/4922)

固件升级教程参考:[https://yinerda.yuque.com/yt1fh6/4gdtu/ro5h186muxf5sngy](https://yinerda.yuque.com/yt1fh6/4gdtu/ro5h186muxf5sngy)

# 二、特殊说明

官方资料是基于模组来测试的，实际产品中，还包括了DC-DC芯片，RS485，运放，LED等其他电路需要消耗电能。要通过硬件系统设计，尽量降低功耗。

低功耗不代表最大功率变小了。对电源的要求还是3.8V 2A，7.6W功率以上，低功耗只是平均功耗降低了，不代表瞬间功率降低，如果电源功率不足，会导致死机。

如果有外部看门狗也影响设备唤醒周期，因为外部看门狗需要周期喂狗。

如果自身系统具有低功耗MCU，不使用网络唤醒的情况下，需要传数据的时候，MCU控制4G模块电源通断，是最节省电能的。

如果没有低功耗MCU，或者只能4G设备作为主机，周期自动唤醒或者服务器网络唤醒系统的时候，就必须用低功耗模块了。

如果有太阳能充电供电，一般不用过于关注低功耗，用普通功耗基本能满足。

YED-D780L1-Y，YED-D780L2-Y，YED-M780E-C，YED-M780EG-C等为超低功耗优化设计的。

如果你需要更多低功耗成品，可以做定制硬件设计。