---
name: cloudsim-cces-job-report
description: >-
  Fetches CloudSim CCES job comparison reports via signed HTTP APIs and
  summarizes metrics in Chinese (aligned with CCES UI: 安全 / 舒适 / 效率,
  长里程任务的合规 / 导航 / 其他, 场景集专项评测 job_type=4 的帧 Fail 映射). Use when the user provides job or list ids,
  asks for CCES 对比报告 / job overview / 长里程 / 场景集 / 专项评测 / PAT 安全 / 舒适 / 效率指标解读,
  or mentions get_job_overview, get_ids_by_filter, or cloudsim.xiaopeng.link CCES.
disable-model-invocation: false
---

# CloudSim CCES Job 报告查询与总结

## 在新对话里怎么复用本 Skill

本 Skill 位于仓库根 **`skills/cloudsim-cces-job-report/`**（团队 SSOT）。Cursor 用户 clone 后执行：

```bash
bash agents/scripts/setup-skills-links.sh
```

会将 `skills/` 链接到 `.cursor/skills` 与 `.agents/skills`。不依赖 Cursor 时，直接阅读本 `SKILL.md`，并运行 `scripts/cloudsim_request.py`（需先配置环境变量，见 `.env.example`）。

---

## 何时使用

用户给出一串 **job 相关 id**，并要求 **拉报告、对比、用中文（与前端一致）总结** 时，按下列流程执行。实现见 **`scripts/cloudsim_request.py`**（`X-Sign` + `CLOUDSIM_ACCOUNT`）。

## 先区分 id 类型（必做）

| 用户口中的 id | 典型形态 | 调用方式 |
|---------------|----------|----------|
| **CCES 任务行 `_id`**（Network 里 `get_job_overview` 的 `ids`） | 较大整数，如 `73306050` | **直接** `cces_get_job_overview([...])` |
| **报告里的 `job_id`**（前端表头常显示） | 如 `11878557`（常与 scenario 同源） | **不能**直接当 `get_job_overview` 的 `ids`；先用 **`get_ids_by_filter`**（见下）把列表 id 换成 CCES `_id`，或直接索要 Network 里 **`get_job_overview` 的 `ids`**。 |

**`get_ids_by_filter` 与前端一致的表单字段**（`application/x-www-form-urlencoded`）：

- **`job_ids`**：JSON 数组字符串，如 `[11878559,11878558]`（界面选中的 id 列表）
- **`job_type`**：**`14`** 常见为 PAT（cost/次数类）；**`1`** 为 **长里程**；**`4`** 为 **场景集 / 专项评测**（帧 Fail 比例 + 分级计数，如 `11861422` 与概览「总体/问题时间段」列，需在请求中显式传入）。
- **`model_type`**：如 `default`
- **`is_exclude_trend_summary_data`**：如 `1`

实现：`cces_get_ids_by_filter(job_ids, job_type=14, ...)`（PAT）；长里程 **`job_type=1`**（`cces_report_long_mileage`）；场景集专项 **`job_type=4`**（`cces_report_scenario_eval`）。若仍走旧版 **`job_type` + `filter` JSON** 才用 `cces_get_ids_by_filter_from_filter_json` / `cces_report_from_filter_json`。

## 拉取报告（代码路径）

1. 在仓库内执行（或等价导入）：
   - `cces_get_job_overview([73306050, ...])`：已知 **CCES `_id`** 时直接用。
   - **`cces_report_long_mileage([11858382, 11858425])`**：等价于 **`job_type=1`**（见 `cloudsim_request.cces_report_long_mileage`）。
   - **`cces_report_scenario_eval([11861422, 11861432])`**：等价于 **`job_type=4`**（见 `cloudsim_request.cces_report_scenario_eval`）。
   - **`cces_report_from_job_ids([11880839, 11880838])`**（默认 `job_type=14`）：PAT 场景集。
   - `cces_report_from_selected_job_ids`：与上等价（旧名）。
   - `cces_report_from_filter_json` / `cces_report_from_filter`：仅当必须用 **`filter` JSON** 旧路径时。
2. **环境**：默认 `base="https://cloudsim.xiaopeng.link"`；dev/staging 需改 `base` 且 `SECRETS` 中已有对应域名密钥。
3. **校验**：`result == "success"`；`data` 含 `job_infos` 与若干以 **Metric 类名** 为 key 的列表。

## 指标块 → 前端中文（安全类）

