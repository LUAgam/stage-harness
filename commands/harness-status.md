---
description: "查看所有 epic 的阶段进度、中断预算消耗、运行时健康度"
---

# harness-status

## CLI Bootstrap

在执行任何 `harnessctl` 命令前，先解析本地 CLI 路径：

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
```


查看当前项目所有 epic 的阶段进度、中断预算消耗、运行时健康度，以及待处理的 must_confirm 决策数量。

## 角色定义

只读状态查看器。只运行 `harnessctl` 查询命令，不修改任何状态文件，不触发任何阶段转换。

## 执行步骤

### Step 1：运行总览

```bash
$HARNESSCTL status
```

展示所有 epic 概览表格：

```
ID                             STAGE      RISK     TASKS      TITLE
────────────────────────────────────────────────────────────────────
sh-1-user-auth                 EXECUTE    medium   3/8        User Authentication
sh-2-payment-flow              PLAN       high     0/5        Payment Flow
sh-3-search-feature            DONE       low      6/6        Search Feature
```

### Step 2：每个 Epic 详情

对每个非 DONE 的 epic，展示：

```
Epic: epic-abc123 — User Authentication
─────────────────────────────────────
当前阶段   : EXECUTE
风险等级   : medium
健康状态   : OK

任务进度:
  done         : 3
  in_progress  : 1
  pending      : 2
  blocked      : 2
  total        : 8

中断预算:
  总预算   : 5
  已消耗   : 1
  剩余     : 4

运行时健康:
  连续失败次数   : 0
  drift_detected : false
  最近活跃时间   : 2026-03-31T10:23:00Z
```

若 `drift_detected = true`，以高亮展示警告。

### Step 3：待处理 must_confirm 汇总

```bash
$HARNESSCTL epic list --json
```

若有待处理的 must_confirm 决策：

```
待处理确认项（共 X 项）:
  sh-1-user-auth: 2 项 must_confirm 待处理
    - [CONF-001] 数据库选型：PostgreSQL vs MySQL？
    - [CONF-002] 认证方案：JWT vs Session？
  sh-2-payment-flow: 1 项 must_confirm 待处理
    - [CONF-003] 支付网关：Stripe vs 支付宝？

运行 /harness:clarify <epic-id> 处理确认项。
```

若无待处理项，显示：`所有 must_confirm 已处理。`

### Step 4：JIT Patch 状态摘要

```bash
$HARNESSCTL patch list --json
```

按 status 分组展示，过滤掉 archived/reverted：

```
JIT Patch 状态:
  active_epic (2):
    - patch-20260403-001 [prompt_rule] sh-1-example
    - patch-20260403-002 [assumption_rule] sh-1-example
  candidate (1):
    - patch-20260401-003 [orchestration_rule] sh-2-feature  ← 未 apply，可运行 harnessctl patch apply
  ready_for_project (1):
    - patch-20260402-004 [project_pattern]  ← 运行 harnessctl patch promote 晋升为项目规则
  project_active (1):
    - patch-20260401-001 [project_pattern]  ← 对所有新 epic 生效
```

若无任何有效 patch，显示：`无激活补丁。`

若有 `ready_for_project` 状态的 patch，高亮提示：
> 💡 有 N 个补丁已验证有效，可运行 `harnessctl patch promote <id>` 晋升为项目级规则。

若有 `consecutive_failures >= 2` 的 epic 但尚无候选 patch，提示：
> ⚠️  Epic <id> 连续失败 N 次，建议运行 `/harness:patch <id>` 进行即时诊断。

## 产物要求

无产物输出。只读查询，不写入任何文件。

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| `.harness/` 不存在 | 提示运行 `$HARNESSCTL init` 或 `/harness:start` |
| 无任何 epic | 提示运行 `/harness:start <需求描述>` 创建第一个 epic |
| `$HARNESSCTL status` 失败 | 展示原始错误信息 |
