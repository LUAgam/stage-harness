# Quick Start

> 本文档已整合到新的文档体系中，请参阅：

- **[README.md](./README.md)** — 插件总览与介绍
- **[usage.md](./usage.md)** — 完整使用指南
- **[architecture.md](./architecture.md)** — 架构与实现细节

## 最快上手

1. 使用 Claude CLI 加载本仓库为插件（路径换成本机克隆目录）：

   ```bash
   claude --plugin-dir /opt/agent-delivery-claude/stage-harness
   ```

2. 在被开发项目根目录设置 `HARNESSCTL`（与 `--plugin-dir` 指向同一克隆时推荐绝对路径），编排说明见 `commands/harness-start.md`。

3. 在对话中启动新 Epic：

   ```text
   /stage-harness:harness-start 你的需求描述
   ```

4. 自治与状态：

   ```text
   /stage-harness:harness-auto
   /stage-harness:harness-status
   ```
