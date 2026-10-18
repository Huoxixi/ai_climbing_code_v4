---
name: "抱石 · 极简影像工作区"
description: "仅限抱石工作区、相关登录和单帧精修的已实现设计系统"
colors:
  brand: "#edcb52"
  brand-hover: "#dfbb3d"
  brand-soft: "#f3f3f3"
  brand-ink: "#28230e"
  ground: "#f7f7f7"
  surface: "#fff"
  surface-subtle: "#ededed"
  surface-raised: "#fafafa"
  ink: "#202020"
  ink-muted: "#606060"
  ink-faint: "#666666"
  line: "#e5e5e5"
  line-strong: "#c8c8c8"
  media-ground: "#181a1b"
  media-ink: "#f2f2f2"
  focus: "#806000"
  danger-solid: "#b7403a"
  danger-outline: "#a9322d"
typography:
  headline:
    fontFamily: '"MiSans", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif'
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.4
  title:
    fontFamily: '"MiSans", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif'
    fontSize: "16px"
    fontWeight: 600
  body:
    fontFamily: '"MiSans", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif'
    fontSize: "14px"
    fontWeight: 400
  label:
    fontFamily: '"MiSans", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif'
    fontSize: "14px"
  supporting:
    fontFamily: '"MiSans", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif'
    fontSize: "13px"
    lineHeight: 1.6
  metadata:
    fontFamily: '"MiSans", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif'
    fontSize: "12px"
  replay:
    fontFamily: '"Replay Noto", "Noto Sans SC", "Source Han Sans SC", "Microsoft YaHei", sans-serif'
rounded:
  control: "6px"
  field: "8px"
  panel: "8px"
  modal: "12px"
  contextual: "10px"
spacing:
  space-1: "4px"
  space-2: "8px"
  space-3: "12px"
  space-4: "16px"
  space-5: "20px"
  space-6: "24px"
  space-8: "32px"
components:
  button-primary:
    backgroundColor: "{colors.brand}"
    textColor: "{colors.brand-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  button-primary-hover:
    backgroundColor: "{colors.brand-hover}"
    textColor: "{colors.brand-ink}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "8px 10px"
  button-danger:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.danger-outline}"
    rounded: "{rounded.control}"
    padding: "0 18px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.field}"
    padding: "11px 12px"
  navigation-active:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    padding: "0 16px"
  work-tab-active:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    padding: "0 2px"
  task-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    width: "288px"
  media-viewer:
    backgroundColor: "{colors.media-ground}"
    textColor: "{colors.media-ink}"
    rounded: "{rounded.panel}"
  canvas-hold-actions:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.contextual}"
    padding: "4px"
  review-file-menu:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.contextual}"
    padding: "8px"
    width: "256px"
  review-tool-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "7px 4px"
    width: "48px"
  review-stage:
    backgroundColor: "{colors.surface-subtle}"
    rounded: "{rounded.panel}"
  workspace-sheet:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.modal}"
---

# Design System: 抱石 · 极简影像工作区

## Overview

**Creative North Star: "极简影像工作区"**

真实照片和复盘视频是工作对象。中性浅灰底承托白色工具面，近黑画布承托影像，石墨文字保持清晰。黄色集中于当前主要操作；界面通过留白、细分隔与明确状态建立秩序。

用户要求高级极简：每页最多保留一个清楚的可见标题，普通说明按需展开，工具随素材与任务出现。删除重复标题、装饰性标签和解释，不删除必要授权、费用、错误与保存反馈。本规范仅覆盖抱石工作区、相关登录和单帧精修；定线工作区继续使用其原系统。

本轮用户明确授权替换前一版视觉，方向记录于 surface contract（seed 5779011d，用户指定风格优先）。已实现的作用域样式及组件是事实来源；本文件覆盖旧抱石工作台规范，不改 PRODUCT.md 或 docs/ui-style-standard/DESIGN.md。

视频复核按同一 surface contract 中的“Rejected review composition · revised direction contract”重建：延续中性灰白、石墨、MiSans 与克制黄色，重新安排素材菜单、近距离编辑工具和同宽确认栏。此前合并全排按钮的构图已被用户拒绝，不是当前完成状态；照片、设置、结果复盘与单帧精修继续保持各自模式。

