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
