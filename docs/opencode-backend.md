# OpenCode 后端集成

## 1. 定位

OpenCode 作为本机 LLM 后端，为 RAG 系统提供模型选择、会话管理、工具调用和回答生成能力。知识库、索引、证据和可视化由本项目维护，OpenCode 负责调用这些能力并生成带来源的回答。

用户的模型账号、供应商配置和凭据继续由 OpenCode 管理。本项目不复制或导出用户的模型密钥。

## 2. 连接层级

后端适配器按以下顺序探测连接方式：

### ACP 结构化连接

优先使用 `opencode acp` 启动 Agent Client Protocol 服务。ACP 适合长期会话、流式事件、工具调用和结构化状态同步。

### 本地服务连接

当用户已经运行 OpenCode 本地服务时，应用可以连接其服务地址。服务连接需要通过 OpenCode 自身的认证机制完成，不在应用中保存长期凭据。

### CLI 兼容连接

使用 `opencode run --format json` 作为兼容路径，适合单次问答、批量抽取和健康检查。应用将请求、结构化输出、错误信息和退出状态封装为统一响应。

## 3. 安装检测

应用启动时执行轻量探测：

```text
查找 opencode 可执行文件
  -> 读取版本
  -> 检查可用模型
  -> 检查 ACP 或本地服务能力
  -> 生成后端状态
```

状态至少包括：

```text
not_found
found_but_not_configured
ready
degraded
unavailable
```

探测只调用公开命令和能力查询，不读取 OpenCode 的密钥文件，也不把完整配置内容展示给应用日志。

## 4. 安装引导

当 OpenCode 未安装时，应用显示安装向导：

1. 说明需要安装 OpenCode 的原因。
2. 展示适合当前操作系统的官方安装方式。
3. 提供打开官方安装页面和复制安装命令的操作。
4. 用户确认后才执行安装命令或交给用户手动完成。
5. 安装完成后重新检测版本、模型和连接方式。

安装向导不把“安装成功”当作“模型可用”。模型列表和一次最小请求都通过后，后端才进入 `ready` 状态。

## 5. 模型选择

应用读取 OpenCode 可用模型列表，展示模型名称、提供商、文本输入、图像输入、PDF 输入和工具调用能力。模型选择保存为项目设置，不保存供应商密钥。

项目可以提供以下默认角色：

```text
extractor       结构化信息抽取
retriever       检索结果重排序
answerer        RAG 回答生成
analyst         关系分析和结论归纳
```

不同角色可以使用不同模型，但每次回答都记录实际使用的模型标识和配置版本。

## 6. RAG 工具接入

项目向 OpenCode 暴露只读知识工具：

```text
search_pages(query, corpus_id, filters)
query_graph(query, corpus_id)
find_similar_text(query, corpus_id, top_k)
find_similar_images(asset_id, corpus_id, top_k)
get_evidence(entity_id)
get_source_locator(source_id)
```

工具可以通过项目自己的工具调用层提供，也可以注册为项目级 MCP 服务。工具返回结构化结果，包含实体、关系、证据片段、来源定位和媒体资源标识。

OpenCode 的回答提示要求：

- 只使用工具结果和用户提供的信息
- 每个事实结论附带来源定位
- 明确区分原文事实、图谱关系和分析推断
- 资料不足时返回待补充信息
- 不修改知识库原始资料

## 7. 权限边界

RAG 应用只需要 OpenCode 的文本生成、图像理解和工具调用能力。项目配置默认关闭与知识问答无关的写文件、执行任意命令和修改代码行为。

检索工具只允许读取索引和证据资源。知识库的写入由资料摄取流程负责，并通过单独的校验接口完成。

## 8. 失败处理

后端适配器将以下情况转换成可读状态：

- OpenCode 未安装
- OpenCode 已安装但没有可用模型
- OpenCode 服务未运行
- ACP 或服务连接失败
- 用户认证失效
- 模型不支持当前输入类型
- 工具调用超时
- 返回内容不是有效结构化数据

应用保留检索结果和引用信息，使模型暂时不可用时仍可以浏览知识图谱、页面证据和搜索结果。

## 9. 后端接口

应用内部不直接依赖 OpenCode 的具体命令格式，而使用统一接口：

```python
class LLMBackend(Protocol):
    def status(self) -> BackendStatus: ...
    def list_models(self) -> list[ModelInfo]: ...
    def complete(self, request: CompletionRequest) -> CompletionResponse: ...
    def stream(self, request: CompletionRequest) -> Iterator[BackendEvent]: ...
```

OpenCode 实现是其中一个适配器。未来可以接入其他本地模型、远程 API 或测试用的模拟后端，而不改变知识库和 RAG 编排层。

## 10. 当前建议

首版使用以下连接顺序：

```text
OpenCode ACP
  -> OpenCode 本地服务
  -> opencode run --format json
```

三种连接方式都使用同一个 `LLMBackend` 接口和同一套 RAG 工具。安装检测、模型探测和最小请求验证通过后，界面再开放完整问答功能。
