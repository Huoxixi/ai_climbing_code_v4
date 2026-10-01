# 攀岩定线系统

当前本地基线为 `local-latest-2026.09.05.3`，唯一开发目录为 `D:\ai_climbing_code\worktrees\ai_climbing_code_v4-photo-yellow-release`。保留照片线路及用户确认的 AI 复盘设计。详细入口见 [LOCAL_LATEST.md](LOCAL_LATEST.md)，功能、证据和限制见 [AI 复盘当前状态](docs/AI复盘_当前状态.md) 与 [照片线路状态](docs/抱石照片线路_当前状态与计划.md)。

## 本地运行

在本项目目录执行 `./start-photo-local.ps1`，打开 <http://127.0.0.1:4176/#/photo-routes>；AI 复盘为 `#/climb-replay`，设置为 `#/settings`。启动依赖主目录 `.tools/` 和已核验专项模型，不得删除。端口占用时先核对已有服务，不改入口绕过。`.local/`、`.private/`、素材、账号数据库与个人照片／视频保留本机，不提交或上传。

## 从 GitHub 发布新版本

仓库为 `Huoxixi/ai_climbing_code_v4`，主分支 `main`；本地既有开发分支为 `codex/photo-v2-yellow-release`。先审查差异、测试并构建，推送开发分支，通过 PR 纳入 main；禁止强制推送或改写历史。只向最终通过审核的 main 提交创建全新不可变 `pilot-vYYYY.MM.DD-rcN` 标签。旧标签不能改动或复用。

1. 运行后端生产测试（`python scripts/run_release_tests.py`，在 backend 下），前端 `npm ci`、`npm test`、`npm run test:release-browser`、`VITE_ENABLE_SIMULATION=false npm run build`。Linux／模型运行时验证以 `.github/workflows/release-gate.yml` 为准。
2. PR 的 `release-gate` 全部通过后合入 main；创建并推送新标签，再核对标签的 `release-gate` 全绿，提交 SHA 必须与 main 审核结果一致。
3. 记录当前运行目录、完整 SHA、备份状态、发布条件和上一版本。确认没有正在编辑或运行的 AI 任务、磁盘足以构建和备份。发布不能跳过门禁或重做首次建设／数据迁移。
4. 固定入口为上海 ECS `cn-shanghai / i-uf60c5wm6ax3behiqau4` 的 [Workbench](https://ecs-workbench.aliyun.com/?from=ecs&instanceType=ecs&regionId=cn-shanghai&instanceId=i-uf60c5wm6ax3behiqau4&resourceGroupId=&language=zh-CN)。用户明确选择密钥方式时，可复用主目录 `project-ops/ssh/config` 的受限运维连接；它的服务器允许列表以 root 调用同一个发布脚本，不扩大 SSH 权限。直接 root 终端只执行：

```bash
/usr/local/lib/ai-climbing/deploy_release.sh <完整新标签>
```

脚本从 GitHub 检出标签、复测、构建、发布前备份、原子切换并在失败时回退。不要用 `git pull`、手工同步或直接修改 current 代替它。脚本所在服务器路径保持不变。旧文档的固定 03:00–04:00 窗口已退出当前操作要求；选择已授权且无编辑／任务冲突的维护时段，不与备份任务重叠。实际任务状态无法确认时不得猜测。

发布后核验：

```bash
readlink -f /opt/ai-climbing/current
cat /etc/ai-climbing/release.env
curl -fsS http://127.0.0.1:8000/api/health
systemctl is-active ai-climbing nginx
```

再检查 <https://www.panyandingxian.cn/> 的登录、照片线路和 AI 复盘：默认 0.75 倍速、简短动作、完整攀爬结束后的总结及小圆盘。手动重开保持显示，同一记录重播不重复演示。观察 30 分钟并登记未完成项目。

## 生产边界与运维

`/root/ai_climbing_code` 仅同步／构建；`/opt/ai-climbing/releases` 保存不可变版本；`/opt/ai-climbing/current` 指向运行版本；`/var/lib/ai-climbing/data` 是生产数据；`/etc/ai-climbing` 是受限配置。数据、照片、数据库、模型、密钥和备份均不在常规清理范围。

2026-10-01 13:55（北京时间）密钥核验：运行 `pilot-v2026.09.23-rc28` / `22120ddbe62004d03c0e350dfd83fd80d1c4ad13`；健康正常，隧道 inactive，备份与健康定时器 active，最新备份已远端验证。用户 root 清理缓存及旧发布后，只保留 rc24、rc26、rc28；磁盘 76%，可用约 9.2 GiB。正式域名为当前入口，隧道不再作为交付入口。

清理先用 `deploy/scripts/cleanup_server_caches.sh audit` 测量；`clean` 仅清理下载缓存。用户已授权历史发布只留最近三个，可用 `deploy/scripts/prune_old_releases.sh audit` 核验，`prune` 执行；当前版本必须在保留集合且三个版本完整，否则停止。发现受保护内容必须检查用途，不绕过保护。完整执行和回退见 [运维手册](docs/试运营上线运维手册.md)，验收见 [发布检查单](docs/试运营发布检查单.md)。
