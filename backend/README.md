# 🧗‍♂️  - AI 攀岩定线核心引擎

本项目是一个基于“大模型推理 (LLM) + 纯数学物理规则校验”的混合智能体架构 (Agentic Workflow) 后端服务。旨在为攀岩者提供符合人体工学、生物力学且极具挑战性的定制化攀爬路线。

---

## 🌍 云端生产环境信息
- **服务器IP**: `106.14.216.81`
- **操作系统**: Ubuntu 24.04 LTS (64位)
- **部署路径**: `/root/ai_climbing_code/backend`
- **对外暴露端口**: `8000` (需在阿里云安全组中放行自定义 TCP `8000/8000`)
- **API 文档地址**: [http://106.14.216.81:8000/docs](http://106.14.216.81:8000/docs)

backend/
├── .env                    # 🔐 环境变量 (绝不提交到 Git)
├── README.md               # 📖 项目说明文档
├── requirements.txt        # 📦 依赖包列表
├── main.py                 # 🚀 FastAPI 主入口 (启动文件)
│
├── agent/                  # 🧠 AI 大脑中枢 (负责调度与思考)
│   ├── controller.py       # (我们刚写的) Agent 核心调度器与反思循环
│   └── tools_def.py        # (我们刚写的) 赋给大模型的工具 JSON 说明书
│
├── core/                   # ⚙️ 核心引擎与契约 (负责规则与标准)
│   ├── config.py           # 环境变量读取配置
│   ├── models.py           # Pydantic 数据结构契约 (所有的数据流转标准)
│   └── validator.py        # 物理规则裁判系统
│
├── data/                   # 🗄️ 静态数据与配置字典
│   ├── empty_wall_grid.json# 纯净的 11x18 孔位网格数据
│   ├── hold_dict.json      # 6大类岩点的物理得分/视觉字典
│   ├── classic_routes.json # (你原有的) 经典路线，用于大模型的 Few-Shot 标杆参考
│   ├── filtered_skeletons.json # (你原有的) 清洗后的骨架数据
│   └── mock_holds.json     # (你原有的) 旧版死墙数据，可留作存档或降级参考
│
├── scripts/                # 🛠️ 独立脚本工具箱 (不参与系统运行，用于离线预处理)
│   ├── generate_wall.py    # 创世脚本：生成空白墙网格
│   ├── upgrade_map.py      # (你原有的) 升级映射脚本
│   ├── print_tree.py       # 打印目录树脚本
│   └── data_washer/        # (你原有的) 数据清洗流水线
│       ├── 1_rough_filter.py
│       └── 2_llm_annotator.py
│
├── raw_datasets/           # 📦 原始爬虫数据集 (保持原样，无需改动)
│   ├── holdIx_to_holdStr
│   ├── holdStr_to_holdIx
│   └── moonGen_scrape_2016_final
│
└── test_api.py         # (你原有的) API 测试脚本

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
taskkill /F /PID 1776
取消后台进程


