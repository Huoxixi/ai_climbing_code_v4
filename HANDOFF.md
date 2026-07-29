# 项目交接文档

> 当前状态说明（2026-07-18）：本文保留较长的历史实现记录，其中的旧账号流程、自由文本 AI 要求、英文工作区名称和早期岩板外观设定不再代表当前产品。当前版本定位为“本地单机版攀岩定线辅助系统”，以 `PRODUCT.md`、`docs/项目业务审核与修改报告.md` 和实际运行界面为准。

## 2026-07-18 最新交接：岩板多板对照与 AI 重组可视化

> 新对话请先读本节。本节是当前最新状态；下方“标准板修复队列”“AI Lab 本地化”等章节是仍有参考价值的历史记录，但其中测试数量、文件状态和待验证事项可能已经过期。

### 一、我们正在做什么

当前主任务是把项目整理成可向老师和非技术客户演示的“本地单机版攀岩定线辅助系统”，
本轮专门完成以下产品需求：

1. 岩板资产页增加“资产列表 / 岩板对照”。
2. 用户可以临时选择 2–4 块已启用岩板，只读并排查看，第一块是基准岩板。
3. AI“重新组合路线”不能再只展示质量数字，必须展示：
   - 原岩板完整布局；
   - 最多两块真实、有效且不同的候选布局；
   - 具体新增、移除、修改、保留坐标；
   - 起点、终点、完整 Beta、质量、预测难度、风险和复用率。
4. 如果只能生成一块有效候选，必须明确说明，不得复制或伪造第二块。
5. 不修改仿真业务，不连接或修改 Supabase，不新增数据库表。

业务规则以 `docs/项目业务审核与修改报告.md` 为准。产品当前不是多用户云端系统，也不能把
规则初审描述成替代专业定线员或现场安全确认。

### 二、本轮已经完成

#### 1. 通用多板对照

岩板资产页已有两种模式：

- `资产列表`
- `岩板对照`

对照模式只读取 `boards.savedBoards`，因此归档岩板不会进入选择器。选择状态只存在于 Vue
页面内存，不写入 JSON、数据库或 Supabase。

已支持：

- 最少 2 块、最多 4 块。
- 第一块自动成为基准。
- “设为基准”会把目标岩板移动到选择顺序第一位。
- “移出对照”和“清空对照”。
- 没有编辑、保存、重命名或归档入口。
- 桌面端 2 块双栏、3 块三栏、4 块两行双栏。
- 窄屏页面内横向滚动和吸附；页面本身不产生横向溢出。

主要实现：

- `frontend/src/App.vue`
- `frontend/src/components/BoardComparisonPanel.vue`
- `frontend/src/utils/boardComparison.js`
- `frontend/src/style.css`

#### 2. 统一差异计算

`compareBoards(reference, target)` 已实现以下确定性规则：

- 基准有、目标没有：`removed`。
- 目标有、基准没有：`added`。
- 坐标相同但类型、变体、旋转、缩放、起点或终点角色变化：`changed`。
- 坐标和属性完全相同：`retained`。
- 单独比较起点、终点和 Beta 四肢目标顺序。
- 被移除岩点会作为淡化、虚线幽灵点显示在目标板上。
- 差异同时使用颜色、`新 / 移 / 改`文字徽标、坐标清单和读屏名称，不能只依赖颜色。
- 岩点旁显示 Beta 步骤序号，画布下方显示完整动作序列。

复用率严格按：

```text
完全保留岩点数 ÷ 基准岩点数
```

分级：

- `>= 70%`：达到最优标准。
- `>= 40%`：达到通过标准。
- `< 40%`：变化较大。

不同规格岩板允许并排查看，但只按坐标名称比较，并明确提示“不代表物理位置完全一致”，
不得据此输出物理尺度优劣。

#### 3. BoardCanvas 真正只读

`frontend/src/components/BoardCanvas.vue` 新增：

- `readonly`
- `comparisonStatusById`
- `showBetaSteps`

只读时：

- 孔位和岩点全部 `disabled`。
- `tabindex=-1`，不可键盘聚焦。
- `place` 和 `select` 事件处理函数会再次检查 `readonly`，不会发出编辑事件。
- 无障碍名称由“放置 / 选择”改为“查看”。

重要：`readonly` 默认仍为 `false`，因此 Studio 和仿真共享画布的既有行为没有被改变。不要把
只读逻辑改成全局默认，否则会破坏 Studio 编辑或仿真页面。

