# AVM鱼眼

> **📋 文档属性**
> 
> - **标识**：avm-fisheye ｜ **所属线**：场景&生产 ｜ **状态**：active
> - **负责人**：王禹丁 ｜ **贡献者**：杨星昊（技术指导/方案决策）
> - **起始**：2026-06-08 ｜ **内容现势**：截至 2026-06-13
> - **相关文档溯源**：技术方案详见嵌套文档[avm链路-鱼眼](https://xiaopeng.feishu.cn/wiki/WDfGwUa0IiRWf5kVnflcokrHnth)（cam9参数映射/Mei模型/方案评估/效果迭代）、3DGS avm链路开发[3DGS avm链路开发](https://xiaopeng.feishu.cn/wiki/JZ24wgQG5if4JgkwvghcQNnYnVf)（三阶段路线图/短期成果）、Gsplat适应mei相机[Gsplat 适应mei相机](https://xiaopeng.feishu.cn/wiki/KU0jwfZFOiQC2zkW28gceAYcnjh)（CUDA+Python代码修改清单），统一在[溯源索引](https://xiaopeng.feishu.cn/docx/SsWCdQbVZohGHFxhE3RcCmJ2nSb)「三、项目维度 → 算法预研/场景&生产 → AVM 鱼眼」维护。

## 一、背景目标

**项目定位**：让 cam9 AVM 前视鱼眼相机（Mei 全方位模型，Xi=0.982）适配 gsplat 的 OpenCV 标准渲染管线，支撑闭环仿真的 AVM 数据渲染需求。

**需求源头**：李元龙 @李坤"有些模型用了 avm 数据，闭环需要 3dgs 支持渲染 avm，至少得支持 cam9"。

**三阶段路线图**（来源[3DGS avm链路开发](https://xiaopeng.feishu.cn/wiki/JZ24wgQG5if4JgkwvghcQNnYnVf)）：

- ① 短期（6.08–6.18）方案验证：gsplat 方案验证【1W】+ 仿真环境构建【1W】；交付物＝gsplat链路适配 + Mei 类型鱼眼相机模型可直接带畸变渲染。
- ② 中期（6.22–7.24）Diffusion 模型优化：配合引擎组搭建鱼眼仿真链路并持续优化维护；鱼眼相机数据拉取链路自动化（7.06–7.10）→ 数据准备用于 Diffusion 训练（7.13–7.17）→ 新版 Diffusion 模型训练与评测（7.20–7.24）。
- ③ 长期（7.13–8.07+）3DGS 闭环训练：鱼眼适配 3DGS 预处理链路（7.13–7.17）→ 适配训练链路含 Mask/天空/仿射变换特殊处理（7.20–7.31）→ UCP 生产自动化链路适配（8.03–8.07）→ 持续效果与耗时优化。

## 二、当前状态（截至 2026-06-13）｜🟠 PENDING（暂缓）

<callout emoji="💡">
**PENDING（暂缓）状态说明**（判定 2026-07-16）：李坤已判定 cam9 **当前不是仿真的 blocking 项**（AI 引擎侧实车已 DT），先交付第一阶段（不带训练），**待确认需求来自哪方后再决定是否追加训练阶段**。项目自 2026-06-13 起无新进展，处于等待需求方确认的暂缓状态。恢复条件：需求方明确后再启动训练阶段。
</callout>

- **渲染端已打通**：gsplat cam9 逆向投射（3D→高斯球查找）6/12 修复，现支持 9 个微相机、可接纳更多 AVM 模型。核心做法：改造 gsplat 渲染管线、**新增 Mei 投影并注入 Xi 参数**（gsplat 内置 fisheye 不支持 Xi，直接映射有精度损失）。技术实现要点（来源[Gsplat 适应mei相机](https://xiaopeng.feishu.cn/wiki/KU0jwfZFOiQC2zkW28gceAYcnjh)）：CameraModelType 枚举新增 MEI=4；Xi 参数当前硬编码 0.9820293188095093（cam9 实际值）写入 CUDA kernel（ProjectionUT3DGSFused.cu）；畸变系数 [k1,k2,p1,p2,k3] 共 5 个元素复用 radial_coeffs 通道传递；Python 端新增 MeiCameraDistortionParameters dataclass；应用层 reconic_simulator.py 对 cam_name=="cam9" 走 mei 专用逻辑。逆 Mei 投影（image_point_to_camera_ray）0611 修复，关键推导 ρ=(ξ+α)/(r_n²+1)，α=√(1+(1−ξ²)r_n²)（来源[avm链路-鱼眼](https://xiaopeng.feishu.cn/wiki/WDfGwUa0IiRWf5kVnflcokrHnth)）；with_eval3d=False 亦可正常工作（UT 前向投影仍正确），精度接近 eval3d。详见 `WDfGwUa0`。
- **遗留问题**：🔴 cam9 闪烁/颜色不对（缺仿射变换矩阵、当前随机初始化，需训练修）；🟡 车身 mask（cam2 近地被车身遮挡致地面空洞）；🟡 天空边界（cam2 sky 贴图）；🟡 空洞（difix 路线修）；训练链路接入后 cam9 对整体指标的量化影响未知。
- **优先级判断**：🔴 李坤判断 cam9 目前**不是仿真的 blocking 项**（AI 引擎侧实车已 DT），先交付第一阶段（不带训练），待确认需求来自哪方后再决定是否追加训练阶段。

## 三、持续进展

> 同一天多来源并入一行、时间单 cell；空格＝该来源当天无记录。

| 时间 | 作战表（日报进展） | 会议纪要 / 日会 | 其他来源 |
|-|-|-|-|
| 2026-06-08 |  |  | 李元龙 @李坤 发起 cam9 鱼眼渲染需求；杨星昊给短/中/长期方案（短期 gsplat 内置鱼眼→中期改底层→长期训练支持），先套用 G-Spec 方案（AVM鱼眼.md） |
| 2026-06-10 |  | 王禹丁gsplat默认鱼眼初步效果外形未对齐，排查相机模型/外参；Cam9开环完成待合入，闭环AVM图像链路de-risk完成可inference（来源：[智能纪要-每日例会2026年6月10日](https://www.feishu.cn/minutes)） | 初步效果出来（gsplat 默认鱼眼），怀疑投影矩阵/外参问题；杨星昊解释 cam2 近地被车身 mask 遮挡→地面空洞、cam7 是唯一近地面视角（AVM鱼眼.md / Q2 Wiki W11） |
| 2026-06-11 |  |  | 确认根因＝Mei vs OpenCV 相机模型差异；改造 Gisplan 新增 Mei 投影、gsplat 已支持 Mei 模型；修复 with_eval3d 效果不佳；遗留 3 问题，当天协同构建镜像（AVM鱼眼.md / Q2 Wiki W11） |
| 2026-06-12（W11） |  | 组内周会：王禹丁 gsplat cam9 3D 逆向投射修复完成、支持 9 个微相机；遗留颜色偏差（仿射矩阵需训练修）+ 空洞；杨星昊建议接 difix 作参考图训练修颜色；李坤定第一阶段不训练先交付、下周与元龙对需求后再决定训练阶段 |  |
| 2026-06-26（W26） |  | Time9、AVM适配已完成（来源：[智能纪要：仿真核心日会 2026年6月26日](https://www.feishu.cn/minutes)） |  |
|  |  |  |  |

## 四、后续规划

- 
- **与李元龙对需求**：确认 cam9 是否上线、短期交付物、需求来自哪方，据此决定是否推进训练链路。
- **一阶段交付**：先交付不带训练的渲染效果；效果 OK 则把训练/difix 等长线任务放后期。
- **修遗留**（来源[avm链路-鱼眼](https://xiaopeng.feishu.cn/wiki/WDfGwUa0IiRWf5kVnflcokrHnth) Todo）：① 为 cam9 添加 mask；② cam9 天空问题不使用 cam2 的 sky 贴图；③ cam9 仿射变换问题Affine/CamPose/Sky embedding 当前对 cam9 新增行保持随机初始化，需补训练。可接 difix 作参考图训练修颜色/闪烁。
- **中期 Diffusion 路线**（来源[3DGS avm链路开发](https://xiaopeng.feishu.cn/wiki/JZ24wgQG5if4JgkwvghcQNnYnVf)）：鱼眼数据拉取自动化（7.06–7.10）→ 数据准备（7.13–7.17）→ Diffusion 模型训练评测（7.20–7.24）。
- **长期 3DGS 闭环**（来源[3DGS avm链路开发](https://xiaopeng.feishu.cn/wiki/JZ24wgQG5if4JgkwvghcQNnYnVf)）：鱼眼适配 3DGS 预处理链路（7.13–7.17）→ 训练链路含 Mask/天空/仿射特殊处理（7.20–7.31）→ UCP 生产自动化（8.03–8.07）→ 持续效果与耗时优化。
- **评估训练影响**：量化 cam9 接入训练链路后对整体指标的影响。