# 知识模型与数据结构

## 1. 资料层级

所有输入资料先建立统一的来源层级：

```text
Corpus
  -> SourceDocument
      -> ContentUnit
          -> Block
              -> Asset
```

其中：

- `Corpus` 表示用户创建的主题语料库。
- `SourceDocument` 表示一个文件、网页快照、音频或视频。
- `ContentUnit` 表示页面、幻灯片、工作表、章节或时间片段。
- `Block` 表示段落、标题、表格、列表、图注或 OCR 区域。
- `Asset` 表示图片、表格截图、音频片段、视频关键帧或原始附件。

不同文件格式通过统一的 `ContentUnit` 和 `Block` 进入知识抽取与检索流程。

## 2. 核心实体

| 实体 | 说明 | 示例 |
| --- | --- | --- |
| `Pattern` | 具体纹样或纹样类型 | 凤鸟纹、云气纹、几何纹 |
| `Motif` | 纹样中的题材母题 | 凤鸟、龙、植物、人物 |
| `Period` | 历史时期 | 新石器时代、战国、唐 |
| `Region` | 地域、遗址或文化区域 | 楚地、中原、敦煌 |
| `Artifact` | 纹样承载的器物或载体 | 青铜器、漆器、织物、壁画 |
| `Material` | 器物或纹样使用的材料 | 铜、漆、玉、丝 |
| `Technique` | 制作或装饰技法 | 铸造、錾刻、彩绘、织绣 |
| `Composition` | 纹样的构成方式 | 对称、连续、适合、散点 |
| `Color` | 颜色或配色信息 | 红、黑、金、蓝 |
| `SourcePage` | 可追溯的页面证据 | 第二册第 46 页 |
| `ImageAsset` | 页面或图版中的图像区域 | 图版裁剪图 |

## 3. 关系类型

```text
belongsToPeriod
associatedWithRegion
decoratesArtifact
usesMaterial
usesTechnique
containsMotif
hasComposition
usesColor
similarTo
variantOf
precedes
follows
documentedOn
depictedIn
supportedBy
derivedFrom
```

## 4. 证据模型

每条知识至少保存以下字段：

```json
{
  "subject": "pattern:phoenix",
  "predicate": "belongsToPeriod",
  "object": "period:warring_states",
  "source_volume": 2,
  "source_page": 46,
  "evidence_text": "页面 OCR 或人工转录文本",
  "evidence_image": "图像资源标识",
  "extraction_method": "manual|rule|ner|model",
  "confidence": 0.92,
  "review_status": "reviewed"
}
```

知识库版本还保存发布状态：

```text
draft       自动处理完成，等待 admin 整体审核
published   已向 user 开放
archived    历史版本，保留用于追溯
```

系统保留来源和抽取置信度，不建立面向 user 的知识权威等级。检索分数只用于结果排序。

## 5. 定位信息

每种格式都保存适合人类复核的定位信息。示例包括：

```text
PDF       pdf_page=46, book_page=46
DOCX      paragraph=18, heading="纹样构成"
PPTX      slide=12, shape=5
XLSX      sheet="统计", cell="D18"
HTML      url="...", selector="article > section:nth-child(2)"
Audio     start=00:12:30, end=00:13:04
Video     timestamp=00:04:18, frame=7800
```

PDF 页码和书内页码可能不同，因此二者都要保存。图像区域使用内容单元标识加区域编号：

```text
vol2:pdf_page:46:image:03
presentation:slide:12:image:02
```

## 6. 存储层

```text
data/raw/              原始 PDF 或受控输入文件
data/pages/            页面清单和缩略图
data/ocr/              OCR 原文和清洗文本
data/annotations/      人工校验和实体关系标注
data/structured/       JSONL、CSV、JSON-LD
data/graph/            RDF、GraphML 和图数据库文件
data/index/            关键词、向量和图像索引
```

内部执行状态和临时文件继续保存在内部资料目录，公开设计文档只描述结构和接口。