将 `data` 下除 `job_infos` 外的 **每个 key** 视为一类指标；列表内按 `job_id` 或 `cces_job_info_id` 对齐两行。

| API `data` 中的 key | 前端「Metric」常见归类 |
|---------------------|-------------------------|
| `PatCollisionMetric` | **碰撞** |
| `PatCollisionWithRoadBoundaryMetric` | **撞 RB**（路沿/道路边界） |
| `PatOncomingAgentYieldMetric` | **逆向车避让不足**（安全；常与效率同屏） |

每条记录内的 **`metric_value`** 与前端列对应关系（PAT 安全概览）：

- **`score`** → **fm raw 碰撞风险 cost**（仅碰撞类常见；撞 RB 若全 0 则表上 cost 为 0）
- **`frame_fail_count`** → **fm raw … 风险帧**（碰撞 / 撞 RB 各自一行）
- **`mp_total_score` / `mp_num_failed_frames` / `mp_fail_frames`** 等 → **mp … cost / 帧**（以实际返回字段为准；常见为 0）
- **`PatOncomingAgentYieldMetric` 内：** **`fm_total_cost_score`** → **fm raw 逆向车避让不足 cost**；**`mp_total_cost_score`** → **mp 逆向车避让不足 cost**

若某 Metric 下无记录或 `metric_value` 全空，前端可能显示 **「-」**，总结中写明 **无数据**。

## 指标块 → 前端中文（舒适类）

前端 **类型 = 舒适** 时，`get_job_overview` 的 `data` 中常见三类（子类名与表头对应如下）。列表内仍按 `job_id` / `cces_job_info_id` 对齐。

| 前端子类（Metric） | API `data` 中的 key | `metric_value` 字段 → 前端「评测指标」 |
|--------------------|---------------------|----------------------------------------|
| **横向摆动** | `PatSwingMetric` | **`fm_total_cost`** → **fm raw 摆动 cost**；**`frame_fail_count`** → **fm raw 摆动次数**；**`mp_total_cost`** → **mp 摆动 cost**；**`mp_failed_frames`** → **mp 摆动次数** |
| **加速度舒适性** | `PatDriverOvertakeJerkCaptureMetric` | **`fm_total_cost`** → **fm raw 舒适 cost**；**`frame_fail_count`** → **fm raw 侧冲次数**；**`mp_total_cost`** → **mp 舒适 cost**；**`mp_failed_frames`** → **mp 侧冲次数** |
| **蛇形行驶** | `PatSnakeDrivingMetric` | **`fm_total_cost_score_0p5s`** → **fm 0.5s 轨迹 cost**；**`fm_total_cost_score_1s`** → **fm 1s 轨迹 cost**；**`mp_total_cost_score_0p5s`** → **mp 0.5s 轨迹 cost**；**`mp_total_cost_score_1s`** → **mp 1s 轨迹 cost** |

**补充（蛇形，接口有但舒适表未必逐行展示）：** `sign_change_count_4pts` / `sign_change_count_2pts` 等与轨迹曲率变化相关；若前端另有「蛇形」子行，以页面为准，总结时一并读出并说明含义。

舒适类 **cost / 次数** 在多数对比里同样 **越小越优**（与前端差值 ▼ 语义一致）；总结前先看该列在页面上是 cost 还是 count，避免与「越大越好」的展示混淆。

## 指标块 → 前端中文（效率类）

前端 **类型 = 效率** 时，`get_job_overview` 的 `data` 常见块与「Metric / 评测指标」对应如下。列表内按 `job_id` / `cces_job_info_id` 对齐。

### 子类与 API key（已对照 `11881724` / `11881725` + RL3/RL4_h93_efficiency）

| 前端子类（Metric） | API `data` 中的 key |
|--------------------|---------------------|
| **跑不到限速** | `TrajectoryNoAccelerationMetric` |
| **不超慢车 / 超车过晚** | `PatOvertakeSlowCarMetric` |

### `metric_value` 英文字段 → 前端「评测指标」文案（与概览表一致）

| API `metric_value` 字段 | 前端评测指标（与概览 UI 一致，仅空格可能不同） |
|-------------------------|----------------------------|
| **`score`**（在 `TrajectoryNoAccelerationMetric` 内） | **fm raw不加速cost** |
| **`mp_total_score`**（同上） | **mp不加速cost** |
| **`score`**（在 `PatOvertakeSlowCarMetric` 内） | **fm不超慢车cost** |
| **`mp_total_score`**（同上） | **mp不超慢车cost** |

