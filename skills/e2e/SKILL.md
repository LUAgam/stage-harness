# SKILL: e2e

> **核心原则**：
> 1. 测试范围跟着本次变动走。后端接口改了，对应的前端流程必须做联调验证；与本次需求无关的功能不测。对于涉及算法、转换准确率等质量敏感型需求，需额外生成专项质量测试。
> 2. **覆盖完整性优先于执行便利性**。不得以"链路复杂"、"需要外部依赖"为由跳过本次变动相关的用例；凡是受变动影响的接口和 UI 流程，都必须生成真实调用/操作用例。
> 3. **UI 测试必须模拟真实用户操作**（定位元素、点击、键入、等待渲染、断言可见文本/状态）。**禁止**将 UI 套件退化为浏览器上下文里的 `page.evaluate(fetch(...))` API 验证——那只是把 API 测试换了执行环境，没有额外价值，不算 UI 测试。
> 4. **通用性**：本 skill 不假设具体业务域，所有规则均以抽象变动面（文件、接口、页面、用户动作）为单位组织，不针对任何特定项目的数据库/领域词汇。
> 5. **E2E 套件必须验证运行时行为**。严禁把"读取源码/配置文件并做字符串/结构匹配"的检查封装成独立 E2E 套件——这类检查属于 lint / unit / code-review 阶段，不能占 E2E 名额。判定一条用例是否为运行时用例，看它是否**实际调用了被测系统对外的可观测面**：HTTP 接口返回值、CLI 退出码与输出、UI 上的 DOM 变化、消息队列消息、数据库读写结果、文件系统产物变化、外部服务的观测信号。只触发"文件读取 + 字符串断言"而未触发任何上述观测面的用例，不计入 E2E 覆盖。
> 6. **优先复用项目级质量技能**。当项目内已存在可调度的质量/准确率/一致性验证技能（skill / agent / 脚本），且其能力与当前变动的质量属性契合时，质量套件必须通过**编排/委托**方式调用该已有能力，不得在 E2E 层重写同类逻辑。项目级技能的发现与匹配规则见 Step 1。
> 7. **UI 全程截图证据强制**。每条 UI 用例必须在每个关键交互节点（导航完成后、关键点击/键入后、最终断言前后）截图保存到 `tests/e2e/artifacts/<epic_id>/<case_id>/`，**无论用例 PASS 还是 FAIL** 都必须保留这些截图作为证据。仅在失败时截图、或整个用例不产任何截图，均视为不合格 UI 用例。
> 8. **流程默认全自动，仅登录凭证缺失时允许中断；认证凭证严禁伪造**：整个 E2E 流程默认不消耗中断预算、不向用户发起追问。**例外**：当被测系统或质量套件依赖的登录态 / 鉴权凭证缺失或过期（典型表现：MCP / API 持续 401、CLI token 文件失效、需要短信验证码或 OAuth 授权等仅用户能提供的信息），允许消耗 1 次中断向用户索取登录所需信息（手机号 + 短信验证码 / 用户名密码 / token 等），完成登录后继续执行；同一次 E2E 执行内最多中断 1 次，超过后按降级路径处理（套件 `skip:true` + `coverage.excluded` + `needs_owner_review:true`）。**严禁**自行伪造、编造、猜测 JWT token 或任何认证凭证——无论何种场景，凭证只能来自用户提供或系统已有的有效会话，此规则无例外。**非登录类**的边界情况（项目级质量技能未命中、套件配置缺失、套件命令调整、跳过原因、阈值微调等）一律取默认行为并写 `needs_owner_review: true`，**不中断**。登录信息只用于本次 skill 调度，不得持久化扩散到无关位置。
> 9. **部署环境端口主动探测（硬性前置）**：在生成测试用例和执行测试之前，必须主动探测真实部署环境的前后端服务端口和接口地址。**禁止**硬编码端口号（如 `localhost:8666`）。探测方式：优先从 `deploy-receipt.json` 读取实际部署的服务地址和端口；若无记录，则通过 `docker ps`、`docker-compose ps`、`ss -tlnp`、`netstat -tlnp` 等手段扫描实际监听端口；探测结果必须写入 `e2e-cases.json.test_environment` 字段，所有测试用例的请求地址从该字段动态获取，不得使用字面量。⚠️ **注意：不同项目（前端/后端）的部署形式各异，绝不可假设仅有 Docker 部署。** 前端可能由 nginx/Apache 托管静态文件、PM2 运行 Node.js SSR、CDN/OSS 直接提供；后端可能以裸进程（`java -jar`、`python`、`go`）运行、通过 systemd/supervisord 管理、或部署为 war 包。探测必须全面覆盖：`deploy-receipt.json` → `docker ps`/`docker-compose ps` → `ss -tlnp`/`netstat -tlnp` → `systemctl list-units` → `pm2 list` → `ps aux | grep` → nginx/Apache 配置检查。
> 10. **Playwright 不可用时必须尝试替代方案**：当 Playwright MCP 工具不可用时，**禁止直接跳过 UI 测试套件**。必须按以下优先级尝试替代：① Python + playwright 库 + 真实浏览器；② Python + selenium + 浏览器驱动；③ 其他可用的浏览器自动化方案。仅当所有替代方案均不可用时，才允许将该套件标记为 `skip: true` 并在 `coverage.excluded` 中详细记录已尝试的所有替代方案及其失败原因，同时设置 `needs_owner_review: true`。
> 11. **质量/准确率测试必须完整执行**：对于涉及转换准确率、一致性、精度等质量验证的测试用例，**无论时间多长、成本多高，都必须对全部样本逐一执行，不得抽样、截断或提前终止**。quality 套件不受 60 分钟默认超时限制（默认 180 分钟，可通过 `timeout_minutes` 覆写为更大值），且禁止以"时间过长""成本过高"为由跳过任何样本。

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