**Key Characteristics:**
- 中性浅色工具、近黑影像、石墨文字与少量黄色主操作。
- 平面分组、细线和小圆角，不叠装饰卡片与常驻阴影。
- 桌面固定工作台，移动端单层导航与纵向任务流。
- 本地中文字体、可见焦点、完整授权与明确分析入口。

## Colors

中性灰白建立安静的工作环境；颜色值以 frontmatter 为准。

### Primary

- **工作黄**（brand）：识别、保存、确认等主操作与必要的画布选中反馈。
- **悬停黄**（brand-hover）：可用主操作的悬停反馈。
- **黄面深字**（brand-ink）：工作黄上的文字。

### Neutral

- **工作底 / 白工具面 / 次级工具面 / 轻辅助面**（ground、surface、surface-subtle、surface-raised）：工作区背景、面板、悬停与辅助表面。
- **静灰辅助面**（brand-soft）：保留既有语义变量名，实际是中性灰，不再代表浅黄导航选中面。
- **石墨 / 次级石墨 / 辅助石墨**（ink、ink-muted、ink-faint）：标题和正文、说明和占位信息。
- **细分隔 / 强边界**（line、line-strong）：工具 footer 分隔、输入与次级按钮边框。
- **近黑画布 / 媒体浅字**（media-ground、media-ink）：照片与视频画布。原始媒体的颜色不受品牌调色影响。
- **焦点棕**（focus）：浅色工具上的键盘轮廓；深色画布内以工作黄显示焦点。
- **危险实面 / 危险文字**（danger-solid、danger-outline）：删除确认、退出账号等明确操作。现有成功和警告继续使用共享语义色。

**The Sparse Yellow Rule.** 黄色集中于主操作和必要的画布选中反馈；导航与任务标签用石墨底线表示当前项。

## Typography

**Body Font:** 本地 MiSans，回退到 PingFang SC、Microsoft YaHei 与系统无衬线。工具区与控件沿用原字体，不引入展示字体。

**Label/Mono Font:** 时间、页码和数量使用 tabular-nums。播放器保留本地 Replay Noto 与 Noto / 思源黑体回退，仅作为复盘媒体说明的既有例外。

**Character:** 清楚、紧凑的中文层级；保留正文可读性，以减少重复信息降低密度。

### Hierarchy

- **Headline**：照片、复盘入口、设置与账号的单一页面标题，使用 frontmatter 中的字号和行高；视频复核隐藏重复的可见页标题，保留无障碍语义。
- **Title**：工具和内容分组；设置分组保留源码中的（18px）。
- **Body / Label**：正文、输入及普通按钮。主操作不借助巨大字号强调。
- **Supporting / Metadata**：按需说明、时间、状态和页码；控件局部有（12–13px）紧凑文字。
- 导入视频标题（22px，500）、照片上传标题（24px，500）和登录标题（26px，500）是已有空态/入口尺寸，不扩展为通用 display 阶梯。

**The Single Title Rule.** 每页最多一个可见页面标题；视频复核由导航与工具栏提供上下文，隐藏重复页标题，保留无障碍语义。面板标签、状态和帮助不重复声明同一个标题或操作理由。

## Layout

2026-10-17 免账号浏览器核心入口（2026-10-18 扩展视频导出）：仅适用于 `frontend/src/browser-replay/BrowserPortal.vue` 及其嵌入式骨架工作台，直接进入本机骨架识别与回放，不提供登录、注册或用户管理。局部继承 MiSans、灰白工具面、石墨文字与稀疏黄色主操作，顶部应用头（56px），移动端使用底部导航。当前浏览器的新旧记录统一在“我的记录”展示，保留原记录标识；本机存储说明和桌面版下载由同一应用壳提供。已支持按当前真人／骨架选择在本机导出已分析区间，静音 MP4 优先、WebM 回退；纯骨架使用深色背景，历史记录导出无需重新推理。此范围不改变原生 App 的登录或工作台规则，也不表示岩点、完整多人跟踪、接触、无人墙面或原生全部导出组合已迁移。

本次浏览器导出面板仅在分析完成后显示，置于现有控制面内，以细顶线分组，沿用既有文字、按钮和至少（44px）触区。说明交代当前画面组合、已分析时长、静音及本机处理；处理中显示进度、真实状态和取消入口，失败显示原因并允许重试。完成后自动下载并保留注明文件格式的显式下载链接；切换画面或开始新导出清除旧下载结果，避免下载到先前组合。此为浏览器复盘的局部操作规则，不扩展为其他页面的通用布局。

