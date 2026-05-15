---
name: verify-and-fix-cases
description: >-
  在 generate-test-cases 阶段之后执行，逐个验证测试用例并在失败时修复项目代码、重新编译部署、再次验证，
  直到通过或达到最大修复次数。覆盖 UI / API / API+UI / 性能测试四个维度，UI 测试通过浏览器真实模拟用户操作并截图，
  API 测试根据项目代码生成可执行的接口脚本，性能测试调用现有性能/质量技能全量执行。
  涉及真实用户登录信息（如手机号+验证码、账号密码、JWT）时必须中断要求用户提供，禁止编造无效凭证。
  所有 case 状态变更必须通过 e2e-case-tracker.sh 脚本持久化，确保中途崩溃可恢复、无 case 遗漏。
---

# 验证测试 Case 与修复项目

## 0. 定位与触发时机

本 Skill 接在 **generate-test-cases** 之后执行，是 E2E 阶段的核心实施步骤。

**触发条件**：
- `<feature_dir>/test-cases.md` 存在且非空
- `deploy-receipt.json` 存在且 `status == "PASS"`
- `<feature_dir>/verify-cases/case-tracker.json` 存在且已注册 case（由 orchestrator 在调度前完成初始化）
- 项目代码可重新编译部署（构建/部署技能或脚本可用）

**输出产物**：
- `<feature_dir>/verify-cases/` — 总目录
  - `verify-cases/<case_id>/` — 每个测试 case 的子目录
    - `plan.md` — 详细测试步骤设计
    - `script.*` — 测试脚本（API 测试时生成；UI/性能可选）
    - `run-<n>.log` — 第 n 次执行日志
    - `result-<n>.json` — 第 n 次执行结果（pass/fail + 证据指针）
    - `screenshots/` — UI 截图（成功/失败均保留）
    - `fix-<n>.md` — 第 n 次修复说明
    - `final-status.json` — 最终结论
  - `case-tracker.json` — 实时状态追踪（由 e2e-case-tracker.sh 维护）
  - `session-state.json` — 全局会话状态（含登录凭证复用句柄）
  - `verify-summary.md` — 总结报告（由 e2e-case-tracker.sh summary 生成）
  - `verify-receipt.json` — 阶段收据（由 e2e-case-tracker.sh summary 生成）

---

## 1. 输入

| 参数 | 来源 | 说明 |
|------|------|------|
| `epic_id` | 调用方传入或从 `state.json` 读取 | 当前 epic 标识 |
| `feature_dir` | `.harness/features/<epic_id>/` | 特性目录路径 |
| `test_cases_path` | `<feature_dir>/test-cases.md` | 测试用例清单 |
| `tracker_path` | `<feature_dir>/verify-cases/case-tracker.json` | case 追踪器（已由 orchestrator 初始化） |
| `spec_path` | `.harness/specs/<epic_id>.md` | 需求规格文档（修复时回查需求） |
| `build_receipt_path` | `<feature_dir>/build-receipt.json` | 构建收据（含变更文件，定位修复点） |
| `deploy_receipt_path` | `<feature_dir>/deploy-receipt.json` | 部署收据（含部署目标、可达地址） |

---

## 2. 核心原则

**P1 — 逐个验证，互不干扰**
所有 case 按 tracker 中的顺序（P0 → P1 → P2 → P3）依次执行，每个 case 拥有独立的产物子目录。一个 case 的修复不能破坏前面已通过的 case；每次修复后必须对**所有已通过的 case**做轻量回归（至少跑 P0）。

**P1.5 — 凭证依赖分批执行（防中断策略）**
为防止等待用户提供凭证时整个流程阻塞，执行顺序采用**两轮策略**：
- **第一轮**：执行所有**不需要登录凭证**的 case（如公开 API、无需 token 的接口）。按优先级顺序（P0→P1→P2→P3）逐个执行。
- **第二轮**：执行所有**需要登录凭证**的 case。在第二轮开始前一次性向用户索取凭证，获取后连续执行所有需要凭证的 case。

判断 case 是否需要凭证的方法：
1. 读取 case 的操作步骤，检查是否涉及需要认证的 API 端点
2. 检查 `session-state.json` 是否已有可复用凭证（若有则该 case 归入第一轮）
3. 若无法确定，先尝试执行——收到 401/403 时再归入第二轮

这样即使用户未及时回答凭证问题，第一轮的所有 case 结果已经持久化到 tracker 中，下次恢复时不会丢失。