E2E 阶段端到端测试技能。生成测试用例，执行各测试套件，解析结果，写 e2e-receipt.json，返回 PASS 或 FAIL。

---

## 触发条件

- 当前 epic state = `E2E`
- 收到 `/stage-harness:harness-e2e` 命令
- 从 FIX 阶段回流后重新测试

---

## 核心概念：测试套件列表

E2E 测试围绕**本次需求变动范围**展开，不是全量回归。套件按"验证对象 + 是否为运行时验证"划分为三类，**仅以下三类允许作为独立 E2E 套件**：

- **API 套件**：通过真实 HTTP/RPC/CLI 调用被测系统，断言对外契约（状态码、业务字段、错误码）
- **UI / 联调套件**：真实浏览器或端上客户端执行用户动作，断言 DOM / 页面状态 / URL / 可见文本；后端接口变动时**必须**同步覆盖对应前端路径（即使前端代码未改动）
- **质量套件**：算法、数据转换、格式转换、准确率、一致性、性能等**结果正确性**类需求，必须驱动完整运行时链路产出结果并断言阈值

**不得作为独立 E2E 套件的形式**（放入对应阶段，不占 E2E 名额）：

| 形式 | 实际归属 |
|------|---------|
| 读取源码 / 配置 / JSON / 模板文件，断言字段存在、字符串出现、键值相等 | unit / lint / code-review |
| 静态 AST / 正则扫描产物 | unit / lint |
| 纯内部方法单测（不过对外接口） | unit |
| 纯 schema 校验（不触发运行时消费） | unit / contract-test |
| 将上述内容包成 pytest 然后命名为 `regression` / `static` 套件 | 仍不允许；必须移回 unit |

> 判定口诀：**"杀掉被测服务进程 / 部署，这条用例还能 PASS 吗？"** 如果还能，就不是 E2E。

`project-profile.yaml` 中用 `e2e_suites` 列表描述：

```yaml
e2e_suites:
  - name: api           # 后端接口功能验证
    command: "pytest tests/e2e/test_api.py -v"
    framework: pytest
    skip: false

  - name: ui            # 前后端联调验证（后端改动时必须包含）
    command: "pytest tests/e2e/test_ui_<epic_slug>.py -v --tb=short"
    framework: pytest
    requires_browser: true
    skip: false

  - name: quality       # 质量/准确率专项（触发条件：spec 含准确率/性能阈值或新增可端到端消费的目标方言/类型）
    command: "<调用项目级质量技能或编排脚本的命令>"
    framework: pytest | skill | script
    skip: false
    delegates_to: "<项目级技能名或脚本路径，若为编排型套件>"  # 用于追溯
    quality_metrics:    # 质量指标阈值（必须显式声明）
      accuracy_threshold: 0.95
      performance_p99_ms: 3000
```

兼容旧格式：若只有顶层 `e2e_command`（无 `e2e_suites`），将其视为单套件 `name = "main"`。

---

## 执行流程


### Step 1 — 生成测试用例

**REQUIRED AGENT:** 调用 `e2e-generator` agent

传入：`epic_id`、`scenarios_path`、`spec_path`、`e2e_suites`

#### 端到端动作清单（硬性前置）

生成任何用例前，**必须**先列出"本次变动让用户首次能完成 / 改变行为的端到端动作清单"，落盘到 `e2e-cases.json.end_to_end_actions`。

**动作定义**：用户在产品对外入口发起的一次完整旅程 = 入口（页面 / CLI / API 消费方）→ 触发动作（点击 / 提交 / 调用）→ 结果可见面（结果页 / Toast / 状态变化 / 文件产物）。

**清单来源（两源交叉，取并集）**：

1. **需求侧锚点**：从 spec / PRD / scenarios / AC 中提取动词短语。重点关注"用户可…""能…""支持…""触发…""在…看到…"等句式，每个动词短语对应一个候选动作。
2. **代码侧锚点**：对每个 `change_surface` 条目，沿运行时调用链向下游遍历到产品对外入口（HTTP route / UI 路由 / CLI 命令 / 消息消费方），抵达入口即记为一个候选动作。

