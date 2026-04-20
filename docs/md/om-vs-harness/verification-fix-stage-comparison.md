# 验证/修复阶段对比

本文承接前面的阶段对比文档，继续分析下一阶段：

- `stage-harness`
- `ai-programmer-oms`

这里对齐的是**代码执行之后的质量闭环**，也就是系统如何验证结果、发现问题、决定是否通过，以及失败后如何修复。

## 一句话结论

如果按阶段功能对齐：

- `stage-harness` 的这一阶段应看作：`VERIFY + FIX`
- `ai-programmer-oms` 的这一阶段应看作：`generate_e2e_case_list + execute_e2e_cases`

也就是说：

- `stage-harness` 更强调**多维审查、spec compliance、验收议会裁决，以及被拒后进入 FIX 回路**。
- `ai-programmer-oms` 更强调**生成完整 E2E case 列表、逐 case 执行、失败后做 case 级自动修复判断**。

## 一、为什么这样对齐

上一份文档已经把“执行阶段”对齐为：

- `stage-harness`: `EXECUTE`
- `ai-programmer-oms`: `execute_tech_design + build_deploy`

再往下一步，两个系统都进入“做质量闭环”的阶段。

但它们对“验证/修复阶段”的定义不一样：

### `stage-harness`

`VERIFY` 不是简单跑一遍测试，而是：

- 汇总 receipt
- 并行技术 review
- logic / test / security / spec compliance 审查
- 对抗式补盲
- 验收议会裁决
- Stage Smoke

如果验收议会 `REJECTED`，则进入：

- `FIX`

也就是说，`stage-harness` 关注的是：

- 是否符合 spec
- 是否通过审查
- 是否达到可交付标准

### `ai-programmer-oms`

它没有单独的 `VERIFY` / `FIX` 状态机阶段，而是把这部分拆成：

1. `generate_e2e_case_list`
2. `execute_e2e_cases`

并且在 case 执行失败时，触发：

- case 级自动修复判断

也就是说，它关注的是：

- 测试用例是否完整
- 每个 case 是否通过
- 如果失败，是否属于 OMS 代码 bug，是否值得自动修

所以两边并不是同一种“验证阶段”，而是：

- 一边偏**多角色验收裁决**
- 一边偏**E2E 测试执行与修复**

## 二、阶段映射

### `stage-harness`

本阶段：

1. `VERIFY`
2. `FIX`

上游输入：

- `.harness/specs/<epic-id>.md`
- `receipts/`
- `coverage-matrix.json`
- domain/scenario 相关产物

下游输出：

- `verification.json`
- `review-summary.md`
- `councils/verdict-acceptance_council.json`
- 若失败则进入 `fix-notes.md` 与修复 receipts

### `ai-programmer-oms`

本阶段：

1. `generate_e2e_case_list`
2. `execute_e2e_cases`

上游输入：

- `final_prd.md`
- 仓库技术方案目录
- 跨仓收敛报告
- 知识库

下游输出：

- `e2e_test_case_list/generated_test_case_list.md`
- `e2e_case_execution/summary` 与 manifest
- 每个 case 的：
  - `test_steps.md`
  - `test_report.md`
  - `execution_result.json`
- 失败时的自动修复产物

## 三、`stage-harness` 的验证/修复阶段实现流程

### 1. VERIFY 入口门禁

正式审查前，先要求：

- `stage-gate check EXECUTE`

必须满足：

- receipts 目录存在
- 所有任务不再是未处理状态

也就是说，它要求：

- 开发执行必须先收口
- 没完成的 task 不能混进验收阶段

### 2. 汇总 runtime receipts

第一步先做证据收集：

- 列出所有 receipt
- 核对每个 task 是否都有 receipt
- 汇总 new risks 和 coverage 信息

如果 receipt 缺失，就直接阻断，不进入后续审查。

这说明 `stage-harness` 的 VERIFY 是：

- 证据驱动

而不是：

- 只看代码 diff

### 3. 并行技术 review

随后并行调度多种 reviewer，例如：

- `code-reviewer`
- `logic-reviewer`
- `test-reviewer`
- `security-reviewer`
- `runtime-auditor`

其中重点不只是代码质量，还包括：

- 高风险场景是否在实现中有证据
- 测试是否覆盖了 domain/scenario 产物
- 实现是否偏离 spec

### 4. 对抗式补盲

在常规 reviewer 之外，还会补一层 adversarial review，专门找：

- 边界条件
- 并发问题
- 错误路径
- reviewer 可能漏掉的问题

这说明它的验证逻辑不是“reviewer 一轮过”，而是：

- 还要专门查 reviewer 的盲区

### 5. 验收议会

所有审查结果汇总后，交给：

- `acceptance_council`

最终裁决：

- `PASS`
- `CONDITIONAL_PASS`
- `REJECTED`

所以在 `stage-harness` 里，“通过与否”不是单点测试结果决定，而是议会裁决决定。

### 6. Stage Smoke

