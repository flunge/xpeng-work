<title>小程序 App 设计（三端）</title>

# 小程序 App 设计（三端）

<callout emoji="💡">
微信小程序原生 + 微信云开发，用户/教练/管理员三端。运营数字化基础功能已实现；设备交互/成绩展示随量产落地。
</callout>

## 一、技术栈与结构

- 框架：微信小程序原生（基础库 3.15.2+）+ 微信云开发
- 主题：主色黄 #FFC928 / 红（选中）#F2554A；单位 rpx（750 设计稿）；颜色走主题 CSS 变量
- 云函数调用：统一封装层，按事件类型路由到各服务模块

## 二、三端页面结构

| 端 | 主要页面 |
|-|-|
| 用户端 | 首页(城市定位+Banner+门店+教练+打榜) · 预约(周日历+筛选+课程+等位) · 训练(已约/已完结/补课+直播+课评+请假) · 我的(课卡+合同+多孩+订单+设置) · 我的设备(蓝牙标定/姿态 + 计时标签扫码绑定/解绑，一人一标签) |
| 教练端（子包） | 课程 CRUD · 我的 |
| 管理员端（子包） | 后台管理 · 设备管理（连接/姿态系统/触发系统）· 计时标签管理（RFID 绑定记录/发卡/解绑，devices-hub 入口） |

## 三、云函数调用流（伪代码）

```js
// 统一封装：小程序 → 云函数单入口 → 按 type 路由 → 服务模块
async function callCloud(type, data):
    res = await wx.cloud.callFunction({ name:'quickstartFunctions', data:{type, ...data} })
    if not res.result.success: toast(res.result.errMsg); return null
    return res.result.data
// 示例：查我的设备
devices = await callCloud('getMyDevice', { openid })
// 示例：激活设备（绑定）
await callCloud('activateDevice', { deviceId, adminKey })
```

**计时标签 EPC（services/device.js）**：EPC 一卡一码固定不变，编码 ST-NNNN 的 ASCII 左对齐右补 0x00 到 12 字节 hex（小程序 rfid-ble.js／云端／固件三端一致）。用户端 `bindEpc`(扫码/手输，三态防误扫，一人一标签替换保护) / `unbindEpc`(解绑，仅改归属、EPC 不动)；管理员端 `adminListTagBindings`/`adminUnbindEpc`/`adminRegisterIssued`(发卡登记，均 requireAdmin)。**发卡↔绑定防空卡闭环**：发卡（BLE 写物理标签，见管理端发卡）成功后小程序调 adminRegisterIssued 登记 issuedCards 台账；bindEpc 绑定前校验 issuedCards——未发卡的 EPC 拒绝绑定，杜绝扫空白码绑成功却过线认不到人。绑定/解绑同步 devices.epc + issuedCards.boundPhone（syncIssuedOwner）。EPC 全局唯一靠云端 devices.epc + issuedCards.epc 唯一索引兜底（防先查后写竞态）。发卡走 BLE 因微信小程序不能直连局域网 IP（仿 tag WiFi-OTA）：小程序连 base-rfid → 读最强 RSSI 卡 → 写 EPC → base 驱动 MA82 两包写卡(Select+Write+回读校验) → notify 结果。

## 四、设备管理页（管理员端，核心交互）

```js
// 设备管理页两大 Tab：姿态系统 + 触发系统（经 BLE 连车载设备）
onLoad:
    bleConnect(device)                       // 搜索并连最强的 tag
onStateInfo(bitmap):                          // 传感器在线位图
    render(imu, baro, lf, gyroCalibrated, accelCalibrated)
// 姿态系统：陀螺标定 / 加计六面 / 实时姿态 / 文件管理
startGyroCalib: 静置采集 ≥10s → 落盘设备 NVS
startAcc6Calib: 6 面各稳定 5s+采集 ≥10s → 全部完成落盘
onPose(rpy): drawHorizon(roll,pitch); showYaw(相对)
// 触发系统：激励器 ID + 红绿灯 + RSSI 时间曲线
onLf(signal, baseId, mag): 灯(绿=已触发/红=未触发); chart.push(mag)
```

## 五、交付前静态校验（硬约束）

1. WXML/WXSS/JSON 校验（标签闭合、绑定与大括号配平、JSON 合法）
2. 改动的 JS 跑语法检查
3. 改数据跑数据库构建脚本，看外键 + 一致性通过

数据—显示—逻辑闭环：每条数据都被消费、每个显示元素都有真实数据支撑、三端口径一致。

## 六、相关

BLE 协议见 [BLE 对接协议](https://fqmtvue07d8.feishu.cn/docx/FT93djQoKo1V7Ax3o0Fc93nen5c)；云端见 [云端设计](https://fqmtvue07d8.feishu.cn/docx/AJFRds2bQoBrLFxOKzScGRjqn7f) 与 [计时数据云](https://fqmtvue07d8.feishu.cn/docx/PxgUdk56Uo4aK5xq4pAcb3QQnKe)。