# 桌面 OpenCode 后端

桌面工作台在管理页检查本机 OpenCode 的路径、版本和可用模型。可选择绝对可执行文件路径和模型，开启远程生成授权。账号和供应商配置由 OpenCode 管理。

Rust 适配器从本地检索命中中整理出处，再调用 `opencode run --format json`。应用展示回答、来源和后端状态。配置错误、授权关闭和进程失败时，仍可使用本地检索。

星图的 DeepSeek 是另一项服务，通过仓库的 `.env.local` 配置。[桌面适配器](../src-tauri/src/opencode.rs) · [DeepSeek 启动](../README.md#deepseek-问答)