在 review 之外，还要求跑：

- 全量回归测试
- 检查 receipts 的 smoke 结果

也就是说，`VERIFY` 实际上把：

- 审查
- 合规
- 安全
- 回归

都合并进来了。

### 7. FIX：失败后修复回路

如果 `VERIFY` 被拒绝，就进入 `FIX`。

`FIX` 的过程是：

1. 从 `verification.json` 提取：
   - `critical_issues`
   - `high_issues`
2. 针对 CRITICAL 问题创建修复 task
3. 用修复模式执行最小修改
4. 写：
   - `fix-notes.md`
   - fix receipts
5. 回到 `VERIFY` 重新审查

所以它的修复回路不是“直接改一改再跑测试”，而是：

- 问题显式化
- 修复任务化
- 修复说明化
- 再审查

### 8. 阶段出口

只有当：

- 技术 review 通过
- spec compliance 无阻断
- 安全审查通过
- 验收议会通过
- Stage Smoke 通过

才会推进到：

- `DONE`

所以 `stage-harness` 的这一阶段更像：

- **多维验收与拒绝后修复中心**

## 四、`ai-programmer-oms` 的验证/修复阶段实现流程

### 1. `generate_e2e_case_list`：先定义验证面

它不会直接执行测试，而是先生成一份：

- 完整测试 case 列表

输入来自：

- `final_prd.md`
- 仓库技术方案目录
- 跨仓收敛报告
- 知识库

输出：

- `generated_test_case_list.md`
- `manifest.json`

这里的关键点是：

- 它先把“要验证什么”文档化
- 这份文档不是测试代码，而是测试范围定义

### 2. `execute_e2e_cases`：按 case 执行

之后按 case list 逐个执行 case。

每个 case 至少产出：

- `test_steps.md`
- `test_report.md`
- `execution_result.json`

页面类测试要求：

- 必须优先用 Playwright

非页面测试要求：

- 优先用 `oms_e2e_tools`

失败时还必须先做：

- 日志分析

所以它的验证闭环是：

- case 级
- 工具链明确
- 现场保留

### 3. 失败后的 case 级自动修复

这部分是 `ai-programmer-oms` 很有特点的设计。

case 执行失败后，并不是一律修。

只有当失败被判断为：

- `oms_code_bug`

时，才允许继续修。

如果属于：

- 测试资产问题
- 工具链问题
- 环境问题
- 非 OMS 行为
- 根因未知

则：

- 不修复
- 不建议继续重试

### 4. 自动修复的硬约束

即使判断为 `oms_code_bug`，想继续重试还必须满足：

- 实际修改了 OMS 代码
- 完成构建与热更
- 确认修复已生效

否则不能把：

- `retry_recommended`

设为 `true`

这说明它的自动修复不是“分析一下就算修复”，而是要求：

- 修代码
- 让修复真正生效
- 再重跑 case

### 5. 自动修复循环

这一层复用了统一的：

- `run_auto_repair_loop()`

逻辑，大致流程是：

```text
执行 case
-> 成功则结束
-> 失败则判断是否要修
-> 若修且建议重试，则下一轮
-> 达到最大轮次后终止
```

也就是说，它的修复闭环是：

- case 级
- 自动决策
- 带重试上限

### 6. 阶段出口

这套流程结束后，系统得到的是：

- 一份完整 case list
- 每个 case 的执行结果
- 必要时的 case 级自动修复记录

它的出口标准更像：

- case 已执行
- 有报告
- 失败 case 已分类
- 能修的 bug 已尝试修

所以 `ai-programmer-oms` 的这一阶段更像：

- **E2E 验证与 case 级修复中心**

## 五、差异总表

| 对比项 | `stage-harness` | `ai-programmer-oms` | 我的判断 |
|---|---|---|---|
| 阶段范围 | `VERIFY + FIX` | `generate_e2e_case_list + execute_e2e_cases` | 两边都在做“执行后的质量闭环”，但一边偏审查裁决，一边偏测试执行。 |
| 核心目标 | 判断是否满足 spec 并决定是否验收通过 | 生成并执行完整 E2E case，识别失败并决定是否修复 | `stage-harness` 更像验收系统，`ai-programmer-oms` 更像测试系统。 |
| 质量判定粒度 | epic / 验收级 | case / 测试级 | `stage-harness` 更偏整体交付判断；`ai-programmer-oms` 更偏单 case 成败判断。 |
| 起点输入 | spec、receipts、coverage、review context | final PRD、tech design、cross repo review、knowledge | 前者更依赖执行证据；后者更依赖测试范围定义输入。 |
| 主要方法 | reviewer 并行审查 + council 裁决 + smoke | case list 生成 + case 执行 + 日志分析 + auto repair | 两边都闭环，但组织方式完全不同。 |
| 是否显式做 spec compliance | 是，runtime-auditor 专项检查 | 间接体现在 case list 和 case 执行中 | 在“实现是否偏离规格”这件事上，`stage-harness` 更直接、更强。 |
| 是否显式做安全审查 | 是 | 不是这一阶段的核心 | `stage-harness` 的验证维度明显更全。 |
| 修复触发方式 | acceptance council `REJECTED` 后进入 FIX | case 执行失败且被判为 `oms_code_bug` 后进入 auto repair | 前者是议会触发，后者是测试失败分类触发。 |
| 修复粒度 | issue/task 级 | case/repo 级 | `stage-harness` 更细地围绕问题修；`ai-programmer-oms` 更围绕失败 case 修。 |
| 修复后的回路 | FIX -> VERIFY 重新审查 | 修复后重跑 case | 一个回到整体验收，一个回到单 case 执行。 |