2026-10-08 拍照定线首屏修订：网页与 App 共用同一组件。首屏内容最大宽 880px，顶部标题、白色导入区与示例照片按任务顺序集中排列。导入区的说明、按钮和按需帮助纵向相邻；示例区紧接导入区，照片完整显示，桌面高 180px、手机高 160px，不在屏幕底部缩成小图。窄屏按钮折行；紧凑桌面仅在内容确实超高时滚动首屏内容。已导入照片的画布、取色与复核工具继续使用原有全窗口工作台。

抱石桌面在（min-width: 900px）启用固定工作台；原约定验收起点为（1280×720），现扩展到紧凑桌面窗口，（1096×704）已确认无页面滚动。顶部导航高（56px），工作内容填满剩余动态视口。照片、分析准备、设置相关工具与单帧编辑器仍采用（288px）工具模式。视频岩点复核为单列画布，撤掉固定右侧 inspector，将空间让给真实影像。列间距与工作区常规外边距（16px），标题与内容间距（12px）。账号和设置桌面外边距（24px 32px），设置内容最大宽（640px）。

工具面板标题内边距（16px 20px 8px），正文（16px 20px），footer（12px 20px 16px）。桌面长工具内容根据实际可用高度分页；分页模式正文填满可用空间并裁切非当前页，分页与主操作固定，未显示页同时退出焦点顺序。未分页时正文不参与 flex 压缩，按内容自然撑高，避免内容溢出到 footer。面板切页保留画布、播放器和草稿；不要把隐藏业务入口当作精简手段。顶层页面挂载行为以 App.vue 为准，不承诺跨路由永久保留全部 DOM。

视频空态仅显示导入画布；选择素材后再展示取色、保留授权与视频设置。照片与视频保持 contain 及原始坐标关系，缩放拖动留在媒体内部。视频复核为居中的内容宽度编辑单元：上方（44px）素材栏、浅灰媒体舞台和同宽近距离 footer。桌面1×工作单元与 footer 的最大宽度均为（max(520px, 适配视频宽度 + 128px)），同时受可用视口宽度约束。ResizeObserver 测量舞台，loadedmetadata 提供原视频尺寸；1×等比系数取（可用舞台宽减128px）与可用高度的较小比例，视窗与完整影像同尺寸，给编辑工具留出近距离空间。放大时工作单元最大宽度放开到（100%），视窗横向扩展到放大影像宽度与舞台可用宽减工具预留空间的较小值，高度保持适配高度；原视频与轮廓继续等比放大，不拉伸画面。footer 随当前视窗宽度加工具空间约束，保持近距离。复核状态隐藏重复的可见页标题。

桌面补删点、精修组成视频左侧竖轨，与当前视窗边缘的定位关系为（视窗左缘 - 64px）；按钮宽（48px）、最小高（56px），轨道间距（4px）。补删点已包含选择：点击真实轮廓或已有岩点编号，随后在画内删除整颗岩点；拖框继续预览补点，不另设选择工具。状态文案为“点击删点，拖框补点”；顶点删改仍留在精修中。文件名是管理菜单入口，右侧眼睛图标控制岩点可见性；换视频、素材、历史及版本集中在原生 popover，不铺成同权按钮行。记录、历史和素材按现有分页访问；不以裁切原图换取封面齐整。

窄屏（max-width: 899px）的其他页面保持纵向任务流。顶部只保留（56px）单层导航，主内容对应偏移（56px），页面标题可见，底部导航预留安全区。视频复核单独使用应用壳的真实 flex 剩余高度：顶部（56px）与底部（64px）导航自然占位，视频适配中间可用空间，（1×）全图时原生播放控件完整可见，放大编辑时隐藏原生控件。编辑竖轨改为素材栏下的紧凑横排，按钮最小宽（84px）、最小高（44px），不再预留桌面128px工具空间；工作单元与 footer 最大宽回到（100%）。全局确认 footer 在视频外近距离独立占位，不使用 sticky 覆盖画面或控件；此规则不改变其他页面的纵向滚动。精修画布为（50dvh）。登录的左侧照片桌面占（48%），窄屏隐藏，表单正常阅读；原生工作浮层允许移动端内部纵向滚动。

