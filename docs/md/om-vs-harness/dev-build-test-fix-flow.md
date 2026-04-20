# Stage-Harness: 开发、编译、测试、修复流程梳理

这份文档只聚焦一条主线：当前插件里，需求进入后是如何推进到代码开发、编译/测试校验、审查、修复，再回到验收通过的。

## 一句话结论

Stage-Harness 当前更像一个"研发流程编排器"：

- 它强约束了阶段、产物、门禁、回执、审查和修复回路。
- 它没有把所有项目的 build/test 命令硬编码到 `harnessctl.py` 里，而是通过命令文档和 skill 契约要求在对应阶段执行项目自己的测试/构建命令。

## 整体状态机

```text
IDEA -> CLARIFY -> SPEC -> PLAN -> EXECUTE -> VERIFY -> DONE
                                ^          |
                                |          v
                                +--- FIX <-+
```

其中和"开发 + 编译/测试 + 修复"最相关的是：

- `PLAN`
- `EXECUTE`
- `VERIFY`
- `FIX`

## 分层理解

这套流程不是只靠一个脚本驱动，而是三层一起工作：

### 1. 控制层

核心文件：`scripts/harnessctl.py`

职责：

- 管理 `.harness/` 目录
- 创建 epic / task
- 维护状态机
- 执行 `stage-gate check`
- 执行 `guard check`
- 写入 `receipt`
- 提供 `setup / doctor / repair`

### 2. 编排层

核心目录：`commands/`

职责：

- 定义每个 slash 命令要推进哪个阶段
- 约定每个阶段的输入、输出、停止条件和下一步

和本主题最相关的文件：

- `commands/harness-work.md`
- `commands/harness-review.md`
- `commands/harness-fix.md`
- `commands/harness-auto.md`

### 3. 执行约束层

核心目录：`skills/`

职责：

- 把阶段里的动作写成更细的执行规范
- 明确什么时候要跑测试、什么时候要做 smoke、什么时候必须回流 PLAN/SPEC

和本主题最相关的文件：

- `skills/work/SKILL.md`
- `skills/review/SKILL.md`
- `skills/plan/SKILL.md`

## 0. 插件自身的启动、自检、修复

在进入业务开发前，插件先有一层"插件运行环境"自检：

### `setup`

作用：

- 修脚本执行权限
- 输出推荐的 `HARNESSCTL`
- 输出推荐的 `claude --plugin-dir`
- 可选初始化目标项目的 `.harness/`

说明：

- `setup --init-project` 会在目标项目根目录初始化 `.harness/`
- 已初始化时会跳过，不重复破坏

### `doctor`

作用：

- 检查插件根目录
- 检查项目目录
- 检查 install-state

说明：

- 若缺少 manifests，会降级到 `recorded-only` 模式，而不是直接报错退出

### `repair`

作用：

- 修复插件脚本权限
- 调 install lifecycle repair

说明：

- 默认是 dry-run
- 只有 `repair --apply` 才真正落盘修复

注意：这里的 `repair` 修的是插件环境，不是业务代码问题。

## 1. 从需求进入开发主线

### Step 1: `harness-start`

入口命令：

```bash
/stage-harness:harness-start <需求描述>
```

底层对应：

```bash
harnessctl start "<需求>"
```

做的事情：

- 若目标项目还没有 `.harness/`，先初始化
- 自动检测项目画像
- 创建 epic
- 初始化 `state.json`
- 把当前阶段置为 `CLARIFY`

产物：

- `.harness/config.json`
- `.harness/project-profile.yaml`
- `.harness/epics/<epic-id>.json`
- `.harness/features/<epic-id>/state.json`

### Step 2: CLARIFY

目标不是写代码，而是把模糊需求整理成可执行问题。

会产出：

- `domain-frame.json`
- `generated-scenarios.json`
- `scenario-coverage.json`
- `requirements-draft.md`
- `challenge-report.md`
- `clarification-notes.md`
- `impact-scan.md`
- `surface-routing.json`
- `unknowns-ledger.json`
- `decision-bundle.json`
- `decision-packet.json`

这一阶段的结果会直接影响后面的：

- 改哪些代码
- 测哪些场景
- 哪些地方要重点 review

### Step 3: SPEC

把澄清结果转成规格说明。

核心产物：

- `.harness/specs/<epic-id>.md`
- `spec-council-notes.md`

### Step 4: PLAN

这是进入开发前的最后一关。

核心动作：

- 基于 spec 拆 task
- 生成任务 DAG
- 建立 `coverage-matrix.json`
- 做计划审查

关键点：

- 每个 unknown/risk 理论上都要映射到 task 或显式落入 `unmapped_risks`
- EXECUTE 不是自由发挥，必须按 PLAN 的 task 来做