## 六、产物差异表

| 类别 | `stage-harness` 代表产物 | `ai-programmer-oms` 代表产物 | 我的判断 |
|---|---|---|---|
| 验证主件 | `verification.json` | `generated_test_case_list.md` + 每 case `execution_result.json` | `stage-harness` 有一个统一验收主件；`ai-programmer-oms` 更分散在 case 级产物上。 |
| 审查/裁决产物 | `review-summary.md`、`verdict-acceptance_council.json` | `test_report.md`、summary/manifest | `stage-harness` 更偏决策产物，`ai-programmer-oms` 更偏测试报告产物。 |
| 修复主件 | `fix-notes.md` | `fix_report.md`、`ai_result.json` | 两边都记录修复，但前者偏“问题修复说明”，后者偏“自动修复决策与结果”。 |
| 证据来源 | receipts、review verdicts、stage smoke | test steps、test report、logs analysis | 前者的证据更偏开发执行链，后者更偏测试执行链。 |
| 回路出口凭证 | `verification.json` 通过 | case 结果 + auto repair attempts | `stage-harness` 更适合给出一个明确的“能否验收通过”答案。 |

## 七、推进逻辑差异

### `stage-harness`

更像这条链：

```text
EXECUTE 完成
-> 汇总 receipts
-> reviewer 并行审查
-> spec compliance
-> security
-> 对抗补盲
-> acceptance council
-> pass 则 DONE
-> rejected 则 FIX
-> 修复后再回 VERIFY
```

它要解决的是：

- 交付是否真的满足 spec
- 有没有严重遗漏风险
- 是否达到可验收状态

### `ai-programmer-oms`

更像这条链：

```text
final PRD + tech design
-> generate case list
-> execute cases
-> fail 时分类
-> oms_code_bug 才修
-> 修完后重跑 case
```

它要解决的是：

- 要测哪些场景
- 每个场景是否通过
- 失败是否属于 OMS 代码问题
- 是否值得继续修和重试

## 八、我的总体判断

### 1. `stage-harness` 更强在“整体验收”

它擅长：

- 多维审查
- spec 对齐
- 安全审查
- 议会裁决
- 被拒后的正式修复回路

所以它更像：

- **整体验收与治理层**

### 2. `ai-programmer-oms` 更强在“测试闭环”

它擅长：

- 明确测试范围
- 按 case 执行
- 失败时做日志分析
- 自动判断是否值得修复
- 修复后重跑

所以它更像：

- **测试执行与自动修复层**

### 3. 如果必须做一句最准确的概括

我的判断是：

- `stage-harness` 的这一阶段，更像“对整个交付结果做多维验收并在不通过时回炉修复”。
- `ai-programmer-oms` 的这一阶段，更像“围绕 E2E case 做执行、定位、修复和重试”。

## 九、适用场景判断

| 场景 | 更适合 `stage-harness` | 更适合 `ai-programmer-oms` | 我的判断 |
|---|---|---|---|
| 需要对交付结果做统一验收裁决 | 是 | 一般 | `stage-harness` 明显更适合。 |
| 需要把测试范围先完整列出来 | 一般 | 是 | `ai-programmer-oms` 的 case list 更自然。 |
| 需要安全、逻辑、测试、spec 多维并审 | 是 | 一般 | `stage-harness` 更完整。 |
| 需要按具体失败 case 做自动修复 | 一般 | 是 | `ai-programmer-oms` 更强。 |
| 需要对失败是否属于代码 bug 做显式分类 | 一般 | 是 | `ai-programmer-oms` 的 case repair 机制更细。 |
| 需要整体质量闸门而不是单 case 结果 | 是 | 一般 | `stage-harness` 更适合。 |

## 十、最终结论

如果把这一阶段看成“验证/修复阶段”，那么两边的差别可以概括为：

- `stage-harness` 更偏**交付验收 + 被拒后修复**
- `ai-programmer-oms` 更偏**E2E 执行 + case 级自动修复**

所以最准确的理解不是“谁验证更全面”或“谁修复更自动化”，而是：

- 一个更擅长做整体验收裁决
- 一个更擅长做测试执行和失败闭环

到这里，主链对比已经基本闭合：

1. 广义需求分析阶段
2. 技术方案/计划阶段
3. 执行阶段
4. 验证/修复阶段
