# 攀岩定线辅助系统前端

当前前端服务于本地单机版产品，包含总览、定线工作台、岩点库、岩板资产、标准线路库、仿真审核入口和 AI 实验室。

- 11×18 标准训练板支持手工定线、完整性检查、AI 组合与审核。
- 14×20、16×24、18×22 支持手工定线与保存，当前不进入 AI 实验。
- 当前没有经过确认的板面材质配置，界面不会展示或推测材质。
- 启动后无需登录；当前版本不宣传云端多用户能力。

从仓库根目录运行 `.\scripts\start_demo.ps1` 可同时启动前后端。仅启动前端时：

```powershell
cd frontend
npm.cmd run dev
```

发布前验证：

```powershell
npm.cmd ci
npm.cmd test
npm.cmd run build
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

`test:e2e` 会在桌面和移动端 Chromium 中验证模板选择、岩点放置、未保存提醒、岩点库、岩板对照、仿真关闭和 AI 安全边界。测试使用本地拦截数据，不会修改真实岩板、账号或服务器数据。