**效率类命名习惯：** 多块里 **fm 侧汇总 cost** 常用字段名 **`score`**，**mp 侧 cost** 常用 **`mp_total_score`**（与安全里 `PatCollisionMetric` 的 `score`、舒适里部分块的 `fm_total_cost` 等并存；**以当前 Metric 的 JSON 为准**）。

### 起步慢

概览中 **起步慢** 行（**fm raw起步慢cost** / **mp起步慢cost**）若接口 **未返回对应 `data` key**，前端多为 **「--」**。Agent 应在总结中写 **「本响应无起步慢 Metric 块」**，勿猜测类名；若用户后续提供含非空起步慢数据的 JSON，再补全映射。

### 与效率同请求中的其它块

同一 `get_job_overview` 响应里可能同时出现 **`PatOncomingAgentYieldMetric`**（见 **安全类** 表），总结效率时不要把它算进效率指标，除非用户要求整页概览。

---

## 长里程任务（CCES 概览，`job_type = 1`）

以下对照在 **`11858382` / `11858425`** 的 `get_job_overview` 响应上核对：`data` 下除 `job_infos` 外为 **Metric 类名**（与 Python/Java 类名风格一致）；每条记录的 **`metric_value`** 为英文字段对象。

### 拉数与里程

- **`cces_report_from_job_ids([...], job_type=1)`**（`model_type`、`is_exclude_trend_summary_data` 与 PAT 相同即可）。
- **`job_infos[].mileage`** 单位为 **米**（如 `419347` → 419.347 km）。前端「每百公里 / 百公里」类数值，常由 **原始计数 ÷ (mileage/1000/100)** 得到；若接口字段已是比率，则不再除。**对比时优先与前端同口径（或同时给出原始值 + 百公里换算）**。

### 类型：安全（长里程概览）

| API `data` key | `metric_value` 字段 | 前端 Metric | 前端评测指标（概览用语） |
|----------------|----------------------|---------------|---------------------------|
| `CollisionSeverityMetric` | `collision_count_total`（及 `collision_count_gte_level_*`、`collision_avg_severity` 等） | **碰撞** | **百公里碰撞次数**（等多级严重度时以前端行为为准） |
| `TimeToCollisionMetric` | `ttc_failed_count` | **TTC** | **百公里 TTC Fail 次数** |
| `TimeToEncroachmentMetric` | `tte_failed_count` | **TTE** | **百公里 TTE Fail 次数** |
| `DangerousLaneChangeMetric` | `dangerous_lane_change_total_count` | **危险变道** | **每百公里总危险变道次数** |
| `RearCollisionRiskOpenloopMetric` | `rear_collision_risk_total_count`（及 `rear_collision_risk_level_*_total_count`） | **RCR** | **每百公里 RCR 次数** |
| `LateralReassuranceMetric` | `lateral_reassurance_frame_total_count` | **横向安心** | **每百公里总横向安心次数** |
| `DriverOvertakeCaptureMetric` | `driver_overtake_capture_count` | **跑车过近** | **每百公里总跑车过近次数** |
| `PedestrianYieldMetric` | `total_failure_events` | **仿真 MPCI** | **百公里 MPCI failed 次数** |
| `CollisionWithRoadBoundaryMetric` | `collision_with_road_boundary_count`（及 `*_gte_level_*`） | （路沿/边界碰撞，若概览单列） | **百公里**相关次数类文案 |

**说明：** 概览中 **「接管」** 等若未与上表单一字段明显对应，**以 Network 中 `get_job_overview` 该行数据来源为准**，勿硬编接口中不存在的键名。

### 类型：舒适（长里程概览）

