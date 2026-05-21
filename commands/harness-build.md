---
description: "编译构建（代码感知自动推断 → 询问用户 → 执行编译 → 写 build-receipt → 失败则触发 FIX）"
argument-hint: "<epic-id>"
---

# harness-build

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

执行编译构建阶段。通过三级推断链确定编译命令（已有配置 → 代码感知自动推断 → 询问用户），执行编译，捕获结果，写 build-receipt，失败则触发 FIX 循环。

## 角色定义

BUILD 阶段 orchestrator。负责验证 VERIFY 前置产物、调度 build skill 通过三级推断链确定并执行编译命令、根据结果推进或回流。不直接执行编译命令——编译由 build skill 负责。

## 前置检查

**模式判定**：先读环境变量 `HARNESS_SKIP_VERIFY_GATE`：

```bash
if [ "${HARNESS_SKIP_VERIFY_GATE:-0}" = "1" ]; then
  # ── auto 模式：VERIFY 已被自治循环跳过，改查 EXECUTE 产物 ──
  RECEIPTS_DIR=".harness/features/<epic-id>/receipts"
  if [ ! -d "$RECEIPTS_DIR" ] || [ -z "$(ls -A "$RECEIPTS_DIR" 2>/dev/null)" ]; then
    echo "❌ EXECUTE 产物缺失：$RECEIPTS_DIR 不存在或为空" >&2
    echo "   提示：先完成 /harness:work <epic-id>" >&2
    exit 1
  fi
  # 校验 receipt 数量 ≥ task 总数，防止部分完成就进入编译
  TASK_COUNT=$($HARNESSCTL task list <epic-id> --count)
  RECEIPT_COUNT=$(ls -1 "$RECEIPTS_DIR" | wc -l)
  if [ "$RECEIPT_COUNT" -lt "$TASK_COUNT" ]; then
    echo "❌ EXECUTE 未完成：receipts $RECEIPT_COUNT/$TASK_COUNT" >&2
    echo "   提示：先完成剩余 task 再进入编译" >&2
    exit 1
  fi
  echo "⚠️  HARNESS_SKIP_VERIFY_GATE=1（auto 模式）：跳过 VERIFY 产物校验"
else
  # ── 手动模式：严格校验 VERIFY 阶段产物 ──
  $HARNESSCTL stage-gate check VERIFY --epic-id <epic-id>
fi
```

**手动模式必须满足**：
- `verification.json` 存在且 `acceptance_council` 为 `PASS` 或 `CONDITIONAL_PASS`
- 无未解决的 CRITICAL 问题

**auto 模式必须满足**：
- `.harness/features/<epic-id>/receipts/` 目录存在且非空（EXECUTE 阶段已产出 task receipts）

若手动模式检查失败，提示先完成 `/stage-harness:harness-review <epic-id>`，终止。
若 auto 模式检查失败，提示先完成 `/harness:work <epic-id>`，终止。

## 注册调度来源

前置检查通过后，立即注册 dispatch 记录：

```bash
$HARNESSCTL dispatch register <epic-id> BUILD --via=skill:harness-build
```

## 读取/推断编译命令

**REQUIRED SKILL:** Use `stage-harness:build` skill

build skill 内部通过三级推断链确定编译命令：

1. **Level 1 — 读取已有配置**：读取 `project-profile.yaml` 中的 `build_command`，非空则直接使用
2. **Level 2 — 代码感知自动推断**：扫描项目根目录特征文件（`package.json` / `go.mod` / `pom.xml` / `build.gradle` / `Cargo.toml` / `requirements.txt` / `setup.py` / `pyproject.toml` / `Makefile` / `Dockerfile` 等），按优先级推断命令，推断成功后写回 `project-profile.yaml` 持久化
3. **Level 3 — 询问用户**：前两级均失败时，展示已扫描特征，消耗 1 次中断预算向用户提问；用户可提供命令或选择跳过编译

向 skill 传入：
- `epic-id`
- `project_root`：项目根目录路径（用于特征文件扫描）

## 质量门禁探测（Quality Gate Detection）

