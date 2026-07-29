# 攀岩定线辅助系统后端

本仓库当前交付的是“本地单机版攀岩定线辅助系统”。后端只监听本机
`127.0.0.1:8000`，前端通过本机代理访问；演示版不启用账号体系、不连接或修改
Supabase，也不应把 8000 端口暴露到公网。

## 本机启动

在仓库根目录执行：

```powershell
.\scripts\start_demo.ps1
```

也可以分别启动：

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000

cd ..\frontend
npm.cmd run dev -- --host 127.0.0.1
```

浏览器访问 `http://127.0.0.1:5173`。API 文档仅供本机调试：
`http://127.0.0.1:8000/docs`。

## 演示版边界

- 11×18 岩板支持完整性检查、AI 组合和 AI 审核。
- 14×20、16×24、18×22 支持手工编辑与保存，但不进入 AI 实验。
- 标准线路数据展示原始名称、定线者、MoonBoard 原始 Font 等级和来源链接；自有线路展示 MoonBoard 等效难度、可信度与校准状态。
- 大模型只允许润色线路名称与说明；排序、难度和安全结论由确定性规则产生。
- Supabase 适配代码只作为未来云端版储备，本机演示不宣传、不连接、不迁移。
- 仿真审核是独立模块，本次客户汇报前整改不审核、不修改其业务规则。

## 非仿真验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest `
  test_ai_lab_experiments `
  test_hold_image_processing `
  test_local_only_mode `
  test_release_readiness `
  test_standard_board `
  test_standard_board_activity `
  test_standard_board_difficulty `
  test_standard_board_local_first `
  test_standard_board_tags
```

`test_api.py` 是显式手工烟测入口，导入测试模块时不会自动请求真实 HTTP、模型或网络。