| API `data` key | `metric_value` 字段 | 前端 Metric | 前端评测指标 |
|----------------|----------------------|---------------|----------------|
| `LongitudinalComfortMetric` | `sim_longitudinal_discomfort_per_100_km` | **组合纵向不舒适度** | **每百公里纵向不舒适度** |
| `LonComfortRecordMetric` | `level_gte_2_num_per_100km_acc`、`intervals_nums`、`level_gte_2_num` 等 | **组合纵向不舒适度**（辅助） | 与纵向不舒适相关的分级/区间统计（以前端展示为准） |
| `EtcPassageSpeedDegradationMetric` | `speed_degradation_count`（及 `_high` / `_middle` / `_low`） | **刹车频次** | **百公里 T21 刹车次数**（以前端聚合口径为准） |
| `JerkCheckMetric` | `jerk_total_count` | **纵向振动** / **顿挫** | **百公里振动次数** / **百公里顿挫次数**（若前端拆成两行，可能共用或拆分字段，以 UI 为准） |
| `SteeringWheelSwingInStationaryMetric` | `steering_swing_frame_fail_count` | **方向盘摆动** | **百公里总方向盘摆动频数** |
| `AccelerationComfortMetric` | `rapid_acceleration_count`、`rapid_deceleration_count` | **急加急减速** | **每百公里总急加速次数** / **每百公里总急减速次数** |
| `InappropriateDecelerationMetric` | `inappropriate_deceleration_count`、`error_deceleration_count` | **减速合理性** | **每百公里总减速时机不合理分数** / **每百公里总误减速分数**（文案以前端为准） |
| `LaneChangeOscillationMetric` | `lane_change_swing_count` | **变道摆动** | **每百公里总变道摆动次数** |
| `LaneChangeLateralOvershootMetric` | `lane_change_overshoot_count` | **变道超调** | **每百公里总变道超调次数** |
| `LaneChangeFoldbackMetric` | `lane_change_turn_back_count` | **变道折回** | **每百公里总变道折回次数** |
| `LaneChangeReturnMetric` | `lane_change_round_count` | **截断拼接** | **每百公里总截断拼接次数** |

### 类型：效率（长里程概览）

| API `data` key | `metric_value` 字段 | 前端 Metric | 前端评测指标 |
|----------------|----------------------|---------------|----------------|
| `SwingCheckMetric` | `swing_count` | **蛇形行驶** | **每百公里总蛇形行驶次数** |
| `MotionSicknessMetric` | `motion_sickness_max_index` | **零动指数** | **每百公里平均零动指数** |
| `SimStrandingMetric` | `stranding_count` | **卡死** | **百公里卡死次数** |
| `CcesVelocityDistributionMetric` | `general_velocity`（及 `general_velocity_fs`、`general_velocity_slt_*`） | **速度分布** | **平均速度 (m/s)** 等（以前端选用子字段为准） |
| `UnreasonableSpeedLimitMetric` | `unreasonable_blue_limit_count`、`unreasonable_speed_limit_count`、`non_conform_due_to_unreasonable_limit_count`、`v_shape_count` | **蓝圈限速不合理** / **限速不合规** | 红圈高于蓝圈、蓝圈高于红圈、**每百公里限速不合规次数** 等（多行对应多字段） |
| `SimUturnSuccessRateMetric` | `uturn_fail_count`、`uturn_pass_percent` | **uturn 通过率** | **每百公里 uturn 失败总次数** / **uturn 通过率** |
| `HrefFollowingDistanceMetric` | `following_time_distance_average` | **跟车距离** | **平均跟车时距** |
| `SpeedConformityMetric` | `speed_conformity_time` | **车速合规性** | **每百公里总车速不合规时间 (s)** |
| `BelowSpeedLimitMetric` | `below_speed_limit_count` | **开不到限速次数** | **每百公里开不到限速次数** |
| `BypassingMetric` | `not_bypassing_count`、`dangerous_bypassing_count`、`bypassing_late_count` | **绕行能力** | **每百公里必不绕行次数** / **每百公里总绕行次数** 等 |
| `LaneChangeEfficiencyMetric` | `lane_change_success_rate`、`lane_change_time_average` | **变道能力** | **每百公里总变道次数**（若由派生得到）/ **平均单次变道时间** / **变道成功率** |
| `LaneChangeHesitationMetric` | `lane_change_hesitation_count` | **变道犹豫** | **百公里变道犹豫次数** |
| `FollowSlowVehicleMetric` | `follow_slow_vehicle_time` | **蹭慢车不超车** | **每百公里总蹭慢车不超车时间** |
| `InsufficientFollowingDistanceMetric` | `following_distance_near_count` | **跟车过近** | **每百公里跟车过近次数** |
| `ExcessiveFollowingDistanceMetric` | `following_scenario_count`、`stopping_scenario_count` | **跟车过近** | **每百公里跟停过近次数**（与上表同属「跟车」大类时以前端分组为准） |
| `HesitateEnterWaitingZoneMetric` | `hesitate_enter_waiting_zone_count` | **不进待行区** | **每百公里不进待行区次数** |
| `LaneChangeNoGapSeekingMetric` | `lane_change_not_pull_count` | **变道到慢车后**（效率表） | **每百公里发生变道到慢车后的次数** |
| `LaneChangeNoGapSeekingMetric` | `lane_change_not_pull_count` | **变道时机晚**（导航表） | **每百公里变道时机晚次数** |