#### 4. AI 重组真实性修复

`backend/agent/experiments.py` 已调整：

- 最终最多返回 2 块候选，`selected_routes` 和 `candidate_routes` 按索引对应。
- 候选签名必须彼此不同。
- 候选签名也必须不同于原岩板。
- 不会为了凑满两块而复制候选。
- 风格变化策略会主动减少中段点，避免把原板原样重新包装成“新候选”。

浏览器真实验收曾发现一个严重问题：旧逻辑只保证“候选之间不同”，没有保证“候选与原板
不同”，导致原板被换名后冒充重组结果。现在 `seen_signatures` 一开始就包含原板签名，这个坑
不能再放回来。

前端 AI 结果现在直接使用 `BoardComparisonPanel`：

- 原板作为基准。
- 候选显示“未保存副本”。
- 展示确定性差异，不让大模型改变事实。
- 风险显示为通俗中文，例如“低（20）”。
- 只有一块候选时显示：“不复制或伪造第二块结果”。
- 保留“载入定线工作台”，载入后仍需用户手动保存。

真实验收示例：

```text
原板：Shrine 3
有效候选：1 块
移除：G7
终点：D17 不变
Beta：9 步 -> 8 步
复用率：89%
等级：达到最优标准
风险：低（20）
```

#### 5. AI 任务 30 秒超时修复

浏览器验收过程中曾出现：

```text
timeout of 30000ms exceeded
```

根因不是前端超时时间太短，而是 CPU 密集的路线搜索运行在 FastAPI 事件循环里，导致任务提交
和轮询接口不能及时响应。此外，FastAPI `BackgroundTasks` 会在响应生命周期中等待后台工作，
不适合这里的长任务。

`backend/main.py` 已改为：

- `/api/generate` 使用 `asyncio.create_task()` 创建真正独立的会话内任务。
- AI 路线搜索通过 `asyncio.to_thread(...)` 移出 API 事件循环。
- API 可以立即返回任务 ID，前端继续轮询 `/api/result/{task_id}`。

不要通过简单提高 Axios 30 秒超时来掩盖这个问题，也不要把 AI 搜索重新改回事件循环同步执行。

#### 6. 旧岩板规格显示兼容

真实本地数据中曾出现旧英文规格：

```text
Standard training board 11x18
```

`App.vue` 现在通过 `boardSpecDisplayLabel()` 按真实行列数显示当前规范中文名称，旧数据仍兼容
读取，但不会把旧材质时代的英文标签重新显示给客户。

#### 7. 报告、截图和修改日志

已更新：

- `docs/项目业务审核与修改报告.md`
- `docs/项目汇报演示稿.md`
- `docs/演示前检查清单.md`
- `backend/data/modification_log.json`

新增截图：

- `docs/screenshots/08-board-compare-1440.png`
- `docs/screenshots/09-board-compare-1024.png`
- `docs/screenshots/10-board-compare-390.png`
- `docs/screenshots/11-ai-recompose-comparison.png`

本轮没有修改 `backend/data/optimal_patterns.json`。如果用户确认要永久记忆，建议加入以下生成
规则：候选必须不同于原板和其他候选；不足数量时不得伪造；差异事实只能由确定性数据生成。

### 三、当前卡在哪里

目前没有代码 blocker，本轮功能和自动化测试都已完成。

剩余工作属于演示前复查和用户确认：

1. 在用户明天实际演示的浏览器里按 `docs/演示前检查清单.md` 再走一遍。
2. 如用户希望，把上述三条“候选真实性规则”写入 `backend/data/optimal_patterns.json` 作为永久
   线路生成记忆；当前只记录在 `modification_log.json`，不要未经确认自动改学习规则。
3. 当前工作区有大量前序任务留下的未提交修改。不要擅自提交整个仓库，也不要重置。
4. Vite 构建仍有主包大于 500KB 的性能提示，但生产构建成功；仿真页已懒加载。本轮没有继续
   拆分 Element Plus，因为这不是功能 blocker。

### 四、下一步建议执行顺序

新对话开始后：

1. 先读：
   - `AGENTS.md`
   - `PRODUCT.md`
   - 本文件最新章节
   - `docs/项目业务审核与修改报告.md`
2. 运行 `git status --short`，确认哪些是用户/前序任务修改，禁止清理整个工作区。
3. 使用项目脚本启动：

