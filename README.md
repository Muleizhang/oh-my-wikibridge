# WikiBridge

WikiBridge 是一个本地优先的多模态知识工程工作台。首版使用 React、Tauri 2 和 Rust Core，支持在 Windows 和 macOS 上导入资料、建立可追溯索引、查看关系图，并通过本机 OpenCode 进行带证据的 RAG 问答。

## 当前首版能力

- 浏览器演示模式，内置示例语料和检索流程
- Tauri 桌面模式，管理员可以创建语料库并导入文件
- 文本、Markdown、HTML、CSV、JSON、XML、DOCX、PPTX、XLSX、ODT、ODP、EPUB 等格式的原生抽取
- PDF 和图片的浏览器端 OCR，支持快速样例、页面续处理和简体中文与英语语言包
- 关闭窗口后驻留系统托盘，可从托盘重新打开或退出
- 草稿知识库、发布版本和只读 user 模式
- SQLite、FTS5、TF-IDF、Word2Vec、共现矩阵、SVD 投影和 RDF/SPARQL 关系查询
- OpenCode `homo/gpt-6.1-terra` 默认模型适配，以及带来源编号的回答
- RAG 检索步骤、图谱关系、证据片段和原始文件预览
- Markdown 报告和原始文件导出

## 开发环境

需要安装 Node.js 24、Rust、系统 WebView 依赖，以及可选的 OpenCode。OpenCode 缺失时仍可运行浏览器演示和本地检索功能。

```bash
npm install
npm run dev
```

浏览器开发模式使用 fixture 数据，适合调试界面和可视化。

启动完整桌面模式：

```bash
npm run tauri dev
```

首次进入管理员工作区时设置本机管理员口令。管理员可以创建语料库，导入资料，等待 OCR 或原生抽取完成，查看整体审核摘要后发布。访客模式只能读取已发布版本。

## 本地知识图谱流水线

当前版本按器物条目提取属性和事件，使用本地 PP-Structure/OCR、中文 UIE、LTP、向量召回和重排模型。名称相同的纹样、时代、工艺、材质和文化提及组织为来源内概念；具体器物、地点和机构保留为独立实例。机器结果保留原文、坐标和 OCR 版本，不自动确认事实或合并实体。

PDF、页面缓存和模型权重不提交到 Git。准备本地语料后运行：

```bash
python3 scripts/prepare_kg_v2_data.py --source /private/path/volume-1.pdf
python3 scripts/download_kg_v2_models.py
npm run pipeline:reliable
```

开发界面：`http://localhost:1420/?view=localgraph`。实体匹配页默认显示概念词表，并可展开每次来源、查看原图和记录复核决定。详细说明见 [本地流水线](docs/reliable-pipeline.md)，数据目录说明见 [data/README.md](data/README.md)。

```bash
npm run test:kg
npm run build
```

## OpenCode

在 OpenCode 中完成模型授权后，管理员在工作区选择或确认：

```text
homo/gpt-6.1-terra
```

应用会先检索已发布证据，再将证据和关系信息交给 OpenCode。回答必须引用 `[1]` 形式的来源编号。模型不可用时，应用仍保留全文检索、图谱和证据浏览功能。

## 构建

```bash
npm run build
npm run tauri build -- --bundles app,dmg
```

Windows 构建使用 `nsis` bundle。GitHub Actions 的跨平台构建配置位于 `.github/workflows/desktop.yml`。

## 数据位置

桌面应用把数据库、原始文件、OCR 结果、图像和索引保存在操作系统的应用数据目录，不依赖仓库中的 `doc` 目录。

## 目录

- `src/` React 界面、检索展示和 OCR 流程
- `src-tauri/src/` Rust Core、SQLite、抽取、知识图谱和 OpenCode 适配器
- `docs/` 公开设计、用户故事和技术架构
- `doc/` 内部资料和执行状态，不参与 Git 提交

### 第一册纹样图录

访客在「关系图谱 → 纹样图录」选择纹样。箭头从器物指向纹样、时代、材质和工艺；点击关系可核对图注，「查询器物与出处」沿相同的器物实例返回带引用的答案。桌面端读取所选语料中当前已发布来源的最新完整 v2 运行，仅采用最新复核决定为“确认”的陈述。管理员可在纹样陈述的证据面板标注器物全图和纹样局部，两处选区独立于 OCR 文本框。

使用吴山编著的《中国纹样全集》第一册生成原书演示，需要 Python、Pillow 和 Poppler 的 pdftoppm。

```bash
python3 scripts/prepare_book_atlas.py /path/to/第一册.pdf
```

生成后可直接打开 `public/book-sample/index.html`。图像已嵌入该 HTML，离线可用。也可在 Vite 浏览器版选择「中国纹样全集 · 原书图版」语料。样本涵盖 PDF 第 4、7 页的两件花卉纹彩陶盆及第 5 页的两件旋纹器物。图录注明 PDF 页码、书内图版页码和图号。分期引用第 3 页的标题，彩陶器材质据器名归类。样本来自对扫描图版的核读，独立于自动抽取和桌面复核记录。生成器校验 PDF 的 SHA-256；扫描书页和生成的演示文件保留在本机。