**P2 — 真实凭证，禁止编造（硬性，无例外）**
任何需要真实用户身份、JWT、API Key 的 case，必须通过 `AskUserQuestion` 中断要求用户提供。**严禁编造任何形式的不可用凭证**（包括占位 token、随手编的手机号验证码、伪造 cookie、猜测的 JWT 等）。当 API/UI case 需要登录态但无法获取有效 JWT 或 session 时，**必须立即中断并向用户索取登录信息**（手机号 + 短信验证码、账号 + 密码等），获取用户提供的凭证并成功登录后方可继续。此规则无例外。

**P3 — 凭证最大化复用**
用户提供过登录信息后，将获得的 token / cookie / 用户上下文写入 `session-state.json`，后续 case 优先复用。仅在以下情况再次询问：
- token 过期或被撤销
- 需要不同角色/租户身份
- 需要重新走登录流程本身的验证

**P4 — 修复闭环不超过 3 次**
单个 case 验证失败 → 判定是否代码问题 → 修代码 → 重新编译 → 重新部署 → 重新验证。最多重复 3 次，仍未通过则标 `failed-after-max-retries`，不阻塞后续 case。

**P5 — UI 必留截图**
UI / API+UI 测试无论通过或失败，必须保留**关键步骤截图**与**最终状态截图**到 `screenshots/`。失败时额外保留 console 日志、网络请求记录。

**P6 — 性能测试不可中断，质量/准确率测试必须完整执行，必须通过 Skill 工具调度**
识别到的性能/质量测试技能必须**全量跑完**，不允许因执行时间长、流程复杂、看起来收敛了等任何理由提前中断。中途失败按修复闭环处理后**完整重跑**，而不是断点续跑（除非该技能本身明确支持续跑）。对于涉及转换准确率、一致性、精度等质量验证的 case，**无论时间多长、成本多高，都必须对全部样本逐一执行，不得抽样、截断或提前终止**。禁止以"时间过长""成本过高"为由跳过任何样本。

**⚠️ 性能/质量测试技能调度方式的硬性约束**：
- 当 test-cases.md 中某个 case 的操作步骤明确指定了要使用的技能名称，**必须通过 `Skill` 工具调用该技能**，由技能内部的完整编排流程执行。
- **严禁"走捷径"**：禁止绕过技能直接调用该技能底层依赖的 MCP 工具或 API 来"手动拼凑"技能本应完成的流程。
- **严禁"手动替代"**：禁止自行编写测试数据、自行调用被测系统接口、自行比对结果来替代技能的编排逻辑。

**P7 — 部署环境端口主动探测（硬性前置）**
在执行任何测试 case 之前，必须主动探测真实部署环境的前后端服务端口和接口地址。**禁止**硬编码端口号（如 `localhost:8666`）。探测方式：优先从 `deploy-receipt.json` 读取实际部署的服务地址和端口；若无记录，则通过 `docker ps`、`docker-compose ps`、`ss -tlnp`、`netstat -tlnp` 等手段扫描实际监听端口；探测结果写入 `session-state.json` 并在所有 case 执行时动态引用。
⚠️ **注意：不同项目的部署形式各异，不可假设仅有 Docker 部署。** 探测时必须**全面排查**，至少覆盖：`deploy-receipt.json` → `docker ps` / `docker-compose ps` → `ss -tlnp` / `netstat -tlnp` → `systemctl list-units --type=service` → `pm2 list` → `ps aux | grep` 关键进程 → 检查 nginx/Apache 配置中的 `proxy_pass` 和 `listen` 指令。

**P8 — 浏览器自动化降级策略（硬性）**
UI/API+UI case 必须通过真实浏览器执行。当默认浏览器引擎不可用时，按以下顺序逐一尝试，直到成功：
1. Playwright Chromium（`p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'])`）
2. Playwright Firefox（`p.firefox.launch(headless=True)`）
3. Playwright WebKit（`p.webkit.launch(headless=True)`）
4. Selenium + 系统已安装的浏览器驱动

每个引擎尝试时若 crash/超时，记录错误后立即尝试下一个。仅当以上全部失败时，才允许标记 case 为 `skipped`（reason 必须列出每个引擎的具体失败原因）。

⚠️ 禁止以"API 验证 + 前端代码分析"替代 UI 真实操作。UI case 的 PASS 证据必须包含浏览器截图，无截图则不可标记为 PASS。

**P9 — 不合理 case 可跳过**
以下情况允许 skip 并在 `final-status.json` 中记录原因：
- case 描述与当前代码状态明显矛盾且经核查是 case 本身错误
- 需要的外部依赖（第三方服务、特殊硬件）当前不可用且非本次需求职责
- 前置条件无法满足且与本次需求无关

禁止以"难测"、"耗时长"、"我不会写脚本"为理由跳过。