（同一 `metric_value` 字段可能被前端挂在 **效率** 与 **导航** 两类不同 Metric 下，以页面为准。）

| `CurveCuttingMetric` | `curve_cutting_count` | （若单列） | 与路口切弯相关次数 |

### 类型：合规（长里程概览）

| API `data` key | `metric_value` 字段 | 前端 Metric | 前端评测指标 |
|----------------|----------------------|---------------|----------------|
| `CrossSolidLineMetric` | `cross_line_count`、`serious_cross_line_count`、`cross_line_single_solid_count`、`cross_line_double_solid_count` 等 | **压实线** | **百公里压实线次数** |
| `EgoLaneDriftMetric` | `lane_drift_count` | **不居中** | **百公里不居中次数** |
| `OppositeRoadIntrusionMetric` | `reverse_count` | **逆行** | **百公里总不合理逆行次数** |
| `BusLaneIntrusionMetric` | `bus_lane_count` | **进公交车道** | **百公里总进公交车道次数** |
| `BicycleLaneIntrusionMetric` | `not_motor_vehicle_count` | **进非机** | **百公里总进非机次数** |
| `RunARedLightMetric` | `run_a_red_light_count` | **闯红灯** | **每百公里闯红灯次数** |
| `TurnSignalVoiceComplianceMetric` | `TSVC_missing_signal_left_turn_count`、`TSVC_missing_signal_right_turn_count` | **打灯语音合规性** | **每百公里漏打左灯次数** / **每百公里漏打右灯次数** |
| 同上 | `TSVC_missing_voice_*`、`TSVC_bad_signal_*`、`TSVC_bad_voice_*` 等 | **打灯语音合规性** | 漏语音 / 不良打灯 / 不良语音等各类 **TSVC_*** 字段（以前端展开行为准） |
| `LaneChangeOverSolidLineMetric` | `lc_over_solid_line_count` | **压线变道** | **百公里压线变道次数** |

### 类型：导航（长里程概览）

| API `data` key | `metric_value` 字段 | 前端 Metric | 前端评测指标 |
|----------------|----------------------|---------------|----------------|
| `NotFollowNavigationMetric` | `not_follow_navi_wrong_lane_count` | **不跟导航** | **每百公里总不跟导航走路次数** |
| `CcesWrongLaneSelectionMetric` | `wrong_lane_selection_at_junction_count` | **路口选道异常** | **每百公里总过路口选道错误次数** 等（多行可能需多字段或前端派生；以 UI 为准） |
| `LaneChangeNoGapSeekingMetric` | `lane_change_not_pull_count` | **变道时机晚** | **每百公里变道时机晚次数**（与效率表「变道到慢车后」可能共用字段时，以前端为准） |
| `BpDowngradeMetric` | `bp_downgrade_count` | **降级** | **百公里降级次数** |

### 类型：其他（长里程概览）

| API `data` key | `metric_value` 字段 | 前端 Metric | 前端评测指标 |
|----------------|----------------------|---------------|----------------|
| `HmiBroadcastLcReturnMetric` | `hmi_lc_return_count` | **HMI 某层变道提醒** | **每百公里 HMI 某层变道次数** |
| `TrajectorySmoothnessMetric` | `trajectory_not_smooth_count` | **轨迹平滑度** | **每百公里轨迹不平滑次数** |
| `IntelligentNavigationChangeMetric` | `intel_navi_change_leak_detection_count`、`intel_navi_change_wrong_detection_count` | **智能偏航触发** | **每百公里智能偏航漏触发次数** / **每百公里智能偏航误触发次数** |

### 长里程其它 API 块（概览未逐行列出时）

以下类名常出现在同一 `job_type=1` 响应中，总结时读出 **`metric_value` 全字段**；若前端未在「概览」展示，可注明 **「接口有、当前概览表未列」**：`BarrierGateDeadlockMetric`、`EtcDeadlockMetric`、`EtcPassageSpeedDegradationMetric`（除刹车外可能还有通行速度退化子指标）等。

---

## 场景集 / 专项评测（CCES，`job_type = 4`）

