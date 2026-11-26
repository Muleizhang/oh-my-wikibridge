# 星图数据与图片

以完整站点的 `manifest.json` 为数据入口。同目录提供 `assets/` 和 `annotations-v2/`。更换数据后重启 Node 服务。

| 字段 | 用途 |
| --- | --- |
| `detailUrl` | 星图与列表缩略图 |
| `imageUrl` | 器物详情，可为单张裁图或组合图 |
| `imageCandidates[].imageUrl` | 组合图中的独立子图 |
| `pageUrl` | 原书整页 |
| `captionUrl` | 图注截图，可为空 |

图片地址用 `new URL(path, manifestURL)` 解析。裁图包含 `artifact` 与 `artifact_candidate` 两种状态。没有绑定裁图的记录使用整页。关系、源图录和规范器物通过 `sourceRecordId`、`sourceEntityId`、`canonicalArtifactId` 关联。

器物分类读取 `items` 和 `rows`。工艺、构图的文献记载与器物分别计数。象征意义和信仰关联读取 `interpretations`，展示主体、解释、原文和卷页。

[启动和复现](../README.md)
