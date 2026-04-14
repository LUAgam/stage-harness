# CLARIFY 真实回归测试方案

## 目标

在真实项目目录 `/opt/agent-delivery-claude/test_oms_2` 中，执行一次端到端 CLARIFY 回归，验证以下三类能力：

1. **关注点闭环**：本轮真实测试使用真实业务需求启动，但在需求澄清完成后，必须显式覆盖以下**人工点名检查点**；若缺失，需要诊断原因。
   - `delete` 后再 `insert` 同一主键行
   - `insert` 冲突时的性能问题
2. **防跨阶段漂移**：CLARIFY 阶段不应被并行子任务拖入 `SPEC/PLAN/WORK/REVIEW/DONE/PATCH` 等后续阶段。
3. **通用性约束**：若需修复插件，方案必须面向**所有项目**，不得夹带 `test_oms_2`、Oracle2OBMySQL 或当前需求的定制逻辑。

## 测试分层说明

本方案中的“测试”分为两层，**不要混淆**：

### 1. 静态验证

静态验证是不启动真实 Claude 会话，只检查已经落盘的产物和门禁：

- `clarify-selfcheck`
- `stage-gate check CLARIFY`
- `verify-artifacts.sh`
- `.harness/features/<epic-id>/` 下的产物文件

它适合：

- 快速判断某个 Epic 当前产物是否合规
- 对已经生成的结果做诊断
- 验证门禁一致性

但它**不等于真实测试**，因为它无法验证：

- agent 运行过程中是否发生阶段漂移
- hook 是否真的拦截了越界行为
- 会话中是否真的采集并闭环了用户显式关注点

### 2. 真实测试

真实测试才是本方案的重点：在真实项目目录中，通过 **后台 `claude -p` 会话** 启动插件命令，完整模拟一次用户运行过程。

典型命令形态：

```bash
cd /opt/agent-delivery-claude/test_oms_2
http_proxy=http://127.0.0.1:7890 https_proxy=http://127.0.0.1:7890 \
claude -p --verbose --output-format stream-json --include-hook-events --dangerously-skip-permissions \
  --plugin-dir /opt/agent-delivery-claude/stage-harness \
  '/stage-harness:harness-start ...需求...' \
  < /dev/null > "/opt/agent-delivery-claude/test_oms_2/harness-start-run.jsonl" 2>&1
```

这层测试的核心是：

- 用真实项目目录启动插件
- 用真实用户需求驱动 `CLARIFY`
- 保留完整流式日志（`jsonl`）
- 观察阶段漂移、hook 拦截、关注点闭环、门禁结论是否符合预期

## 问题处理原则

- **小问题**：先记录，不中断整轮回归。
- **大的阻碍性问题**：立即停止继续跑业务流程，转而优先修插件，再从同一测试方案重新回归。
- **修复标准**：所有修复必须提炼为通用机制，不能把当前项目语义写死进插件规则、门禁或提示词。

## 测试目录

- **被测项目目录**：`/opt/agent-delivery-claude/test_oms_2`
- **插件目录**：`/opt/agent-delivery-claude/stage-harness`
- **CLI 路径**：`/opt/agent-delivery-claude/stage-harness/scripts/harnessctl.py`

## 前置准备

### 重测前必须清理历史记录

在同一测试目录重复回归前，必须先清理**所有 stage-harness 历史产物与运行日志**，避免旧 Epic、旧门禁状态、旧 `jsonl` 日志污染本轮结论。

在 `/opt/agent-delivery-claude/test_oms_2` 中，至少清理以下内容：

- `.harness/`
- `harness-start-run.jsonl`
- `harness-clarify-run.jsonl`
- `harness-auto-run-clean.jsonl`
- 其他由 stage-harness 测试生成的 `harness-*.jsonl`

推荐命令：

```bash
cd /opt/agent-delivery-claude/test_oms_2
rm -rf ".harness"
rm -f harness-*.jsonl
```

清理后再执行：

```bash
cd /opt/agent-delivery-claude/test_oms_2
export HARNESSCTL=/opt/agent-delivery-claude/stage-harness/scripts/harnessctl.py
python3 "$HARNESSCTL" status
```

若还没有 `.harness/`，先通过真实会话执行 `/harness:start`。

## 真实测试启动方式

真实测试应优先采用**后台执行**，而不是前台人工盯住终端。推荐把输出统一写入 `jsonl` 文件，便于事后分析。

### 推荐启动命令