在 **`11861422` / `11861432`**（`rerun_B2CT11 … E29`，`mileage=23216` 米）的 `get_job_overview` 上核对：与 **PAT（`job_type=14`）**、**长里程（`job_type=1`）** 不同，本类 **`metric_value` 大量为「帧维度 Fail 比例 + 问题段比例 + 次数」**，前端常写 **「总体时间段 Fail 频次比例」** 或 **「Fail 帧数比例」**，多与下列 **`*_frame_fail_percent`** 同源。

### 通用字段模式（`job_type=4`）

| `metric_value` 字段模式 | 前端评测指标（常见文案） |
|-------------------------|--------------------------|
| **`*_frame_fail_percent`**（无 `_issue` 后缀） | **总体时间段 Fail 帧数比例** / **总体时间段 Fail 频次比例** |
| **`*_frame_fail_percent_issue`** | **问题时间段 Fail 帧数比例** / **问题时间段 Fail 频次比例** |
| **`*_frame_fail_count`**、**`*_frame_total_count`** | 帧统计（用于理解比例或派生展示） |
| **`collision_count_level_1` / `_2` / `_3`** | **轻微 / 中等 / 严重**碰撞次数（与 `CollisionMetric` 同行；级别语义以前端为准） |
| **`collision_vru_count`** | **VRU 碰撞次数** |
| **`ego_speed_too_high_count`** 等 `*_count` | **车速过高次数** 等「次数」类行 |

### 类型：安全（与图「安全」表）

| API `data` key | 主要 `metric_value` 字段 | 前端 Metric | 前端评测指标 |
|----------------|--------------------------|-------------|--------------|
| `CollisionMetric` | `collision_frame_fail_percent`、`collision_frame_fail_percent_issue`、`collision_count_level_1/2/3`、`collision_vru_count` | **碰撞** | 总体/问题 Fail 比例；**轻微/中等/严重碰撞次数**；**VRU 碰撞次数** |
| `TimeToCollisionMetric` | `ttc_frame_fail_percent`、`ttc_frame_fail_percent_issue` | **TTC** | 同上 |
| `TimeToEncroachmentMetric` | `tte_frame_fail_percent`、`tte_frame_fail_percent_issue` | **TTE** | 同上 |
| `DangerousLaneChangeMetric` | `dangerous_lane_change_frame_fail_percent`、`dangerous_lane_change_frame_fail_percent_issue` | **危险变道** | 同上 |
| `RearCollisionRiskOpenloopMetric` | `rear_collision_risk_frame_fail_percent`、`rear_collision_risk_frame_fail_percent_issue` | **RCR 频次** | 同上 |
| `CollisionWithRoadBoundaryMetric` | `collision_with_road_boundary_frame_fail_percent`、`collision_with_road_boundary_frame_fail_percent_issue` | **撞 RB** | 同上 |
| `LateralReassuranceMetric` | `lateral_reassurance_frame_fail_percent`、`lateral_reassurance_frame_fail_percent_issue` | **横向安心感** | 同上 |
| `InsufficientFollowingDistanceMetric` | `insufficient_following_distance_frame_fail_percent`、`insufficient_following_distance_frame_fail_percent_issue` | **跟车过近** | 同上 |
| `EgoSpeedTooHighMetric` | `ego_speed_too_high_frame_fail_percent`、`ego_speed_too_high_frame_fail_percent_issue`、`ego_speed_too_high_count` | **车速过高** | 总体/问题比例；**车速过高次数** |

### 类型：安全 / 扩展（图「专项」上半，无单独「类型」底色时仍多属安全）

| API `data` key | 主要字段 | 前端 Metric |
|----------------|----------|-------------|
| `OncomingAgentYieldMetric` | `oncoming_agent_yield_frame_fail_percent`、`oncoming_agent_yield_frame_fail_percent_issue` 等 | **逆向车偏移不足** |
| `RunningAYellowLightMetric` | `running_a_yellow_light_frame_fail_percent`、`running_a_yellow_light_frame_fail_percent_issue` 等 | **冲黄灯** |
| `NoSlowdownInBlindZonesMetric` | `no_slowdown_in_blind_zones_frame_fail_percent`、`no_slowdown_in_blind_zones_frame_fail_percent_issue`、`no_slowdown_in_blind_zones_count` | **盲区不减速**（含次数） |
| `IntersectionSqueezeMetric` | `intersection_squeeze_frame_fail_percent`、`intersection_squeeze_frame_fail_percent_issue` | **路口内桥旁车** |
| `PedestrianYieldMetric` | `pedestrian_yield_fail_frame_percent`（命名略异，仍为帧级比例） | **礼让行人** |
| `VehicleCreepMetric` | `vehicle_creep_fail_frame_percent`、`accumulated_vehicle_creep_duration`、`accumulated_vehicle_creep_event_count` | **溜车**（比例 + **溜车时长** + **溜车次数**） |
| `DangerousOvertakingMetric` | `dangerous_overtaking_frame_fail_percent`、`dangerous_overtaking_frame_fail_percent_issue` | **危险绕行** |