```powershell
cd "D:\学校课程\ai攀岩定线问题\ai_climbing_code"
.\scripts\start_demo.ps1
```

4. 如果提示端口占用，先检查 5173 和 8000 的监听进程，或运行项目的停止脚本：

```powershell
.\scripts\stop_demo.ps1
```

不要连续启动多个后端。之前用户遇到的 `WinError 10048 / 10013` 大多来自已有服务仍占用端口，
不是代码语法错误。

5. 浏览器重点验收：
   - 岩板资产 → 岩板对照。
   - 选择 2、3、4 块岩板。
   - 设为基准、移出、清空。
   - 390px 下确认页面不横向溢出，滚动只发生在对照区域内。
   - AI 实验室 → 重新组合路线。
   - 确认候选与原板不同，最多两块。
   - 只有一块时确认诚实提示。
   - 确认候选显示“未保存副本”和“载入定线工作台”。
6. 如果继续开发，先运行当前回归测试，再做小范围修改。

### 五、已完成的最终验证

后端非仿真测试：

```powershell
cd "D:\学校课程\ai攀岩定线问题\ai_climbing_code\backend"
$tests = Get-ChildItem -File -Filter 'test_*.py' |
  Where-Object { $_.Name -notin @('test_simulation.py','test_api.py') } |
  ForEach-Object { $_.BaseName }
& .\.venv\Scripts\python.exe -m unittest $tests
```

结果：

```text
Ran 59 tests
OK
```

前端：

```powershell
cd "D:\学校课程\ai攀岩定线问题\ai_climbing_code\frontend"
npm.cmd test
npm.cmd run build
```

结果：

```text
9 tests passed
production build passed
```

浏览器：

- 1440px：2 块岩板双栏，无页面横向溢出。
- 1024px：岩板仍清晰显示，无页面横向溢出。
- 390px：对照区横向滚动，页面宽度等于视口宽度。
- 对照画布中 `button:not(:disabled)` 数量为 0。
- AI 实测返回 1 块与原板不同的有效候选。
- 修复后任务提交不再出现 30 秒超时。

### 六、本轮一定不要再踩的坑

1. **不要把原板换个名字当候选。**
   候选必须不同于原板，也必须彼此不同。
2. **不要伪造第二块候选。**
   0、1、2 块都是合法结果，数量不足必须解释。
3. **不要让大模型决定差异、难度、安全或排序事实。**
   大模型只能润色中文名称和说明。
4. **不要用 FastAPI `BackgroundTasks` 重新承载 CPU 密集 AI 搜索。**
   会堵塞响应生命周期；保持 `create_task + to_thread`。
5. **不要只提高前端 timeout。**
   这会掩盖后端事件循环阻塞。
6. **不要把只读设成 BoardCanvas 全局默认。**
   Studio 和仿真共享该组件，默认必须保持可交互。
7. **不要只用颜色表示差异。**
   必须保留文字徽标、坐标清单和读屏名称。
8. **不要把相同坐标名说成不同规格上的相同物理位置。**
   不同规格只做名称级比较。
9. **不要让归档岩板进入对照选择器。**
   对照只使用 `savedBoards`，不是 `archivedBoards`。
10. **不要在 PowerShell 直接运行 `npm`。**
    该机器执行策略会阻止 `npm.ps1`，必须使用 `npm.cmd`。
11. **不要启动重复服务。**
    端口 5173 或 8000 被占用时先确认原进程并通过停止脚本关闭。
12. **不要清理或重置脏工作区。**
    禁止 `git reset --hard`、`git checkout -- .`，也不要提交全部未知改动。
13. **不要改 Supabase 或仿真业务。**
    本轮明确边界是不连接 Supabase、不迁移数据库、不审核或修复仿真。

### 七、本轮关键文件

- 多板入口和 AI 结果：`frontend/src/App.vue`
- 通用对照面板：`frontend/src/components/BoardComparisonPanel.vue`
- 确定性差异规则：`frontend/src/utils/boardComparison.js`
- 只读画布：`frontend/src/components/BoardCanvas.vue`
- 响应式和差异视觉：`frontend/src/style.css`
- 前端差异测试：`frontend/test/board-comparison.test.mjs`
- AI 候选生成：`backend/agent/experiments.py`
- AI 异步任务：`backend/main.py`
- AI 回归测试：`backend/test_ai_lab_experiments.py`
- 修改审计：`backend/data/modification_log.json`
- 业务报告：`docs/项目业务审核与修改报告.md`
- 汇报演示稿：`docs/项目汇报演示稿.md`
- 演示检查：`docs/演示前检查清单.md`

