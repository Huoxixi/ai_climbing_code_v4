# CLAUDE.md

## 用户指定的本地开发基线（2026-09-05）

当前版本 `local-latest-2026.09.05.1` 为用户指定的本地最新版。后续本地代码修改以本目录最新提交为基础，参见 `LOCAL_LATEST.md` 与 `LOCAL_VERSION.json`。不要把旧 audit 工作区、历史快照或生产版本当成本地开发基线。固定入口为 `http://127.0.0.1:4176/#/photo-routes`，本地持久数据及 API 密钥必须保留在 `.local/` 并保持 Git 忽略。

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

# User Communication / Product Interpretation

Treat the user as non-technical by default. User requests may be emotional, imprecise, incomplete, or expressed in everyday language rather than engineering terms.

Before turning a request into implementation:
- First interpret the product intent: what user-facing outcome, workflow, pain point, or business goal is probably being requested.
- Translate vague language into concrete product requirements and state the interpretation briefly.
- Avoid exposing unnecessary technical jargon. Explain technical constraints in plain language and connect them to user impact.
- If the request can reasonably mean multiple things, list the likely interpretations and ask only the smallest blocking question.
- If a safe, minimal assumption is enough to proceed, state that assumption and continue.
- Keep communication calm and direct even when the user's wording is impatient or emotionally charged.
- Do not blindly implement literal wording when it conflicts with the likely product goal; surface the mismatch and recommend the product-sensible path.

Success means the agent behaves like a product-minded engineer: clarify the real need, reduce user decision burden, and convert non-technical requests into verifiable implementation steps.

## 实施前产品澄清

除低风险、孤立且可逆的小改动外，在实施前必须先完成以下步骤：

1. 先用只读检查确认代码、数据结构、现有交互和兼容性，不能把可从项目中发现的事实反问给用户。
2. 用通俗语言说明对用户目标的理解，以及准备交付的用户可见结果。
3. 只提出会影响范围、历史数据处理、用户流程、关键取舍或验收标准的必要且实际问题；问题应附带推荐方案，避免要求用户做技术实现决策。
4. 在关键问题得到确认后再修改代码或数据；若采用了安全默认值，必须明确说明该假设。

目标是避免因需求理解偏差导致返工，同时不以无关问题阻塞正常实现。

---

# Project-Specific Database / Supabase Rules

本部分用于约束 AI Agent 在本项目中使用 Supabase / 数据库时的行为。

项目名称：`ai_climbing_code`

数据库工具命名空间：

```text
mcp__supabase__
```

## 1. Supabase 使用权限

Agent 可以使用 `mcp__supabase__` 协助完成：

1. 查看 Supabase 项目、组织、表结构、迁移记录、日志。
2. 设计数据库表结构。
3. 编写 SQL。
4. 创建表、字段、索引、函数、触发器。
5. 创建和修改 RLS 策略。
6. 创建和管理 Storage bucket。
7. 生成 migration。
8. 执行安全 SQL。
9. 为项目代码接入 Supabase。
10. 查询少量测试数据用于验证功能。

## 2. 高风险操作规则

以下操作允许执行，但必须先获得用户明确确认：

1. 删除表。
2. 删除字段。
3. 删除数据。
4. 清空表。
5. 删除函数。
6. 删除触发器。
7. 删除 RLS policy。
8. 删除 Storage bucket。
9. 修改 `auth.users`。
10. 重置 schema。
11. 重置数据库结构。
12. 任何可能造成数据不可恢复丢失的操作。

执行前必须使用以下格式确认：

```text
【高风险操作确认】
目标对象：
将执行的 SQL 或操作：
影响范围：
是否会造成数据丢失：
是否可以回滚：
建议备份方式：
请用户回复“确认执行”后再继续。
```

只有当用户明确回复：

```text
确认执行
```

才可以继续。

以下回复不算确认：

```text
可以吧
继续
你看着办
ok
go ahead
```

## 3. 绝对禁止

1. 禁止删除 Supabase 项目。
2. 禁止泄露、打印、提交任何 token、service_role key、数据库密码、`.env` 内容。
3. 禁止把真实密钥写入代码。
4. 禁止把 `.env`、`.venv`、`node_modules` 提交到 GitHub。
5. 禁止无说明地执行破坏性 SQL。
6. 禁止导出全表数据，除非用户明确要求。

## 4. 数据库设计原则

1. 默认优先使用 migration 管理数据库结构。
2. 默认开启 RLS。
3. 每张业务表都应考虑权限策略。
4. 前端只能使用 publishable / anon key。
5. 后端高权限操作必须通过服务端环境变量读取密钥。
6. 不要在前端暴露 service_role key。
7. 查询数据时默认只查询少量样例。
8. 对批量写入、批量更新、批量删除必须先说明影响范围。

## 5. 执行数据库任务的流程

处理 Supabase / 数据库任务时，Agent 应按以下流程执行：

1. 先只读检查当前 Supabase 项目。
2. 确认目标项目。
3. 检查已有表结构、RLS、迁移记录。
4. 明确用户目标。
5. 给出最小可行方案。
6. 对非高风险操作，可以在说明后执行。
7. 对高风险操作，必须等待用户回复“确认执行”。
8. 执行后验证结果。
9. 最后汇报执行内容。

## 6. 汇报格式

完成任务后，必须按以下格式汇报：

```text
完成情况：
- 

Supabase 操作：
- 

执行的 SQL / migration：
- 

修改的项目文件：
- 

是否涉及高风险操作：
- 

需要用户手动处理：
- 
```

如果只是检查，没有修改任何内容，必须明确说明：

```text
只读检查完成，没有修改任何文件或数据库。
```

---

# Project-Specific Server Deployment Rule

When giving server deployment commands for this project, use the user's preferred GitHub-to-server sync workflow by default. Do not assume `/root/ai_climbing_code` should be updated with `git pull`.

Preferred sync workflow:

```bash
cd /tmp
rm -rf ai_climbing_code_v4
git clone git@github.com:Huoxixi/ai_climbing_code_v4.git

rsync -av \
  --exclude='backend/.env' \
  --exclude='backend/.venv' \
  --exclude='node_modules' \
  --exclude='frontend/node_modules' \
  /tmp/ai_climbing_code_v4/ /root/ai_climbing_code/
```

After this sync, run project-specific build, dependency install, Nginx reload, or backend restart commands from `/root/ai_climbing_code` as needed.
