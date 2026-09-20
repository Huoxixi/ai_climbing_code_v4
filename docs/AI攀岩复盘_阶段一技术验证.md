# AI 攀岩复盘：阶段一技术验证

## 当前范围

本阶段提供独立的用户页面和后台验证接口，不进入照片线路默认流程，也不修改已保存线路。

已完成：

- 登录账号隔离的 MP4 上传；
- 200 MB、90 秒、2700 帧和 1080p 级别的上传门禁；
- 单并发、可恢复、可取消和可重试的后台任务；
- 从已有线路读取颜色，或直接指定测试颜色；
- 通过 VLM Run 调用 SAM 3.1 与 ViTPose+ Large；
- 输出岩点编号、手脚接触、使用顺序、身体中线、估算用时及模型用量；
- 明确将结果标记为 `prototype_needs_review`。

尚未完成：

- 结果视频渲染；
- SAM 像素掩膜接触判断；
- 地面分割和正式计时规则；
- 用户手工修正；
- 原视频保留期限和删除入口；
- 真实视频准确率、云端费用和生产资源验收。

## 开关与密钥

- 接口默认开放；如需临时停用，可设置 `ENABLE_CLIMB_REPLAY=false`。
- 生产环境仍需配置 `VLMRUN_API_KEY` 才会将用户主动提交的视频发送到分析服务。
- 云端密钥：`VLMRUN_API_KEY`。密钥仅由服务端读取，不能返回前端或写入代码。
- 可选网关地址：`VLMRUN_BASE_URL`，默认 `https://gateway.vlm.run/v1/openai`。

没有配置密钥时，上传和任务队列仍可验证，但任务会安全失败，并显示“视频未发送到云端”。

## 接口

- `POST /api/climb-replay/jobs`：上传 MP4；表单字段为 `video`、可选 `route_id`、或 `route_color`。
- `GET /api/climb-replay/jobs`：当前账号的任务列表。
- `GET /api/climb-replay/jobs/{id}`：任务状态和结构化结果。
- `POST /api/climb-replay/jobs/{id}/cancel`：取消排队或运行中的任务。
- `POST /api/climb-replay/jobs/{id}/retry`：重试失败或取消的任务。

## 验收顺序

1. 使用固定机位、单人、5–10 秒 SDR 视频验证。
2. 人工核对岩点数量、手脚顺序和完成状态。
3. 记录上传量、云端耗时、单次费用和失败原因。
4. 再验证 90 秒视频及连续三次任务。
5. 完成隐私、清理、准确率和资源验收后，才进入前端原型与生产评审。

## 技术来源

模型请求契约和接触判断思路参考 Jeremy Park 的 Apache-2.0 开源项目：
<https://github.com/jeremyipark/vision-demos/tree/main/rock_climbing>。
