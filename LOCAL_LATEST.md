# 本地最新版

版本：`local-latest-2026.09.05.1`。用户于 2026-09-05 指定此版本为以后本地开发的基线。

- 本机唯一主开发目录：`D:\ai_climbing_code\worktrees\ai_climbing_code_v4-photo-yellow-release`。
- 本地开发分支：`codex/photo-v2-yellow-release`；GitHub 主分支：`main`。
- 启动：在上述目录执行 `./start-photo-local.ps1`。
- 入口：<http://127.0.0.1:4176/#/photo-routes>；设置：<http://127.0.0.1:4176/#/settings>。
- 本地数据和密钥：`.local/`，必须保留且不得上传 GitHub。
- 以当前目录的最新提交继续开发。若创建隔离工作区，从该最新提交分支；不要回到旧 audit、clean、服务器快照或历史验收目录作为默认基线。
- 本次只更新本地运行版及 GitHub 源码，没有部署生产服务器。

版本内容涵盖简化抱石流程、后台任务、自动保存与重启恢复、MobileSAM 自动采样精修、服务端 DeepSeek 视觉复核，以及右上角齿轮设置、账号退出/登录、密钥保存和连接测试。

真实云端能力由有效服务端密钥与实际测试结果决定；代码版本标记不表示云端验收或整体识别准确率已通过。
