# 技术架构

## 1. 架构决策

第一版采用本地优先的桌面架构，不部署独立的远程后端服务，也不要求用户安装 Python、Go 或 Node.js 运行环境。

```text
React + TypeScript
        ↕ invoke / events
Tauri 2 + Rust Core
        ├── 文件和目录管理
        ├── OpenCode 进程管理
        ├── SQLite 与全文检索
        ├── RDF 图谱查询
        ├── 后台任务调度
        └── 跨平台系统能力
```

Tauri 的 Rust Core 承担本地后端职责。React 负责界面和交互，知识处理、文件访问、OpenCode 调用和数据存储由 Rust Core 统一管理。

## 2. 前端

前端使用 React、TypeScript 和 Vite，主要模块包括：

- user 和 admin 界面
- 语料库选择和文件导入
- 解析任务和发布状态
- RAG 问答与工具调用展示
- 证据页面和图像卡片
- RDF 关系图
- 时间轴、统计图和降维图
- 系统状态和 OpenCode 设置

开发阶段支持浏览器模式，使用模拟的 Tauri API 和本地测试数据。桌面模式通过 Tauri `invoke` 调用 Rust 命令，并通过事件接收长任务进度。

## 3. Tauri 与 Rust Core

Rust Core 负责以下能力：

### 文件和资产

- 打开文件和目录选择器
- 复制和保存原始文件
- 计算 SHA-256 和维护版本
- 管理应用数据目录
- 读取页面、文档和媒体资源

### 知识处理

- 内容单元生成
- 文本清洗和分块
- BoW、TF-IDF 和共现矩阵
- Word2Vec 相似度查询
- 三元组保存和图谱查询
- SVD 或 PCA 数据准备

### 系统进程

- 检测 OpenCode
- 启动 `opencode run --format json`
- 启动或连接 OpenCode ACP
- 读取结构化输出和错误状态
- 推送流式事件到 React

### 任务管理

长任务使用后台线程或异步任务执行，避免阻塞界面。任务状态保存为：

```text
queued
running
paused
completed
failed
cancelled
```

## 4. 本地数据存储

应用数据存放在操作系统的标准应用数据目录中，不依赖源码目录。

```text
data/
  corpora/       语料库元数据
  documents/     原始文件和版本
  pages/         页面和内容单元
  ocr/           OCR 文本
  images/        图像和图像区域
  graph/         RDF、GraphML 和导出文件
  index/         FTS、词向量和相似度索引
  logs/          处理日志和会话记录
```

### SQLite

保存用户、语料库、文件版本、内容单元、来源定位、审核状态、发布版本、任务和会话元数据。

### SQLite FTS5

提供基础全文检索和关键词检索。TF-IDF 结果可以基于同一份文档索引计算。

### RDF 图谱

优先使用 Rust 中的嵌入式 RDF 存储。图谱保存实体、关系、来源和发布版本，并提供 SPARQL 查询和 GraphML 导出。

### 向量索引

第一版使用 Word2Vec、TF-IDF 和本地向量文件完成语义检索。后续可以加入 ONNX 文本模型和图像模型，不改变上层检索接口。

## 5. 文档和 OCR 处理

### 直接解析

第一版优先处理带文字层的 PDF、DOCX、PPTX、XLSX、Markdown、HTML、TXT 和 CSV。

### 扫描资料

三册纹样资料主要是扫描页面。初始语料在项目准备阶段生成 OCR 和页面索引，运行时保存页面图像、OCR 文本和定位信息。

用户新增扫描资料时，系统支持以下路径：

- 图片和页面图像使用 Tesseract.js
- 系统已安装 Tesseract 时调用原生 OCR
- OCR 结果保留置信度和原始图像
- 低置信度内容进入 admin 发布前审核汇总

扫描资料不会在文件导入动作中同步处理整本书。admin 先看到待 OCR 状态，可以处理前几页样例，再继续剩余页面。每批页面单独提交，重复提交会按页编号去重，便于暂停和恢复。

OCR 是独立的处理模块，未来可以替换为 Node sidecar 或其他本地 OCR 引擎。

## 6. OpenCode 集成

OpenCode 由 Tauri Rust Core 启动和管理，应用不复制用户的模型密钥。

第一阶段使用：

```text
opencode run --format json
```

Rust Core 负责把问题、语料库范围和检索结果发送给 OpenCode，并把模型输出、工具调用和错误状态传回 React。

后续可以使用 ACP 和 MCP，让 OpenCode 原生调用：

```text
search_pages
query_graph
find_similar_text
find_similar_images
get_evidence
```

应用内部统一使用 `LLMBackend` 接口，因此 CLI、ACP 和其他模型后端可以逐步替换。

## 7. 可选 sidecar

主路径不依赖独立后端进程。遇到特定格式或 OCR 能力难以在 Rust 中稳定实现时，可以增加可选 Node.js sidecar：

```text
Tauri Rust Core
        ↕ local IPC
Node.js sidecar
        -> 格式解析或 OCR
```

sidecar 需要为 Windows、macOS arm64 和 macOS x64 分别打包。它只提供明确的处理接口，不改变 React、SQLite、RDF 和 RAG 的上层结构。

## 8. 跨平台策略

- 使用 Rust 标准进程和路径接口，不依赖 shell 命令拼接
- 统一使用应用数据目录保存文件和索引
- 文件选择、OpenCode 探测和进程启动使用平台适配层
- 支持 Windows x64、macOS arm64 和 macOS x64
- 使用 GitHub Actions 构建不同平台的 Tauri 安装包
- 在每个平台执行启动、文件导入、索引和 OpenCode 健康检查

## 9. 开发和构建模式

### 浏览器开发

```text
React dev server
  -> mock Tauri API
  -> fixture data
```

适合界面、图谱和 RAG 展示开发。

### 桌面开发

```text
Tauri dev
  -> React
  -> Rust Core
  -> 本地数据目录
  -> OpenCode
```

适合测试文件访问、进程管理、OCR 和完整数据流。

### 发布构建

```text
GitHub Actions
  -> macOS arm64
  -> macOS x64
  -> Windows x64
```

## 10. 首版实现顺序

1. 创建 React、Vite、TypeScript 和 Tauri 2 工程
2. 实现 Rust Core 与 React 的 `invoke` 和事件通信
3. 实现 OpenCode 检测和一次最小问答
4. 实现 SQLite 语料库、文件和版本元数据
5. 实现文本文件导入、分块和 FTS5 检索
6. 实现 TF-IDF、Word2Vec 和基础 RAG
7. 实现三元组、RDF 查询和关系图
8. 实现 admin 审核发布和 user 只读查询
9. 加入 OCR、图像检索和完整工具调用展示
10. 构建 Windows 和 macOS 安装包