## 给新对话的第一句话

这是一个室内攀岩定线工具项目，核心模块包括 Studio 岩板编辑、岩点库、岩板资产、标准板库、AI Lab。最近主要在处理两条产品主线：

1. **AI Lab**：用户必须先从“岩板资产”里选择一块已保存岩板，再执行“重新组合路线”和“提出修改建议”。
2. **标准板库**：把本地标准板路线库做成可用工作台，包括修复队列、修复前后对比、批量发布修复版路线、点亮岩点可视化增强，并且标准板库必须本地优先，不依赖 Supabase。

用户不是技术用户，沟通时要用产品语言解释影响：例如“页面能不能打开、路线能不能显示、数据保存在哪里”，不要直接丢 JWT、RLS、外键这些术语，除非必须解释原因。

## 当前目标

当前最近一轮目标是：**标准板库和修复队列必须稳定可用**。

具体要求：

- 标准板路线库从本地文件读取，不从 Supabase 读取。
- 标准板页面不能因为 Supabase auth 超时而卡住。
- 标准板画布背景固定为 11 x 18，不跟 Studio 当前岩板规格变化。
- 待修复路线点击后必须能显示：
  - 可尝试但未修复路线：显示原始路线和失败原因。
  - 已修复路线：显示修复前 / 修复后对比。
- 已修复路线可以批量选择并发布进标准板线路库。

## 已经完成的内容

### 1. 标准板库本地优先

标准板路线本体确认在本地：

- `backend/data/raw_datasets/moonGen_scrape_2016_final`
- `backend/data/standard_board_review_queue.json`

标准板主接口应只走本地逻辑：

- `GET /api/standard-board/routes`
- `GET /api/standard-board/routes/{source_id}`
- `GET /api/standard-board/repairs`
- `GET /api/standard-board/repairs/{source_id}`
- `POST /api/standard-board/generate`

标准板收藏、评分、训练记录已改成本地 JSON：

- `backend/data/standard_board_activity.json`

注意：标准板路线库不是 Supabase 数据源。Supabase 只应该是登录、远程个人数据等可选能力，不能阻塞标准板库。

### 2. Supabase 超时隔离

之前出现过：

```text
Supabase auth validation failed: Supabase GET ... /auth/v1/user request failed: 超时
```

原因是后端某些资源/活动接口会先校验 Supabase 用户。已经做过的方向：

- 标准板 activity 不应调用 Supabase auth。
- `/api/holds/mapping`、`/api/holds/vectors` 优先读本地 JSON。
- `/api/my-boards` 优先读本地 `saved_boards.json`。
- Supabase 网络请求超时时应被包装成可捕获错误，不能直接让页面资源加载失败。

### 3. 标准板 11 x 18 固定背景

标准板预览画布已改为固定规格：

- 11 列：A-K
- 18 行：1-18
- 孔距：200 x 200 mm
- 规格：2440 x 3660 mm
- 不再使用 `studio.coordinateColumns`、`studio.coordinateRows`、`studio.getCoordStyle` 来渲染标准板预览。

影响范围：

- 标准板路线预览。
- 修复队列“修复前”预览。
- 修复队列“修复后”预览。

不影响 Studio 普通岩板编辑。

### 4. 修复队列与前后对比

用户报错：

```text
standardBoardService.compareRepair is not a function
```

原因：

- `App.vue` 已经调用 `standardBoardService.compareRepair()`。
- 但 `frontend/src/services/standardBoardService.js` 没有这个方法。
- 后端也缺少 `/api/standard-board/repairs/{source_id}/comparison`。

已经补齐的方向：

- 前端服务：
  - `compareRepair(sourceId)`
  - `publishRepairs(sourceIds)`
- 后端模型：
  - `StandardBoardRepairComparison`
  - `StandardBoardRepairPublishRequest`
  - `StandardBoardRepairPublishResponse`
- 后端接口：
  - `GET /api/standard-board/repairs/{source_id}/comparison`
  - `POST /api/standard-board/repairs/publish`
- 后端逻辑：
  - `repair_comparison(source_id)`
  - `publish_standard_board_repairs(source_ids)`
  - 修复版路线使用稳定 ID：`repaired-{source_id}`
  - 发布后的修复版路线合并进标准板线路库。

