# 从三册 PDF 复现星图和 SQLite

从 Linux 上的新克隆开始，在仓库根目录执行。现有抽取脚本读取三册 PDF，生成 OCR、版面、图谱、SQLite 及合册星图。

## 准备

- 使用 Node.js 24、Python 3.11、uv、Tesseract 的 `chi_sim` 和 `eng` 语言包，以及 Poppler 的 `pdftoppm`。
- 放置 `source/第一册.pdf`、`source/第二册.pdf`、`source/第三册.pdf`。三册共 1,240 页，分别为 494、401、345 页。
- PaddleOCR 与 NLP 对 `tokenizers` 的版本要求不同。分别使用两个仓库内的 venv。

~~~bash
uv venv --python 3.11 .venv/rebuild-layout
uv venv --python 3.11 .venv/rebuild
uv pip install --python .venv/rebuild-layout/bin/python -r scripts/requirements-kg-v2-layout.txt
uv pip install --python .venv/rebuild/bin/python \
  --index https://download.pytorch.org/whl/cpu 'torch==2.6.0+cpu'
uv pip install --python .venv/rebuild/bin/python \
  -r scripts/requirements-kg-v2-nlp.txt -r scripts/requirements-kg-dimensions.txt

export WIKIBRIDGE_LAYOUT_MODELS="$PWD/.venv/rebuild-models/layout"
export PADDLE_PDX_CACHE_HOME="$PWD/.venv/rebuild-models/paddlex"
export HF_HOME="$PWD/.venv/rebuild-models/huggingface"
sha256sum --check source/SHA256SUMS
.venv/rebuild-layout/bin/python scripts/prepare_kg_v2_layout_models.py
.venv/rebuild/bin/python scripts/download_kg_v2_models.py
~~~

下载脚本固定模型版本。后续运行要使用同样的模型目录。已有可用解释器时，可以用 `WIKIBRIDGE_LAYOUT_PYTHON`、`WIKIBRIDGE_LTP_PYTHON` 和 `WIKIBRIDGE_DIMENSIONS_PYTHON` 指定绝对路径。

## 抽取、裁图和合库

~~~bash
bash scripts/rebuild_atlas.sh
npm run atlas -- --port 1423 --site data/local-kg/merged/site
~~~

脚本先处理三册全页 OCR、版面、字段抽取、链接、校验和入库，再补抽器类、属性和文献解释。裁图阶段组合原图、版面框和图号，并按卷页与图录 ID 绑定。第一册的四张人工裁图按 PDF 校验值和图录绑定。最后应用器物身份映射、名称材质补充、全文补抽和图录修订。自动裁图和关系作为候选保留。

如果 Linux 禁用网络命名空间，运行 `bash scripts/rebuild_atlas.sh --no-network-namespace`。该模式用模型库的离线设置读取同一份缓存。已有人工审核或额外语料时，用干净克隆重建，便于保留现有产物。

| 产物 | 位置 |
| --- | --- |
| 单册 OCR、图谱、原页 | 第一册在 `data/local-kg/`，二、三册在其 `vol2/`、`vol3/` |
| SQLite、导入的 PDF 和预览 | `data/local-kg/database/` |
| 合册网页、清单、裁图 | `data/local-kg/merged/site/` |
| 审计报告与写入前备份 | `data/local-kg/report/`、`data/local-kg/archive/` |

若要直接写入 Linux 桌面应用的数据库，在运行前显式设置 `WIKIBRIDGE_KG_DATABASE_ROOT="$HOME/.local/share/cn.wikibridge.desktop"`。单独运行旧入口时仍可用 `WIKIBRIDGE_KG_DATA` 指定当前册。

## 打包原尺寸页图

合册工作目录使用小预览。执行以下命令生成包含原尺寸页图的 ZIP 并启动解压后的站点。

~~~bash
.venv/rebuild/bin/python scripts/package_kg_share.py
unzip data/local-kg/share/wikibridge-three-volumes-original-pages.zip -d data/local-kg/share
npm run atlas -- --port 1423 --site data/local-kg/share/wikibridge-three-volumes/site
~~~

可用 `--output` 指定新 ZIP，或用 `--image-mode preview` 生成小预览版。分享时提供整包目录。原始 PDF 由使用者另行放入 `source/`。

## 检查

~~~bash
.venv/rebuild-layout/bin/python -m unittest discover -v -s scripts -p 'test_*.py'
node --test scripts/test_*.mjs
~~~

重建前，测试会标出依赖图谱或抽取产物的用例。重建后核对合册清单的三册页数、原页、裁图和 SQLite 入库结果。旧分享包的 4,063 个规范器物可作为对照。OCR 和推理结果可能随库版本和硬件变化。历史审核报告如已存在会一并读取。干净克隆使用仓库提供的六条待核记录。