```bash
cd /opt/agent-delivery-claude/test_oms_2

(http_proxy=http://127.0.0.1:7890 https_proxy=http://127.0.0.1:7890 \
claude -p --verbose --output-format stream-json --include-hook-events --dangerously-skip-permissions \
  --plugin-dir /opt/agent-delivery-claude/stage-harness \
  '/stage-harness:harness-start 长海医院用户诉求：oracle2obmysql
insert/update原样下发
delete不物理删除，只做逻辑删除，update set record_type = delete where 原本数据行
需要支持无主键表
实现时需要考虑整个功能，比如增加页面入口、后端接口适配、结构迁移、全量迁移、增量迁移delete改写等' \
  < /dev/null > "/opt/agent-delivery-claude/test_oms_2/harness-start-run.jsonl" 2>&1) &
```

说明：

- **真实启动输入以这条长海医院用户诉求为准**，不要替换成下面的通用模板。
- 下文提到的两个关注点（`delete` 后 `insert` 同一主键行、`insert` 冲突性能）是**人工验收检查点**，用于判断插件产物是否达到了预期澄清深度；它们不是要求把这两个点硬编码进插件。

### 进度观察方式

```bash
tail -f /opt/agent-delivery-claude/test_oms_2/harness-start-run.jsonl
pgrep -af 'claude -p'
wc -c /opt/agent-delivery-claude/test_oms_2/harness-start-run.jsonl
```

说明：

- `jsonl` 文件用于保留完整运行证据
- 后续关于阶段漂移、hook 拦截、异常退出的判断，优先基于该日志
- 若需继续跑 `clarify` 而不是 `start`，可改为后台执行 `/stage-harness:harness-clarify <epic-id>`

## 人工验收关注点

对于这条真实业务需求，回归验收时需要额外检查插件产物是否自然关注到了以下两点；如果没有，需要诊断原因：

1. `delete` 后再 `insert` 同一主键行的行为
2. `insert` 冲突时的性能问题

判断原则：

- 这两点是**人工发现的关键检查点**，用于评估 CLARIFY 产物质量。
- 若产物缺失这两点，应优先诊断是：
  - 需求采集失败
  - Focus Points / 用户关注点落盘失败
  - 语义信号未命中
  - 产物回写链路丢失
  - 或属于插件层阻碍性问题
- 不能为了让当前测试通过，把这两个点写死进插件规则、提示词或门禁逻辑；任何修复都必须抽象成**面向所有项目的通用机制**。

## 通用模板（仅供机制说明）

下面这个模板只用于说明“当用户显式点名关注点时，测试如何检查闭环机制”；**本次真实测试不要用它来替换长海医院用户诉求**。

在需要演示“显式关注点闭环”机制时，可使用以下模板：

```text
/harness:start 我们要评估一条数据库变更链路的语义正确性。

请务必覆盖以下两个关注点：
1. delete 后再 insert 同一主键行的行为是否正确
2. insert 冲突时的性能问题是否会恶化

其它小问题先记录；如果遇到大的阻碍性问题，可以中止并优先修插件。

注意：如果插件需要修复，修复方案必须是通用的，不能夹带当前项目或当前需求相关的定制逻辑。
```

如 Epic 已存在，也可继续执行：

```text
/harness:clarify <epic-id>
```

## 执行步骤

### 1. 找到当前 Epic

```bash
python3 "$HARNESSCTL" epic list
python3 "$HARNESSCTL" status
```

记录 `<epic-id>`。

### 2. 检查 CLARIFY 产物是否生成

```bash
ls -la ".harness/features/<epic-id>"
```

重点关注：

- `clarification-notes.md`
- `scenario-coverage.json`
- `requirements-draft.md`
- `challenge-report.md`
- `decision-bundle.json`
- `unknowns-ledger.json`
- `focus-points.json`（可选）

### 3. 检查用户关注点是否真的被覆盖

打开：

```bash
sed -n '1,260p' ".harness/features/<epic-id>/clarification-notes.md"
```

重点核对：

- 是否存在 `## Focus Points` / `## 用户关注点` / `## 用户点名关注`
- 对于本轮人工验收关注点，产物中是否已经覆盖：
  - `delete` 后再 `insert` 同一主键行
  - `insert` 冲突时的性能问题
- 若存在 Focus Points，每条是否映射到 `REQ-*` / `CHK-*` / `SCN-*` / `DEC-*` / `UNK-*`

**合格示例**：

```text
- delete 后再 insert 同一主键行 -> SCN-002, REQ-005
- insert 冲突性能 -> DEC-001, UNK-003
```

**不合格示例**：

```text
- 要注意 delete 后 insert
- 要分析 insert 冲突性能
```

### 4. 跑自检与正式门禁

```bash
python3 "$HARNESSCTL" clarify-selfcheck --epic-id "<epic-id>"
python3 "$HARNESSCTL" clarify-selfcheck --epic-id "<epic-id>" --json
python3 "$HARNESSCTL" stage-gate check CLARIFY --epic-id "<epic-id>"
bash /opt/agent-delivery-claude/stage-harness/scripts/verify-artifacts.sh "<epic-id>" CLARIFY
```

预期：