### 5. 修复队列默认隐藏不可修复

产品要求：

- 前端不展示不可修复路线。
- 后端默认 `query_standard_board_repairs(status=None)` 不返回 `unrepairable`。
- 后端仍保留内部计算，不删除 review queue 数据。

### 6. 点亮岩点可视化增强

`BoardCanvas` 已加过更明显的点亮表现：

- 已点亮岩点提高层级和尺寸。
- 未点亮岩点降低透明度和视觉权重。
- 起步手点、起步脚点、中间点、终点有不同视觉标记。
- 增加角色小标记，例如“手 / 脚 / 线 / 顶”。

目标是让用户在满板岩点上也能一眼看到路线。

## 当前卡点

目前没有明确的代码 blocker，但有一个高风险状态：**需要在真实浏览器里重新验证修复队列交互**。

重点验证：

- 刷新前端后，`standardBoardService.compareRepair is not a function` 是否消失。
- 点击待修复路线是否能选中。
- `repairable` 路线是否显示修复前原始路线和失败原因。
- `repaired` 路线是否显示修复前 / 修复后对比。
- 批量选择和“放入线路库”是否可用。
- 发布后标准板线路库是否出现 `repaired-{source_id}` 修复版路线。

如果用户仍看到旧报错，优先判断是不是前端 Vite 没重启或浏览器缓存没刷新。

## 下一步计划

建议新会话按这个顺序继续：

1. **重启服务并复现**
   - 后端：
     ```powershell
     cd "D:\学校课程\ai攀岩定线问题\ai_climbing_code\backend"
     .\.venv\Scripts\python.exe main.py
     ```
   - 前端：
     ```powershell
     cd "D:\学校课程\ai攀岩定线问题\ai_climbing_code\frontend"
     npm.cmd run dev
     ```
   - 浏览器强制刷新。

2. **验证修复队列**
   - 进入标准板库。
   - 切换到待修复路线。
   - 点击一条 `repairable`。
   - 点击一条 `repaired`。
   - 验证前后对比和失败原因。

3. **验证批量发布**
   - 勾选已修复路线。
   - 点击“放入线路库”。
   - 回到标准板线路库查找修复版路线。
   - 确认不会覆盖原始标准板数据。

4. **补充测试或修小问题**
   - 如果接口 404，先查 `backend/main.py` 路由是否加载的是当前代码。
   - 如果前端方法不存在，先查 `frontend/src/services/standardBoardService.js`。
   - 如果画布不是 11 x 18，查 `App.vue` 标准板 `BoardCanvas` 是否又用了 Studio 的 columns/rows/coord style。

## 已跑过的验证

最近相关验证命令：

```powershell
cd "D:\学校课程\ai攀岩定线问题\ai_climbing_code\backend"
.\.venv\Scripts\python.exe -m py_compile main.py core/models.py core/standard_board.py core/supabase_repo.py
```

```powershell
cd "D:\学校课程\ai攀岩定线问题\ai_climbing_code\backend"
.\.venv\Scripts\python.exe -m unittest test_standard_board.py test_standard_board_local_first.py
```

```powershell
cd "D:\学校课程\ai攀岩定线问题\ai_climbing_code\frontend"
npm.cmd run build
```

最近一次结果：

- 后端语法检查通过。
- 后端标准板相关测试通过，曾显示 `19 tests OK`。
- 前端构建通过。
- Vite 大 chunk 警告不是运行错误，可以暂时忽略。

## 一定不要再踩的坑

### 1. 不要让标准板库依赖 Supabase

标准板路线库在本地。标准板页面打开、筛选、点击路线、查看修复队列，都不应该因为 Supabase auth、JWT、profiles、网络超时而失败。

### 2. 不要把 Studio 当前岩板规格用于标准板预览

标准板库背景必须永远是 11 x 18。不要再把这些传给标准板 `BoardCanvas`：

- `studio.coordinateColumns`
- `studio.coordinateRows`
- `studio.getCoordStyle`
- `studio.currentBoardSpec`

标准板应该用固定的 standard board columns/rows/spec/coord style。

### 3. 不要只修前端方法名

`compareRepair is not a function` 看起来是前端问题，但完整链路需要：

- 前端 service 方法。
- 后端 `/comparison` 接口。
- 后端 response model。
- 后端 `repair_comparison` 逻辑。

只加 JS 方法会导致下一步变成 404 或接口数据不对。