**P10 — 全量执行强制（硬性，无例外）**
在 Phase B 循环结束后，必须调用 `e2e-case-tracker.sh check-complete` 验证所有 case 都已处理。若存在 pending/in_progress case，必须继续执行直到全部处理完毕。不允许以"时间不够""上下文不足"为由终止。只有 check-complete 返回 0 时，才允许进入 Phase C（汇总）。

**P11 — 执行顺序不可跳跃**
按 tracker 中的 case 列表顺序（P0→P1→P2→P3）逐个执行。不允许"先跳过难的，后面再回来"——每个 case 必须在当前位置处理完毕（pass/fail/skip）后才能进入下一个。

**P12 — 进度实时可查**
每处理完一个 case，输出当前进度：
```
[3/12] TC-API-003 PASSED (P0)
[4/12] TC-UI-001 FAILED-AFTER-MAX-RETRIES (P0)
```

**P13 — 状态变更必须通过 tracker 脚本**
所有 case 状态变更（start/pass/fail/skip/attempt）**必须且只能**通过 `e2e-case-tracker.sh` 脚本执行。禁止直接编辑 `case-tracker.json` 文件。这确保了原子写入和中途崩溃恢复能力。

**P14 — UI 测试登录重定向处理（硬性）**
当浏览器访问目标页面后被重定向到登录页（URL 包含 `/login`、`/signin`、`/auth` 等模式），必须按以下流程处理：
1. 检查 `session-state.json` 是否已有可复用的登录凭证（cookie/token/账号密码）
2. 若有凭证 → 在登录页自动填写并提交，等待跳转回目标页面后继续执行
3. 若无凭证 → 通过 `AskUserQuestion` 向用户索取登录信息，获取后完成登录并将凭证写入 `session-state.json`
4. 登录成功后重新导航到原目标页面，继续执行 case 的后续步骤

禁止因"被重定向到登录页"而直接放弃 UI 测试或降级为 API 验证。

---

## 3. 执行流程

### Phase A：初始化

1. 读取 `case-tracker.json`，获取 case 列表和当前状态
2. **恢复模式检测**：检查是否有 `in_progress` 状态的 case（表示上次中途崩溃）
   - 若有 `in_progress` case → 从该 case 恢复执行
   - 若只有 `pending` case → 正常从头执行
   - 若无 `pending` 且无 `in_progress` → 所有 case 已处理，直接进入 Phase C
3. 获取待执行 case 列表：
   ```bash
   e2e-case-tracker.sh pending <epic-id>
   ```
4. 初始化或读取 `session-state.json`：
   ```json
   {
     "credentials": {},
     "service_endpoints": {},
     "counters": {"passed": 0, "failed": 0, "skipped": 0},
     "build_tool": null,
     "deploy_tool": null,
     "started_at": "<iso8601>"
   }
   ```
5. 识别项目的构建/部署入口（优先复用 `harness-build` / `harness-deploy` 或 `build-receipt.json` 中记录的命令）
6. 识别项目内可用的性能/质量测试技能或脚本
7. **端口探测**（P7 硬性前置）：探测真实部署环境的服务端口，写入 `session-state.json.service_endpoints`

### Phase B：逐个 case 执行

**执行顺序（两轮策略）**：

```
第一轮（无凭证依赖）：
  1. 扫描所有 pending case，识别哪些需要登录凭证（检查操作步骤中是否涉及需认证的 API）
  2. 先执行所有不需要凭证的 case（按 P0→P1→P2→P3 顺序）
  3. 第一轮结束后，所有无凭证 case 的结果已持久化到 tracker

第二轮（需凭证）：
  4. 检查 session-state.json 是否已有可复用凭证
  5. 若无凭证 → 一次性向用户索取（AskUserQuestion）
  6. 获取凭证后，连续执行所有需要凭证的 case（按 P0→P1→P2→P3 顺序）
```

若第一轮执行中某个 case 意外收到 401/403（预判失误），将该 case 标记为 `pending`（回退状态），归入第二轮处理。

对每个 case，按以下子步骤执行：

**B1 — 标记开始（必须首先执行）**
```bash
e2e-case-tracker.sh start <epic-id> <case-id>
```
此步骤将 case 状态从 `pending` 改为 `in_progress`，确保中途崩溃时可识别断点。

**B2 — 准备**
1. 创建 `verify-cases/<case_id>/` 子目录
2. 详细阅读该 case 描述、关联需求、关联代码修改
3. 设计具体的执行计划，写入 `plan.md`：
   - 测试目标（用一句话）
   - 详细可执行步骤（精确到点哪个按钮、调哪个接口、传什么参数）
   - 预期断言点（如何判定通过/失败）
   - 所需凭证 / 数据 / 环境前置
   - 维度特化说明（API 脚本草图 / UI 操作脚本 / 性能测试技能名）

