# 🧗‍♂️ 智行通途 (Zhi Xing Tong Tu) - AI 攀岩定线核心引擎

本项目是一个基于“大模型推理 (LLM) + 纯数学物理规则校验”的混合智能体架构 (Agentic Workflow) 后端服务。旨在为攀岩者提供符合人体工学、生物力学且极具挑战性的定制化攀爬路线。

---

## 🌍 云端生产环境信息
- **服务器IP**: `106.14.216.81`
- **操作系统**: Ubuntu 24.04 LTS (64位)
- **部署路径**: `/root/ai_climbing_code/backend`
- **对外暴露端口**: `8000` (需在阿里云安全组中放行自定义 TCP `8000/8000`)
- **API 文档地址**: [http://106.14.216.81:8000/docs](http://106.14.216.81:8000/docs)

---

## 📂 核心文件结构与架构契约

- `models.py` —— **数据孪生契约**。定义了前后端交互的 Pydantic 模型，包括攀岩者体征(`ClimberProfile`)和单步动作(`RouteStep`)。
- `validator.py` —— **物理规则引擎 (法官)**。包含纯数学逻辑，计算欧氏距离，拦截大模型生成的超出臂展/身高极限的反人类动作。
- `agent.py` —— **智能体反思核心 (大脑)**。对接 DeepSeek 大模型，实现 `Generate -> Critique -> Reflect` 的自动纠错闭环。
- `main.py` —— **主路由出口**。基于 FastAPI 构建，将核心引擎挂载到 HTTP 接口上。
- `.env` —— **环境变量配置 (机密)**。存放 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`，**严禁提交到公开的代码仓库**。
- `mock_holds.json` —— **虚拟岩库**。存放当前岩板的数字孪生坐标系。

---

## 💻 常用服务器运维指令

### 1. 远程直连服务器
打开本地终端 (VS Code Terminal 或 PowerShell)，输入：
```bash
ssh root@106.14.216.81
# 随后盲打输入阿里云 root 密码

同步新依赖 (抓药)
如果在本地开发时新增了包并更新了 requirements.txt，上传后需在云端同步：
pip install -r requirements.txt

cd ~/ai_climbing_code/backend
source .venv/bin/activate


在激活了 .venv 的状态下，以对外公开的模式启动引擎：
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

把项目挂在在后台：
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > api.log 2>&1 &

kill 1776
取消后台进程