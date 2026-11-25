# 图片与分类适配

修改前端时，以完整分享包的 `site/manifest.json` 为展示入口，连同 `site/assets/` 和 `site/annotations-v2/` 一起提供静态访问。`graphs/volN.graph.json` 是原生抽取结果，不含展示层全部裁图绑定；旧分享包也不含后来的属性补抽。

## 图片

- `detailUrl` 用于星图和列表，`imageUrl` 用于详情，`imageCandidates[].imageUrl` 用于多张独立子图，`pageUrl` 用于原页核读。自动裁图的 `detailUrl` 是缩略图，不一定是纹样局部。
- 显示裁图时同时接收 `artifact` 和 `artifact_candidate`。后者表示自动候选，不能当成没有图片。
- 所有媒体路径相对于 manifest 的实际地址解析，例如 `new URL(item.imageUrl, manifestURL).href`。不要按名称或页码拼路径，也不要假定图片全部为 JPG。
- 旧数据适配层若只将裁图字段放在 rows 或 sourceRecords，新查看器会按记录 ID 读取这些字段。规范器物、源图录、源实体通过 `canonicalArtifactId`、`sourceRecordId`、`sourceEntityId` 关联，同名不能代替 ID。

例如 `annotations-v2/vol2/p0001/crops/r01.jpg` 必须能从同一个站点请求到；只有 assets 可以访问时，整页图片正常而裁图会返回 404。

## 分类与文献属性

器物的时代、材质、纹样、器类及其他维度来自 items 和 rows。其他维度由 `src/kg-reasoner.js` 的 `EXTRA_DIMENSIONS` 定义，包括装饰材料、造型、工艺、文化归属、构图形式、装饰部位、装饰角色、出土与发现、收藏单位。字段数组与对应关系均需保留。

正文抽出的知识单独存在 `interpretations`。工艺、构图分类同时收录相关正文记载，卡片将器物数量和文献数量分开显示。正文对概念的描述不能直接挂到所有关联器物上。

`kind: symbolism` 表示象征意义，`kind: belief` 表示信仰关联；主体在 `subject.label`，属性值在 `value`，原文在 `text`，出处在 `page`、`volumePage`、`locator` 等字段。它们作为纹样属性展示，不要求在器物 rows 中出现同名关系，也不另画成意义节点。

图录直接提供“象征意义”“信仰关联”入口；纹样图谱的属性卡和器物详情可查看原文与原页。工艺、构图的正文记载同样可从对应分类进入，零件器物加若干处文献表示只有概念层的记载。

## 启动

```bash
node server/atlas-server.ts --port 1423 --site /解压目录/wikibridge-three-volumes
```

也可指定上一级解压目录或具体 site 目录。Git 仓库不包含完整图谱和图片，拉取代码后仍需提供最新数据包；运行时以终端输出的数据路径为准。不传 --site 时优先使用本机 merged/site，再查标准分享包目录和旧样本目录。