编译命令确定并执行成功后（exit_code = 0），**必须**额外执行质量门禁探测。质量门禁的目的是发现"编译通过但运行时会被项目自身的 lint/format 检查拦截"的问题。

**核心原则**：harness-build 不定义什么是"好代码"，它只发现并执行**项目自己定义的质量门禁**。

### 探测逻辑（通用，语言无关）

按优先级依次探测，取第一个命中的级别：

**Level 1 — 项目显式声明的 check/lint 命令**

扫描项目的包管理器/构建系统配置中是否定义了检查类命令：

| 配置文件 | 探测的命令名（按优先级） | 执行方式 |
|---------|------------------------|---------|
| `package.json` scripts | `check` > `lint` > `lint:check` > `verify` > `typecheck` | `npm run <script>` 或 `yarn <script>` |
| `Makefile` / `GNUmakefile` | `check` > `lint` > `verify` target | `make <target>` |
| `Cargo.toml` | 存在即视为有 clippy | `cargo clippy --all-targets -- -D warnings` |
| `pyproject.toml` [tool.ruff] / [tool.flake8] / [tool.pylint] | 检测工具配置存在性 | `ruff check` > `flake8` > `pylint` |
| `composer.json` scripts | `check` > `lint` > `phpstan` | `composer run <script>` |
| `build.gradle` / `build.gradle.kts` | `checkstyleMain` / `spotbugsMain` / `ktlintCheck` | `./gradlew <task>` |
| `pom.xml` | checkstyle / spotbugs plugin 存在性 | `mvn checkstyle:check` |
| `.golangci.yml` / `.golangci.yaml` | 存在即视为有 golangci-lint | `golangci-lint run` |

**Level 2 — 运行时门禁配置探测**

Level 1 未命中时，检测项目是否配置了**运行时会执行的质量检查**（dev server / bundler 在加载时触发的检查）：

扫描 bundler/dev-server 配置文件（`vite.config.*`、`webpack.config.*`、`next.config.*`、`nuxt.config.*`、`angular.json` 等）中是否引入了 lint 插件：

| 检测到的插件/配置 | 推断的 CLI 命令 |
|-----------------|---------------|
| `vite-plugin-eslint` / `@nabla/vite-plugin-eslint` | `npx eslint <changed_files>` |
| `eslint-webpack-plugin` / `eslint-loader` | `npx eslint <changed_files>` |
| `stylelint-webpack-plugin` | `npx stylelint <changed_files>` |
| `@angular-eslint` | `npx ng lint` |
| `nuxt/eslint` module | `npx eslint <changed_files>` |

**Level 3 — 无门禁**

Level 1 和 Level 2 均未命中 → 不追加额外检查，quality_gate 状态记为 `SKIPPED`。

### 执行作用域

- **优先对本次 epic 修改的文件执行**：从 receipts 的 `files_changed` 聚合所有变更文件路径
- 若 lint 工具不支持指定文件（如 `make lint`、`cargo clippy`），则全量执行但在 receipt 中标注 `scope: full_project`
- 若支持指定文件（如 `eslint`、`ruff`、`golangci-lint`），则仅传入变更文件，标注 `scope: changed_files`

### 失败处理

- 质量门禁失败 → 整体 BUILD 状态为 `FAIL`（与编译失败同级）→ 触发 FIX 回流
- FIX 阶段负责修复（可以 auto-fix），BUILD 阶段只检测不修复

### 不做的事

- 不安装任何 lint 工具（项目没有配置就不执行）
- 不自动修复（`--fix`）——BUILD 只报告问题，FIX 负责修复
- 不对项目未配置的检查做假设（没有 lint 配置就不跑 lint）
- 不硬编码任何特定的 lint 规则

## 产物要求

| 产物 | 路径 |
|------|------|
| Build Receipt | `.harness/features/<epic-id>/build-receipt.json` |

