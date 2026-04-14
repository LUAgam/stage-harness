---
description: "从模糊需求创建 Epic 并停在 CLARIFY 起点"
argument-hint: "<模糊需求描述>"
---

# harness-start

目标：稳定创建 Epic 并把项目带到 `CLARIFY` 起点。

根目录约定：
- 本命令遵循 `harnessctl start` 默认 bootstrap root 语义。
- 优先使用已有 `.harness/`，否则使用 git root，否则回退到当前执行目录。
- 若你希望在别的目录初始化 `.harness/`，应先切换到目标项目目录再运行本命令。

硬性要求：
- **第一动作必须是执行下面唯一的 Bash 块。**
- **禁止**在本命令里继续串行触发 `harness:clarify` / `harness:spec` / `harness:plan`。
- **禁止**把“Run CLARIFY workflow”之类的后续阶段任务放进本命令。
- **一旦 `harnessctl start` 成功返回，立即停止。不得再调用任何 `Skill` / `Bash` / `Read` / 其他工具。**
- **如果在 `harnessctl start` 成功后又触发了额外工具调用，则本命令视为失败。**
- 本命令成功标准只有一个：`harnessctl start` 跑完并输出新建 epic 的下一步命令。

## CLI Bootstrap

立刻执行：

```bash
if [ -z "${HARNESSCTL:-}" ]; then
  candidates=(
    "./stage-harness/scripts/harnessctl"
    "../stage-harness/scripts/harnessctl"
    "$(git rev-parse --show-toplevel 2>/dev/null)/stage-harness/scripts/harnessctl"
  )

  for candidate in "${candidates[@]}"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      HARNESSCTL="$candidate"
      break
    fi
  done
fi

test -n "${HARNESSCTL:-}" && test -x "$HARNESSCTL" || {
  echo "harnessctl not found. Set HARNESSCTL=/abs/path/to/stage-harness/scripts/harnessctl" >&2
  exit 1
}

"$HARNESSCTL" start "$ARGUMENTS"
```

完成后只做两件事：
- 展示 `harnessctl start` 输出里的 `epic_id`、`next_step`、`manual_step`
- 结束当前命令，不再自动进入 CLARIFY
- 直接结束当前 turn；**不要**分析现有 active epic，不要建议立即运行 `/harness:clarify`，不要自动恢复任何旧流程

后续约定：
- 想继续自动推进：运行 `next_step`，通常是 `/harness:auto <epic-id>`
- 想手动逐阶段推进：运行 `manual_step`，通常是 `/harness:clarify <epic-id>`
