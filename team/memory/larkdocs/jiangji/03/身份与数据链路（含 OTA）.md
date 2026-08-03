<title>身份与数据链路（含 OTA）</title>

# 阶段 1.5 · 身份与数据链路（EPC → 云端 → App）+ OTA

> 讲清两件事：① RFID 标签的身份体系（EPC/二维码/绑定）；② 从过线到 App 展示的完整数据流；③ 基站封盒后如何无线升级（OTA）。

## 一、标签身份原理

无源 UHF 标签不带电，靠读写器发射的射频能量供电，用**反向散射**把芯片里存的 ID 反射回读写器。

- 身份用 **EPC 码**（芯片里可读可写的一串编号，每张唯一）；
- 还有出厂唯一、不可改的 **TID**（防伪用）；
- EPC 区**可擦写约 10 万次**（够用到报废）。

## 二、二维码绑定 + EPC 配对

标签可镭射二维码。绑定流程：**用户扫二维码 → 得到编号 → 云端把编号绑到 user_id**。

**关键**：过线计时靠 RFID 读 **EPC**（车飞驰而过没法扫码），用户绑人扫 **二维码**——这是两个 ID，必须建立 `EPC ↔ 二维码编号` 的配对。

**最佳做法**：下单要求厂家**「EPC 与二维码用同一编号」**（或提供 EPC-二维码对照 CSV）→ 出厂即配对，省掉对照表。

**可否提前镭射**：二维码内容（编号）**可提前生成让厂家批量镭射**（连号）；但"绑到具体用户"是用户扫码那一刻才发生（镭射时还不知道给谁）。

- 写标签要近距离在**发卡台**做（写距 < 读距），过线点**只读不写**；
- 写完可给 EPC 区上锁防篡改。

## 三、完整数据流（EPC → 云端认人 → App 展示）

```
① 报名绑定（一次性）
   用户扫二维码 → 小程序 → 云端写: tag_bindings{ epc, user_id, status:bound }

② 过线计时（每次骑行）
   车过线 → RFID 读 EPC + 光电锁微秒时刻 t
   → 基站关联 {epc, 点位(起/终), t, rssi} → 4G 上云

③ 云端识别 + 入库（云函数 process-crossing）
   收到 {epc, 点位, t}
   → 查 tag_bindings[epc] → 得 user_id      ← 【EPC 在这里被翻译成人】
   → 写 crossings(user_id, epc, 点位, t)
   → 配对起/终点算圈速 → 写 laps(user_id, 圈速)
   → epc 未绑定 → 存 unbound 待认领

④ App 展示
   小程序按 user_id 查 laps/sessions → 展示"我的成绩/圈速/排行"
```

**认人路由核心**：基站上传的包**只带 EPC，不带用户信息（基站不知 EPC 是谁），云端用 EPC 查绑定表翻译成 user_id**。好处：基站无需知道隐私，换人只改云端绑定表，标签不动。

**数据模型**（复用主线量产云端）：

| 集合 | 关键字段 |
|-|-|
| tag_bindings | epc(主键) → user_id, status ← 路由核心 |
| crossings | user_id, epc, 点位, 微秒时刻, session_id |
| laps | user_id, session_id, 圈号, 圈速 |
| sessions | user_id, 场馆, 起止时刻, 圈数, 最快圈 |

App 展示复用现有三端小程序的用户体系（openid）——数据按 user_id 索引存，用户进 App 按 openid 拉自己数据。

## 四、基站 OTA（封盒无线升级）

基站封在防水盒、无 USB → 必须无线 OTA。设计与主线标签 OTA 同源（A/B 双分区 + SHA256 + 自检回滚）。

**认知要点**：① 上传的是编译产物 **.bin**（不是 elf）；② **ESP32 自己写 OTA 分区**（原生 esp_ota），4G 只是字节管道，不是"串口烧录"。

**路线 B（透传分片，已实现）**：4G 模块透传/MQTT 模式下 ESP32 无 IP 栈，手动分块拉取：

```
① 编译得 .bin → 上传云端 COS，记 {版本, 大小, sha256}
② 小程序【管理员】选版本 → 推送 → 云端经 4G 下行:
   {"cmd":"ota","key","ver","size","sha256"}
③ 基站收到并校验 key → 逐块 OTAGET <偏移> <长度> 拉 .bin
④ 写入空闲 OTA 槽(ota_0/ota_1) → 全收后校验 SHA256
⑤ 校验过 → 切换启动分区 → 重启进新固件
⑥ 新固件自检 OK → 标记有效（取消回滚）；失败/崩溃 → bootloader 自动回滚
⑦ 上报结果给云 → 小程序显示升级成功/失败
```

