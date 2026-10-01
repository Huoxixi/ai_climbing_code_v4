# 知识数据合同 v1

`docs/bouldering-knowledge/` 是唯一内容根目录。知识以 UTF-8 JSON 保存，手册从它生成；编辑 JSON，不分别维护两套正文。JSON 字段按下文及已有单元生成，脚本 `check` 是结构约束的可执行部分。

## 文件

- `sources.json`：对象，`schema_version: 1` 与 `sources` 数组。
- `units/KB-FOOT-001.json` 等：每文件一个知识对象，文件名与 `id` 一致。
- `state.json`：批次、实际条目和下一步；不存模型臆测的完成百分比。
- `runs/*.md`：人工可读的运行记录；同日多轮用不同文件名。
- `HANDBOOK.md`：派生阅读文件，首行为生成标记；可随时由脚本重建。

## 来源及证据定位

每项来源必须有 `id`、`title`、`author`、`url`、`source_type`、`published`、`accessed`、`access_status`、`scope`、`limitations` 和非空 `evidence`。

`source_type` 为 `coaching` / `federation` / `research`；表示性质，不是质量排名。出版日期未显示时 `published` 写明未知，不能采用网页页脚版权年份冒充。

`access_status` 为 `located` / `section_read` / `full_text_read`。后者指实际读过全文，不包括只读摘要或只展开一节。只能引用后两种状态中的已读段落；资料初查未打开的可保存 `located`，不能支撑可调用主张。

每张证据卡有 `id`、`locator`、`supports`、`limits`。定位使用人能重复找到的标题/段落或版本/页码，网络工具内部结果编号和临时行号不能作为唯一定位。不同来源的证据 ID 在库内唯一。摘要短写，不复制整页或书籍图片。

## 知识单元

必填字段：

- `schema_version: 1`, `id`, `version`（正整数）, `batch_id`, `title`。
- `aliases`, `questions`, `tags`, `action_codes`, `stage_tags`, `related_units`：字符串数组；未知动作代码留空，不能新造业务代码。
- `context`: `activity` 固定为 `indoor_bouldering`，`applies_if` 和 `exclusions` 为非空数组。
- `claims`: 每条有单元内唯一 `id`、`statement`、`basis`、`evidence_ids`。
- `observation`: `required_views`, `events`, `unknowns`, `cannot_infer`，均为非空字符串数组。这是项目提出的观察合同，不冒充原文实验定义。
- `next_step`: `kind: review_only`, `text`, `conditions`, `compare`。后两项为非空数组。
- `examples`: 至少两项，包含 `kind: constructed`、`scenario`、`allowed`、`disallowed`。首版没有授权实拍样本，不能标为真实视频。
- `review`: `content` 为 `draft` / `ai_source_checked`；`professional` 为 `pending`；`video_validation` 为 `not_started`；`automatic_use` 为 false。
- `gaps`: 字符串数组，记录证据、语义或验证缺口。

`basis` 取值：

| 值 | 说明 | 约束 |
|---|---|---|
| source_summary | 对已读原文的有限摘要 | 至少一条实际证据 ID；措辞不比原文更强 |
| conditional_transfer | 从原任务迁移到抱石的候选解释 | 有证据 ID 与 `transfer_note`，写明任务/对象/条件差异 |
| teaching_hypothesis | 自己提出的教学或比较假设 | 不要求伪造证据 ID；应说明如何观察或验证 |
| product_rule | 本项目的定义、记录或表达约定 | 不当成运动科学结论；来源可为空 |

每个单元至少一项有依据的摘要或迁移；同一证据只支持 `supports` 范围。其他字段里的技术断言也要核对：不能把需要证据的力学断言藏到 `observation`、例子或提示语。

初版审核枚举刻意不含“已教练审核/已验证”。专业审核和实测真正发生后，先增加可引用审核记录、独立验证材料与对应校验规则，才能升级合同。不能仅把布尔值改为 true。

## 进度

`state.json` 包含 `schema_version: 1`、`updated`、`last_run`、`batches`。

批次有 `id`、`topic`、`status`、`unit_ids`、`next_action`。状态为 `pending` / `in_progress` / `authored`；`authored` 必须有非空且真实存在的 `unit_ids`。所有知识单元必须被其所属批次列出，且不得混列到另一批次。

批次进度和知识审核分别解释。重写条目增加 `version`，保存旧版本或依赖已保存的版本历史；没有版本历史的既有文件不要先覆盖再补记。

## 脚本与证据边界

脚本校验结构、引用和状态，不能验证网页作者身份、原文语义、技术可行性或建议效果。搜索只返回候选，不提供“适用概率”。`search --purpose video` 在 v1 返回空，因为自动视频建议尚未启用；知识问答使用默认 `learn`，读取条目后按可见证据和条件解释。

真实视频将来绑定已有动作 ID、岩点版本、实际采样率、时间来源和人工复核版本，不在知识卡中保存个人素材或密钥。
