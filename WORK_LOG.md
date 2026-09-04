# Work Log - Backend Interface Sync

## 2026-09-03 最新新增：保留原墙面的背景净化原型

- 用户新增“去除其他线路，留下背景墙和目标线路”；范围与实现见 `docs/照片线路背景净化补充需求.md`。
- 本地 MobileSAM 全景扫描 + 显式复核 + 本地 LaMa 修补，输出独立背景、目标合成图及修补蒙版。人物和标牌暂保留，是否一起清理的问题尚待用户回复。
- 黄色保留 12 个对象，蓝色保留 10 个；人工选择/补画清理蒙版，不是全自动通过。目标及修补蒙版外改动像素均为 0。
- 两图全景扫描各约 103/106 秒，修补各约 11 秒，未计人工复核和之前选线耗时。42 项相关测试通过；墙面纹理与人物接触处仍有痕迹，尚未验收。
- 原图与历史结果保留；未接入业务接口/前端，未部署或推送。原服务器验证包不含此次背景模型。

## 2026-09-03 最新接续：识别测量与压缩计划

- 新对话优先读 `docs/照片线路执行计划.md` 和 `docs/照片线路识别续接验证记录.md`；下方为历史记录。
- 保留 v5 对照，新增显式选用的 v6 局部采样及小批次实验。批次 2：黄色 21.484 秒 / 1333.7 MiB，蓝色 49.281 秒 / 1412.4 MiB（完整冷启动，Windows 本机）；与批次 8 蒙版一致。
- 严重轮廓错误、正式人工标注、服务器实测仍未解决，门槛不通过。未接入完整照片库/编辑器，未部署或推送。
- 新增独立进程硬超时/取消、进程树内存测量、蒙版指纹绑定复核；35 项相关测试通过。
- 已准备含样本和本地模型的服务器隔离验证包及说明。受限 SSH 无该操作入口，未修改权限或生产文件。无数据库操作。

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
- 详情见 `docs/照片线路提取需求与实施状态.md` 和 `docs/照片线路识别可行性验证报告.md`。后续应先确认标注并提高识别质量，不得把本实验当成完整功能或已验收结果。

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
- 详见 `docs/照片线路电子岩板实现说明.md`。运行数据仅在本机，未连接 Supabase、未推送或部署；完整识别工作流和轮廓修复仍待后续阶段。