**强制覆盖**：每个动作 ≥ 1 条 UI 用例，从浏览器内的真实操作驱动到结果可见面。**不允许**用 API 用例替代、**不允许**拆成多条点状 UI 用例（仅断言下拉 / Header / 徽标）顺带覆盖。

**落盘字段**：

```json
"end_to_end_actions": [
  {
    "action_id": "ACT-001",
    "name": "<动词短语，如 submit-sqlserver-to-pg16-conversion>",
    "source": ["requirement: <FR-id 或 spec 引用>", "code: <change_surface_id>"],
    "entry": "<入口路径，如 /app/project_manager → AddTaskModal>",
    "result_surface": "<结果可见面，如 /app/task_detail 目标 SQL 区域>",
    "covered_by": ["UI-XXX"]
  }
]
```

**门禁**：`end_to_end_actions[*].covered_by` 任一为空，或所覆盖用例非 `test_type=ui`，视为 FAIL，`failed_suites` 追加 `"e2e-action-coverage"`，触发 FIX。

#### 变动范围自动感知

agent 在生成用例前，先自动提取本次变动范围，**无需外部传入 changed_files**：

```bash
# 优先从 BUILD 阶段产物读取
cat .harness/features/<epic-id>/build/build-receipt.json | jq '.changed_files'

# 兜底：从 git diff 提取（与上一个 tag 或 main 分支对比）
git diff --name-only HEAD~1 HEAD 2>/dev/null || git diff --name-only origin/main HEAD
```

提取到变动文件后，**必须**生成一份"变动面枚举清单"（change-surface inventory），作为用例生成的强制锚点：

| 维度 | 从变动文件提取的内容 | 本次用例的覆盖责任 |
|------|--------------------|------------------|
| 后端接口 | 每个被改动的路由/控制器方法对应的 HTTP 端点（path + method）及其消费/生产方 | 每个端点至少一条真实 HTTP 调用用例，断言业务结果（不仅 200） |
| 后端服务/领域方法 | 被改动的 service/domain 类的公共方法 | 通过入口端点或专项集成路径触发，断言行为契约 |
| 配置/注册表 | 被改动的配置文件/注册点（json/yaml/常量表） | 通过消费该配置的接口或页面验证新增/修改项生效 |
| 前端页面 | 被改动或被接口牵动的页面/组件路径 | 每个页面至少一条 UI 用例，模拟用户到达该页面并完成核心操作 |
| 前端数据源 | 被接口变动牵动的前端数据拉取点 | 通过 UI 操作触发拉取并断言页面上的可见变化（非 API 回看） |
| 质量属性 | spec 中提到的准确率/一致性/性能阈值 | 专项质量用例，断言阈值 |

**清单必须落盘**到 `.harness/features/<epic-id>/e2e-cases.json` 的 `change_surface` 字段，后续覆盖率门禁据此核对。

#### 用例生成原则

基于变动面清单，按以下原则生成测试用例：

1. **接口全覆盖**：对清单中列出的每个后端接口，**至少生成一条真实 HTTP 调用用例**。不允许以"链路较深"、"需要组合多个接口"为由省略。组合链路（例如创建→查询→操作→结果）应作为一条端到端用例覆盖，而不是跳过。
2. **后端驱动联调**：后端接口有变动，**必须**同时覆盖该接口对应的前端操作路径——真实浏览器里由用户动作触发，验证页面上的可见状态变化。前端代码是否改动不影响此判断。
3. **UI 真实交互强制 + 一组件一用例**：UI 用例的断言对象必须是 **DOM 元素可见性 / 文本内容 / 表单状态 / URL 变化 / toast/modal 出现**，不能是浏览器里手动 `fetch()` 回来的 JSON。**变动面归属判定规则**：
   - 凡是用户在浏览器里能看到、能点到、能填写、能选择、能感知的变动（页面元素、下拉项、表格行、按钮文案、跳转流程、错误提示等），**全部必须**有 UI 用例覆盖，禁止以"API 已经覆盖了"为由不写 UI 用例。
   - 仅当某变动只发生在后端、没有任何用户可见面（如内部数据迁移、定时任务、纯日志/审计字段）时，才可不出现在 UI 套件，由 API 套件独立覆盖。
   - 不存在"该变动有用户可见面，但因为 API 已断言所以不写 UI"的合法路径。这是底线规则。
   - **每条 UI 用例只允许有一个主断言可见面**：下拉选项 / Header 文案 / 列表行 / Toast / 详情页字段 任选其一；同一变动牵动 N 个独立可见位置，就生成 N 条 UI 用例，禁止多组件"顺带验证"挤进一条流程用例。
   - **"用户可见" 类 AC**（含"展示 / 显示 / 可见 / 标签 / 下拉 / 列表 / 详情 / 提示 / 按钮文案" 等关键词）必须各自独立成 UI 用例；不允许多条该类 AC 被同一条 UI 用例同时 covers 而仅断言其中一条。
   - **后端反查穷尽**：endpoint / config_entry / display-name 等改动必须 grep 出所有前端消费点（页面、组件、Header、Badge、列表列、详情字段、Drawer、Toast 文案等），每个消费点登记为独立 ui_component 并各自配 1 条 UI 用例；反查不彻底视为生成不合格。
