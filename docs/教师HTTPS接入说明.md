# 教师 HTTPS 接入说明

目标入口为：

```text
https://climb.panyandingxian.cn
```

马老师和邓老师使用各自独立账号。Nginx 访问日志记录账号名，基础认证密码不会转发给后端。后端仍只监听 `127.0.0.1:8000`，不得公开 `8000`、`8080`、`8081`、`5173`。

## 上线前门禁

公网模式必须同时满足：

1. `panyandingxian.cn` 已取得 ICP 备案号。
2. 子域名 `climb.panyandingxian.cn` 的 A 记录已指向服务器公网 IP。
3. 已生成上线前完整数据备份，并完成对象存储回读校验。
4. 已签发 `climb.panyandingxian.cn` 的有效 HTTPS 证书。
5. 云安全组仅新增 TCP 80、443；应用和开发端口继续关闭。
6. `/etc/ai-climbing/icp-number` 已由负责人写入获批备案号。

备案未完成时，只能启用服务器本机 `127.0.0.1:8443` 的内部验收入口，不得通过域名公开服务。

## 账号文件

- 服务器密码摘要：`/etc/nginx/ai-climbing-teacher-users.htpasswd`
- 首次生成的明文交付文件：`/root/ai-climbing-teacher-credentials.txt`

明文文件复制到负责人电脑后应从服务器删除。负责人分别把对应账号通过私下渠道交给老师，不得在群聊、Git、日志或发布记录中保存密码。

## 内部验收

```bash
python3 /root/ai_climbing_code/deploy/scripts/create_teacher_credentials.py
bash /root/ai_climbing_code/deploy/scripts/provision_teacher_gateway.sh internal
```

内部入口必须验证：

- 未提供账号返回 `401`。
- 两个账号分别可以打开首页和 `/api/health`。
- `/docs`、`/openapi.json` 和仿真接口返回 `404`。
- 基础认证头没有传递到后端。
- `8000`、`8080`、`8081` 和 `8443` 均未监听公网地址。

## 备案完成后的公网切换

取得备案号、配置 DNS、在安全组中开放 TCP 80/443 后，先把备案号写入服务器门禁文件，再签发证书并自动切换：

```bash
install -o root -g root -m 0644 /dev/stdin /etc/ai-climbing/icp-number
bash /root/ai_climbing_code/deploy/scripts/issue_teacher_certificate.sh
```

第一条命令会等待从标准输入读取备案号，输入完成后按 `Ctrl+D`。签发失败时脚本会自动恢复内部 HTTPS 入口。

公网验收通过后才能把链接和独立账号交给老师。