### 4. 不要把不可修复路线删掉

产品要求是“前端去除不可修复”，不是删除数据。

正确做法：

- 默认查询隐藏 `unrepairable`。
- `status=unrepairable` 可以保留给内部检查。
- 不修改原始 review queue。

### 5. 不要污染真实本地 JSON 测试数据

涉及这些文件时要小心：

- `backend/data/saved_boards.json`
- `backend/data/standard_board_activity.json`
- `backend/data/standard_board_review_queue.json`
- `backend/data/standard_board_accepted_repairs.json`

测试发布修复路线时应使用 `tempfile` 和 `patch` 临时路径，不要写真实 accepted repairs 文件。

### 6. 不要执行数据库高风险操作

不要删除 Supabase 表、字段、数据、policy、bucket。

不要打印、提交、泄露：

- `.env`
- service role key
- token
- 数据库密码

如果用户明确要求数据库高风险操作，必须按项目规则先让用户回复“确认执行”。

### 7. 不要回滚用户或前序任务改动

这个工作区之前有多轮修改。不要使用：

```powershell
git reset --hard
git checkout -- .
```

如果需要提交，先让用户确认提交范围。

## 关键文件索引

- 后端入口：`backend/main.py`
- 标准板核心逻辑：`backend/core/standard_board.py`
- 数据模型：`backend/core/models.py`
- Supabase 封装：`backend/core/supabase_repo.py`
- 标准板前端服务：`frontend/src/services/standardBoardService.js`
- 前端主界面：`frontend/src/App.vue`
- 画布组件：`frontend/src/components/BoardCanvas.vue`
- 全局样式：`frontend/src/style.css`
- 标准板测试：`backend/test_standard_board.py`
- 本地优先 / 修复接口测试：`backend/test_standard_board_local_first.py`

## 给新对话的判断标准

如果用户说“标准板库又卡 Supabase / 超时”，先查：

1. 标准板接口是否调用了 `resolve_supabase_user()`。
2. activity 接口是否又改回 Supabase 优先。
3. 前端是不是在标准板详情加载失败时把 activity 错误覆盖成主错误。
4. 后端是不是没重启，仍在跑旧代码。

如果用户说“修复队列点不了 / 没有前后对比”，先查：

1. `standardBoardService.compareRepair` 是否存在。
2. `/api/standard-board/repairs/{source_id}/comparison` 是否存在。
3. `standardBoard.repairComparison` 是否被正确赋值。
4. `repairable` 是否返回 `original` 且 `repaired: null`。
5. `repaired` 是否返回两份 detail。

如果用户说“标准板背景不对”，先查：

1. 标准板 `BoardCanvas` 是否固定传入 11 x 18 columns/rows。
2. 是否误用了 Studio 的 current board spec。
3. `getStandardBoardCoordStyle` 是否仍按 2440 x 3660 和 200mm 孔距计算。
## 2026-07-13：AI Lab 全本地化与可用性修复（最新）

### 一句话背景

用户反馈 AI Lab 经常超时，后端日志出现：

```text
Supabase task create skipped: Supabase POST .../rest/v1/ai_generation_tasks request failed
```

用户的产品目标是：单机单用户运行，所有业务数据留在本地；不再因为 Supabase 登录、任务表或存储请求失败而影响 AI Lab。LLM 仍然允许调用已配置的 OpenAI 兼容服务，仅用于生成结果的文案润色。

### 本轮已完成

- 后端本地模式已改为默认值：`backend/core/supabase_repo.py` 的 `is_local_only_mode()` 在没有环境变量时返回本地模式。
- `backend/.env` 已新增 `LOCAL_ONLY=true` 与 `LLM_MODEL_NAME=gpt-4o`。不要打印、复制或提交该文件中的任何密钥。
- 因此 `/api/generate`、`/api/result/{task_id}`、岩板、岩点和标准板活动都会使用现有本地 JSON / 内存路径，不再进入 Supabase 认证、任务创建、任务更新或任务查询。
- 前端 `frontend/src/services/authService.js` 已改为固定本地用户，源码中已没有 Supabase URL、认证端点或 `VITE_SUPABASE_*` 的调用；启动后会直接进入工作台。
- AI Lab 候选载入 Studio 时：
  - 通过 `loadAiCandidateIntoStudio()` 调用 `studio.loadBoard(..., { markUnsaved: true })`；
  - `useStudioEditor.loadBoard()` 会清除候选的 `saved_id`，防止保存时覆盖来源岩板；
  - 用户必须点击现有“保存岩板”才能写入 `backend/data/saved_boards.json`；
  - 离开 Studio 的导航、刷新或关闭页面时，未保存候选会得到提示。
