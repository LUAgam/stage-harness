# OMS vs SQLShift 阶段对比总览

本文作为 `ai-programmer-oms` 与 `ai-programmer-sqlshift` 流程对比的总览索引。

文档组织约定：

- **一个阶段对应一个文件**
- 每个阶段文件都同时对比：
  - `ai-programmer-oms`
  - `ai-programmer-sqlshift`
- 若后续出现“阶段错位”或“阶段缺位”，也仍然按该阶段编号归档，但会在对应文件内明确说明

## 当前已整理的阶段

### 阶段1

文件：

- `docs/md/oms-vs-sqlshift-stage1-comparison.md`

当前结论：

- `oms`：`precheck + init + clarification`
- `sqlshift`：`precheck + init + draft_prd`

核心判断：

- `oms` 第一阶段是“先澄清，再继续”
- `sqlshift` 第一阶段是“先成文，再继续”

### 阶段2

文件：

- `docs/md/oms-vs-sqlshift-stage2-comparison.md`

当前结论：

- `oms`：`apply-clarification + draft_prd`
- `sqlshift`：当前主流程里不存在一个完整等价阶段，呈现为“阶段前移 + 中段缺位”

核心判断：

- `oms` 的阶段2是一个完整存在的“回复收敛 -> 初版文档生成”阶段
- `sqlshift` 的阶段2在当前主链中更像流程断层，而不是一个完整独立阶段

### 阶段3

文件：

- `docs/md/oms-vs-sqlshift-stage3-comparison.md`

当前结论：

- `oms`：`discussion + summary_effect + finalize_prd`
- `sqlshift`：`discussion`、`summary_effect`、`merge-final` 相关能力存在，但默认主流程未自动串联

核心判断：

- `oms` 的阶段3是一个完整存在的“影响面补强 -> 产品确认 -> 最终定稿”阶段
- `sqlshift` 的阶段3不是没有能力，而是后处理模块已具备，但默认主链没有闭合

### 阶段4

文件：

- `docs/md/oms-vs-sqlshift-stage4-comparison.md`

当前结论：

- `oms`：`execute_tech_design + build_deploy`
- `sqlshift`：`execute_tech_design + build_deploy`

核心判断：

- 阶段4按阶段对齐时，最合理的定义就是“方案执行阶段”
- 两边在这一阶段重新回到同一主线，但 `oms` 更偏细粒度控制，`sqlshift` 更偏短入口 + 专用部署后端

### 阶段5

文件：

- `docs/md/oms-vs-sqlshift-stage5-comparison.md`

当前结论：

- `oms`：`generate-case-list + execute-cases`
- `sqlshift`：`generate-case-list + execute-cases`

核心判断：

- 阶段5按阶段对齐时，最合理的定义就是“验证 / E2E / 自动修复闭环阶段”
- 两边主线一致，但 `oms` 更偏通用 E2E 控制与 OMS 代码缺陷修复，`sqlshift` 更偏真实改动驱动的专用验证体系、前后端精细归因与准确率专项闭环

### 阶段6

文件：

- `docs/md/oms-vs-sqlshift-stage6-comparison.md`

当前结论：

- `oms`：阶段5后没有新的稳定主链，剩余的是知识沉淀与手动清理能力
- `sqlshift`：阶段5后同样没有新的稳定主链，剩余的是知识沉淀、证据保留与专用收尾能力

核心判断：

- 阶段6如果继续编号，最合理的定义只能是“收尾与知识沉淀阶段（非稳定主链）”
- 这一步最重要的结论不是“新增了一个标准阶段”，而是“两边主流程实际上已经在阶段5闭环”

## 结构说明

从阶段2开始，`oms` 与 `sqlshift` 已经不再适合机械地做“阶段 N 对阶段 N”的平移对齐。

后续文件仍然建议继续按“阶段编号”归档，但在每个文件中都要显式说明以下之一：

1. 阶段直接对应
2. 阶段前移
3. 阶段缺位
4. 阶段压缩
5. 能力存在但主流程未接入

这样做的好处是：

- 文件结构仍然清晰
- 不会因为强行一一对应而失真
- 后续若仍继续编号，也能保持一致口径

## 当前总判断

到阶段6为止，可以先形成一个比较稳定的判断：

- `oms` 更像一套**按阶段闭环推进**的需求文档生产链
- `sqlshift` 更像一套**保留了关键能力模块，但在主流程中做了压缩与裁剪**的变体

更具体地说：

- `oms` 的优势在于主链完整、阶段边界清楚、产品确认与最终定稿自然承接
- `sqlshift` 的特点在于前段更快，中后段更依赖人工决定是否启用相关模块，但到了执行与验证阶段又切回较强的专用落地与验收能力；主链结束后则保留更多产品专属收尾能力

## 后续建议

下一步如果继续分析，更建议先回答一个问题：

- 这一阶段在两边是“直接对应”，还是“阶段错位”？

如果答案已经变成“后面不再存在稳定主阶段”，那么更适合改成：

- 能力对比专题文档
- 收尾/复盘能力专题文档
- 知识沉淀机制专题文档