4. **范围收敛**：与本次变动无交集的功能不生成测试用例，避免无意义的全量回归。
5. **质量测试强制**：命中 质量套件触发条件（spec 含准确率/一致性/精度/性能阈值；变动涉及 LLM 提示词/转换引擎/生成器/规则引擎/匹配算法/模型推理；新增可端到端消费的目标版本/方言/类型）任一时，**必须**生成质量用例。质量用例必须满足：
   - 驱动被测系统完整链路产出真实制品（转换结果、生成文件、推理输出、排序结果等）
   - 断言对象为"可观测的质量指标"：与期望结果的 diff / 数值误差 / 阈值比较 / 样本集通过率；**不得**只断言接口 200 或任务状态 `success`
   - 若项目内已有质量技能（项目级质量技能发现结果），用例的"method"必须是"调用该技能并采集其产物"，不得重写同类逻辑；用例需在 `covers` / `delegated_to` 字段显式记录所调度的技能名
   - 样本量、输入来源、阈值必须在用例描述中显式写出，避免空壳质量用例
6. **回归基线显式化**：若 spec 中的 AC 要求"某既有路径不回归"（例如旧版本路径保持原行为），须为其生成独立用例，而不是默认已有测试覆盖。
7. **运行时性强制**（新增硬性约束）：任何 E2E 用例都必须触发至少一次"对被测系统对外可观测面的真实消费"——HTTP/RPC/CLI 调用、UI 用户动作、文件产物生成、下游消息等。**禁止**把"读取源码文件 / 配置文件并做字符串或结构断言"命名为一条 E2E 用例；此类检查移入 unit / lint，并在 `e2e-cases.json.moved_to_unit` 中登记，不占 E2E 覆盖名额。

每个用例必须包含 `test_type`（`api` / `ui` / `quality`；**不再接受 `unit` 作为 E2E 用例类型**）、`purpose`（测试目的）、`method`（测试方法）字段，以及 `artifacts_dir`（中间产物目录）、`covers`（覆盖的 FR/AC/变动面条目 ID 列表）。若用例为编排型（委托给项目级技能），另需 `delegated_to`（技能/脚本名）和 `metrics`（断言的质量指标及阈值）。

#### 覆盖率门禁（硬性）

用例落盘前，agent **必须**自行执行覆盖率核对并写入 `coverage_report` 字段：

- **端到端动作清单**：`end_to_end_actions[*].covered_by` 不得为空，且所引用的 `case_id` 必须是 `test_type=ui` 的用例；若动作仅被 api / quality 用例覆盖，视为未覆盖
- 变动面清单中每一项的 `covered_by`：列出覆盖它的 `case_id`；若为空，用例生成不通过
- 变动面中每一项的 `covered_by` 所指向的用例，**至少有一条是运行时用例**（api / ui / quality）；若某变动面只被静态断言用例"覆盖"，视为未覆盖
- spec 中每条 AC 的 `covered_by`：列出覆盖它的 `case_id`；若为空且该 AC 非"纯静态文件/离线脚本校验"，用例生成不通过
- 上述质量套件触发条件命中时，`coverage_report` 必须包含 `quality_suite_present: true` 以及 `quality_skill_reuse` 字段（若有项目级技能则填技能名，否则填 `"new"` 并附 `needs_owner_review: true`）

agent 输出 `coverage_report.gaps` 列出所有缺口（接口、页面、AC、质量阈值未覆盖）。门禁判定：
- `gaps` 非空 → agent 必须补齐用例后重新核对，不得直接落盘
- 若某缺口确实不在 E2E 职责范围（例如纯爬虫产物校验、git diff 层面字节级不变），须显式写入 `coverage_report.excluded` 并注明原因与归属阶段（unit / code-review / lint / 其他）

#### 用例落盘要求

**e2e-cases.json 必须在测试文件生成之前写入**，作为权威来源：

```
.harness/features/<epic-id>/e2e-cases.json
```

生成产物：
- `.harness/features/<epic-id>/e2e-cases.json`：结构化用例列表（先落盘）
- `tests/e2e/test_<epic_slug>.py`（或对应框架格式）：API/功能测试文件
- `tests/e2e/test_ui_<epic_slug>.py`：UI 测试文件（检测到前端时生成）
- `tests/e2e/conftest.py`：不存在时生成基础版本

**降级策略**：agent 失败时，使用已有测试文件直接执行，输出警告。

---

### Step 1.5 — 凭证门禁（条件触发 — 硬性）

#### 预扫描

1. 扫描 `e2e-cases.json` 中所有用例，识别哪些用例需要认证访问：
   - 用例的 `method` 或前置条件中包含认证相关描述
   - 用例的操作步骤涉及需要登录态的接口或页面
