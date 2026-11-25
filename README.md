# WikiBridge

WikiBridge 是一个本地优先的多模态知识工程与纹样知识图谱工作台，使用 React、Tauri 2、Rust Core 与独立星图推理服务，支持多格式资料入库、可追溯图谱抽取、2D/3D 聚类星图浏览，以及「无 LLM 符号推演 + DeepSeek Agent」双模知识推理。

## 核心能力

- **工作台与入库**：Tauri 桌面端与浏览器演示模式，支持 PDF/图片 OCR 及多格式原生抽取、草稿审核发布、SQLite / FTS5 / TF-IDF / 共现矩阵 / SVD 与 OpenCode RAG 问答。
- **纹样星图前端（通用三册架构）**：全屏历史长河时间线、2D/3D 聚类星图（按时代默认材质聚类、按材质默认纹样聚类、按纹样默认时代聚类）、图录索引、原页扫描红框核读与深空/宣纸明暗双主题。
- **双模知识推理**：
  - **无 LLM 符号推演（[src/kg-reasoner.js](src/kg-reasoner.js)）**：RDFS 时代/材质/纹样本体闭包、K-Shortest 多跳演化路径与 Horn 规则证明链、双实体交差集对比与原生 `SPARQL-lite`（支持 `FILTER NOT EXISTS`）、基于关联规则与共同邻居（PathSim）的缺失知识补全。
  - **DeepSeek 神经-符号 Agent（[server/atlas-server.ts](server/atlas-server.ts)）**：多步 Function Calling 调度符号引擎、代码级三态核验（`[实证 E#]` / `[推论 R#]` / 图谱未载），并实时驱动 2D/3D 画布光轨与原页红框溯源。

## 快速启动

需要 Node.js 24（桌面端另需 Rust 与系统 WebView；图谱流水线需 Python 3）。

### 1. 启动纹样星图与双模推理服务

在仓库根目录创建 `.env.local`（已被 `.gitignore` 忽略）配置 DeepSeek Key（不配置时无 LLM 符号推演模式仍完整可用）：

```bash
echo "DEEPSEEK_API_KEY=你的密钥" > .env.local
npm run atlas -- --port 1423 --site data/local-kg/atlas-100/site
```

启动后访问 `http://127.0.0.1:1423/`，按 **`R`** 或点击顶栏 **「推理」** 打开双模推理工作台。

### 2. 启动主工作台（Vite / Tauri）

```bash
npm install
npm run dev          # 浏览器开发模式（http://localhost:1420）
npm run tauri dev    # 桌面工作台模式
```

## 本地知识图谱流水线与跨册合库

流水线从原书 PDF 抽取器物属性、事件与坐标证据，原始 PDF、扫描页与模型权重均不提交到 Git（详阅 [docs/reliable-pipeline.md](docs/reliable-pipeline.md)）。

```bash
# 1. 下载本地 NLP 权重（国内环境建议配镜像）
HF_ENDPOINT=https://hf-mirror.com python3 scripts/download_kg_v2_models.py

# 2. 按册独立提取（通过 WIKIBRIDGE_KG_DATA 隔离目录）
WIKIBRIDGE_KG_DATA=data/local-kg/vol1 python3 scripts/prepare_kg_v2_data.py --source /path/to/第一册.pdf
WIKIBRIDGE_KG_DATA=data/local-kg/vol1 npm run pipeline:reliable

# 3. 将多册（graph.json 或 manifest.json）合并为跨册总图谱并生成站点
python3 scripts/merge_kg_volumes.py \
  --volumes 第一册=data/local-kg/vol1 第二册=data/local-kg/vol2 第三册=data/local-kg/vol3 \
  --output data/local-kg/merged/site

# 4. 加载跨三册总图谱
npm run atlas -- --port 1423 --site data/local-kg/merged/site
```

## 测试与构建

```bash
node --test scripts/test_kg_reasoner.mjs
node scripts/test_edge_depth.mjs && node scripts/test_graph_trial.mjs
python3 -m unittest scripts/test_merge_kg_volumes.py
npm run test:kg
npm run build
```

## 目录说明

- `src/` React 工作台、2D/3D 空间渲染与共享符号推理核心（`kg-reasoner.js`）
- `server/` 统一星图与 DeepSeek Agent 服务（`atlas-server.ts`）及 Vite 推理插件
- `scripts/` 通用星图前端模板（`atlas_viewer.html`）、图谱抽取流水线、跨册合库脚本（`merge_kg_volumes.py`）与测试
- `src-tauri/src/` Rust Core、SQLite、本地抽取与 OpenCode 适配器
- `docs/` 设计文档、课堂方法映射与流水线说明