## Elevation & Depth

2026-10-08 视频复核修正：底部状态提示独占完整一行，骨架采样设置再独占一行，最后并排显示确认状态与开始分析；不把长中文提示和全部控件挤入同一行。状态提示保持可读宽度，footer 的展开内容最多占用 40dvh 并内部滚动，防止反过来压塌画面。缩放以约 220ms 连续过渡同时更新图像、轮廓与视窗，快速反向缩放从当前可见尺寸衔接；减少动态效果设置使用直接缩放。拟合宽度按页面内容可用宽度计算，工具区随实际视窗渐进扩展，替代切换放大档位时直接放开布局宽度。精修每次进入或读取新帧默认自由描边，包括已有岩点和带入候选轮廓；用户明确选择调整顶点或描边完成后仍可进入顶点工具。整帧缩略图在画布角落浮置，不在缩放时插入额外布局高度。

常驻工作区、工具面板和媒体容器没有装饰阴影。表面、留白、底线和 footer 的单像素分隔承担层级；账号、设置和登录表单不再包裹卡片。视频复核的近距离 footer 本身取消顶线，保持工作单元轻量。原生模态工作面板保留遮罩和柔和阴影，表达真实的模态层级。画内岩点上下文操作使用白色浮条与柔和阴影；文件菜单进入浏览器原生 top layer，使用白面和轻阴影，避免受媒体容器裁切。两者都不是常驻卡片。

### Shadow Vocabulary

- **Workspace sheet**（0 18px 56px #10191040）：仅用于原生 dialog 工作面板。
- **Canvas actions**（0 6px 24px rgba(0,0,0,.22)）：仅用于视频画内岩点上下文操作。
- **Review file menu**（0 10px 32px #20202026）：仅用于原生 popover 素材菜单。
- 既有输入焦点 halo 及播放器总结圆盘属于局部状态，不提升为常驻卡片或按钮的通用阴影规范。

**The Flat Tools Rule.** 常驻工具保持平面；深度仅用于实际模态层、画内上下文操作或已有焦点状态。

## Shapes

主操作沿用（6px）控件圆角；输入和一般次级控件、工具面板、媒体外壳使用（8px）。模态工作浮层保留（12px），画内上下文浮条使用（10px）圆角。导航与任务标签取消容器圆角，使用底线。头像使用小方角，颜色样本和轮廓顶点保留其功能形状。媒体外壳可裁切溢出，原图本身保持比例与可访问范围。

## Components

### Buttons

主按钮是少数工作黄实面，照片主动作内边距（10px 16px）；复盘准备主动作保留自身最小高（48px），视频复核全局确认最小高（44px）。普通工具动作为白面中性边框，媒体工具沿用深面浅字。标准触区至少（44px），按下位移（1px），常规反馈（160ms ease）。主操作禁用时为浅灰面与可读灰字，不再留下似乎可点的黄色；其他禁用控件沿用自身透明度。视频复核全局确认禁用时使用（#ededed）背景、（#707070）前景和不透明度（1）；正常 CircleCheck 为静态图标，仅实际 holdReviewSaving 时替换为 Loading.primary-spinner 并设置 aria-busy，旋转只作用于该加载类。

危险操作保留语义红；账号退出为红字描边，视频复核文件菜单底部的删除入口为红字并保留当前记录上下文，删除确认可用实红。可见键盘焦点不能因去边框而消失。减少动态偏好下取消过渡和非必要动画。复核全局确认是唯一持续主动作；候选出现时，全局确认禁用，画内“确认”沿用局部确认黄色。选择、补删点与精修工具不染黄，选中工具使用石墨面与白字。

### Chips

记录与配置状态保持短文字和必要状态图形，避免额外胶囊底。照片颜色选择是带 aria-pressed 的真实按钮，选中时采用强边界和浅灰面；视频仍只允许从当前画面点选样本，不添加照片调色盘快捷色。

### Cards / Containers

工具面板为白面小圆角，取消外描边和常驻阴影。仅桌面分页模式固定正文可用高度和 footer；未分页模式正文自然撑高，不被 flex 压扁。记录卡同样采用平面小圆角；照片保持比例和原始信息。账号、设置表单直接排在工作底上，不为每个段落增加卡片。

