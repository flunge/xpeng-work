<title>过线基站固件设计（base / base-passive）</title>

# 过线基站固件设计（base / base-passive）

协议载体：上行 ESP-NOW 包（32B odom_packet_t）的**唯一权威定义**见 [《ESP-NOW 链路协议 · Tag → Base》](https://fqmtvue07d8.feishu.cn/docx/JPNrdCEsVo33qGxTF7rc9WEAnTg)；base 侧 dedup / 丢包统计规则同步维护于此。

<callout emoji="💡">
两种独立并存的基站固件：**base**（主线，ESP-NOW 聚合有源标签）与 **base-passive**（阶段 1.5，RFID + 光电无源计时）。互不影响。
</callout>

## 一、base（主线，ESP-NOW 聚合上云）

职责：ESP-NOW 收全场标签 odom → per-tag 去重/统计 → 组 JSON → WiFi/4G 上云。圈速在云端算（用标签时间戳）。

### 核心流程伪代码

```c
// ESP-NOW 收包回调（WiFi 任务上下文，非 ISR）
on_espnow_recv(mac, data):
    if len(data) != sizeof(odom_packet): return  // 校验长度
    xQueueSend(rx_queue, {packet, mac, rx_us})

loop uplink_task:
    it = xQueueReceive(rx_queue)
    t = tag_slot(it.tag_id)                        // per-tag 状态表
    // 去重 + 乱序丢弃（ESP-NOW 无重传）
    d = (int32)(it.seq - t.last_seq)               // 32 位回绕安全
    if d <= 0: t.dup_ooo++; continue               // 重复/乱序，丢弃
    if d > 1: t.gap_lost += d-1                     // 序号缺口 = 估计丢包
    t.last_seq = it.seq; t.accepted++
    json = build_json(it.packet, mac)
    if cloud_send_json(json) == 0: t.uploaded++
    if recv % 50 == 0: link_report()               // 打印收发/丢包率
```

**阶段一联调加固**：per-tag 收/去重/丢包率统计（收发对账）；TLS 证书校验 + X-Base-Key 鉴权头；主机孪生测试纳入护城河。

## 二、base-passive（阶段 1.5，无源计时）

职责：光电边沿锁微秒戳（何时）+ RFID 读 EPC（是谁）+ 单列关联 → 4G 上云。**计时铁律：只有光电边沿锁时刻，RFID/RSSI 只认人不改时刻。**

### 核心流程伪代码

```c
// 光电中断：只锁微秒戳（计时核心）
void IRAM_ATTR gate_isr():
    e.t_us = esp_timer_get_time()
    e.point = gpio_read(POINT_SEL)          // 起点/终点
    xQueueSendFromISR(gate_queue, e)

// RFID 任务：维护"在场"标签（单列 → 有效一个）
loop rfid_task:
    epc, rssi = parse_rfid_frame(uart_read())
    if rssi >= present.rssi or same_epc:
        present = {epc, rssi, last_seen: now}

// 关联 + 上云
loop uplink_task:
    e = xQueueReceive(gate_queue)           // 光电边沿（权威时刻）
    p = present                             // 当前在场标签
    fresh = (e.t_us - p.last_seen) <= PRESENCE_TTL
    debounced = (e.t_us - p.last_report) < 300ms   // 去抖
    if not fresh or p.rssi < RSSI_MIN: drop; continue
    if debounced: continue                  // 同标签重复遮断
    p.last_report = e.t_us
    json = {station, point, epc: p.epc, t_us: e.t_us, rssi: p.rssi}
    cloud_send_json(json)                   // 4G DTU 透传
```

## 三、OTA（base-passive 封盒无线升级）

```c
// 云端推送 {cmd:ota, ver, size, sha256} → 基站自更新
ota_task:
    job = parse_ota_push(cloud_recv_line())
    verify_auth_key(job)                    // 防乱推
    slot = esp_ota_get_next_update_partition()   // 空闲 A/B 槽
    esp_ota_begin(slot, job.size)
    for off in 0..size step CHUNK:
        buf = cloud_ota_pull(off, CHUNK)     // 4G 分块拉 .bin
        esp_ota_write(slot, buf); sha.update(buf)
    if sha != job.sha256: abort; return      // 校验失败拒绝
    esp_ota_set_boot_partition(slot); reboot
    // 新固件启动自检 OK → mark_valid；失败 → bootloader 自动回滚
```

分区表双 OTA 槽 + 回滚；只刷 app、NVS 保留；A/B 回滚是封盒设备的救命稻草。

## 四、相关

方案见 [阶段 1.5 方案总览](https://fqmtvue07d8.feishu.cn/docx/HrqGdHQkXo5xucxzeL8czzeRnHd) 与 [身份与数据链路（含 OTA）](https://fqmtvue07d8.feishu.cn/docx/SzkxdSTjjoKeyHxq3UecTaPJnSa)；标签固件见 [车载标签固件设计](https://fqmtvue07d8.feishu.cn/docx/AFs2dqXLYokSndxO1SocdMrzn9c)。

## 双基站时钟同步（无源计时，Method B）

<callout emoji="💡">
起点/终点是两台独立 ESP32，各有各的时钟。圈速=终点时刻−起点时刻跨两个时钟 → 必须对齐，否则圈速错。**有源主线无此问题**（同一标签时钟相减）；无源路线把时刻挪到基站侧才引入。
</callout>

**方案**：finish 网关(slave)经 ESP-NOW **双向交换**对齐到 start 网关(master)时间轴。主机孪生实测圈速残差 **\~120-270µs（<1ms）**，10m 近距板载天线够、无需外接。

### 核心伪代码

```c
// 双向交换：offset = ((T2-T1)-(T4-T3))/2，对称延时抵消
// 铁律：T1..T4 在 ESP-NOW 收发回调最早处打戳（非应用层，否则调度抖动毁精度）
slave 每轮:
  for k in 0..10:                        // 一轮 10 次交换
    T1 = esp_timer_get_time(); 发 REQ(T1)
    收 REP → T2,T3(master), T4=收到时刻
    round.push(offset, rtt)
  med_rtt = median(rtt)
  good = offset where rtt <= 1.5*med_rtt // 剔高 RTT 异常
  new_off = median(good)
  est_skew = (new_off - prev_off)/(t - prev_t)  // 估频率差
  sleep 5s; 重同步                        // 补漂移

// 过线时刻换算到 master 轴（云端据此相减算圈速）
t_master = t_local + (est_off + est_skew*(t - est_off_t))
上报附 sync_age_ms → 云端判成绩可信度（同步过旧则标记）
```

四件事缺一不可（孪生验证）：**底层打戳(<0.5ms jitter) + 10 次中位数 + 剔异常 RTT + 估 skew 周期重同步**。做错任一（如应用层打戳）退化到几 ms。master=start 网关只在回调里回复；slave=finish 网关驱动同步+换算。

## MA82 RFID 驱动（已实现真实协议）

之前的 `parse_rfid_frame` 占位已替换为 MA82/MA60-80 真实帧解析：字节流组帧(BB..7E) + checksum 校验 + 通知帧(Type=02/Cmd=22)提取 RSSI+EPC；开机发连续盘存指令(0x27, CNT=0xFFFF)。3.3V TTL @115200 直连 ESP32。

```c
// 开机启动连续盘存
inv = {0x22, 0xFF, 0xFF}; ma_send_cmd(inv, 0x00, 0x27);   // BB 00 27 00 03 22 FF FF ck 7E
// UART 字节流组帧：遇 BB 开帧、逐字节存、遇 7E 且长度>=7 收帧
on each byte b:
  if !in_frame: if b==0xBB -> in_frame, fr=[BB]
  else: fr.push(b); if b==0x7E and len>=7 -> try ma_parse_notify(fr)
// ma_parse_notify: 校验 BB/7E、PL+7==len、checksum、Type==02&&Cmd==22&&PL==0x11
//   -> rssi=int8(payload[0]); epc = payload[3..14] 转 hex(12字节)

```

主机孪生 `test_host/ma82_parser_twin_test.py` 用厂商协议示例帧验证：EPC=30751FEB705C5904E3D50D70、RSSI=-55、checksum=0xEF、坏帧拒绝、粘包切帧 —— 全 PASS。资料见 firmware/reference/rfid/。