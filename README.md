# 攀岩定线系统：线上试用主要运维指令

> **本地最新版：`local-latest-2026.09.05.1`**。日常本地开发与启动请先阅读 [本地最新版说明](LOCAL_LATEST.md)。下文为生产服务器运维资料，不代表本次已部署生产服务器。

适用环境：阿里云 Ubuntu 24.04 服务器  
服务器项目目录：`/root/ai_climbing_code`  
线上数据目录：`/var/lib/ai-climbing/data`  
当前运行版本：`/opt/ai-climbing/current`

> 本文所有指令都在阿里云服务器的 root 终端执行。  
> 不要把密码、AccessKey、AI Key 或 `.env` 内容复制到聊天、GitHub或截图中。

## 1. 每天开始试用前：快速检查

先进入项目目录：

```bash
cd /root/ai_climbing_code
```

运行系统自检：

```bash
/usr/local/lib/ai-climbing/daily_check.sh
```

检查三个主要服务：

```bash
systemctl is-active ai-climbing nginx ai-climbing-tunnel
```

正常应连续显示三个：

```text
active
active
active
```

查看老师当前使用的临时网址：

```bash
cat /run/ai-climbing-tunnel/url
```

检查后端健康：

```bash
curl -fsS http://127.0.0.1:8000/api/health
```

检查磁盘和内存：

```bash
df -h /
free -h
```

磁盘使用率达到80%时，应停止批量上传和系统更新并处理空间问题。

## 2. 查看当前临时 HTTPS 网址

最常用指令：

```bash
cat /run/ai-climbing-tunnel/url
```

同时查看隧道状态和网址：

```bash
echo "隧道状态："
systemctl is-active ai-climbing-tunnel
echo "当前网址："
cat /run/ai-climbing-tunnel/url
```

Quick Tunnel重启后网址可能变化。服务器重启、后端重启、隧道重启、每日备份或重新发布后，都要重新执行以上指令，再把最新地址发给老师。

## 3. 网站打不开时的排查顺序

### 第一步：检查服务

```bash
systemctl is-active ai-climbing nginx ai-climbing-tunnel
```

### 第二步：检查服务器内部是否健康

```bash
curl -i http://127.0.0.1:8000/api/health
curl -I http://127.0.0.1:8080/
```

### 第三步：查看当前网址

```bash
cat /run/ai-climbing-tunnel/url
```

如果内部健康、老师仍打不开，先确认老师使用的是这里显示的最新地址。

### 第四步：查看错误日志

后端最近100行日志：

```bash
journalctl -u ai-climbing -n 100 --no-pager
```

临时隧道最近100行日志：

```bash
journalctl -u ai-climbing-tunnel -n 100 --no-pager
```

Nginx错误日志：

```bash
tail -n 100 /var/log/nginx/ai_climbing_error.log
```

### 第五步：只重启出现故障的服务

后端故障：

```bash
systemctl restart ai-climbing
```

Nginx故障：

```bash
nginx -t && systemctl restart nginx
```

隧道不是 `active` 时：

```bash
systemctl restart ai-climbing-tunnel
sleep 10
cat /run/ai-climbing-tunnel/url
```

不要在隧道正常时随意重启。任何服务重启后，都要重新查看临时网址。

## 4. 查看账号密码

查看负责人、马老师、邓老师的账号凭据：

```bash
cat /root/ai-climbing-pilot-credentials.txt
```

只把各自的密码私下发给对应老师，不要发送整个文件或截图。

检查凭据文件权限：

```bash
stat -c '%a %U %G %n' \
  /root/ai-climbing-pilot-credentials.txt \
  /etc/ai-climbing/pilot-users.json
```

正常应分别为：

```text
600 root root
640 root ai-climbing
```

## 5. 查看当前程序版本

查看当前运行目录：

```bash
readlink -f /opt/ai-climbing/current
```

查看当前发布提交号：

```bash
cat /etc/ai-climbing/release.env
```

查看服务器同步目录的Git提交号：

```bash
git -C /root/ai_climbing_code rev-parse HEAD
```

注意：`/opt/ai-climbing/current`和`/etc/ai-climbing/release.env`代表实际运行版本；`/root/ai_climbing_code`只是同步和构建目录。