- 没有改动候选线路的岩点坐标、难度、A* 规则或历史训练数据；候选路线仍沿用既有验证流程。

### 已验证的结果

在 `backend` 目录运行：

```powershell
.\.venv\Scripts\python.exe -m unittest test_local_only_mode.py test_ai_lab_experiments.py
```

结果：`Ran 9 tests ... OK`。

在 `frontend` 目录运行：

```powershell
npm.cmd run build
```

结果：Vite 生产构建通过。构建会提示主 bundle 大于 500 kB；这是性能提示，不是本次功能错误。

模型服务还做过只读连通性检查：已配置的密钥和地址可读取模型列表，默认 `gpt-4o` 位于可用模型列表中。绝不能在日志、回复、Git diff 或脚本输出中泄露密钥。

### 当前状态 / 卡点

代码和自动化测试没有 blocker。唯一尚未完成的是在用户实际运行环境中重启前后端并手动走一遍 UI：

1. 后端重启后确认日志不再出现 `Supabase task create/update/result skipped`。
2. 前端刷新后确认不显示云端登录页，而是直接进入本地工作台。
3. 先保存一块岩板，在 AI Lab 运行“重新组合路线”或“提出修改建议”。
4. 将候选载入 Studio 后离开或刷新，确认提示出现；保存候选后重启后端，确认它仍在岩板资产列表中，且来源岩板没有被覆盖。

### 给下一位的执行顺序

1. 先查看 `git status --short`。当前工作区存在用户此前留下的标准板标签筛选改动；不要覆盖、重置或格式化这些无关文件。
2. 用项目虚拟环境运行后端，不要用系统 Python：

```powershell
cd "D:\学校课程\ai攀岩定线问题\ai_climbing_code\backend"
.\.venv\Scripts\python.exe main.py
```

3. 前端开发服务使用：

```powershell
cd "D:\学校课程\ai攀岩定线问题\ai_climbing_code\frontend"
npm.cmd run dev
```

4. 按“当前状态 / 卡点”的四步做浏览器验证。若用户要求部署，按项目 `AGENTS.md` 中指定的 GitHub-to-server 同步流程，不要假设服务器目录可直接 `git pull`。

### 一定不要再踩的坑

- **不要把 `LOCAL_ONLY` 改为空或删除**：这会在已配置 Supabase 凭据时重新启用云端请求，并把 AI Lab 的任务创建、运行和结果轮询重新暴露给网络超时。
- **不要把 AI 候选沿用来源岩板的 `saved_id` 保存**：这会覆盖用户原始岩板。候选必须以新资产保存。
- **不要为了“本地化”删除 Supabase 表、密钥或历史云端数据**：本轮只是不使用它们；任何删除都是高风险操作，须按 `AGENTS.md` 获得用户精确确认。
- **不要输出 `backend/.env` 的内容**，包括密钥长度以外的任何敏感值；不要把 `.env` 提交进 Git。
- **不要用系统 Python 3.8 跑测试**：测试使用 Python 3.10+ 语法，系统 Python 3.8 会报 `SyntaxError`。必须使用 `backend/.venv/Scripts/python.exe`（当前为 Python 3.13）。
- **PowerShell 中不要直接用 `npm`**：该机器的执行策略会阻止 `npm.ps1`；使用 `npm.cmd`。
- **不要用 `git reset --hard`、`git checkout -- .` 或递归删除来清理工作区**。现有未提交变更属于用户，除非用户明确授权，否则必须保留。

### 本轮关键文件

- `backend/core/supabase_repo.py`：本地优先总开关。
- `backend/main.py`：AI Lab 异步任务、任务内存状态与本地 fallback。
- `backend/test_local_only_mode.py`：本地模式不访问 Supabase 的回归测试。
- `backend/agent/experiments.py`：AI Lab 本地算法与可选 LLM 文案润色。
- `frontend/src/services/authService.js`：固定本地用户，不可恢复 Supabase 网络调用。
- `frontend/src/composables/useStudioEditor.js`：候选路线的未保存状态与 `saved_id` 清除。
- `frontend/src/App.vue`：AI Lab 候选载入、离开提示、刷新/关闭提示。
