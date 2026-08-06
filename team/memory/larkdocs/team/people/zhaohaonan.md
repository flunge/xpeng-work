# 赵浩南

> **📋 文档属性**
> 
> - **标识**：zhaohaonan ｜ **状态**：active ｜ **二级部门**：仿真与验证部
> - **核心项目**：Diffusion预研 (contributor)、World Model预研 (contributor)
> - **内容现势**：截至 2026-07-03（W27）
> - **来源**：HR群offer卡片、入职排期、李坤6/30确认方向

## 一、角色总览

**基本信息**

- **职级**：P0（实习生） ｜ 入职时间 2026-06-30
- **历史绩效**：暂无（新入职实习生）。
- **mentor**：高炳涛（直属上级）

**角色定位（Q2 OKR 分工）**

- 归 **O4 预研&Agents 线**：负责 Diffusion / World Model 方向预研（李坤 2026-06-30 确认）。
- 具体课题、与靳希睿/杨星昊（WM 内部探索）的分工待入职后从日报/周五预研评审补充。

**性格特点**

- 暂无观察数据（入职仅数天）。

**潜力与短板**

- **潜力**：投递岗位为"仿真场景算法实习生"，方向明确为 diffusion/WM 预研。
- **短板**：暂无观察数据。

## 二、核心项目

| 项目 | 负责内容 | 项目 ledger |
|-|-|-|
| **WM-内部探索** | contributor：Diffusion / World Model 预研（与靳希睿/杨星昊协同，分工待定） | [WM-内部探索 ledger](https://xiaopeng.feishu.cn/docx/N65zd5za0odP0NxrNmAcGZILnsi) |

**代码提交记录**

暂无代码提交记录。

## 三、日常表现

| 时间 | 来源 | 内容 & 分析 |
|-|-|-|
| 2026-06-30（W27） | HR群offer卡片 + 入职排期 | 正式入职，归仿真算法组，直属上级高炳涛。6/17 已接受 offer，6/26 确认入职排期。 |
| 2026-06-30（W27） | 李坤确认 | 负责 diffusion 和 world model 方向的预研。 |
| 2026-07-20\~24（W30） | 作战表 W30 周一 | 首次出现实质产出：训练 7 视角可控驾驶视频自回归生成，分别验证 Feedforward 3dgs / 高质量 3dgs / nvfixer 优化 3dgs 渲染视频作为 control video 的效果；尝试将训练模型用于场景泛化 day2night。**跨项目协作**：为王禹丁场景泛化提供泛化后黑夜效果图作为开环所需 dds（王禹丁 7/23 据此得出夜间画龙对比结论）。方向落到 WM 预研 + 场景泛化落地结合处。（来源：Q3作战表 W30 周一） |

> 说明：本表以周为粒度汇总；赵浩南为新入职实习生，后续从日报/周五预研评审持续补充。

## W31 开题评审增量（2026-07-31）

**可控世界模型方向被明确要求从通用研究收缩为仿真特化落地。** <cite type="user" user-id="ou_f3ec31ec2eeff018016f5eeba3aaded1" user-name="赵浩南"></cite> 已完成基础视频生成和初步多视角、白天转黑夜能力，当前主要难点是短窗口自回归的累计误差。评审认为其 3DGS 控制和仿真闭环是差异化优势，但单人无法覆盖通用世界模型，应优先选择车衣、黑夜或新视角中的一个刚需做可验收 demo，再扩展能力。GPU 资源仍有缺口。来源：<cite doc-id="Dm5ZdwiuToVJFRx6HJDc71mPnSd" file-type="docx" title="智能纪要：AI实习生③班-开题报告（5） 2026年7月31日" type="doc"></cite>、<cite doc-id="MQzldSixToM2xexthQNcIzoXnmg" file-type="docx" title="文字记录： AI实习生③班-开题报告（5） 2026年7月31日" type="doc"></cite>。