2. 按**凭证消费方式**将需要认证的用例分组为"凭证组"：
   - 同一组内的用例可以共享同一份凭证（相同的消费方式和目标服务）
   - 不同消费方式（如 API token vs 浏览器表单登录 vs CLI 认证）分为不同组
3. 检查 `<feature_dir>/verify-cases/session-state.json` 是否存在各组的有效凭证
4. 检查 `deploy-receipt.json` 中 `frontend.auth_required` 字段

分组原则（具体分组由被测服务的认证架构决定，不预设形式）：

| 凭证组 | 消费方式 | 典型场景 |
|--------|---------|---------|
| api_auth | HTTP Header / Cookie / Bearer Token | 后端 API 接口调用 |
| browser_auth | 在登录页面填写表单提交 | UI 测试的浏览器登录 |
| service_auth | CLI 登录 / 环境变量 / 配置文件写入 | 质量测试工具或外部服务认证 |

注意：不同项目的认证方式各异（OAuth、LDAP、SSO、API Key、用户名密码、
短信验证码、证书、SAML 等），预扫描只需识别"是否需要认证"和"消费方式是否相同"，
不预设具体的认证形式。

#### 凭证获取（条件触发）

预扫描完成后：

- **所有组的 case 数量均为 0**（项目无需认证）：
  跳过本阶段，直接写入门禁状态并继续执行，零摩擦。

- **存在需要认证的组，且 session-state.json 中已有该组的有效凭证**：
  复用已有凭证，该组无需中断。

- **存在需要认证的组，且无有效凭证**：
  1. 分析各组之间是否可共享凭证（同一服务的不同消费方式可能使用同一组登录信息）
  2. **调用 AskUserQuestion 一次性向用户索取所有需要的凭证信息**：
     - 列出哪些测试维度需要认证（及对应的 case 数量）
     - 说明每组需要什么类型的凭证（由被测服务决定，不预设形式）
     - 询问各组是否可使用同一组凭证
  3. 用户提供后，按组写入 `<feature_dir>/verify-cases/session-state.json`
  4. 用户部分拒绝 → 对应组的 case 标记 `skip: true`
     （reason: "用户拒绝提供凭证"），其余组继续，设置 `needs_owner_review: true`
  5. 用户全部拒绝 → 所有需要认证的 case 标记 skip，不需要认证的 case 继续执行

#### session-state.json 结构

```json
{
  "epic_id": "<epic-id>",
  "created_at": "ISO",
  "credential_groups": [
    {
      "group_id": "<标识>",
      "type": "<消费方式描述>",
      "obtained_at": "ISO",
      "expires_at": "ISO or null",
      "cases": ["TC-XXX", "TC-YYY"],
      "value": {}
    }
  ]
}
```

`value` 字段的内容由被测服务的认证方式决定，技能不预设结构。

#### 运行时认证失败中断

执行用例过程中遇到认证失败（HTTP 401/403、token expired、连接被拒、
认证握手失败等）：
- 识别失败属于哪个凭证组
- 若该组已有凭证但过期/失效 → 向用户索取该组的新凭证
- 若该组从未获取过凭证（预扫描遗漏）→ 向用户索取
- **每个凭证组最多触发 1 次运行时中断**，超过则该组剩余 case 标记 skip
- 不同组的中断互不影响
- 获取新凭证后更新 session-state.json 并重试当前用例

#### 禁止的绕过模式

以下行为均视为违反凭证门禁，触发 `failed_suites` 追加 `"auth-bypass"`：
- 用公开接口的返回结果推断需要认证的接口"应该也能通过"
- 在服务运行时环境内部直接执行业务逻辑绕过认证层
- 将需要认证的用例降级为"静态验证"（读取配置文件/代码）后标记通过
- 以"核心逻辑已验证"为由跳过真实接口调用
- 自行伪造、编造、猜测任何形式的认证凭证（token、密码、密钥、证书等）

#### 门禁状态写入

凭证阶段完成后，写入门禁：

```bash
E2E_TRACKER="$(dirname "$HARNESSCTL")/e2e-case-tracker.sh"
$E2E_TRACKER gate set <epic-id> credential_gate PASS \
  --field total_groups=<凭证组数量> \
  --field groups_resolved=<已获取凭证的组数量> \
  --field groups_skipped=<用户拒绝的组数量> \
  --field total_auth_cases=<需要认证的 case 总数> \
  --field skipped_for_no_credential=<因无凭证跳过的 case 数>
```

#### 门禁校验规则

| total_groups | groups_resolved + groups_skipped | 判定 |
|---|---|---|
| 0 | 0 | ✅ PASS — 项目无需认证，零摩擦通过 |
| N | == N | ✅ PASS — 所有凭证组已处理（获取或用户拒绝） |
| N | < N | ❌ INVALID — 有未处理的凭证组（未向用户索取） |

---

### Step 2 — 按套件顺序执行测试

