---
description: "MMR 快速修复流程（方案 -> 三模型方案复审 -> 执行 -> 三模型代码复审）"
argument-hint: "<需求或 bug 描述>"
---

# mmr

Claude Code 版 MMR 入口命令。用于不需要完整 `.harness` Epic 状态机、但需要“先方案、再三模型方案复审、再执行、最后三模型代码复审”的快速修复或小型改动。

## 适用场景

- 修复明确 bug。
- 小范围功能调整。
- 用户要求“一次性完成修复和 review，不要频繁交互”。
- 不希望启动完整 `/stage-harness:harness-start` 到 `/stage-harness:harness-done` 流水线，但仍希望有方案和复审约束。

## 不适用场景

- 大型跨模块重构。
- 需要正式需求澄清、规格、任务 DAG、验收议会的 Epic。
- 高风险数据迁移、权限模型重做、核心协议变更。
- 缺少关键上下文，继续执行会明显增加误改概率。

这些场景应使用完整 stage-harness 流程。

## 角色映射

| 阶段 | Claude Code agent | 配置模型 | 责任 |
|------|-------------------|----------|------|
| 方案制定 | `mmr-planner` | `inherit` | 输出最小可执行方案 |
| 方案复审 1 | `mmr-plan-reviewer-gpt-5-5` | `gpt-5.5` | 正确性、可执行性、回归风险 |
| 方案复审 2 | `mmr-plan-reviewer-gemini-3-1-pro-preview` | `google/gemini-3.1-pro-preview` | 边界、契约、一致性、隐性风险 |
| 方案复审 3 | `mmr-plan-reviewer-claude-opus-4-6-thinking` | `claude-opus-4.6-thinking` | 深度推理、系统性风险、维护成本 |
| 执行落地 | `mmr-executor` | `inherit` | 按已确认方案做最小必要改动 |
| 代码复审 1 | `mmr-code-reviewer-gpt-5-5` | `gpt-5.5` | 逻辑正确性、回归风险、测试缺口 |
| 代码复审 2 | `mmr-code-reviewer-gemini-3-1-pro-preview` | `google/gemini-3.1-pro-preview` | 边界、契约、一致性、错误处理 |
| 代码复审 3 | `mmr-code-reviewer-claude-opus-4-6-thinking` | `claude-opus-4.6-thinking` | 系统一致性、根因闭环、长期维护风险 |

说明：三模型 reviewer 的 frontmatter 已直接配置上述 `model` 值；运行环境需要能识别这些模型标识。

## 执行流程

### Step 1：主会话收集最小上下文

在调用 agent 前，先收集必要上下文：

```bash
git status --short
git diff --stat
```

根据用户输入和当前仓库，读取与问题最相关的文件。不要全仓无边界扫描。

### Step 2：调用 `mmr-planner`

向 `mmr-planner` 传入：
- 用户需求或 bug 描述：`$ARGUMENTS`
- 已收集的相关上下文
- 当前 git 状态摘要

要求其输出可执行方案、影响范围、风险、回滚点和验证方案。

### Step 3：调用三模型方案复审

依次调用：
- `mmr-plan-reviewer-gpt-5-5`
- `mmr-plan-reviewer-gemini-3-1-pro-preview`
- `mmr-plan-reviewer-claude-opus-4-6-thinking`

每个方案复审 agent 都传入：
- 用户需求
- `mmr-planner` 输出
- 主会话认为重要的上下文

如果任一方案复审发现 P0 且无法小范围收敛，停止并向用户说明阻塞。若只有 P1/P2，主会话应合并三份复审意见，将必须修正项并入最终执行提示后继续推进。

### Step 4：调用 `mmr-executor`

仅在方案无 P0 阻塞时调用。传入：
- 用户需求
- 最终方案
- 三模型方案复审结论
- 明确的范围边界和验证要求

执行 agent 只能按方案做最小必要改动。执行完成后，主会话读取 `git diff --stat` 和必要 diff，为复审准备输入。

### Step 5：调用三模型代码复审

依次调用：
- `mmr-code-reviewer-gpt-5-5`
- `mmr-code-reviewer-gemini-3-1-pro-preview`
- `mmr-code-reviewer-claude-opus-4-6-thinking`

每个代码复审 agent 都传入：
- 用户需求
- 最终方案
- 三模型方案复审结论
- 执行摘要
- 本次 diff
- 校验结果
- 前序代码复审结论（如已完成）

要求三份代码复审分别覆盖正确性、边界契约、系统性风险。若任一复审返回 P0/P1，主会话应汇总风险并说明是否需要再次执行修复。

### Step 6：最终汇总

最终回复必须包含：

```markdown
## 问题理解
## 根因分析
## 最终修复方案
## 实际改动文件
## 校验结果
## GPT-5.5 方案复审结论
## Gemini 方案复审结论
## Claude 方案复审结论
## GPT-5.5 代码复审结论
## Gemini 代码复审结论
## Claude 代码复审结论
## 最终风险与建议
## 是否建议提交
```

## 中途暂停条件

只有以下情况允许中途停止并请求用户确认：

1. 方案复审发现 P0 风险，且无法在小范围内收敛。
2. 执行阶段遇到高风险阻塞，需要明显扩大改动范围。
3. 需要删除、重构、迁移核心逻辑，且影响面较大。
4. 缺少关键上下文，继续执行会明显增加误改概率。
5. 测试、构建、运行结果表明修复方向可能错误。

其余情况默认继续跑完整个 MMR 流程，最后一次性汇总。
