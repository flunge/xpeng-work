<title>Air780EPM系列透传固件更新日志</title>

# Air780EPM系列透传固件更新日志

> 来源: https://yinerda.yuque.com/yt1fh6/4gdtu/vfo805a24dfptz7s  
> 路径: 固件下载和升级方法 > Air780EPM系列透传固件更新日志

说明:Air780EPM，比Air780EP/Y100EP内存大很多，任务可以做更复杂的功能,可以跑50K任务。如果Air780EP/Y100EP做任务内存不够的时候，更换Air780EPM/Y100EPM方案

# 一、固件版说明

Air780EPM模块不在对外提供固件版本。如果写任务崩溃，按住Rload按键，然后给设备上电，然后保持Reload按键15秒左右，松开Rload按键，理论就应该恢复出厂设置。

原因是：

银尔达DTU要重新烧录固件，不能擦除模块的flash数据，否则授权数据会丢失，模块必须返厂授权。

如果是自己那设备二次开发烧录过自己的固件，需要重新烧录我们的固件，设备能返回正常命令，但是100秒回重启，模块必须返厂授权才能正常工作。



# 二、关于离线储存问题

DTU可以做离线储存。DTU硬件有一定的flash。关键是要存多久时间，储存频率，每次数据多长。可以更换Air780EHM方案更大的flash。

如果只是数据，3M左右的数据，一个小时存一次，一次30个字节，可以存4,369天 ， 1M=1024K，1K=1024字节 。

# 三、更新日志

版本YED_DTU4_V2.0.3

日期:202510116

1、增加阀门系列，保存阀门的开关状态0表示未知，1表示开，2表示关闭

2、增加重启回调函数UserRebootBckFun()如果在任务里面调用实现了这个函数会先调用这个函数在执行重启

3、串口缓存从8K改成了16K

4、增加airlbs 付费基站定位功能配置.免费基站定位换成lbsLoc2库，WIFI定位免费模式不支持

5、增加websocket支持设置IPV6功能

版本YED_DTU4_V2.0.2

日期:20251013

1、固件基于LuatOS-SoC_V2016_Air780EPM_103.soc

2、增加lbsLoc2库

版本YED_DTU4_V2.0.1

日期:20250916

1、固件基于LuatOS-SoC_V2014_Air780EPM_103.soc打包解决os.time()可能有概率死机问题

2、增加airlbs库，可以在任务里面调用付费的定位API，增加基站定位精度

版本YED_DTU4_V2.0.0

日期:20250811

1、固件基于LuatOS-SoC_V2012_Air780EPM_103.soc打包

2、添加配置文件pins_Air780EPM.json

3、修复SSL客户端证书异常问题

4、模组增加授权信息,必须授权才能使用,否则100秒左右自动重启

版本V1.0.1

日期:20250610

1、固件基于LuatOS-SoC_V2007_Air780EPM.soc打包

2、优化ADC采集精度，初始化ADC范围为adc.ADC_RANGE_MIN 后采集电压，数据更精确

3、增加API PerAdcSetScale PerAdcReInitParam PerAdcReOpenAdc 重新在任务里面初始化ADC

4、默认就支持国密SM2，SM4加密



版本V1.0.0

日期:20250429

1、基于Y100EP DTU固件 V1.1.17功能修改，支持次版本之前的全部个功能

2、固件基于LuatOS-SoC_V2005_Air780EPM.soc

3、网络通道支持4路通道(Y100EP系列是2路)

4、串口缓存支持8K(Y100EP系列是4K)