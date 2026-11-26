# 名称材质补充

`catalog-name-material-v1` 从图录的明确材质和器物主体结构补充 `made_of`。例如「战国铜鉴」抽取铜，「鹳鸟衔鱼石斧纹彩陶缸」抽取陶。名称中的纹样题材、表面工艺与器物材质分别处理。

每条候选指向原始 OCR 文本区间，保留原字形和材质粒度。历史运行新增 500 条候选，其中 494 条进入合册展示。试算和应用分别使用以下命令。

~~~bash
.venv/rebuild/bin/python scripts/enrich_name_materials.py
.venv/rebuild/bin/python scripts/enrich_name_materials.py --apply
~~~

报告在 `data/local-kg/report/name-material-enrichment.json`。[三册复现](reliable-pipeline.md)