**关键点**：分区表用双 OTA 槽 + 开回滚；只刷 app 分区、NVS 保留；SHA256 校验 + 设备密钥鉴权（防乱推）；**A/B 回滚是封盒设备的救命稻草**（刷坏自动退回旧固件）。

> 若 4G 模块支持 **PPP 拨号**（给 ESP32 完整 IP 栈），可改用一行 `esp_https_ota(url)` 全自动下载（路线 A，更省事）。

**云端待补**：COS 存 bin + 云函数实现 `OTAGET 偏移 长度` 返回字节段 + 小程序管理员推送页。

> 相关（见同目录）：**方案总览**、**器件选型**、**供电与接线**。

## 双点位时钟同步（决定圈速精度）

起点/终点各一台独立基站时，圈速=终点时刻−起点时刻**跨两个时钟**。两时钟的零点差（开机不同，可达几秒）+ 晶振频率差（±20ppm，30s 累积几百 µs）若不消除，圈速直接错。

| 方案 | 精度 | 说明 |
|-|-|-|
| A. 各自 NTP，云端 UTC 相减 | 几十\~几百 ms | 够"秒级显示"，不够精确排名 |
| **B. ESP-NOW 两基站互相授时** | **<1ms（实测 \~120-270µs）** | ✅ 推荐；复用 2.4G，10m 板载天线够 |
| 有源标签主线 | 无需同步 | 同一标签时钟相减，天然抵消 |

**关键洞察**：网络延时**不会**破坏授时——双向交换让对称延时数学抵消，ESP-NOW 延时小且抖动低。真正伤精度的是**抖动**，靠"收发回调最早处打戳 + 剔异常 RTT + 多次中位数"压住。做对四件事（底层打戳+中位数+剔异常+估skew周期重同步）→ 圈速残差 <1ms。详见「基站固件设计」时钟同步章节。

## master↔slave 通讯整体逻辑（心跳 + 授时 + OTA）

> 本节汇总双基站间三条 ESP-NOW 链路的当前实现（`firmware/base-passive/main/`）。角色按 MAC 白名单的**槽位**决定：slot0=master（起点，唯一挂 4G DTU，做圈速配对+全部上云），slot1=slave（终点，无 DTU）。两块板烧同一固件，开机各读自身 WiFi STA MAC（`esp_read_mac`，走 efuse 不依赖 WiFi）比对白名单定角色。

### 一、总体架构：两条线程解耦

核心设计原则是 **master↔slave 通讯** 与 **master→DTU 上云** 彻底解耦，跑在不同上下文、互不阻塞：

- **ESP-NOW 接收回调**（master 侧）把 slave 的心跳/过线/授时应答写进一份**共享快照**`s_slave`（portMUX 临界区保护）；
- **DTU 上行任务**每个心跳周期只**读**这份快照拼 JSON 上云，从不直接依赖 ESP-NOW 是否刚收到包。

好处（fallback 语义）：ESP-NOW 链路抖动/中断时，DTU 上报的数据不变，只是**回退到快照里的最后值**并按 `last_seen` 龄期标记 slave 离线；反之 DTU 掉线也不影响 master↔slave 的授时同步。任一条坏了，另一条照常。

### 二、心跳链路（合并为一条 JSON）

slave 每 `HEARTBEAT_MS`（当前 **10 秒**）通过 ESP-NOW 把自己的心跳（固件版本、MAC、运行时长、空闲内存、授时精度）发给 master；master 收到即更新 `s_slave` 快照。master 自己也按 10 秒节奏，把**两站合并成一条** JSON 经 DTU 上云：

```json
{"type":"basehb","key":"...",
 "master":{"station":1,"fw_ver":"1.2","mac":"...","uptime_s":..,"free_heap":..,"ota_state":..,"ota_pct":..},
 "slave" :{"station":2,"fw_ver":"1.2","mac":"...","uptime_s":..,"free_heap":..,
           "sync_prec_us":..,"online":true|false,"link_age_ms":..} }
```

