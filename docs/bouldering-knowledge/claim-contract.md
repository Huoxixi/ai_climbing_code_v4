# 个性化复盘主张与独立验收合同

日期：2026-09-27。实现依据为[修改报告与建议边界](../archive/pre-release-20261001/个性化攀岩复盘_修改报告与建议边界_2026-09-26.md)。本合同补充知识单元合同，不改写既有 24 个单元的审核状态。当前新增的 3 条主张均为 `draft`、`automatic_use: false`；没有专业批准，也没有真实效果验收。

## 主张权限

运行时只读取本地文件。`claims/*.json` 每个文件是一条全局唯一主张；`unit_id` 与 `source_claim_id` 指向已有知识单元中的具体主张。知识单元获准、检索命中、模型自报审核号或模型条件文字非空都不能授予建议权限。风险判断始终不开放。

首版仅接受以下三类，均限成人、室内抱石、固定机位和缓慢连续移动：

| category | 候选范围 | 必需的类别条件 |
|---|---|---|
| `existing_foot_sequence` | 已有脚序的预先确认 | `foot_sequence_visible`、`adjustment_confirmed` |
| `same_foothold_preparation` | 同一落点的落脚准备 | `shoe_contact_process_visible`、`contact_identity_reliable`、`following_action_visible` |
| `existing_transition_preparation` | 已有动作的衔接准备 | `before_pause_after_visible`、`next_target_confirmed` |

全部类别还必须有 `camera_fixed`、`slow_continuous`、`limbs_and_next_target_visible`、`single_wall_clear_perspective`、`existing_plan_unchanged`。必要视觉条件不能改成由用户自述证明；“保留已有方案”在画面检查中指同一已示范的局部任务，不能倒推用户未报告的计划或意图。目标相关性在事实成立后独立判断，不能作为观察输入，无法建立关联就只留观察。

主张还保存固定 `adjustment_template`、`verification_template`、逐项 `exclusions`、`cannot_infer`、`evidence_links`、版本和停用状态。模型只能选择本地候选并提供待检查条件，不能自由重写处方、来源或审核权限。产品规则和无来源假设不能直接充当专业证据；当前三个草案的教学方向仍待教练确认，原资料的青少年教学不能直接证明成人迁移有效。

## 审核与撤回

`reviews/*.json` 只保存真实主张审核，模板另放 `templates/`，不会被运行时加载为批准记录。每条批准需有：

- 确切的 `claim_id`、整数 `claim_version`、`claim_sha256` 和一致 `scope`。
- 实际审核人标识、成人抱石教学经验确认、真实审核日期、理由与未决分歧。
- 与本地主张完全相同的来源 ID、证据 ID、具体段落定位，以及对应源记录摘要 `evidence_sha256`。
- 主张与证据语义对应、适用人群迁移已经实际审核；`status: approved`、`revoked: false` 且无撤回时间。

字符串非空或 `approved` 本身不够。程序会核对本地记录真实存在、内容与版本完全匹配。重复 ID、错误来源、修改后未重新审核或撤回都拒绝。结构检查不能替代教练阅读原文，也不能证明审核者身份；审核记录由有权限的维护者保存，模型输出不能写入这些目录。

`claim_sha256` 为稳定 JSON 编码摘要，只排除两个审核记录 ID，避免循环引用；`evidence_sha256` 绑定所引用的来源和证据卡内容。填写记录时使用 `ClaimRegistry.evidence_digest()` 和 `claim_digest()`，不得手填看起来合理的摘要。主张或固定文案变更必须更新版本并重审。

撤回时保留记录，将 `revoked` 设为 `true` 并写明 `revoked_at`。来源、主张、审核、嵌套验收文件与运行规则版本共同进入报告依据指纹，旧报告不会静默改成新结果；运行时停止使用撤回内容。

## 条件三态与证据

每个必要条件只接受 `satisfied`、`not_satisfied`、`unknown`。必要条件必须已满足，排除情形必须已不满足；任何缺失、未知、不符或重复编号均拒绝该建议。

画面条件示例：

```json
{
  "condition_id": "shoe_contact_process_visible",
  "state": "satisfied",
  "evidence": [{
    "kind": "visual_fact",
    "fact_id": "observation-1",
    "frame_ids": ["frame-10", "frame-11", "frame-12"]
  }]
}
```

`fact_id` 必须存在于已经独立看画面复核的事实；事实需记录有效帧 ID 和时间。独立复核要明确可见、时序充分、无记录冲突、无标注依赖；其 `condition_checks` 还必须对同一条件作出相同三态判断，并引用同一事实和覆盖以上锚点的实际画面。条件的所有帧必须属于该事实的已复核证据。仅引用合法时间、给所有条件填同一个事实编号或在整理阶段声称成立均不够。程序仍不能证明帧内容语义正确，第二次模型检查也不等于人工独立效果验收。