### 类型：舒适（`job_type=4`）

| API `data` key | 主要字段 | 前端 Metric | 前端评测指标 |
|----------------|----------|-------------|----------------|
| `HarshBrakeMetric` | `sim_longitudinal_discomfort_frame_fail_percent` 等 | **纵向不舒适度** | **总体时间段 Fail 帧数比例** |
| `SwingCheckMetric` | `swing_frame_fail_percent` | **横向摆动** | 总体 Fail 帧数比例 |
| `SteeringWheelSwingInStationaryMetric` | `steering_swing_frame_fail_percent` | **方向盘抖动** | 同上 |
| `JerkCheckMetric` | `jerk_frame_fail_percent`、`jerk_frame_fail_percent_issue` | **顿挫** | 总体 / **问题时间段** Fail 帧数比例 |
| `AccelerationComfortMetric` | `acceleration_comfort_frame_fail_percent`、`acceleration_comfort_frame_fail_count`、`acceleration_comfort_frame_total_count` | **急加急减速** | Fail 比例（及帧统计）；与 **总体加减速** 相关行以前端分组为准 |
| `InappropriateDecelerationMetric` | `total_decel_timing_score_mean`、`total_unnecessary_decel_score_mean`、`total_decel_late_score_mean`、`total_decel_early_score_mean` 等 | **减速合理性** | **平均减速时机分数**、**平均减速评分/晚分数** 等（与图「总体/危险时间段」各列对应，以前端列名为准） |
| `MotionSicknessMetric` | `motion_sickness_frame_fail_percent` | **举动指数** | 总体 Fail 帧数比例 |
| `CcesIntersectionSwingMetric` | `cces_intersection_swing_frame_fail_percent` | **路口内摆动** | 同上 |
| `SimStrandingMetric` | `stranding_frame_fail_percent` | **卡死** | 同上 |
| `CcesVelocityDistributionMetric` | `general_velocity`（及 `general_velocity_fs`、`general_velocity_slt_*`） | **速度分布** | **平均速度 (m/s)** 等 |

### 类型：效率（`job_type=4`）

| API `data` key | 主要字段 | 前端 Metric |
|----------------|----------|-------------|
| `CcesJunctionStraightExitLaneValidityMetric` | `cces_junction_straight_exit_lane_frame_fail_percent`、`*_issue` | **直行路口出路口连通不合理** |
| `SpeedConformityMetric` | `speed_conformity_frame_fail_percent` | **车速合理性** |
| `BelowSpeedLimitMetric` | `below_speed_limit_frame_fail_percent`、`below_speed_limit_frame_fail_percent_issue` | **开不到限速** |
| `FollowSlowVehicleMetric` | `follow_slow_vehicle_frame_fail_percent` | **跟慢车不超车** |
| `HesitateEnterWaitingZoneMetric` | `hesitate_enter_waiting_zone_frame_fail_percent` | **不进待行区** |
| `NoAccelerationMetric` | `no_acceleration_frame_fail_percent` | **不加速** |
| `ExcessiveFollowingDistanceMetric` | `excessive_following_distance_frame_fail_percent` | **顾车过远** |
| `SlowToStartMetric` | `slow_to_start_frame_fail_percent`（及 `*_issue` 若存在） | **起步慢** |
| `TurningRadiusAtIntersectionMetric` | `turning_radius_at_intersection_frame_fail_percent`、`turning_radius_at_intersection_frame_fail_percent_issue`、`turning_wide_radius_fail_count`、`turning_sharp_radius_fail_count` | **路口转大小弯**（比例 + **转大弯次数** / **转小弯次数**） |
| `LaneChangeToSlowVehicleMetric` | `lane_change_to_slow_vehicle_frame_fail_percent` | **变道到慢车后** |
| `CcesLaneChangeTrajectorySlowMetric` | `cces_lane_change_trajectory_slow_frame_fail_percent` | **变道轨迹僵硬** |
| `CcesLaneChangeToLowerPriorityLaneMetric` | `lane_change_to_lower_priority_lane_frame_fail_percent` | **虚穿软虚线**（与低优先级车道变道相关，以前端表头为准） |