核心产物：

- `bridge-spec.md`
- `coverage-matrix.json`
- `.harness/tasks/*.json`

## 2. 开发与编译/测试：EXECUTE

入口命令：

```bash
/stage-harness:harness-work <epic-id 或 task-id>
```

### 前置门禁

执行前先检查：

```bash
$HARNESSCTL stage-gate check PLAN --epic-id <epic-id>
```

至少要求：

- 已有 task 文件
- 已有 `coverage-matrix.json`

### 单个 task 的 5 Phase 内循环

`EXECUTE` 的真实工作被定义成固定五步：

#### Phase 1: Re-anchor

重新加载上下文：

- 读取 task 详情
- 读取 epic 当前状态
- 看 git 状态
- 看最近提交
- 回读 memory

目标：

- 确认当前任务范围
- 锁定当前基线提交

#### Phase 2: Preflight

进入实现前先验证：

- 前置 task 是否已完成
- 工作区是否干净
- 基线测试是否通过
- 当前 task 是否仍在 `surface-routing.json` 的范围内

这里已经出现了"测试"要求。文档里没有把命令写死，而是使用：

```bash
<project-test-command>
```

也就是：

- 前端项目可能是 `npm test`
- Python 项目可能是 `pytest`
- Go 项目可能是 `go test ./...`
- 其他项目用自己的测试命令

#### Phase 3: TDD

严格要求按 TDD 走：

1. RED: 先写失败测试
2. GREEN: 写最小实现让测试通过
3. IMPROVE: 重构并确认测试仍通过

如果在实现过程中发现问题超出当前 task 范围，不允许静默顺手扩写，而要分类：

- `local_fix`: 当前 task 内可处理
- `plan_patch`: 需要回流 PLAN
- `spec_patch`: 需要回流 SPEC

#### Phase 4: Smoke

做 task 级最小可运行验证。

检查点包括：

- 相关测试通过
- evidence 文件存在
- 没有新增编译/类型错误
- 证据完整

这一步就是"编译/类型检查/最小验证"的落点之一。

如果 smoke 连续失败 3 次：

- 自动 triage
- 标记任务阻断
- 停止继续推进

#### Phase 5: Commit + Receipt

完成后要求：

- 提交当前 task 相关变更
- 调用 `harnessctl receipt write`
- 把 task 状态标成 `done`

回执默认写到：

- `.harness/features/<epic-id>/receipts/<task-id>.json`

回执会记录：

- `task_id`
- `epic_id`
- `base_commit`
- `head_commit`
- `preflight`
- `smoke.passed`
- 时间戳

### EXECUTE 阶段的本质

这一步不是"改完代码就算了"，而是要求每个 task 都有：

- 代码改动
- 测试证据
- smoke 结果
- receipt

它把开发过程变成了可审计的执行链。

## 3. 审查与回归测试：VERIFY

入口命令：

```bash
/stage-harness:harness-review <epic-id>
```

### 前置门禁

执行前先检查：

```bash
$HARNESSCTL stage-gate check EXECUTE --epic-id <epic-id>
```

要求至少满足：

- `receipts/` 非空
- task 不能还停在未处理状态

### VERIFY 的 7 个动作

#### 1. 汇总 receipts

先把 EXECUTE 阶段所有 task 的 receipts 收齐。

如果缺 receipt，直接阻断，不进入后续 review。

#### 2. 并行技术 review

并行角色通常包括：

- `code-reviewer`
- `logic-reviewer`
- `test-reviewer`

它们会结合：

- spec
- receipts
- `domain-frame.json`
- `generated-scenarios.json`
- `scenario-coverage.json`

来判断：

- 代码是否符合规格
- 高风险场景是否真的被实现和测试覆盖

#### 3. spec compliance 审查

由 `runtime-auditor` 检查：

- 实现是否偏离 spec
- 是否出现 undocumented drift

#### 4. 安全审查

由 `security-reviewer` 检查安全问题。

#### 5. 对抗式补盲

尝试找出前面 reviewer 漏掉的风险，尤其是：

- 边界条件
- 未测路径
- 隐含逻辑缺口

#### 6. 验收议会

执行 acceptance council，核心成员包括：

- code-reviewer
- logic-reviewer
- security-reviewer
- test-reviewer
- runtime-auditor

议会裁决决定：

- `PASS`
- `CONDITIONAL_PASS`
- `REJECTED`

#### 7. Stage Smoke

这一层要求跑更接近全量的回归验证。

文档要求的是：

```bash
<project-test-command>
```

并同时确认：

- 所有 receipts 存在
- 所有 receipt 的 smoke 为通过

### VERIFY 产物

核心产物：

