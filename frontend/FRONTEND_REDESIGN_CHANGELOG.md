# 前端企业级改版修改报告

生成时间：2026-05-21

## 1. 修改概览

本次修改围绕“企业级前端设计升级”和“功能页划分”展开，完成了以下工作：

- 引入企业级 Vue UI 框架 Element Plus。
- 新增顶部工作区导航。
- 新增 Dashboard 总览工作区。
- 将原本单页混杂的功能通过工作区进行视觉和任务分流。
- 优化整体暗色控制台视觉，包括导航、卡片、指标、按钮和背景层次。
- 运行生产构建验证，并记录构建结果。
- 新增本地设计报告与修改报告。

## 2. 修改文件清单

### 2.1 `frontend/package.json`

新增依赖：

- `element-plus`
- `@element-plus/icons-vue`

说明：用于为后续企业级 UI 组件化改造提供基础。

### 2.2 `frontend/src/main.js`

修改内容：

```js
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

createApp(App).use(ElementPlus).mount('#app')
```

说明：完成 Element Plus 全局注册。

### 2.3 `frontend/src/App.vue`

主要修改：

1. 产品标题从“智能定线工作台”升级为“智能定线企业工作台”。
2. 新增工作区导航 `workspace-switcher`。
3. 新增状态变量：

```js
const activeWorkspace = ref('dashboard')
const workspaceTabs = [
  { key: 'dashboard', label: '总览', icon: '📊', desc: '状态与快捷入口' },
  { key: 'studio', label: '路线设计', icon: '🧗', desc: '岩板编辑与动作序列' },
  { key: 'generator', label: 'AI 定线', icon: '🤖', desc: '画像参数与智能生成' },
  { key: 'library', label: '岩点资源', icon: '🧱', desc: '上传与管理' },
  { key: 'boards', label: '岩板资产', icon: '🗂️', desc: '收藏与版本管理' },
]
```

4. 新增 Dashboard 总览页面，包括：
   - 英雄介绍卡片
   - 指标卡片
   - 快速入口
   - 最近岩板预览
5. 新增针对不同工作区的 CSS 过滤与展示逻辑。
6. 新增企业级导航与 Dashboard 视觉样式。

### 2.4 `frontend/FRONTEND_DESIGN_REPORT.md`

新增文件，记录本次设计目标、问题分析、设计策略、页面结构、构建验证结果和后续建议。

### 2.5 `frontend/FRONTEND_REDESIGN_CHANGELOG.md`

新增文件，记录本次实际修改内容、构建结果、遗留问题和后续建议。

## 3. 构建验证

执行命令：

```bash
npm --prefix frontend run build
```

结果：成功。

构建输出摘要：

```text
vite v8.0.0 building client environment for production...
✓ 1623 modules transformed.
dist/index.html                     0.45 kB │ gzip:   0.29 kB
dist/assets/index-DQxIr6Hv.css    393.02 kB │ gzip:  54.20 kB
dist/assets/index-C4F_RNAP.js   1,039.28 kB │ gzip: 337.36 kB
✓ built in 1.71s
```

警告：

```text
Some chunks are larger than 500 kB after minification.
```

判断：该警告不会阻断构建，但说明当前包体积偏大。主要原因是 Element Plus 全量引入和当前 `App.vue` 功能仍高度集中。

## 4. 已实现的体验升级

### 4.1 功能页划分

用户现在可以通过顶部工作区导航进入：

- 总览
- 路线设计
- AI 定线
- 岩点资源
- 岩板资产

这解决了原先所有功能堆叠在同一屏的问题。

### 4.2 Dashboard 总览

新增 Dashboard 后，用户进入系统时可以先看到：

- 当前工作状态
- 关键数据指标
- 快速操作入口
- 最近岩板

这让产品更接近企业级应用，而不是直接暴露复杂编辑器。

### 4.3 视觉系统增强

新增或增强了：

- 企业级导航按钮
- 卡片式指标
- 深色控制台背景
- 渐变强调色
- 更强的分区层次
- Dashboard 操作入口

### 4.4 UI 框架基础

已接入 Element Plus，为后续将按钮、表单、弹窗、消息提示、抽屉、表格等全部替换为企业级组件打下基础。

## 5. 当前遗留问题

### 5.1 App.vue 仍然过大

虽然本次已完成工作区分区和视觉升级，但 `App.vue` 仍然承担大量业务逻辑。后续应继续拆分。

