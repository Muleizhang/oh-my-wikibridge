# WikiBridge

WikiBridge 将多格式资料整理成可追溯的知识库。三册《中国纹样全集》星图提供历史长河、2D/3D 聚类、图录、原页核读、符号推演和 DeepSeek 问答。React/Tauri 工作台用于导入、检索、审核和发布资料。

## 从 GitHub 克隆后复现三册

1. 将三个 PDF 放入仓库的 `source/`，命名为 `第一册.pdf`、`第二册.pdf`、`第三册.pdf`。
2. 按[复现说明](docs/reliable-pipeline.md)准备 Node.js 24、OCR 工具、仓库内的 venv 和模型权重。
3. 执行以下命令。

~~~bash
bash scripts/rebuild_atlas.sh
npm run atlas -- --port 1423 --site data/local-kg/merged/site
~~~

已有三册分享包时，完整解压后将 `--site` 指向包内 `site/`。保留同一包的 `manifest.json`、`assets/` 和 `annotations-v2/`。更换清单后重启服务。[图片字段说明](docs/atlas-frontend-adaptation.md)

## DeepSeek 问答

在仓库根目录的 `.env.local` 中设置以下变量。

~~~dotenv
ATLAS_AGENT_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的密钥
~~~

启动后打开星图，按 `R` 进入推理面板。网页和 API 由同一进程提供。[本机星图](http://127.0.0.1:1423/)

默认模型是 `deepseek-flash`。可用 `DEEPSEEK_MODEL` 指定模型，或通过 `ATLAS_AGENT_PROVIDER=openrouter`、`OPENROUTER_API_KEY` 和可选的 `OPENROUTER_MODEL` 使用 OpenRouter。浏览和符号推演无需密钥。

用 `curl -fsS http://127.0.0.1:1423/api/kg/status` 查看服务状态。`deepseekReady` 表示已读取密钥，实际回答和引用核验结果见「AI 对话」。

## 工作台与检查

~~~bash
npm ci
npm run dev                      # 浏览器工作台，1420
npm run tauri dev                # 桌面工作台，需 Rust 和系统 WebView
npm run build
node --test scripts/test_*.mjs
~~~

Python 测试使用[复现流程配置的 venv](docs/reliable-pipeline.md#检查)。

- `src/` 和 `src-tauri/` 包含工作台和共享推理器。
- `server/` 提供星图和 DeepSeek API。
- `scripts/` 包含抽取、入库、导出、打包及测试。
- `source/` 放 PDF，`data/local-kg/` 放生成数据。PDF 和生成数据由 Git 忽略。
- [文档目录](docs/README.md)