对所有 `skip: false` 的套件依次执行，**不因单个套件失败而中止其他套件**（与部署不同，测试需要收集所有失败信息）：

```
[1/3] 执行 api...
[2/3] 执行 ui（Playwright，真实用户操作）...
[3/3] 执行 quality（按需）...
```

每个套件：
1. 执行命令，捕获 stdout / stderr / exit_code
2. 解析测试框架输出，提取 passed / failed / skipped 数量和失败用例列表

**UI 套件执行契约**（强制）：
- 必须使用 Playwright（或等价的真实浏览器驱动），通过 `page.locator()` / `page.get_by_*()` 等 API 定位元素
- 必须包含用户动作：`click` / `fill` / `press` / `select_option` / `check` 至少之一
- 断言对象：`expect(locator).to_be_visible()` / `to_have_text()` / `to_have_value()` / 页面 URL 变化 / toast/modal 出现等真实用户可见状态
- **禁止**一个 UI 用例内仅包含 `page.goto()` + `page.evaluate("fetch(...)")` + JSON 断言。若发现此类用例，视为不合格，须改为真实交互或移入 API 套件
- **全程截图证据强制**：每条 UI 用例必须在以下节点都截图保存到 `tests/e2e/artifacts/<epic_id>/<case_id>/`，**PASS 与 FAIL 都保留**：
  1. 页面首次加载完成后 `01_loaded.png`
  2. 每个关键用户动作执行后（点击/填表/选择）`NN_<action>.png`，按时序编号
  3. 最终断言通过/失败前后 `99_final_<pass|fail>.png`
  失败时**额外**抓取 `page.content()` 写入 `dom_at_failure.html`，以及 Playwright trace（`tracing.start/stop` 或 `--trace=on`）
- 用例不产生任何截图，或仅在失败时截图，视为不合格 UI 用例，`failed_suites` 追加 `"ui-evidence"`

**Quality 套件执行契约**（强制）：
- 必须驱动被测系统完整链路产出真实制品（转换结果 / 生成内容 / 推理输出 / 排序产物等），断言对象是"可观测的质量指标"。只断言任务状态 `success`、只检查接口 200、只比较日志字符串，均不合格。
- 若 项目级质量技能（扫描 .claude/skills、Makefile、scripts/、package.json scripts、pyproject.toml task runner 后）匹配到，`command` 必须是"驱动该技能并收集其产物的命令"，不得绕过该技能写平行脚本
- 必须落盘以下产物到 `tests/e2e/artifacts/<epic_id>/<case_id>/`：
  - 输入样本清单（含样本来源、规模、选取理由）
  - 被测系统实际输出的制品
  - 期望/基线（若存在）及差异报告
  - 指标计算过程（准确率 / 一致性 / 延迟等），以机器可读格式（JSON / YAML）保存
- 所有阈值必须**显式**从用例或 `project-profile.yaml` 的 `quality_metrics` 读取，不得硬编码在测试代码中；最终断言必须对比"实测值 vs 声明阈值"
- 单样本失败不代表套件 FAIL：若声明了 `accuracy_threshold`，按通过率断言；若未声明，默认"全部样本必须通过"

**套件合法性运行时校验**（对 api / ui / quality 三类套件均适用）：
- 每个套件必须在执行过程中产生至少一次"对被测系统的真实交互证据"（HTTP 请求日志 / 浏览器 trace / 质量制品 / CLI 输出等）
- 若执行完毕后 `artifacts_dir` 为空，或仅含纯静态读取日志，视为不合格套件，`failed_suites` 追加 `"runtime-contract"`

**中间产物管理**：
- 每个用例的中间产物（截图、响应体、trace、质量制品、日志）必须存放在 `tests/e2e/artifacts/<epic_id>/<case_id>/` 下，**`<epic_id>` 一级目录强制存在，不可省略**
- UI 测试失败时，测试代码负责截图并保存到对应 `artifacts/<epic_id>/<case_id>/` 目录
- 所有产物路径必须在项目工作目录内，禁止写入 `/tmp/`、`/var/`、`/root/` 等系统路径
- **多需求隔离强制**：禁止任何用例直接写入 `tests/e2e/artifacts/<case_id>/`（缺少 epic 一级），也禁止跨 epic 复用产物目录。这是为了避免多个并行需求开发时中间产物互相覆盖、混淆审计证据
- `<epic_id>` 取自 `harnessctl epic show` 返回的 id，禁止用 slug 或别名替代；测试代码读取 `EPIC_ID` 环境变量或 `.harness/features/<epic_id>/state.json` 注入
- Step 3 执行器在调度每个套件前必须 `mkdir -p tests/e2e/artifacts/<epic_id>/`，并把 `EPIC_ID=<epic_id>` 注入子进程环境变量
- 套件执行完成后，若发现产物落到了 `tests/e2e/artifacts/<case_id>/`（无 epic 层级）或落到其他 epic 目录下，视为不合格，`failed_suites` 追加 `"artifact-isolation"`

`skip: true` 的套件直接记录为 SKIPPED。