### Inputs / Fields

白底、强中性边框、可见焦点，照片字段内边距（11px 12px），最小高度（44px）。登录沿用 Element Plus 的实际输入组件。错误、处理中、保存成功以及费用提示继续使用真实状态文案。坐标、数值与范围保留原业务单位。

### Navigation

桌面顶部为单层文本导航，左右内边距（16px），当前项为石墨文字、较强字重与（2px）底线。任务标签同样采用底线，间距（12px），文字（13px），不套胶囊轨道。移动底部导航为白面细顶线，当前项加深文字与图标，不增加彩色底块。

### Disclosures / Consent

普通说明使用按需展开的 details；账号信息分组使用（44px）summary 触区和旋转箭头。保留与授权放在明确标签内，保留完整告知、勾选、告知版本与撤回入口；footer 可直接跳转到授权页。照片选色后由用户主动识别；视频先确认全部岩点，再独立点击开始本地分析。付费服务仍保留独立费用与授权。

### Workspace Sheet / Editor Dialog

继续使用原生 dialog 与 showModal，保持关闭、Escape 和焦点恢复。工作面板最大宽（560px），距视口边缘（20px）；精修从导航下覆盖工作区，保留自由描边、顶点编辑、补画、擦除、平移和确认操作。sidecar 仅记录外观片段，真实状态及焦点行为以组件源码为准。

精修的确认动作从右侧工具分页 footer 移到整个编辑器底部的 editor-savebar，跨媒体与工具列持续可见。保存栏保留细顶线、提示文字和黄色主按钮，按钮最小高（48px）、最小宽（160px）；有待确认 proposal 时显示静态 Check 与“确认保存”，aria-label 分别明确新增岩点或修改轮廓，只有实际 saving 时显示 Loading、正在保存文案及 aria-busy。无 proposal 时底栏只有“核对当前轮廓”：手绘核对仍调用既有 preview，用户另行 confirm 后才保存草稿，不自动保存或分析。窄屏底栏 sticky 在编辑器底部，可换行；（max-width:600px）按钮占满可用宽度。

精修工具限于自由描边、调整顶点、补画、擦除与平移画面，并保留（1 / 2 / 4 / 8×）缩放、已有岩点选择及顶点移动/插入/删除。新增岩点默认自由描边，松手后闭合并转入顶点编辑；载入已有岩点默认顶点编辑。移除多边形逐点描边、框选识别区及其闭合和模型识别入口；此前移除的“周围背景”“待复核候选”和“核对原候选轮廓”入口不恢复。精修保留原手绘核对 preview → confirm 保存，不把模型模式、上下文范围或接口参数推广为当前精修控件规范。

### Media Workspace

导入画布以近黑面和清楚的选择动作开场。已有视频复盘继续展示真人骨架、右侧线路图与下方动作顺序；补点与确认直接可见。视频岩点复核使用内容宽度工作单元，媒体外侧为浅灰舞台。编辑工具从文件管理中分离，持续位于视频近旁，不恢复已拒绝的横向按钮堆叠或远端换视频胶囊。

素材栏以文件名触发原生 popover="auto"，文件名保持省略显示并提供完整 title。菜单宽（256px）、内边距（8px）、圆角（10px），菜单项触区至少（44px）；上方再次显示当前文件名，文字的两行 clamp 放在无 padding 的内部 span，外层段落保留间距，避免露出第三行。随后是更换视频、本地素材、最近分析、记录与版本。菜单按钮在抱石作用域明确无边框，悬停仍使用浅灰面；结果记录的播放版本选中项使用白面，骨架和事件等选项保持按需访问。底部通过分隔与红字明确“删除这条记录”的对象。菜单进入浏览器 top layer，Escape、外部点击及焦点行为沿用原生 popover，不替换为自造键盘菜单。相关资料仍按需打开既有 WorkspaceSheet。

岩点可见性使用覆盖（44×44px）图标触区的原生 checkbox，Eye / EyeOff 对应真实 checked 状态，键盘焦点落在 checkbox 并在外层显现。已有轮廓只绘制保存的真实 polygon，编号为白色小标记：可见牌高（18px）、最小宽（18px）、文字（11px），外部点击范围（44×44px）。旧数据缺少 polygon 时仅显示带虚线标记的编号与明确缺少轮廓状态，不以 bbox 伪造边界；bbox 可用于旧编号定位，不代表真实轮廓。