- `verification.json`
- `councils/verdict-acceptance_council.json`
- `review-summary.md`

### VERIFY 门禁

`stage-gate check VERIFY` 会检查：

- `verification.json` 是否存在
- `code_review / logic_review / test_review / security / spec_compliance` 是否有 `FAIL`
- 是否还有 `critical_issues`
- `acceptance_council` 或 `council_verdict` 是否为可接受状态

所以 VERIFY 本质是：

- 代码审查
- 测试审查
- 规格对齐
- 安全审查
- 全量验证

五者合一，而不是简单"跑一遍测试"。

## 4. 修复闭环：FIX

入口命令：

```bash
/stage-harness:harness-fix <epic-id>
```

触发条件通常是：

- `VERIFY` 被拒绝
- `verification.json` 里存在 `critical_issues`

### FIX 的处理步骤

#### Step 1: 读取问题清单

从 `verification.json` 提取：

- `critical_issues`
- `high_issues`
- reviewer 详细意见

#### Step 2: 创建修复 task

对每个关键问题创建修复任务。

#### Step 3: 修复执行

修复仍然走 `work` skill，但会带 `mode=fix` 约束：

- 只修和问题相关的最小范围
- 不允许顺手重构或扩大改动
- 修完仍要写 receipt

#### Step 4: 写修复说明

产物：

- `.harness/features/<epic-id>/fix-notes.md`

它记录：

- 修了哪些 CRITICAL 问题
- 修复方案是什么
- 改动范围边界在哪里

#### Step 5: 回到 VERIFY

修完后状态回切到 `VERIFY`，重新跑审查。

所以闭环是：

```text
VERIFY(REJECTED) -> FIX -> VERIFY -> 通过后 DONE
```

### FIX 的核心价值

它把"修 bug"从一次随手修改，变成：

- 有来源的问题清单
- 有修复任务
- 有修复说明
- 有重新验证

## 5. 自治模式如何串起整条链

入口命令：

```bash
/stage-harness:harness-auto <epic-id>
```

自治模式做的事情不是自己发明流程，而是循环：

1. `guard check`
2. `state next`
3. 调用当前阶段对应命令
4. 检查是否需要暂停或停止

阶段映射大致是：

- `run_clarify` -> `/harness:clarify`
- `run_spec` -> `/harness:spec`
- `run_plan` -> `/harness:plan`
- `run_execute` -> `/harness:work`
- `run_verify` -> `/harness:review`
- `run_done` -> `/harness:done`

停止条件包括：

- `must_confirm` 未处理
- 安全审查失败
- 同一 task 连续失败 3 次
- stage smoke 失败
- 中断预算耗尽

所以 auto 模式只是把同一条状态机自动推进，不会绕开门禁。

## 6. 当前实现里"已落地"与"约定驱动"的边界

### 已落地得比较实

- 状态机
- Epic / Task / Receipt 管理
- `.harness/` 目录结构
- `stage-gate check`
- `guard check`
- `setup / doctor / repair`
- VERIFY / FIX 回路
- trace / audit / hook 拦截

### 仍然偏约定驱动

- 具体 build/test/compile 命令自动识别
- 不同技术栈下统一测试命令的适配
- work/review 阶段对真实构建系统的强绑定执行

文档里反复出现的是：

```bash
<project-test-command>
```

这说明当前插件已经明确要求"要测试、要 smoke、要回归、要看编译/类型错误"，但真正执行什么命令，仍由目标项目栈决定。

## 7. 最终理解

如果只看"代码开发 + 编译 + 测试 + 修复"，可以把当前插件理解成下面这条链：

```text
PLAN
  -> 拆任务、建覆盖矩阵
  -> EXECUTE
     -> preflight 跑基线测试
     -> TDD 写实现
     -> smoke 校验测试/证据/编译类型错误
     -> receipt 落盘
  -> VERIFY
     -> 并行 review
     -> spec compliance
     -> security review
     -> 全量回归/Stage Smoke
     -> 生成 verification.json
  -> FIX
     -> 读取 verification.json
     -> 最小范围修复
     -> fix-notes.md
     -> 回到 VERIFY
  -> DONE
```

## 8. 相关文件索引

### 核心实现

- `scripts/harnessctl.py`
- `scripts/verify-artifacts.sh`

### 阶段编排

- `commands/harness-start.md`
- `commands/harness-work.md`
- `commands/harness-review.md`
- `commands/harness-fix.md`
- `commands/harness-auto.md`

### 执行规范

- `skills/clarify/SKILL.md`
- `skills/plan/SKILL.md`
- `skills/work/SKILL.md`
- `skills/review/SKILL.md`

### 参考文档

- `README.md`
- `docs/usage.md`
- `docs/architecture.md`
