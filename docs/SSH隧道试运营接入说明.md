# SSH 隧道试运营接入说明

## 适用范围

- 试运营成员：系统负责人、马老师、邓老师。
- 系统负责人使用操作入口，可以查看和编辑。
- 马老师、邓老师使用只读入口，服务器会拒绝写入请求。
- 每人使用自己的 SSH 密钥和账号，不共用私钥、密码或浏览器链接。
- 域名、备案和公网 HTTPS 暂不启用。

## 安全边界

服务器网页服务只监听本机端口：

- `127.0.0.1:8080`：操作入口。
- `127.0.0.1:8081`：只读入口。
- `127.0.0.1:8000`：后端，仅供 Nginx 转发。

云安全组不得开放 `80`、`443`、`8000`、`8080`、`8081`、`5173`。参与者只能通过公网 SSH 端口建立加密隧道。

## 第一次准备

每位参与者在自己的 Windows 电脑打开 PowerShell，运行：

```powershell
ssh-keygen -t ed25519 -a 64 -f "$env:USERPROFILE\.ssh\ai-climbing-pilot"
```

出现提示时设置一个自己记得住的私钥口令。生成后，只把以下公钥文件发给系统负责人：

```text
C:\Users\自己的用户名\.ssh\ai-climbing-pilot.pub
```

不要发送没有 `.pub` 后缀的私钥文件。

## 系统负责人创建账号

把收到的公钥临时上传到服务器后，分别执行：

```bash
sudo /usr/local/lib/ai-climbing/create_tunnel_user.sh operator pilot-owner /tmp/owner.pub
sudo /usr/local/lib/ai-climbing/create_tunnel_user.sh viewer pilot-ma /tmp/ma.pub
sudo /usr/local/lib/ai-climbing/create_tunnel_user.sh viewer pilot-deng /tmp/deng.pub
```

账号创建成功后，应删除服务器上的临时公钥副本。公钥本身不是秘密，但不应长期散落。

## 每次使用

系统负责人运行：

```powershell
ssh -NT -i "$env:USERPROFILE\.ssh\ai-climbing-pilot" -L 127.0.0.1:18080:127.0.0.1:8080 pilot-owner@服务器公网IP
```

马老师、邓老师运行：

```powershell
ssh -NT -i "$env:USERPROFILE\.ssh\ai-climbing-pilot" -L 127.0.0.1:18080:127.0.0.1:8081 自己的账号@服务器公网IP
```

保持 PowerShell 窗口打开，然后在浏览器访问：

```text
http://127.0.0.1:18080
```

关闭 PowerShell 窗口即断开访问。

## 使用规则

1. 只有系统负责人进行编辑；老师先查看、搜索和反馈。
2. 编辑前在三人群里说明，确认没有另一人正在修改同一岩板。
3. 不把姓名、电话等个人信息发送给 AI。
4. 发现保存失败、数据异常或页面无法进入时立即停止编辑并记录时间和页面。
5. 设备丢失或人员退出时，当天在服务器锁定对应账号。

## 撤销单个参与者

```bash
sudo usermod --expiredate 1 pilot-ma
```

需要恢复时：

```bash
sudo usermod --expiredate -1 pilot-ma
```

锁定账号后还应删除其 `authorized_keys` 或直接归档该试运营账号，避免旧密钥再次使用。