补删点的文件栏提供原生“视频放大倍数”select，选项为（1 / 2 / 4 / 8×），Ctrl+滚轮逐级缩放，旁边是（44px）平移按钮；（1×）时平移禁用，恢复完整画面。放大视窗横向利用舞台两侧空间并隐藏溢出，同一个 video 元素及真实 polygon 按原比例一起放大和平移。开启平移层可拖动或用方向键移动，关闭平移即可继续单指拖框；放大时滚轮、触控板和双指触摸无需切换模式即可平移，Shift+滚轮横向移动。补删点与平移层上的轻点均可命中真实岩点轮廓并打开整颗岩点操作。切换 job 重置视图，同一 job 的逐点保存与切换工具保留当前放大位置；缩放不改变原视频或岩点坐标。

单点操作直接出现在画面内：候选为确认、修改轮廓、取消；已选岩点为修改轮廓、删除、取消，补删点模式下也保持可用。操作触区至少（44px），候选出现不滚动定位。删除针对所选原岩点 ID 的整颗岩点，沿用既有删除服务，不与精修的“删除选中顶点”混淆。候选及所选岩点操作浮条属于外层视窗，与放大媒体分离，不随视频变大或移出视窗；默认距视窗底（60px），目标轮廓经过缩放平移投影后的底缘超过视窗（70%）时改为顶部（12px）。拖框继续通过实际 scaled video rect 归一化到原片坐标；百分比输入备用入口只在补删点空选、无候选时出现，保持透明工作底。选中工具的悬停继续保持石墨，不降为普通浅灰。候选修改在同一帧将 initialPolygon 传入原单帧编辑器进行顶点编辑，打开或取消编辑均不保存、不分析。底部同宽近距离 footer 独立保留全局“确认全部岩点”；全部确认后才出现“开始本地分析”，仍由用户另行点击。面板切页、逐点保存与普通确认不会自动开始骨架或付费分析。

## Do's and Don'ts

### Do:
- **Do** 将抱石样式限定在 .workspace-boulder、.boulder-login 和 .boulder-editor，保留定线系统。
- **Do** 让素材先出现，工具随当前任务展开，普通说明按需阅读。
- **Do** 使用至少 44px 的标准触区、可见焦点和减少动态回退。
- **Do** 保留完整授权、费用、错误、保存反馈及独立分析操作。
- **Do** 保留真人骨架、右侧线路图、动作顺序和直接可见的补点确认。
- **Do** 将视频复核的文件栏、浅灰舞台和确认 footer 对齐为同宽工作单元，编辑工具贴近视频。

### Don't:
- **Don't** 恢复重复标题、口号、装饰标签或反复解释同一动作。
- **Don't** 用层叠卡片、装饰阴影或大面积黄色增加常驻工作台层级。
- **Don't** 把桌面工具藏进页面滚动或通过 CSS 删除真实功能入口。
- **Don't** 裁切工作素材、改变坐标几何或让切页和逐点保存自动开始分析。
- **Don't** 把既有局部焦点效果、总结圆盘或旧样式残留推广成新通用规范。
- **Don't** 恢复视频复核中被拒绝的同权按钮长排、远端换视频胶囊或脱离媒体的全宽确认栏。

来源：boulder-workspace.css、base.css、tokens.css、TaskPanel.vue、WorkspaceSheet.vue、EditorDialog.vue、PhotoRouteWorkflowPage.vue、ClimbReplayPage.vue、UnifiedReplayPlayer.vue、AccountPage.vue、SettingsPage.vue、PilotLogin.vue、App.vue 及 surface contract。视频复核的本次结构以最新源码与修订合同为准，不引用此前已被拒绝构图的 ship 结论。本次没有新增或替换 shipping 位图，未触及 .local 或生产部署；界面记录不代表识别精度验收。


## 2026-10-08 复盘结果页补充