### 5.2 Element Plus 当前为全量引入

这导致构建产物 JS chunk 超过 500kB。

建议后续改为按需导入或页面级动态加载。

### 5.3 工作区分离主要通过 CSS/状态过滤实现

本次为了尽量保留原有业务逻辑，采用了低风险的渐进式重构方式。后续建议进一步拆成真正的页面组件。

## 6. 后续建议

建议下一步继续：

1. 页面组件化拆分。
2. Element Plus 按需导入。
3. 使用 `ElMessageBox` 替换原生 `alert/confirm/prompt`。
4. 将岩点资源页升级为表格 + 筛选 + 批量管理。
5. 将岩板资产页升级为表格 + 搜索 + 标签 + 可见性筛选。
6. 使用动态 import 拆分构建产物。

---

## 7. 追加修改报告：模拟系统聚焦版改造

追加时间：2026-05-21 晚

### 7.1 本轮目标

本轮在上一版“企业级工作区改版”基础上，继续将产品主叙事从“AI 定线工具”调整为“攀岩岩板模拟设计系统”。核心目标是：

- 默认体验聚焦手动模拟设计，而不是自动生成路线。
- AI 定线入口采用软封印策略，保留未来恢复空间，但不再作为主路径诱导用户使用。
- 底层岩板从固定 `11 × 18` 扩展为多规格模板系统。
- 岩板坐标、孔位、拖拽落点、新建空白板、保存数据都跟随岩板规格动态变化。
- 通过第一批组件/模块拆分降低 `App.vue` 的继续膨胀风险。

### 7.2 主要新增与修改文件

#### `frontend/src/constants/boardTemplates.js`

新增岩板模板常量与规格工具函数：

- `BOARD_TEMPLATES`
- `DEFAULT_BOARD_TEMPLATE_ID`
- `LEGACY_BOARD_TEMPLATE_ID`
- `getBoardTemplateById()`
- `createAxisLabels()`
- `createBoardSpecSnapshot()`
- `normalizeBoardSpec()`

当前内置模板包括：

| 模板 ID | 名称 | 规格 | 说明 |
| --- | --- | --- | --- |
| `classic-11x18` | 标准训练板 | 11 × 18 | 兼容原始训练板 |
| `studio-14x20` | 扩展训练板 | 14 × 20 | 默认模拟设计规格 |
| `commercial-16x24` | 大型设计板 | 16 × 24 | 更复杂线路与更多岩点 |
| `competition-18x22` | 宽体比赛板 | 18 × 22 | 宽体横移动作模拟 |

同时新增旧模板 ID 兼容映射：

- `studio-13x21` → `studio-14x20`
- `commercial-15x24` → `commercial-16x24`
- `competition-17x28` → `competition-18x22`

#### `frontend/src/components/BoardTemplatePicker.vue`

新增底层岩板模板选择组件，用于 Dashboard 中展示多规格岩板入口。组件职责：

- 展示可选岩板模板卡片。
- 高亮当前模板。
- 点击模板后向父组件发出 `select` 事件。
- 将模板 UI 从 `App.vue` 中拆出，作为本轮第一批高价值组件拆分。

#### `frontend/src/composables/useBoardEditor.js`

升级 `createBlankBoard()`：

- 支持根据 `board_spec` / `template_id` 生成空白岩板。
- 默认创建 `studio-14x20` 扩展训练板。
- 新增 `board_spec` 字段写入。
- 默认文案改为模拟设计优先，不再强调 AI 定线主流程。

#### `frontend/src/App.vue`

主要调整包括：

1. **产品定位调整**
   - 顶部品牌保持“攀岩岩板模拟设计系统”。
   - Dashboard 文案明确“选择底层岩板规格、组合岩点库、拖拽布点、编辑岩板属性并保存资产”。

2. **导航结构调整**
   - 工作区从原先的 AI 主导结构调整为：
     - 总览
     - 岩板设计
     - 岩点资源
     - 岩板资产
     - AI 实验室
   - `generator` 工作区被替换为 `ai-lab` 封印态工作区。

3. **AI 软封印**
   - 新增 AI 实验室说明页。
   - 保留 `notifyAiSealed()` 提示逻辑。
   - `generateRoute()` 仍存在但只触发封印提示，不进入 `/api/generate` 主流程。
   - Dashboard 不再把 AI 作为快捷主入口。

