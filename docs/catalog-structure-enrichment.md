# 图录结构补充

规则按器物名称区分材质、器类、造型、工艺和装饰材料。例如「青铜象尊」拆为青铜、尊和象形。第一册图版分节标题在 PDF 第 3–8 页与第 117–270 页内提供年代候选，每条关联保留标题出处与适用范围。

替代陈述保留在源图谱中并标为 `superseded`。展示和查询使用生效投影。文献解释保留原书给出的时代、用途与推测语气。

历史运行新增 1,764 条候选并替代 20 条分类，星图增加 1,731 条来源关系。这些数字描述覆盖变化，精确率和召回率需独立标注评估。

~~~bash
.venv/rebuild/bin/python scripts/enrich_catalog_structure.py --apply
~~~

省略 `--apply` 可试算。应用报告在 `data/local-kg/report/catalog-structure-applied.json`。[三册复现](reliable-pipeline.md)