当前自述只能用于主张明确声明的 `source: current_self_report` 条件，须附 `self_report_field` 和 `expected_value`。引用为 `{"kind":"current_self_report","field":"goal"}`；运行时从本次真实输入取值，不读取模型提供的用户背景。自述不能证明画面事件、身体能力或失败原因。缺填不等于没有不适。

## 冻结协议与逐尝试数据

`validations/*.json` 为主张验收记录；其 `protocol_file`、`evaluation_file` 只能指向本目录下 JSON 实物，并核对文件内容摘要。现有模板全部未开始，不构成批准。

冻结协议记录数据集 ID、主张版本、类别、纳入/排除条件、分层与停止规则、开发集分组标识及六项 `generation_versions`：模型、提示、采样、知识、排序、画面压缩。技术建议须使用已知日期快照；别名模型只用于观察。协议、逐尝试数据与当前运行六项版本必须完全一致，变化后必须重新回归验收。`knowledge` 是来源、单元和主张内容摘要，不包含审核文件以避免循环摘要。

数据文件保存两名不同审核者的匿名标识、是否独立盲审、分歧是否解决及 `attempts`。每一行是一整次尝试，失败、无建议和重试费用仍计入该尝试，不拆成大量近似片段增加样本。不同尝试使用不同 `attempt_id`；同人或同线路共享匿名分组 ID，开发/验收之间不得交叉这些分组。个人素材、姓名、账号或授权正文不存入本知识库。

一行数据的格式如下，内容为构造示例，不是实测结果：

```json
{
  "attempt_id": "opaque-attempt-id",
  "participant_group": "opaque-participant-group",
  "route_group": "opaque-route-group",
  "category": "existing_foot_sequence",
  "in_scope": true,
  "authorized": false,
  "real_video": false,
  "normal_action": false,
  "should_refuse": false,
  "has_supported_opportunity": true,
  "technical_problem_asserted": false,
  "advice": [],
  "critical_observations": [true, false],
  "primary_focus_acceptable": null,
  "user_understands": null,
  "prohibited_content_count": 0,
  "cost_cny": null,
  "latency_seconds": 15,
  "strata": ["occluded", "no_personal_background"]
}
```

若实际输出建议，`advice` 只能有一项，分别填入布尔审核结果 `facts_correct`、`knowledge_supported`、`conditions_met`、`adjustment_appropriate`、`verification_appropriate`；五项全真才算正确且适用。缺项拒绝评估，不当作通过。`critical_observations` 每个布尔值代表一条关键事实的人工核实结果；`null` 的重点或理解结果表示没有评估，不算正确。

从 `backend` 目录使用已有 Python 运行时执行 `python -X utf8 -m core.replay_coaching_evaluation <评估文件> --output <汇总文件>`，只做离线汇总，不访问云服务、不改变知识状态。不要将真实个人数据输出到公共调试位置。

## 指标解释与拟定门槛

汇总逐类、逐分组公开分子、分母和 95% 不确定区间，另列全范围尝试数及范围外误建议。空建议的建议正确率为 `null`、分母 0，绝不计作正确；正常无建议也不计作合格机会漏检。费用未知保持 `null`，全部失败和无建议尝试保留在总次数及成本记录中。

关键观察正确率按关键事实数计算，同时额外提供更严格的“该次所有关键事实都正确”的尝试级指标。多个事实仍属于同次尝试，不当作独立样本。对同用户或同线路形成的相连组，使用固定种子的组级重采样，并保留以组数计算的保守 Wilson 边界，避免全对时得到无不确定性的 `[1,1]`。相关资料不足 20 个独立组时不报告可放行区间；独立单次样本使用 Wilson 区间。该估计是保守的本地验收工具，不能替代适合具体采样设计的统计复核。

每类至少 60 次独立尝试；需实际包含正常和应拒绝场景；建议正确适用率至少 95%、95% 区间下界至少 90%；关键事实正确率至少 95%、重点可接受率和用户理解率至少 90%。必须公开覆盖率、合格机会覆盖率、正常误判和应拒绝误建议；禁止内容、范围外建议与拒绝误建议不得出现。样本不足或分母为零继续不放行，不以其他类别平均值补足。

程序达到算术门槛本身不会自动批准主张。只有真实授权材料、冻结协议、两名审核者与主张级审核共同通过才能形成可用记录；组间差异、高分歧类别和误差后果仍需人工决定是否收紧。所有工具汇总保留 `effect_improvement_established: false`：单一流程的合格率不证明比旧流程更准确，也不证明完攀、用力或伤害风险得到改善。