## 6. 从GitHub发布新版本

发布前必须：

1. 通知老师停止编辑；
2. 确认没有正在运行的AI任务；
3. 新代码已经通过测试；
4. GitHub已经创建不可变的 `pilot-v...` 标签；
5. 记录当前版本，准备回退。

列出已有发布版本：

```bash
ls -1 /opt/ai-climbing/releases
```

使用发布标签部署。以下只是格式示例，不能原样运行：

```bash
/usr/local/lib/ai-climbing/deploy_release.sh pilot-v2026.08.01-rc1
```

将示例中的标签替换成准备发布的新标签。发布脚本会自动：

- 从GitHub克隆指定标签；
- 使用 `npm ci` 安装前端依赖；
- 运行前后端测试；
- 构建生产前端；
- 安装锁定的Python依赖；
- 在临时端口检查新版本；
- 生成发布前数据备份；
- 原子切换运行版本；
- 失败时恢复上一程序版本。

发布结束后检查：

```bash
readlink -f /opt/ai-climbing/current
cat /etc/ai-climbing/release.env
curl -fsS http://127.0.0.1:8000/api/health
systemctl is-active ai-climbing nginx ai-climbing-tunnel
cat /run/ai-climbing-tunnel/url
```

禁止直接在 `/opt/ai-climbing/current` 中修改代码，也不要在 `/root/ai_climbing_code` 中直接执行 `git pull` 作为生产发布方式。

如确实需要人工重新同步GitHub代码到构建目录，使用项目约定流程：

```bash
cd /tmp
rm -rf /tmp/ai_climbing_code_v4
git clone git@github.com:Huoxixi/ai_climbing_code_v4.git

rsync -av \
  --exclude='backend/.env' \
  --exclude='backend/.venv' \
  --exclude='node_modules' \
  --exclude='frontend/node_modules' \
  /tmp/ai_climbing_code_v4/ /root/ai_climbing_code/
```

该同步只更新构建目录，不等于完成生产发布；正式上线仍使用 `deploy_release.sh` 和发布标签。

## 7. 程序故障时回退上一版本

程序回退不会回退老师数据。

先查看可用版本：

```bash
ls -1 /opt/ai-climbing/releases
readlink -f /opt/ai-climbing/current
```

例如回退到 `pilot-v2026.07.30-rc9`：

```bash
/usr/local/lib/ai-climbing/rollback_release.sh pilot-v2026.07.30-rc9
```

回退后检查：

```bash
curl -fsS http://127.0.0.1:8000/api/health
readlink -f /opt/ai-climbing/current
cat /run/ai-climbing-tunnel/url
```

只在确认目标版本目录完整时执行。不要删除当前数据目录。

## 8. 查看和执行数据备份

查看最近一次备份状态：

```bash
cat /var/lib/ai-climbing/ops/last-backup.env
```

查看本机最近的每日备份：

```bash
ls -lht /var/backups/ai-climbing/daily | head -n 20
```

查看备份定时器：

```bash
systemctl status ai-climbing-backup.timer --no-pager
systemctl list-timers ai-climbing-backup.timer --no-pager
```

立即执行一次与正式每日任务相同的备份：

```bash
/usr/local/lib/ai-climbing/backup_data.sh daily
```

该指令会短暂停止后端、打包数据、计算SHA-256、上传OSS、重新下载并校验，然后恢复服务。完成后必须重新查看临时网址：

```bash
cat /run/ai-climbing-tunnel/url
```

查看OSS备份对象：

```bash
rclone --config /etc/ai-climbing/rclone.conf \
  lsf oss:climbing-pilot-backup-sh-2026/daily/ \
  --recursive | tail -n 30
```

不要在终端打印 `/etc/ai-climbing/rclone.conf` 的内容。

## 9. 查看线上数据但不修改

查看数据目录大小：

```bash
du -sh /var/lib/ai-climbing/data
```

查看主要数据文件：

```bash
find /var/lib/ai-climbing/data -maxdepth 2 -type f \
  -printf '%TY-%Tm-%Td %TH:%TM %10s %p\n' | sort
```

查看岩板总数：