### 类型：合规

| API `data` key | 主要字段 | 前端 Metric |
|----------------|----------|-------------|
| `CrossSolidLineMetric` | `cross_line_frame_fail_percent` | **压实线** |
| `EgoLaneDriftMetric` | `lane_drift_frame_fail_percent`（及 `drifting_left_percent_total` 等若展示） | **不居中** |
| `OppositeRoadIntrusionMetric` | `opposite_road_intrusion_frame_fail_percent`、`opposite_lane_occupation_frame_fail_percent`、`unreasonable_occupation_frame_fail_percent`、`opposite_road_intrusion_with_rb_frame_fail_percent` 等 | **调头内** 下多行（**进逆向** / **靠道折回慢** / **不合规慢速** / **侵入带隔离屏障车道** 等，**行 ↔ 子字段顺序以前端为准**） |
| `BusLaneIntrusionMetric` | `buslane_intrusion_frame_fail_percent`、`buslane_intrusion_frame_fail_percent_issue` | **进公交车道** |
| `BicycleLaneIntrusionMetric` | `bicyclelane_intrusion_frame_fail_percent`、`bicyclelane_intrusion_frame_fail_percent_issue` | **进非机** |
| `RunARedLightMetric` | `run_a_red_light_frame_fail_percent` | **闯红灯** |
| `RlStoppingPosUnreasonableMetric` | `rl_stopping_pos_unreasonable_frame_fail_percent` | **红灯刹停过线过远** |
| `TurnSignalVoiceComplianceMetric` | `TSVC_missing_signal_*`、`TSVC_bad_signal_*` 等（计次，非比例） | **杆灯状态备查**（漏打单灯、错打乱打等） |
| `CcesDeviateTurnGuidanceInWaitingZoneMetric` | `deviate_turn_guidance_frame_fail_percent`、`deviate_turn_guidance_frame_fail_percent_issue`、`deviate_turn_guidance_count` | **环岛交通** / **不进待转区/导流线行驶**（以前端把该块挂在哪一行为准） |

### 类型：智能

| API `data` key | 主要字段 | 前端 Metric |
|----------------|----------|-------------|
| `NotFollowNavigationMetric` | `not_follow_navi_frame_fail_percent` | **不照导航** |
| `NavigationLaneChangeLateMetric` | `nlc_late_frame_fail_percent` | **变道时机晚** |

### 类型：其他

| API `data` key | 主要字段 | 前端 Metric |
|----------------|----------|-------------|
| `ValidityMetric` | `trajectory_validity_frame_fail_percent` | **轨迹有效率** |
| `TrajectoryConsistencyMetric` | `trajectory_consistency_frame_fail_percent` | **轨迹一致性** |

---

## 总结输出结构（建议）

用中文输出，并尽量对齐前端三列逻辑（多 job 时两两对比或表格）：

1. **任务对照**：来自 `job_infos` — `job_id`、`job_name`、`binary_name`、`job_type`、`mileage`（若有）。
2. **按类型 / Metric 分组**：按接口与 **`job_type`** — **PAT（14）**、**长里程（1）**、**场景集专项（4）** 各节映射表；勿假设未返回的块存在。
3. **逐行指标**：用对应 **`job_type`** 小节的映射，把 **`metric_value` 字段名** 写成 **前端中文评测指标**（注意 **`job_type=4`** 下 **比例字段多为 `*_frame_fail_percent`**），再写各 job 数值 → **差值/百分比**。
4. **结论段**：哪条 job 在哪些子项更好、差异量级、无数据项。

## 注意

- **不得在对话中复述 `SECRETS` 明文**；仅通过已有代码签名调用。
- `get_ids_by_filter` 若返回空 `data`，核对 **`job_type` / `model_type` / `job_ids`** 是否与 Network 一致；仍不行则请用户粘贴 **`get_job_overview` 的 `ids`** 或旧版完整 **`filter` JSON**。
- 不同 `job_type` / 业务线下返回的 Metric key 集合可能不同；**以接口实际 keys 为准**，勿臆造未返回的指标。
