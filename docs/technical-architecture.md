# 技术架构

| 入口 | 实现 | 职责 |
| --- | --- | --- |
| 浏览器工作台 | React、Vite、PDF.js、Tesseract.js | 样例浏览、导入界面、开发期本地图谱预览 |
| 桌面工作台 | Tauri 2、Rust、SQLite | 语料与权限、导入、校验发布、FTS5 检索、OpenCode |
| 三册星图 | Node.js 24、原生 HTML/Canvas、共享 JS 推理器 | 历史长河、2D/3D 星图、原页证据、DeepSeek |

`src/` 包含工作台和 `kg-reasoner.js`。`src-tauri/src/` 负责桌面存储、权限与资料处理。开发期 Vite 路由由 `server/reasoning.ts` 提供。正式静态构建只包含前端资产。

`server/atlas-server.ts` 读取指定清单并托管图片和 `/api/kg/*`。符号推演可以在浏览器运行。DeepSeek 调用在服务端发起，在浏览器中流式显示过程、已核验引用与相关图谱。静态站点和动态服务共用星图模板。

三册离线抽取由 `scripts/` 生成 JSON、页图和 SQLite。Node 星图服务从清单和原页资产启动。SQLite 用于桌面入库、检索和发布。[从 PDF 复现](reliable-pipeline.md) · [桌面后端](opencode-backend.md)