---

### Step 3 — 写 e2e-receipt.json

写入 `.harness/features/<epic-id>/e2e-receipt.json`：

```json
{
  "epic_id": "<epic-id>",
  "status": "PASS | FAIL | SKIPPED",
  "started_at": "<iso8601>",
  "completed_at": "<iso8601>",
  "suites": [
    {
      "name": "api",
      "command": "<cmd>",
      "framework": "pytest",
      "status": "PASS | FAIL | SKIPPED",
      "total": 10,
      "passed": 10,
      "failed": 0,
      "skipped": 0,
      "failed_cases": [],
      "stdout": "<最后300行>",
      "skip_reason": ""
    }
  ],
  "total_passed": 20,
  "total_failed": 0,
  "total_skipped": 2,
  "failed_suites": [],
  "coverage": {
    "change_surface_total": 12,
    "change_surface_covered": 12,
    "ac_total": 25,
    "ac_covered": 23,
    "ac_excluded": 2,
    "gaps": []
  }
}
```

整体 `status`：
- 所有套件均无失败 且 `coverage.gaps` 为空 → `PASS`
- 任一套件有失败 → `FAIL`
- 覆盖率有未解释的缺口（`gaps` 非空）→ `FAIL`，`failed_suites` 中追加 `"coverage-gate"`
- 全部 SKIPPED → `SKIPPED`

---

### Step 4 — 生成 e2e-summary.md（必须执行）

所有套件执行完毕后，在 `.harness/features/<epic-id>/e2e-summary.md` 生成人类可读的测试总结报告。

报告格式：

```markdown
# E2E 测试总结 — <epic_id>

**执行时间**：<started_at> ~ <completed_at>
**整体结果**：PASS / FAIL / SKIPPED
**通过率**：<total_passed> / <total_passed + total_failed>（<百分比>%）

---

## 套件详情

### <suite_name>（<framework>）

| 指标 | 数值 |
|------|------|
| 状态 | PASS / FAIL / SKIPPED |
| 总用例 | N |
| 通过 | N |
| 失败 | N |
| 跳过 | N |

**执行命令**：`<command>`

#### 失败用例（若有）

| 用例名 | 失败原因 | 截图/产物 |
|--------|---------|----------|
| test_xxx | AssertionError: 期望 200，实际 422 | — |
| test_yyy | TimeoutError: 元素未在 5s 内出现 | tests/e2e/artifacts/<epic_id>/UI-003/screenshot_failure.png |

---

## 所有测试项

| 编号 | 套件 | 用例名 | 测试类型 | 测试目的 | 结果 |
|------|------|--------|---------|---------|------|
| 1 | api | test_create_resource | api | 验证创建接口返回 201 及正确的资源 ID | ✅ PASS |
| 2 | api | test_list_resources | api | 验证列表接口分页参数生效 | ✅ PASS |
| 3 | ui | test_page_loads | ui | 验证页面正常渲染，无 JS 错误 | ✅ PASS |
| 4 | ui | test_form_submit | ui | 验证表单提交后列表刷新并显示新条目 | ❌ FAIL |

---

## 中间产物

| 用例 | 产物路径 | 说明 |
|------|---------|------|
| UI-003 | tests/e2e/artifacts/<epic_id>/UI-003/screenshot_failure.png | 失败截图 |

---

## 跳过原因（若有）

- **<suite_name>**：<skip_reason>

---

## 结论

<若 PASS>：所有 <N> 条测试用例通过，本次变动验证完成。
<若 FAIL>：<N> 条用例失败，需修复后重新执行。失败集中在：<简要描述失败模式>。
```

若写文件失败，输出错误但不影响整体 E2E 阶段状态判断。

---

## 输出路径约束

**所有产物必须写入项目工作目录内**，禁止写入 `/tmp/`、`/var/`、`/root/` 等系统路径：

| 产物 | 路径 |
|------|------|
| 用例落盘 | `.harness/features/<epic-id>/e2e-cases.json` |
| 执行回执 | `.harness/features/<epic-id>/e2e-receipt.json` |
| 测试总结 | `.harness/features/<epic-id>/e2e-summary.md` |
| 测试文件 | `tests/e2e/test_<epic_slug>.py` 等 |
| 中间产物 | `tests/e2e/artifacts/<epic_id>/<case_id>/` |

---

## 输出

### 全部通过（PASS）

```
✅ E2E PASS
   api:      10/10 通过  [pytest]
   ui:        5/5  通过  [playwright]
   quality:  SKIPPED（未配置）
   产物:
     .harness/features/<epic-id>/e2e-receipt.json
     .harness/features/<epic-id>/e2e-summary.md
     tests/e2e/artifacts/<epic_id>/（按 epic 隔离的中间产物目录）
```

### 有失败（FAIL）