**B3 — 凭证检查**
1. 检查 `plan.md` 是否需要登录态或外部凭证
2. 检查 `session-state.json` 是否已有可复用凭证
3. 不可复用时通过 `AskUserQuestion` 向用户索要（明确说明需要什么、用于哪个 case）
4. 写入 `session-state.json`，标注获取时间与失效条件

**B4 — 执行（按维度分流）**

- **API 测试**：
  - 根据项目语言/框架生成对应接口脚本（curl / httpx / fetch / 项目内既有 client），保存为 `script.*`
  - 执行脚本，输出写入 `run-<n>.log`
  - 解析响应做断言

- **UI 测试**：
  - 使用浏览器自动化（Playwright）真实模拟用户操作
  - 关键步骤逐步截图保存到 `screenshots/step-XX.png`
  - 最终状态截图 `screenshots/final.png`
  - 失败时额外保存 `screenshots/failure.png` + console 日志

- **API+UI 测试**：先按 UI 流程操作，同时用浏览器网络面板/拦截记录后端调用与响应；分别对前端可见行为与后端响应做断言

- **性能测试**：
  - **必须通过 `Skill` 工具调用** test-cases.md 中该 case 指定的技能
  - **禁止绕过技能直接调用底层 MCP 工具或 API**
  - 等待技能返回结果后，将技能产出的报告/产物归档到 case 目录
  - 技能必须**完整跑完**，不得提前中断

执行完成后写入 `result-<n>.json`：
```json
{
  "attempt": 1,
  "status": "pass|fail",
  "started_at": "<iso8601>",
  "finished_at": "<iso8601>",
  "evidence": ["run-<n>.log", "screenshots/final.png"],
  "failure_reason": "<若 fail，简短归因>",
  "failure_class": "code|env|data|case-itself|unknown"
}
```

**B5 — 失败归因与修复决策**

失败时判断 `failure_class`：
- `code` → 进入 B6 修复闭环
- `env` → 尝试修复环境（重启服务、清缓存）后重跑当前 attempt（不计入 3 次修复预算）
- `data` → 修正测试数据后重跑
- `case-itself` → case 本身有误，标 `skipped` 并记录原因
- `unknown` → 重读代码与 case，归类后再处理；连续 2 次仍 `unknown` 则按 `code` 处理

**B6 — 代码修复闭环（最多 3 次）**

1. 记录修复尝试：
   ```bash
   e2e-case-tracker.sh attempt <epic-id> <case-id>
   ```
2. 定位问题代码（结合 `build-receipt.json` 的修改文件清单与失败现象）
3. 修改代码，写入 `fix-<n>.md`：包含修改文件列表、修改前后差异摘要、修复意图
4. 重新编译（调用 Phase A 识别的构建命令），失败则归入本次 fix 失败
5. 重新部署（调用 Phase A 识别的部署命令），失败则归入本次 fix 失败
6. 跳回 B4 重跑当前 case，attempt 计数 +1
7. 第 3 次仍失败则停止，标记失败：
   ```bash
   e2e-case-tracker.sh fail <epic-id> <case-id> "failed-after-max-retries: <具体原因>"
   ```

**B7 — 通过后的回归保障**

当前 case 通过且本轮有过代码修改时：
1. 对所有此前已 passed 的 P0 case 做轻量回归（仅复跑断言，不重写脚本）
2. 出现回归则将该被回归的 case 状态改为 `regressed`，并优先修复

**B8 — 写入最终状态**

通过时：
```bash
e2e-case-tracker.sh pass <epic-id> <case-id>
```

跳过时：
```bash
e2e-case-tracker.sh skip <epic-id> <case-id> "<合法理由>"
```

同时写入 `final-status.json`：
```json
{
  "case_id": "<id>",
  "final_status": "passed|failed-after-max-retries|skipped|regressed",
  "attempts": 1,
  "fixes_applied": 0,
  "reason": "<skipped/failed 时必填>",
  "evidence_dir": "verify-cases/<case_id>/"
}
```

**B9 — 输出进度**
```
[<当前序号>/<总数>] <case_id> <STATUS> (<priority>)
```

### Phase B-END：完整性验证（强制门禁）

Phase B 循环结束后，**必须**执行：
```bash
e2e-case-tracker.sh check-complete <epic-id>
```

- 若返回非零（存在 pending/in_progress case）：
  1. 列出所有未处理的 case
  2. 对每个未处理 case 给出原因
  3. **继续执行这些 case**，直到全部处理完毕
  4. 不允许以任何理由终止
