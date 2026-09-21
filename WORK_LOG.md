# Work Log - Backend Interface Sync

## 2026-09-21：AI 复盘内部试点发布候选

- 用户确认真实视频复盘形式，并要求上传 GitHub 与部署；按邀请制内部试点处理，不视为商业公开上线批准。
- 完成桌面端和手机端复盘布局、中文动作时间轴、动作命名补充，以及知识库范围、评价边界与文献证据地图。
- 本地发布门禁通过：后端 297 项通过（9 项按环境跳过），前端 89 项通过，生产构建通过；仓库未跟踪 `.local/`、密钥或视频文件。
- 商业发布仍受 PRD 中阿里云合同与数据处理证据、模型/训练数据权利链、独立授权测试集和 SBOM/NOTICE 等门槛约束。

## 2026-09-20：AI 攀岩复盘阶段交接

- 按 PRD v2.1 分轮推进；前三轮已由用户验收，已完成可审计授权、媒体保留与删除、分析证据、叠加播放及本地测试视频入口。
- 后端 22 项、前端 12 项和前端构建通过；未自动授权、未部署生产，工作区改动尚未提交。
- 第 4 轮仍待验收：现有 Pexels 样例未拍全顶部和全部岩点，用户将自行寻找固定正面、全线路和全身入镜、权利清晰的 H.264 MP4。
- 接手说明见 `HANDOFF.md`；新视频合格并经用户验收前，不进入下一阶段。

## 2026-09-17：工作区分流、手机线路库与公共示例图发布

- 登录起始页新增工作区选择，将“抱石线路”和原有“标准板定线”分开进入；相关返回入口已补齐，用户可在两个模块之间清晰切换。
- 抱石线路手机端底部新增独立“线路库”栏目；线路以一行两张的照片卡片展示，选中岩点使用白色细荧光轮廓突出，卡片下方显示名称和日期。
- 公共示例照片改为随前端构建发布，并转换为可实际上传的文件对象；两张照片不再依赖开发电脑本地路径，线上用户可直接试用。
- 前端 68 项测试与生产构建通过；GitHub 发布门禁运行 `35191761182` 全部通过。本轮功能提交为 `9d767c822b8c4503c269274c22e71eeeca3152a7`，分支 `codex/photo-v2-yellow-release` 已推送，并以不可变标签 `pilot-v2026.09.17-rc21` 发布。
- 服务器发布检查通过（前端 68 项、后端 128 项且 1 项按条件跳过、临时健康检查和 Nginx 配置检查）。2026-09-17 17:45（Asia/Shanghai）生产从 rc20 原子切换到 rc21。
- 发布前备份 `ai-climbing-pre-deploy-20260917T094502Z.tar.gz` 已完成并异地回读校验；对象存储首次 403 后自动重试成功。部署后服务为 active，公网健康接口返回本次提交 SHA，首页加载 rc21 的 JS/CSS 指纹，两张公共示例照片返回 200，`/docs` 与 `/openapi.json` 继续为 404，启动日志无异常。
- 未把 `.local/` 数据、个人照片、API 密钥、未验证的识别实验或其他无关工作区改动带入本次提交与发布。

## 2026-09-17：照片线路改为“专项模型完成后再点击选线”

- 新上传和旧版重新识别均先完整运行攀岩岩点专项实例分割与 `interior-v4` 轮廓内分色，完成后才进入“点击一个岩点，预览同色整条线路”；颜色确认不再触发第二次推理。
- 旧版颜色粗筛结果不再显示为正式轮廓，旧任务可无损创建新岩板版本后重新识别；原照片、旧岩板和已保存线路不覆盖。
- 专项流程跳过孔位网格检测，并移除会回落到 MobileSAM 的“添加遗漏岩点”入口和接口；旧版流程继续兼容。
- 同一张仓库示例墙图真实运行专项模型：17.172 秒、60 个实例，模型配置为短边 1200 / 候选上限 300 / `interior-v4`，无孔位锚点；数量只证明真实模型链路生效，不代表准确率通过。
- 后端全量 301 项通过（8 项按条件跳过），前端全量 63 项通过，生产构建通过，Impeccable 页面检测 0 项；手机 390×844 实测返回线路复核路径正常，专项流程不再出现旧补点入口。
- 专项链路提交为 `54b9c12c19bd54e6d64866ae24e0dbc6670d0d16`；生产依赖兼容提交为 `7272c989aa8d9347ca8a74b32f5ee9525bfe94c9`，以不可变标签 `pilot-v2026.09.17-rc20` 发布。GitHub 发布门禁运行 `35175942327` 全部通过。
- 用户确认本项目仅供自用、非商业用途。专项权重已按 SHA-256 校验后安装到生产持久目录，Detectron2 固定源码包已随生产依赖交付；`.local/`、实验文件和个人照片未上传。
- 2026-09-17 11:22（Asia/Shanghai）生产从 rc18 原子切换到 rc20。发布前备份 `ai-climbing-pre-deploy-20260917T032202Z.tar.gz` 已完成并异地校验；公网健康接口和首页返回 200，调试文档与 OpenAPI 返回 404，启动后日志无异常。
- 生产服务器以服务账号真实加载同一权重并推理仓库示例图：60 个实例、算法 29.727 秒、进程峰值约 1.63 GiB；运行后无交换区使用、无 24 小时内核 OOM。该结果证明生产运行链路和资源门禁可用，不代表独立留出准确率通过。