云端 `baseHeartbeatCombined` 把它拆成 base1/base2 两条记录分别落库。slave 段的 **online 由 master 判定**：ESP-NOW 链路 `last_seen` 超过 `SLAVE_OFFLINE_US`（当前 **30 秒**，即 3× 心跳）就上报 `online:false`（掉线但保留最后值 = fallback）。云端在线新鲜度窗口 **40 秒**（4× 心跳），主要兜住 master 整机掉电。

<callout emoji="📌">
阈值必须随心跳周期联动：心跳周期变了，`SLAVE_OFFLINE_US`（固件）与云端新鲜度窗口都要按 3×/4× 同步调整，否则会出现「拔电后长时间仍显示在线」。
</callout>

### 三、授时同步链路（决定圈速精度）

slave 驱动、master 在 ISR 里应答的双向交换（PTP/SNTP 式，Method B）。四个时间戳 T1..T4 在 **ESP-NOW 收发回调最早处** `esp_timer_get_time()` 打戳（不进应用层，否则调度抖动毁精度）。每轮 10 次交换，估计 `offset = ((T2-T1)-(T4-T3))/2`。当前算法要点：

- **NTP clock-filter 选样**：按 RTT 升序取 **best-K（K=4）个最低 RTT 样本**取中位——RTT 最小=MAC 竞争最少=往返最对称=offset 最准；
- **skew 估计 + 每 5 秒重同步**：连续两轮 offset 估晶振频率差，两次重同步之间线性外推；
- **授时精度指标 = best-K offset 样本的 MAD（中位绝对偏差）**，即估计值的真实不确定度。**它不是 RTT/2**：对称往返延迟在双向公式里数学抵消，精度只取决于样本一致性，**与距离/RTT 绝对值无关**（10m 传播仅 33ns，可忽略）。

App「授时精度」只显示 slave 的该 MAD 值（master 是时间基准，不显示）；越小越准，孪生实测圈速残差 \~120–270µs（<1ms）。存活性无需单独判断——心跳断则授时也断，走心跳即可。

### 四、OTA 链路（云→master→slave 中继）

命令经心跳响应下行：管理员在 App 选版本 → 云端把 `{type:"ota",ver,size,sha256,fileID,station,key}` 挂到该站 pendingCmd → master 下个心跳的 HTTP 响应里带回。`station:2` 表示目标是 slave，master 转成 ESP-NOW 中继；否则 master 自更新。两站均 A/B 双分区 + SHA256 + 自检失败自动回滚。

**字节下载路径**（master 自更新与 slave 中继共用）：base 逐分片 POST `{ota_get,fileID,off,len,key}`，云端 `dtuIngest ota_get` 从 COS 切片回 base64（warm 容器缓存整包，避免每片重下全量）。slave 中继时，master 从云取字节后再用 200B/包（ESP-NOW 单包上限）转发给 slave，slave 循环拼满一个 OTA 分片。

<callout emoji="❗">
**实测硬约束**：DTU 单次下行只能完整转发几 KB。8KB 分片（base64≈11KB 响应）会被 DTU **截断**（串口见 JSON 无闭合 `}`、off=0 超时）；**1KB 分片（≈1.4KB 响应）稳定通过**。故 `OTA_SU_CHUNK` 必须 ≤1KB，禁止为提速调大——提速只能走波特率。
</callout>

**可靠性三件套**（应对 4G/UART 偶发字节错误）：① **每分片 CRC32 校验 + 单片重传**（错一字节只重取该片，不再整包 SHA 失败）；② **花括号配平 JSON framing**（`cloud_recv_line` 在对象内部丢弃 CRLF，抗 DTU 分片/chunked 注入的换行截断）；③ **命令幂等重投**（下发不即清，收到确认前每心跳重发，防单次响应丢失导致 OTA 永不开始）。进度按每分片上报 `ota_done/ota_total` 字节数，App 显示「已下载 X / Y KB」——百分比动得慢时用字节数确认在推进。

### 五、波特率与联调纪律

固件 `pins.h DTU_BAUD` **必须与 DTU WEB 配置的串口波特率一致**，否则全乱码、心跳上不去、页面显示离线。改任一端都要同步另一端并重烧/重配。实践：460800/230400 在本链路曾现字节乱码，115200 最稳；OTA 瓶颈是 DTU 下行分片上限（几 KB）而非波特率本身。

> 实现细节见「基站固件设计」文档；本节聚焦三条链路的整体逻辑与已定型的约束。