- 只有返回 0 时，才允许进入 Phase C

### Phase C：汇总（通过脚本生成）

**不再手动拼 JSON**，而是通过 tracker 脚本自动生成：

```bash
e2e-case-tracker.sh summary <epic-id>
```

此命令自动生成：
- `verify-cases/verify-receipt.json` — 阶段收据
- `verify-cases/verify-summary.md` — 总结报告

状态判定（由脚本自动完成）：
- 全部 passed 或 skipped 合理 → `PASS`
- 有 failed 但 P0 全过 → `PARTIAL`
- P0 有未通过 → `FAIL`

---

## 4. 硬性约束

**C1 — 严禁编造凭证**：JWT、token、API key、用户密码、验证码任何一种当无法通过用户/已存安全渠道获得时，必须中断询问；不得用占位符或猜测值。

**C2 — 修复必须重新部署**：任何代码修改后必须走完整的编译 + 部署，再重新验证；不允许只改源码就声明修好。

**C3 — UI 必有截图**：UI / API+UI case 无论成败必须保留至少一张最终状态截图；失败时还必须保留失败时刻截图。

**C4 — 性能测试不得中断**：识别出的性能技能必须从头跑到尾，不得因"看起来已经达标"或"耗时太长"提前结束。

**C5 — 修复次数上限 3**：单个 case 的代码修复闭环最多 3 次，超过即标失败，不得无限重试。

**C6 — 凭证复用优先**：已有可用凭证时禁止重复询问用户；只有在过期/换角色/验证登录本身时才再次索取。

**C7 — 跳过必须有理由**：skipped 必须在 `final-status.json` 写明原因，不得无理由跳过；难测、耗时长不是合法理由。

**C8 — 每个 case 独立产物目录**：所有执行产物（脚本、日志、截图、修复说明）必须落在该 case 自己的子目录下，不得共用。

**C9 — 修复后回归 P0**：每次代码修改导致重新部署后，必须对此前已通过的 P0 case 做回归验证。

**C10 — 不绕过验证**：禁止通过修改测试用例描述、降低预期、注释断言等方式让 case "通过"；只允许修复被测代码或将 case 标为 skipped 并写明原因。

**C11 — 技能调度不可绕过（硬性，无例外）**：当 test-cases.md 中某个 case 的操作步骤明确指定了要使用的技能（skill）时，**必须且只能**通过 `Skill` 工具调用该技能来执行。

**C12 — 状态变更必须通过 tracker 脚本**：所有 case 状态变更必须通过 `e2e-case-tracker.sh` 执行。禁止直接编辑 `case-tracker.json`。违反此约束将导致崩溃恢复失效。

**C13 — 全量执行不可中断**：`check-complete` 返回非零时，必须继续执行未处理的 case。不允许以任何理由（上下文不足、时间过长、turn 预算）终止执行。若确实因系统限制无法继续，必须在输出中明确标注"INCOMPLETE — 需要恢复执行"，以便 orchestrator 重新调度。

**C14 — 先 start 后执行**：每个 case 执行前必须先调用 `e2e-case-tracker.sh start`。这是崩溃恢复的关键——只有标记为 `in_progress` 的 case 才能在恢复时被识别为断点。

**C15 — UI case 验证纯净性**：UI 维度 case 的 PASS 判定必须基于浏览器中的真实可见状态（截图 + DOM 断言）。禁止以"API 返回正确数据 + 前端代码逻辑分析 = UI 必然正确"作为 PASS 证据。这种推理属于静态分析，不是端到端验证。若无法获取浏览器截图，该 case 只能标记为 skipped，不能标记为 passed。

---

## 5. 所需工具

- `Read` / `Write` / `Edit` — 读写文档、修复代码、记录产物
- `Bash` — 执行测试脚本、构建、部署、grep/find 定位、**调用 e2e-case-tracker.sh**
- `AskUserQuestion` — 索取登录凭证 / 确认歧义 case
- `playwright` — UI 测试浏览器自动化与截图
- `Skill` — **性能/质量测试 case 的唯一合法执行方式**
- `TaskCreate` / `TaskUpdate` — 跟踪每个 case 的进度

---

## 6. 输出

- 目录：`<feature_dir>/verify-cases/`
- 关键产物：`verify-summary.md`、`verify-receipt.json`、`case-tracker.json`、每个 case 子目录下的 `final-status.json` 与证据
- 状态：`PASS` / `PARTIAL` / `FAIL`，由 `verify-receipt.json.status` 体现
- 完整性保证：`e2e-case-tracker.sh check-complete` 返回 0