- `clarify-selfcheck`
- `stage-gate check CLARIFY`
- `verify-artifacts.sh`

三者对关注点闭环和 CLARIFY 门禁的结论一致。

### 5. 检查是否发生跨阶段漂移

```bash
tail -f /opt/agent-delivery-claude/test_oms_2/harness-start-run.jsonl
rg "clarify_stage_drift_blocked|harness-spec|harness-plan|harness-patch|harness-done" ".harness/logs"
rg "clarify_stage_drift_blocked|stage_gate" ".harness/logs/epics/<epic-id>"
```

预期：

- 如果有并行子任务试图在 CLARIFY 阶段越界调用后续阶段命令，应看到 `clarify_stage_drift_blocked`
- 不应出现 CLARIFY 流程被错误推进到后续阶段的情况
- 若 `jsonl` 日志中出现了后续阶段命令尝试，也应被 hook 拦住，而不是实际推进阶段

### 6. 负向验证：故意破坏关注点闭环

先备份：

```bash
cp ".harness/features/<epic-id>/clarification-notes.md" "/tmp/<epic-id>-clarification-notes.md.bak"
```

然后手工删除某条关注点中的 `REQ-/CHK-/SCN-/DEC-/UNK-` 映射，再执行：

```bash
python3 "$HARNESSCTL" stage-gate check CLARIFY --epic-id "<epic-id>"
python3 "$HARNESSCTL" clarify-selfcheck --epic-id "<epic-id>" --json
bash /opt/agent-delivery-claude/stage-harness/scripts/verify-artifacts.sh "<epic-id>" CLARIFY
```

预期：

- 门禁失败
- `focus_point_errors` 非空
- 说明关注点闭环不是摆设

恢复文件：

```bash
cp "/tmp/<epic-id>-clarification-notes.md.bak" ".harness/features/<epic-id>/clarification-notes.md"
```

## 缺失关注点时的诊断方式

若 CLARIFY 完成后没有覆盖以下两点：

- `delete` 后 `insert` 同一主键行
- `insert` 冲突时的性能问题

按以下顺序诊断：

1. **需求输入是否明确点名**
   - 检查用户原始输入中是否真的把两点作为“必须覆盖”的关注点明确写出。
2. **Focus Points 是否落盘**
   - 若 `clarification-notes.md` / `focus-points.json` 没有对应条目，说明是“关注点采集失败”。
3. **语义信号是否命中**
   - 第一条应命中 `StateAndTime` / `ConstraintsAndConflict`
   - 第二条应命中 `CostAndCapacity` / `ConstraintsAndConflict`
4. **是否被错误归并或遗漏**
   - 检查 `scenario-coverage.json`、`decision-bundle.json`、`unknowns-ledger.json` 中是否有对应条目但未回写到 Focus Points。
5. **是否属于插件阻碍性问题**
   - 若模型多次稳定漏掉用户显式关注点，或 CLARIFY 被跨阶段漂移打断，应视为插件问题，而不是项目问题。
6. **修复是否违反通用性标准**
   - 若要让这两点出现，只能靠写入当前项目专有词、当前业务规则或当前需求特判，则该方案不合格，应回退并重新抽象为通用机制。

## 阻碍性问题判定

满足以下任一条件，可视为**大的阻碍性问题**，应停止继续业务流程并优先修插件：

- 用户明确点名的关注点未进入 `Focus Points` 或等价结构化落点
- 门禁未能阻止“无映射的关注点”通过
- CLARIFY 阶段被并行子任务越界推进到后续阶段
- `clarify-selfcheck`、`stage-gate`、`verify-artifacts.sh` 三者结论不一致
- 修复方案需要写入当前项目语义才能通过测试

## 修复后的复测要求

任何插件修复完成后，必须重新在 `/opt/agent-delivery-claude/test_oms_2` 按本方案完整复跑，并额外确认：

1. 修复内容没有提及当前项目专有词或业务规则
2. 对另一个无关项目也能解释得通
3. 两个必查关注点仍被正常识别并闭环
4. 其它小问题可记录，但不应再阻断主流程

## 结果记录模板

建议每次回归至少记录以下字段：

- 测试类型：静态验证 / 真实测试（后台 `claude -p`）
- 测试目录：`/opt/agent-delivery-claude/test_oms_2`
- 日志文件：`harness-start-run.jsonl` / `harness-clarify-run.jsonl`
- Epic ID：`<epic-id>`
- 是否覆盖关注点 1：是 / 否
- 是否覆盖关注点 2：是 / 否
- 是否出现 CLARIFY 跨阶段漂移：是 / 否
- `clarify-selfcheck`：通过 / 失败
- `stage-gate check CLARIFY`：通过 / 失败
- `verify-artifacts.sh`：通过 / 失败
- 小问题清单
- 是否触发插件修复：是 / 否
- 若修复：是否满足通用性约束：是 / 否