4. **岩板模板系统接入**
   - `boardPresets` 改为读取 `BOARD_TEMPLATES`。
   - `activeBoardPresetId` 默认使用 `DEFAULT_BOARD_TEMPLATE_ID`。
   - `currentBoardSpec` 支持从保存数据中恢复 `board_spec`，并通过 `normalizeBoardSpec()` 兼容旧岩板。

5. **动态坐标与孔位**
   - `coordinateColumns` 从规格中的 `xLabels` 或 `createAxisLabels(columns)` 生成。
   - `coordinateRows` 从规格中的 `yLabels` 或 `rows` 生成。
   - `getCoord()` 改为通过 `parseCoord()` 支持多字符列名。
   - 拖拽落点使用 `getColumnLabel()`，避免继续依赖单字符 `String.fromCharCode(65 + index)`。

6. **新建空白板流程**
   - `createNewBlankBoard(presetId)` 支持指定模板。
   - Dashboard 模板卡片通过 `startBoardFromPreset()` 直接创建并进入 Studio。
   - 快速开始按钮通过 `startStudioWithBlankBoard()` 统一处理未保存确认。

7. **保存与资产兼容**
   - 保存前执行 `syncCurrentBoardSpec()`，保证岩板资产携带当前规格。
   - 加载旧岩板时，如果缺少 `board_spec`，回落到 `classic-11x18`。
   - 加载已有 `board_spec` 时执行 `normalizeBoardSpec()`，修复旧 ID 与缺失字段问题。

8. **服务层复用**
   - 保存、更新、删除、列表读取改为复用 `boardService`。
   - 岩点资源与任务轮询改为复用 `apiClient`，减少裸 `axios` 分散调用。

### 7.3 代码审查记录

本轮按用户要求未执行构建验证，只做静态审查与差异检查。已检查内容：

- `git diff --stat`：确认本轮主要改动集中在 `App.vue`、`useBoardEditor.js`，并新增模板常量与模板选择组件。
- `git status --short`：确认涉及文件包括：
  - `frontend/src/App.vue`
  - `frontend/src/composables/useBoardEditor.js`
  - `frontend/src/components/BoardTemplatePicker.vue`
  - `frontend/src/constants/boardTemplates.js`
  - 前端设计/修改报告文档
- `git diff --check`：发现并修复 `App.vue` 中一处行尾空格。
- 审查并修复 `isHoldInsideSpec()` 坐标解析逻辑，避免在 `hold.x` 存在但 `hold.y` 缺失时错误拼接坐标。

### 7.4 未执行构建说明

按用户最新指示：**本轮不执行构建验证**。

因此本节不记录新的 `npm run build` 结果。上一轮文档中的构建结果仅代表上一轮企业级工作区改版，不代表本轮“模拟系统聚焦 + AI 软封印 + 多规格岩板”追加改造的构建结论。

### 7.5 当前已知风险

1. `App.vue` 仍然承担大量模板、状态、业务逻辑和样式，虽然已新增 `BoardTemplatePicker` 与 `boardTemplates`，但还没有完成页面级拆分。
2. `components/Wall.vue` 与 `components/WallDisplay.vue` 仍保留旧的 `ABCDEFGHIJK`、`18`、`450 × 650` 写死逻辑；当前主入口 `App.vue` 已改为动态规格，但后续如果重新启用这些旧组件，需要同步升级。
3. 工作区切换仍主要依赖 `activeWorkspace` 与 CSS 过滤，建议下一阶段拆为真实页面组件。
4. `generateRoute()` 底层函数仍保留，但 UI 入口已软封印；未来恢复 AI 实验室时需要重新梳理生成流程和提示文案。
5. 当前未执行构建验证，建议在后续允许时执行一次前端构建或至少运行开发服务器做浏览器级回归。

### 7.6 下一步建议

建议下一轮优先：

1. 拆出 `DashboardPage.vue`、`StudioPage.vue`、`HoldLibraryPage.vue`、`BoardsPage.vue`、`AILabSealedPage.vue`。
2. 抽出 `BoardCanvas.vue`，并将当前动态坐标、孔位、拖拽落点逻辑从 `App.vue` 下沉。
3. 升级或废弃旧的 `Wall.vue` / `WallDisplay.vue`，避免旧固定规格组件误用。
4. 将岩点资源管理拆为 `useHoldLibrary` + `HoldLibraryPage`。
5. 将岩板资产保存/载入逻辑拆为 `useBoardPersistence`。
6. 在用户允许后补跑构建验证，并记录本轮构建结果。