本轮用户最新截图要求覆盖旧“动作顺序必须烧录”和“计时连续总结”。保留现有字体、配色、逐段回看与小圆盘。真人区占合成画面 70%，右侧线路图占 30%；旧视频通过本地 canvas 根据保存几何重排，原片和旧成片保持。移除旧底部动作顺序，视频后以平面 dl 显示已有基础数据，未来评价尚未实现时不添加占位评分。

总结每次仅一张卡，手动上一张／下一张、跳过总结、收起和项目切换。播放结束有有效路线时先展示中心路线。路线、未用点卡置于画面下方，真人和右图保持清楚可见；其他数据卡沿用背景模糊。路线以统一 viewBox 映射并严格裁切到线路图可视区。未用点使用真实 polygon，单一动画组驱动两侧闪烁三次后常亮；减少动态时直接常亮。手机控件维持 44px 触区，内容纵向排列。

专项构造视频已验证桌面和手机的几何、卡片、同步高亮及无横向溢出；机械检查无发现。没有生成或替换产品位图。本轮未进行真实攀爬识别准确率认证。

2026-10-08 上传准备补充：按用户截图要求移除“关联线路”，视频选择后直接显示“从画面取色”；该页不分页，避免取色按钮被藏到第二页。换视频回到取色页并要求新样本。保留原字体、配色、授权、其他设置与历史记录。1096／1440／390px 实际工作区检查通过；未新增位图。

同日最新上传准备：用户要求右侧仅一个“线路取色”面板，撤掉“保留与授权”“视频设置”、原片说明、勾选框、拍摄建议与分页。取色与上传按钮合并在紧凑面板内，不保留满高白色空栏；视频预览独立保持可用高度。原片保留、显式点击上传、确认岩点后独立分析及 AI 评语的独立授权继续执行。超过 90 秒仅显示简短分析范围提示。桌面／手机构造流程检查通过；无新增位图。

2026-10-09 最新复盘约定覆盖旧 70／30、画面下方卡片及背景模糊：真人与线路图等宽、同原片比例和缩放，普通播放利用可用宽度。总结是视频图层内独立浮动小窗口，沿用石墨色和克制黄色，柔和投影表达悬浮；左上收起、右上跳过，左右箭头和底部圆点翻页，首末箭头禁用。圆点有卡片名和选中状态，44px 触区；短画面正文内部滚动。原有圆盘重开、手动停留、中心路线与双画面未用点闪烁保留。桌面／手机交互和有界截图检查通过，机械检查无发现，无新增位图。验收记录：docs/AI复盘_骨架与浮动总结修复_2026-10-09.md。


2026-10-09 最新适屏与总结约定覆盖此前利用全宽、底部圆点及纯手动总结：视频按当前窗口剩余高度完整显示，真人与线路图保持等宽同比例。总结窗口固定 440×320px，小画面仅按可用空间收缩，正文内部滚动；去掉全部选页圆点，左右箭头首尾循环、支持键盘和明确按下反馈。首次完整播放结束后每张约 6 秒自动展示一次，悬停／焦点／页面隐藏暂停，手动翻页转为停留，最后收起到圆盘；提前预览不消耗首次自动展示。窗口和文字有平滑出现及方向切换动画，尊重减少动态设置。App 0.1.9-replay-preview.20261009，见 docs/AI复盘_适屏与自动总结_2026-10-09.md。
Operate 模式；继承 MiSans、石墨色和克制黄色，不新增产品位图。桌面与手机构造视频合并视觉检查、26 项针对性单元／浏览器检查通过；机械检查无发现。finish verdict: ship。


2026-10-09 用户最新要求覆盖此前全部总结卡片约定：移除复盘总结卡片、首次结束自动播放、收起／跳过／翻页按钮、总结入口和右下角圆盘，只保留视频下方基础数据统计。卡片关联的结束中心路线与未使用岩点闪烁不再展示，不自动定位或遮挡最终画面；基础骨架与当前中心点、同尺度双画面、适屏尺寸、动作回看、慢放、修正、导出及独立评语授权保留。历史分析数据和媒体不改写，旧烧录总结尾段仍在原攀爬结束时停止。App 0.1.10-statistics-preview.20261009；见 docs/AI复盘_移除总结卡片_2026-10-09.md。
Operate 模式，继承现有中性配色与字体；不新增位图。桌面／手机构造视频同批视觉检查及 20 项浏览器回归通过，机械检查无发现。finish verdict: ship。