`build-receipt.json` 必须包含：
- `epic_id`
- `build_command`：实际执行的命令
- `status`：`PASS`、`FAIL` 或 `SKIPPED`（编译 + 质量门禁均通过才为 PASS）
- `exit_code`：编译进程退出码
- `stdout`：编译输出（截断至最后 200 行）
- `stderr`：错误输出（截断至最后 100 行）
- `started_at` / `completed_at`：ISO 时间戳
- `error_summary`：失败时的错误摘要（PASS 时为空字符串）
- `quality_gate`（对象，质量门禁探测结果）：
  - `detected_level`：`L1` / `L2` / `L3`（对应探测逻辑的三个级别）
  - `tool_source`：门禁来源描述（如 `package.json scripts.lint`、`vite.config.ts vite-plugin-eslint`、`none`）
  - `command`：实际执行的质量检查命令（L3 时为空字符串）
  - `scope`：`changed_files` / `full_project`（执行作用域）
  - `status`：`PASS` / `FAIL` / `SKIPPED`（L3 无门禁时为 SKIPPED）
  - `errors`：失败时的错误列表（PASS/SKIPPED 时为空数组）
- `notes`（可选对象，推荐填写）：
  - `project_type`：推断出的项目类型（如 `Python / Flask`、`Node / Next.js`、`Go / Module`）
  - `build_tool`：实际使用的构建工具链（如 `pip + Makefile`、`npm`、`go build`）
  - `inference_level`：命令来源（`Level 1 (config)`、`Level 2 (auto-detected from <特征文件>)`、`Level 3 (user-provided)`）
  - `changed_files_checked`：本次编译校验涉及的变更文件列表
  - `full_ast_scan`：语法级全量扫描结果（如 `PASS — all .py files parse without SyntaxError`）
  - `pre_existing_warnings`：编译过程中发现的非本次引入的预存警告

## 出口条件

### 编译成功且质量门禁通过（status = PASS）

编译 exit_code = 0 **且** quality_gate.status 为 `PASS` 或 `SKIPPED`：

```bash
$HARNESSCTL state transition <epic-id> DEPLOY
```

提示下一步：`/stage-harness:harness-deploy <epic-id>`

### 编译失败或质量门禁失败（status = FAIL）

以下任一条件触发 FAIL：
- 编译 exit_code ≠ 0
- quality_gate.status = `FAIL`

处理流程：
1. 将错误信息写入 build-receipt.json（区分 `error_summary` 来自编译还是质量门禁）
2. 输出错误摘要，标注失败原因和来源
3. 触发 FIX 循环：

```bash
$HARNESSCTL state transition <epic-id> FIX
```

FIX 阶段完成后，重新执行 `/stage-harness:harness-build <epic-id>`。

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| VERIFY 门禁未通过（手动模式） | 终止，提示先完成审查阶段 |
| EXECUTE 产物缺失（auto 跳过模式） | 终止，提示先完成 `/harness:work` |
| 三级推断均失败且预算耗尽 | 终止，提示手动配置 `build_command` |
| 用户选择跳过编译 | 写 SKIPPED receipt，推进到 DEPLOY |
| 编译命令不存在（command not found） | 写 FAIL receipt，提示检查运行环境 |
| 编译超时（> 30 分钟） | 写 FAIL receipt，标注 timeout，触发 FIX |
| 编译失败 | 写 FAIL receipt（含错误分类），触发 FIX 循环 |
| 质量门禁失败（lint/format error） | 写 FAIL receipt（quality_gate.errors 含具体错误），触发 FIX 循环 |
| 质量门禁工具不可执行（已配置但未安装） | 写 FAIL receipt，error_summary 标注工具缺失，触发 FIX |

## 与其他阶段的关系

```
手动模式：
  VERIFY (PASS) → /stage-harness:harness-build
                 → 编译成功 → DEPLOY
                 → 编译失败 → FIX → /stage-harness:harness-build（重试）

auto 模式（low/medium 风险）：
  EXECUTE (all done) → state 经 VERIFY → BUILD（HARNESS_SKIP_VERIFY_GATE=1）
                       → 编译成功 → DEPLOY
                       → 编译失败 → FIX → /stage-harness:harness-build（重试）
```
