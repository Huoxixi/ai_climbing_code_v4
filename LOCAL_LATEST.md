# 本地最新版

版本：`local-latest-2026.09.05.3`。用户于 2026-09-05 指定此版本为以后本地开发的基线。

- 本机唯一主开发目录：`D:\ai_climbing_code\worktrees\ai_climbing_code_v4-photo-yellow-release`。
- 本地开发分支：`codex/photo-v2-yellow-release`；GitHub 主分支：`main`。
- 启动：在上述目录执行 `./start-photo-local.ps1`。
- 入口：<http://127.0.0.1:4176/#/photo-routes>；设置：<http://127.0.0.1:4176/#/settings>。
- 本地数据和密钥：`.local/`，必须保留且不得上传 GitHub。
- 以当前目录的最新提交继续开发。若创建隔离工作区，从该最新提交分支；不要回到旧 audit、clean、服务器快照或历史验收目录作为默认基线。
- 正式入口为 https://www.panyandingxian.cn/；生产部署通过通过检查的 GitHub 发布标签执行。

版本内容涵盖简化抱石流程、后台任务、自动保存与重启恢复、MobileSAM 自动采样精修、服务端 DeepSeek 视觉复核，以及右上角齿轮设置、账号退出/登录、密钥保存和连接测试。

真实云端能力由有效服务端密钥与实际测试结果决定；代码版本标记不表示云端验收或整体识别准确率已通过。

## 注册与个人数据（2026-09-05）

本版本采用一次性邀请码注册。原有共享岩板、岩点文件保持只读，新注册账号的岩板和岩点写入独立目录；公共岩板可另存个人副本。原试用账号停止用于生产登录，其文件和原照片数据不删除、不自动分配给新用户。照片线路继续按账号隔离。

生产账号数据库位于持久数据目录 accounts.sqlite3，邀请码只保存摘要，7天有效、使用一次即失效。服务器负责人可在已部署后执行：

```bash
cd /opt/ai-climbing/current/backend
sudo -u ai-climbing .venv/bin/python -m core.member_accounts invite
```

输出的邀请码应单独交给受邀者，不放入源码、公开页面或公共文档。注册后用本人用户名和密码登录。新账号不继承旧账号身份。个人模式不再竞争全站编辑权。