## 2026-09-17：照片线路移动端与前端质量整改

- 上传确认页补齐返回路径；返回时只清理未上传草稿。示例照片改为携带真实文件字节，空文件在网络请求前拦截，上传错误在确认区就近展示。
- 移动端底栏收敛为五项，照片线路并入“定线”并提供“岩板定线 / 照片线路”切换；360 px 小屏品牌、同步状态和底栏排版已修正。
- 复核页新增移动端固定操作栏、只读写保护、键盘操作、可见焦点、人类可读岩点标签和岩点列表；未改变识别链路、数据库、业务实体或历史数据。
- 63 项前端测试与生产构建通过；实测 360×800、390×844、1440×1000，浏览器控制台无错误或警告，Impeccable 最终检测为 0 项。
- 本轮移动端与前端修复已单独提交为 `c71fc5aeb09c83e9aed76a28c99daeb2a959b9e8`，以不可变标签 `pilot-v2026.09.17-rc18` 发布；未把未验证的识别实验、后端改动、历史文档或 `.local/` 数据带入发布。
- GitHub 发布门禁通过（前端 59 项、后端 176 项及生产构建）；服务器发布检查通过（前端 59 项、后端 72 项、临时健康检查和 Nginx 配置检查）。2026-09-17 09:00（Asia/Shanghai）已从 `pilot-v2026.09.16-rc17` 原子切换到 rc18。
- 发布前备份 `ai-climbing-pre-deploy-20260917T010007Z.tar.gz` 已完成并异地回读校验；对象存储首次 403 后脚本第二次重试成功。部署后服务为 active、健康接口 200，正式站点加载 rc18 的 JS/CSS 指纹，`/docs`、`/openapi.json` 和仿真入口继续为 404。
- 识别独立留出质量、目标服务器资源和完整阶段 3 业务验收仍未通过；本次只代表已验证的前端修复上线。主 JavaScript 分块约 583 KiB gzip 的提示留待后续性能优化。
- 当前详细状态继续只维护在 `docs/抱石照片线路_当前状态与计划.md`，`LOCAL_LATEST.md` 的指定基线版本不变。

## 2026-09-08：抱石照片识别收敛

- 复盘确认精度回退来自任务范围由指定颜色提取扩大为整墙开放识别，并叠加通用分割、二次修边、语义复核、孔位和背景处理。
- 后续目标固定为岩点轮廓和颜色；采用攀岩专项实例分割原生掩膜与轮廓内分色，用户复核后复用现有线路库，不再进入电子岩板流程。
- 不叠加 MobileSAM，不增加云端复核、孔位、起终点、难度、背景净化或新业务实体。
- 旧阶段文档已合并，唯一入口为 `docs/抱石照片线路_当前状态与计划.md`；历史图片和指标证据继续保留。
- 离线评测入口默认改为攀岩专项实例模型和 `interior-v4` 分色；MobileSAM、粗识别和已保存结果只保留为显式对照模式。
- 独立留出合同固定为 5–10 张完整墙面照片，其中至少 3 张验证、2 张来自不同场景的留出；照片、来源和场景不得跨集合，验证通过并锁定配置后才允许运行留出集。
- 识别报告新增实例精确率/召回率、颜色准确率及困难条件切片、边界 F1、严重轮廓错误、逐图与 P95/最大耗时、进程峰值内存；孔位不再是识别门禁。
- 新增只生成摘要和空标注清单的非破坏性留出初始化工具；真实独立留出标注仍为 0/2，因此未产生正式成绩，未提交、推送或部署。
- 本轮 174 项照片后端测试通过（8 项独立 ONNX 依赖测试跳过），46 项前端测试和生产构建通过。

> Historical archive: this log records an earlier interface contract. References to free-text AI requirements, account flows, Studio, or AI Lab are not current product promises. Use `PRODUCT.md`, `docs/项目业务审核与修改报告.md`, and the running local UI as the current source of truth.

Date: 2026-05-25

## Completed