```
❌ E2E FAIL
   api:       3/10 失败
     - test_create_resource: AssertionError: 期望 201，实际 422
     - test_list_resources:  ConnectionError: 服务未响应
   ui:        1/5  失败
     - test_form_submit: TimeoutError: 按钮未在 5s 内出现
       截图: tests/e2e/artifacts/<epic_id>/UI-004/screenshot_failure.png
   产物:
     .harness/features/<epic-id>/e2e-receipt.json
     .harness/features/<epic-id>/e2e-summary.md
```

---

## 阻断条件

| 条件 | 说明 |
|------|------|
| `e2e_suites` 未配置且扫描无结果 | 提示配置后终止 |
| 任一套件有失败（failed > 0） | 写 FAIL receipt，触发 FIX，FIX 后从 BUILD 重新开始 |
| `coverage.gaps` 非空（存在未解释的变动面/AC 缺口） | 视为 FAIL，`failed_suites` 追加 `"coverage-gate"`，触发 FIX |
| UI 套件存在不含真实用户交互的用例（仅 `page.evaluate(fetch(...))`） | 视为 FAIL，`failed_suites` 追加 `"ui-contract"`，触发 FIX |
| UI 用例未产生关键节点截图（PASS / FAIL 均要求保留），或仅在失败时截图 | 视为 FAIL，`failed_suites` 追加 `"ui-evidence"`，触发 FIX |
| 端到端动作清单中存在 `covered_by` 为空、或被非 UI 用例覆盖的动作 | 视为 FAIL，`failed_suites` 追加 `"e2e-action-coverage"`，触发 FIX |
| 用户可见面变动只被 API 套件覆盖、未生成对应 UI 用例 | 视为 FAIL，`failed_suites` 追加 `"ui-coverage"`，触发 FIX |
| 同一变动有 N 个独立的用户可见位置（下拉/列表/Header/详情/Toast 等），但 UI 用例数 < N（被合并"顺带验证"） | 视为 FAIL，`failed_suites` 追加 `"ui-granularity"`，触发 FIX |
| endpoint / config_entry / display-name 改动的前端消费点反查不彻底（`change_surface[*].discovery` 缺失或与 grep 结果不一致） | 视为 FAIL，`failed_suites` 追加 `"change-surface-discovery"`，触发 FIX |
| 用例的 `covers` 中出现本次 `change_surface` 与 spec AC 列表之外的 ID（越界用例） | 视为 FAIL，`failed_suites` 追加 `"scope-creep"`，触发 FIX |
| 中间产物未落到 `tests/e2e/artifacts/<epic_id>/<case_id>/`（缺少 epic 层级，或落到其他 epic 目录） | 视为 FAIL，`failed_suites` 追加 `"artifact-isolation"`，触发 FIX |
| 存在"读取源码/配置文件并做字符串匹配"类用例被列入任何 E2E 套件 | 视为 FAIL，`failed_suites` 追加 `"runtime-contract"`，触发 FIX（该用例应移入 unit） |
| 质量套件触发条件命中但未生成 quality 套件，或 quality 套件仅断言任务状态/接口 200 | 视为 FAIL，`failed_suites` 追加 `"quality-gate"`，触发 FIX |
| 项目内存在可匹配的质量技能但 quality 套件未复用（被标记为在 E2E 层重写同类逻辑） | 视为 FAIL，`failed_suites` 追加 `"skill-reuse"`，触发 FIX |
| 写 receipt 失败 | 报告 IO 错误，终止 |

以下**不是**阻断条件，而是降级处理：
- 浏览器 / Playwright MCP 不可用 → **禁止直接跳过**。按优先级尝试替代方案：① Python + playwright 库 + 真实浏览器；② Python + selenium + 浏览器驱动；③ 其他可用的浏览器自动化方案。仅当所有替代方案均不可用时，才跳过该套件，继续其他套件（须在 `coverage.gaps` 中记录缺失的 UI 覆盖及所有已尝试替代方案的失败原因，并设置 `needs_owner_review: true`）
- 项目级质量技能所依赖的外部服务（如真库连接、LLM 服务）不可达 → 质量套件按 `skip: true` 处理并在 `coverage.excluded` 注明；同时输出 `needs_owner_review: true`，**不**自动降级为"包一层静态断言"

**降级策略下仍必须守住的门禁**：
- e2e-generator agent 不可用时，主流程必须自行执行"变动面枚举 → 用例生成 → 覆盖率核对"三步，并将结果落盘到 `e2e-cases.json`；不得直接跳到执行"已有测试文件"而放弃覆盖率评估
- 降级生成的用例同样必须遵守"UI 真实交互"、"接口全覆盖"、"运行时性强制"、"质量套件强制"四条强制规则
- 项目级质量技能可达性不确定时，仍应把调用命令写入套件 `command`，由 Step 3 执行阶段的真实失败信号来决定降级，而不是在生成阶段绕开

---

## FIX 回流后的重试策略

E2E 失败触发 FIX 后，修复完成需从 BUILD 重新开始，确保修复后的代码经过完整的编译 → 部署 → 测试链路。最多允许 3 轮 FIX 循环，超过后暂停等待人工干预。