```bash
/opt/ai-climbing/current/backend/.venv/bin/python -c \
  "import json; print(len(json.load(open('/var/lib/ai-climbing/data/saved_boards.json', encoding='utf-8'))))"
```

查看切换前旧数据归档：

```bash
ls -ld /var/lib/ai-climbing/archives/*
```

## 10. 数据恢复：高风险操作

数据恢复会用旧备份替换当前线上数据。不要为了修复网页或程序故障而恢复数据；程序故障应先使用第7节的程序回退。

恢复前必须：

1. 停止所有老师编辑；
2. 保留当前数据现场；
3. 找到备份压缩包及同名 `.sha256` 文件；
4. 确认备份时间和影响范围；
5. 由负责人准确回复“确认执行”。

恢复脚本格式：

```bash
/usr/local/lib/ai-climbing/restore_data.sh \
  /var/backups/ai-climbing/daily/具体备份文件.tar.gz
```

脚本会再次显示高风险说明，只有在终端准确输入：

```text
确认执行
```

才会继续。不要预先复制示例路径执行，必须先确认实际备份文件。

## 11. 立即停止或恢复老师的公网访问

临时停止外部访问，但保留服务器和数据：

```bash
systemctl stop ai-climbing-tunnel
```

恢复外部访问：

```bash
systemctl start ai-climbing-tunnel
sleep 10
cat /run/ai-climbing-tunnel/url
```

恢复后会生成新网址，需要重新发给老师。

## 12. 检查端口是否安全

```bash
ss -lntp | grep -E '(:22|:80|:443|:8000|:8080|:8081|:8443|:5173)'
```

正常情况下：

- SSH `22` 可以监听公网；
- `8000`、`8080`、`8081`、`8443`只能监听 `127.0.0.1`；
- 不应看到公网监听的 `80`、`443`、`5173`。

## 13. 常用日志和状态

```bash
# 后端状态
systemctl status ai-climbing --no-pager

# Nginx状态
systemctl status nginx --no-pager

# 隧道状态
systemctl status ai-climbing-tunnel --no-pager

# 后端最近日志
journalctl -u ai-climbing -n 100 --no-pager

# 隧道最近日志
journalctl -u ai-climbing-tunnel -n 100 --no-pager

# Nginx访问日志
tail -n 100 /var/log/nginx/ai_climbing_access.log

# Nginx错误日志
tail -n 100 /var/log/nginx/ai_climbing_error.log

# 最近备份状态
cat /var/lib/ai-climbing/ops/last-backup.env

# 当前网址
cat /run/ai-climbing-tunnel/url
```

## 14. 严禁执行的操作

- 不要删除 `/var/lib/ai-climbing/data`。
- 不要直接覆盖线上数据目录。
- 不要直接修改 `/opt/ai-climbing/current`。
- 不要把 `.env`、密码、AccessKey或AI Key提交GitHub。
- 不要把Nginx、8000、8080、5173端口直接开放公网。
- 不要公开OSS Bucket。
- 不要把老师密码写到登录页。
- 不要使用数据恢复解决普通程序问题。
- 不要在未备份和未确认影响范围时执行删除、覆盖或恢复。

## 15. 每次操作后的最终检查

```bash
systemctl is-active ai-climbing nginx ai-climbing-tunnel
curl -fsS http://127.0.0.1:8000/api/health
cat /run/ai-climbing-tunnel/url
cat /var/lib/ai-climbing/ops/last-backup.env
df -h /
```

确认：

- 三个服务都是 `active`；
- 健康接口返回 `success`；
- 临时网址能够打开登录页；
- 未登录不能读取业务数据；
- 最近备份状态为 `success`；
- 数据和磁盘空间正常；
- 如网址变化，已经把新网址发给老师。

## 抱石照片线路（本地在途）

当前目标收敛为识别岩点轮廓和颜色，再由用户复核、保存为个人照片线路卡片并进入现有线路库。照片线路流程不再提供电子岩板、位置确认、孔位网格或点位校准。默认计划采用攀岩专项实例分割的原生掩膜，不叠加 MobileSAM、云端语义复核、自动孔位或墙面净化，也不新增业务实体。识别质量尚未通过独立留出验收，未发布到服务器。详见[唯一状态与执行计划](docs/抱石照片线路_当前状态与计划.md)。