- Rebuilt the backend API contract around the redesigned frontend board studio.
- Added `python-multipart` to `backend/requirements.txt`; dependency installation is left to the user.
- Added board-aware Pydantic models for board specs, board assets, AI experiment requests, task envelopes, and review responses.
- Reworked `/api/generate` and `/api/result/{task_id}` to use a unified async task envelope:
  - `pending`
  - `running`
  - `completed`
  - `failed`
  - `cancelled`
- Added AI Lab modes:
  - `compose_route`: recomposes a route from the current board's existing holds using the A* solver.
  - `review_route`: validates the current route and returns suggestions without mutating the board.
- Preserved the existing board persistence paths while saving full frontend board metadata:
  - `/api/save-board`
  - `/api/my-boards`
  - `/api/my-boards/{saved_id}`
- Kept legacy recipe-style generation compatible through the old `RouteRequest` payload path.
- Updated the frontend AI Lab to send mode, current board, and user requirements.
- Updated frontend polling to read the new result envelope.
- Added explicit Vite HTML input to avoid the Vite 8/Rolldown Windows Chinese-path build issue.
- Removed generated tracked `__pycache__` files from the workspace; `.gitignore` already prevents new ones.

## Verification

- `python -m py_compile` passed for backend entrypoint, agent modules, and core modules.
- FastAPI TestClient health/basic route checks passed:
  - `/api/health`
  - `/api/holds/mapping`
  - `/api/holds/vectors`
  - `/api/my-boards`
- Contract regression passed:
  - saves a new-style board without losing `board_spec` and `tags`
  - lists the saved board with those fields intact
  - `review_route` returns a completed task envelope
  - `compose_route` returns a completed task envelope
- `npm.cmd run build` passed after the Vite config change.

## Notes

- `python-multipart` is still not installed in the current local Python environment. The backend now imports and starts without it, but image upload requires installing `backend/requirements.txt`.
- Git commit/staging was intentionally not performed.


## 2026-09-03：照片线路提取前置验证

- 已确认并保存单图自由布局照片线路需求，建立 `codex/photo-route-extraction` 分支。
- 实现隔离的 OpenCV / MobileSAM 本地识别实验、证据导出和显式评审计数；未接入业务 API 或前端。
- 最新黄色样本 14 个候选对应暂定 12 个对象，精确率 85.71%；蓝色样本 9 个明显蓝色对象提出，但造型/岩点轮廓分界仍异常，灰蓝小点归属待确认。均未通过实施门槛。
- 本机 MobileSAM 两张样本分别 14.015 秒、19.500 秒；不是服务器性能结论。
- 新旧相关测试共 24 项通过；原有上传测试增加元数据临时路径隔离，业务数据无遗留修改。
- 历史结论已合并到 `docs/抱石照片线路_当前状态与计划.md`。后续应先确认标注并提高识别质量，不得把本实验当成完整功能或已验收结果。

## 2026-09-03：灰蓝小点归属确认与局部识别改进

- 用户确认第二张中央造型中部灰蓝小点属于蓝线，验收清单固定十个对象，不需再询问归属。
- 新增大对象局部放大识别、裁剪边缘残片排除，以及分割后对象颜色纯度复核。v5 已独立定位灰蓝小点。
- 暂定黄色 12/13 个候选正确（92.31%），蓝色 10/10 个对象定位；轮廓及完整流程尚未验收，保持未通过状态。
- 本机两张样本分别 14.656 秒和 91.812 秒；27 项相关测试通过。旧 v2 证据已归档，最新报告、编号、复核和计数同步为 v5。

## 2026-09-03：30×20 照片线路电子岩板与独立草稿

- 按用户确认规格新增照片线路专用 6200×4100 mm 无框浅木纹墙，600 个参考孔；自由对象不吸附，原网格板及 AI 数据合同保留。
- 接通已有提取包到本地草稿的幂等导入、整线与单对象几何编辑、层级/起终点、撤销重做、双指缩放及原图/净化背景对照。
- 新增隔离数据目录与本地接口，素材 SHA-256 校验、原子写入、进程间锁、版本冲突和编辑权失效保护、两秒自动保存及浏览器恢复副本。
- 黄色 12 个暂定对象；蓝色 10 个含灰蓝小点，两个已知轮廓问题继续明确标记。已有实验文件和原始图像未覆盖。
- 新增后端 9 项、前端 10 项测试；原前端 15 项、后端相关 52 项通过。浏览器验证三种宽度、真实触控缩放、编辑保存和冲突恢复；Impeccable 检测无发现，生产构建通过。
- 当前电子岩板状态已合并到 `docs/抱石照片线路_当前状态与计划.md`。运行数据仅在本机，未连接 Supabase、未推送或部署。
