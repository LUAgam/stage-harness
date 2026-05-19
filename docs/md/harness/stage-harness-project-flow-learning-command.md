# stage-harness 项目流程学习命令设计整理

## 背景

`stage-harness` 的初衷是一个**通用插件**：

- 不贴具体项目
- 不贴具体需求
- 内核能力可复用

但在真实使用中，如果后续要让 `stage-harness` 稳定支持某个具体项目的需求开发，仅靠通用的 `CLARIFY / PLAN / WORK / VERIFY` 还不够。原因不是需求分析不够，而是不同项目的实际执行方式差异很大：

- 业务源码组织方式不同
- 编译/构建入口不同
- 部署/热更方式不同
- 测试通道和测试证据不同
- 原项目里可能还有一层自己的工具壳，不一定能直接复用于 Claude Code 挂载 `stage-harness` 的运行方式

以 `ai-programmer-oms` 为例，项目里虽然已有 `generate_code.py`、`run_e2e.py`、`build_deploy.json` 等实现，但这些实现原本是围绕其自身的运行壳设计的，其中还包含对 Cursor/原有 session/原有 manifest 体系的依赖。`stage-harness` 不能简单把这些脚本原样拿来直接当成自己的标准流程。

因此，真正需要新增的不是“直接支持某个项目的 build/test”，而是一个新的**项目流程学习与 harness 化适配能力**。

## 需求收敛

需求可以收敛成一句话：

在 Claude Code 挂载 `stage-harness` 插件后，新增一个类似 `/stage-harness:harness-clarify` 的 slash 命令，先对某个具体项目做一次**项目流程学习与适配**；该命令扫描项目的业务源码、编译/构建脚本、部署脚本、测试脚本与相关实现，识别真实流程，再将其**改造成适合 `stage-harness` 使用的运行协议**并固化下来。之后再用 `stage-harness` 处理该项目的真实业务需求时，就可以直接复用这套固化好的 build/deploy/test 流程稳定执行。

这里有两个关键点：

1. 该命令不是普通的分析命令，而是**学习 + 适配**命令。
2. 后续真实需求开发时：
   - 需求分析和测试内容生成，仍然由 `stage-harness` 围绕当前需求动态完成
   - 但 build/deploy/test 的执行通道与证据规则，直接使用这个命令已经固化好的项目流程

## 调整后的定位

这个新命令的正确定位不是：

- `CLARIFY` 的子步骤
- `WORK` 里的补丁
- 某个项目的专用脚本入口

而是：

- 一个与 `/stage-harness:harness-clarify` 同风格的**独立 slash 命令**，**不进入** `CLARIFY / PLAN / WORK / VERIFY` **主状态机**（单次需求流程不强制经过本命令）
- 面向“项目级长期知识”，而不是“单个 Epic”
- 用来把项目原有流程翻译成 `stage-harness` 可接管的运行协议

可选命令名示例：

- `/stage-harness:harness-learn-project`
- `/stage-harness:harness-project-bootstrap`
- `/stage-harness:harness-project-flow`

在当前讨论里，`/stage-harness:harness-learn-project` 最符合语义：先学习项目，再固化为后续阶段可用的运行方式。

## 为什么不能直接复用原项目脚本

这个新命令的目标不是“记录项目里有哪些脚本”，而是“识别并改造项目流程”。

对 `ai-programmer-oms` 这类项目来说，原项目已有实现里通常混了两层东西：

1. **项目真实流程知识**
   - 怎么 build
   - 怎么 deploy
   - 怎么 test
   - 成功证据看什么
2. **项目原有工具壳**
   - 原有 session/manifest 目录设计
   - 原有 Agent/LLM 调用方式
   - 原有 Cursor 风格的执行模型
   - 原有自动修复环路

`stage-harness` 真正需要复用的是第 1 层，而不是无条件复用第 2 层。

因此这个命令要做的不是“发现脚本并记录命令”，而是：

- 识别项目原有流程实现
- 把项目流程知识和原工具壳拆开
- 把前者抽象出来
- 再翻译成 `stage-harness` 在 Claude Code 插件环境下的运行方式

## 核心实现思路

这个命令的实现思路可以概括成四步。

### 1. 扫描项目真实流程

扫描目标项目中的：

- 业务主入口
- 构建/编译入口
- 部署/热更入口
- 测试生成入口
- 测试执行入口
- 配置入口
- 结果产物与证据文件
- 与 Agent/LLM/外部工具相关的运行壳

目标不是“列文件”，而是回答：

- 这个项目真实是怎么跑起来的
- build/deploy/test 各自的入口、前置条件和成功证据是什么

### 2. 归一化为项目原始流程模型

把扫描结果从项目源码层，归一化成统一结构；为支持复杂项目，**流程按多通道表达**（例如 `build_flows` / `deploy_flows` / `test_flows`，每项可含 `id` 与多条步骤），而不是单体 `build_flow` / `test_flow` / `deploy_flow`。同层还可包含：

- `artifact_flow`（产物与证据路径约定）
- `runtime_constraints`
- `tooling_shell_dependencies`

这一层仍然是“项目原本怎么跑”的中立抽象。

落实到 harness 运行协议时，**多步骤 / 多通道的显式交接**是 adapter 的必要契约组成部分，不能只靠步骤隐式顺序猜测数据流。每个 `step` 应支持（或语义等价的字段）`inputs`（上序产物以何键/路径注入本步）、`outputs`（本步对外暴露的键/路径）、`depends_on`（例如 deploy 依赖 build 的哪些输出、`VERIFY` 依赖哪一步）、`evidence_refs`（本步可复核证据的路径或引用，供 `VERIFY` 与断言绑定）。字段名实现可压缩，但语义须覆盖上述交接与依赖关系。

### 3. 适配为 harness 运行协议

这是最关键的一步。

要明确哪些原实现：

- 可直接复用为底层执行器
- 需要被 `stage-harness` 包装后再执行
- 必须被 `stage-harness` 自己替换

尤其是：

- 原项目中与 Cursor/原 Agent 调用方式强耦合的部分，不能直接继承
- 测试内容的生成责任应该从原项目 AI 壳迁移给 `stage-harness`
- 但项目已有的测试执行通道、构建通道、部署通道可以在适配后被 harness 复用

### 4. 固化为后续阶段直接可用的项目适配产物

最终产物不是普通说明文档，而是“后续 `CLARIFY / PLAN / WORK / VERIFY` 可以直接读取的项目流程定义”。

**完整闭环（数据生成 → 执行 → 结果解析）**应贯穿实现与文档：`stage-harness` 按当前需求生成测试载荷（及关联输入），按 adapter 约定的路径与 **JSON Schema** 写出 **JSON 文件**（`${HARNESS_TEST_CASES_FILE}`）；`WORK` 调用 adapter 中声明的通用执行器与原项目命令，注入标准变量；执行结束后 `VERIFY` 仅依据 `success_criteria` 中的 **`artifact_assertions` 等机器断言**（及与 `evidence_refs` 可对齐的采集结果）判定是否通过，**不得**依赖未结构化的自然语言验收句。

因此后续真实需求开发将变成：

- 前半段：harness 按当前需求做动态分析
- 后半段：harness 直接调用已固化好的项目 build/deploy/test 流程
- 测试内容：由 harness 围绕当前需求动态生成
- 测试执行：沿项目已适配好的执行通道完成

## 对 `ai-programmer-oms` 的理解示例

针对 `ai-programmer-oms`，该命令最终学到的重点不应只是“有哪些脚本”，而应是以下结论。

### 项目定位

- 当前仓库是 OMS 的工作流编排仓，不是单一业务实现仓
- 真实业务修改对象通常位于 `WORKING_DIR/workdir/*`
- 当前仓库的职责包括：
  - PRD 流程
  - 技术方案流
  - 跨仓执行
  - 构建热更
  - E2E case 生成与执行

### 构建与部署流程

- 顶层 build/deploy 入口是 `generate_code.py build-deploy`
- 具体 repo 级构建路由由 `build_deploy.json` 决定
- 底层构建脚本分布在 `script/**/*.sh`
- 支持本地构建与远程构建
- 成功证据不是单个退出码，而是：
  - `build_deploy/manifest.json`
  - repo 级 report
  - 部署日志与版本摘要

### 测试流程

- 顶层测试入口不是传统单测命令，而是：
  - `run_e2e.py generate-case-list`
  - `run_e2e.py execute-cases`
- 测试执行是 session 驱动的
- UI 场景依赖 Playwright
- 非 UI 场景依赖 `oms_test/ai-e2e/oms_e2e_tools/*`
- 测试成功证据包括：
  - case 级 `test_report.md`
  - case 级 `execution_result.json`
  - 汇总 `manifest.json`

### 需要被适配的部分

- 原项目中围绕 Cursor/原 Agent 的 case 生成与失败修复逻辑，不能作为 harness 的直接运行壳
- `stage-harness` 需要接管：
  - 当前需求的测试内容生成
  - 基于当前需求的验证策略选择
  - 最终 `WORK / VERIFY` 的阶段编排
- 原项目已有的 build/test 通道则可在适配后作为底层执行器继续使用

## 命令的核心产物

如果按当前思路实现，为了避免产物碎片化和知识腐化，这个新命令的产物应**强力收敛为两层**。不要生成无意义的中间扫描记录，所有输出只为“后续阶段可执行”服务。

### 1. 机器执行层（核心执行契约）

例如：`project-harness-adapter.json`

这是最核心的产物，后续阶段（`CLARIFY / PLAN / WORK / VERIFY`）直接消费它。

**Adapter 版本与人工修改保护**：顶层必须包含 `schema_version`，用于 harness 侧解析与演进兼容；**人工对 adapter / profile 的修正为权威来源**，内核不得把项目逻辑硬编码覆盖本地配置。协议升级时通过提升 `schema_version` 并文档化迁移说明收敛；实现侧应优先读取磁盘上已接纳的 adapter，而非静默覆盖。

**标准变量模板 / 注入协议（首版 canonical）**：命令行、`working_dir`、`success_artifacts` 路径、测试载荷输出路径等凡需与当次运行绑定的，统一使用下列占位符，由 harness 在执行前展开；**不再使用「或等价名」**：文档与 adapter 只应出现这一套名字。

- `${HARNESS_RUN_ID}`：当次运行标识
- `${HARNESS_WORK_ROOT}`：本 run 解析得到的仓库 / 工作区根（**禁止**在示例或推荐契约里用裸 `"."` 代替；若相对路径相对于工作区根，须写清为基于 `${HARNESS_WORK_ROOT}` 的解析规则）
- `${HARNESS_TEMP_DIR}`：当次临时与运行输出根目录（与会话目录的关系由实现定义，但变量名固定）
- `${HARNESS_TEST_CASES_FILE}`：harness 生成的 **JSON** 测试载荷文件路径

凡使用上述变量的通道，adapter 中应声明依赖，避免静默缺参。

**测试内容 harness 生成、原通道执行的交接契约**：首版 **唯一**机器格式为：**`test_payload_schema` 必须是 JSON Schema**；harness 生成的载荷为 **JSON 文件**，路径即 `${HARNESS_TEST_CASES_FILE}`。执行步骤通过 `command` 引用该变量交给项目侧命令。项目专有 executor 名称不得出现；执行侧统一为**通用白名单执行器思路**，例如 `shell` / `make` / `npm` / `python_script` 等（实现可为字符串 `executor_type` + 参数对象），由 harness 映射到具体调用方式。

**成功判定（机器可断言）**：每个通道除 `success_artifacts`（预期产物路径，可含变量）外，`success_criteria` **必须**为结构化断言，**禁止**嵌入自然语言判定句（如「报告摘要规则」「按项目字段名映射」）。首版推荐形态为 `artifact_assertions`：**数组**；每项**显式绑定** `artifact`（产物路径或 harness 约定的步骤元数据键，如进程退出码绑定到约定字面量 `@step`）；`assertions` 数组内仅允许声明式断言类型，例如 `json_path_equals`、`json_path_all_in`、`file_must_exist`、`exit_code_equals`（类型名与字段以实现 schema 为准，但须可机械执行）。

**VERIFY 独立性**：`VERIFY` **不能**仅以项目命令在终端自报「成功」为充分条件。`success_criteria` 与 `evidence_refs` 须至少能关联到 **一类可复核证据**（例如结构化日志路径、manifest、外部 run id、产物内容哈希、execution summary 文件等），由 harness 按断言解析；证据应来自落盘或可追溯元数据，**避免**仅依赖 adapter 内一段不可机验的自证描述。以上为通用协议要求，**不做**项目特判。

它必须包含确定性的 Schema，明确后续阶段如何调用。例如（示意，字段以可执行为目标）：

```json
{
  "schema_version": "1",
  "project_type": "workflow_orchestrator",
  "build_flows": [
    {
      "id": "default",
      "steps": [
        {
          "id": "build-default",
          "executor_type": "python_script",
          "command": "python generate_code.py build-deploy",
          "working_dir": "${HARNESS_WORK_ROOT}",
          "inputs": {},
          "outputs": { "build_manifest": "${HARNESS_TEMP_DIR}/build_deploy/manifest.json" },
          "depends_on": [],
          "evidence_refs": ["${HARNESS_TEMP_DIR}/build_deploy/manifest.json"],
          "required_env": ["WORKING_DIR", "BUILD_DEPLOY_CONFIG_FILE"],
          "success_artifacts": ["${HARNESS_TEMP_DIR}/build_deploy/manifest.json"],
          "success_criteria": {
            "artifact_assertions": [
              {
                "artifact": "@step",
                "assertions": [{ "type": "exit_code_equals", "value": 0 }]
              },
              {
                "artifact": "${HARNESS_TEMP_DIR}/build_deploy/manifest.json",
                "assertions": [{ "type": "file_must_exist" }]
              }
            ]
          }
        }
      ]
    }
  ],
  "deploy_flows": [],
  "test_flows": [
    {
      "id": "e2e",
      "test_generator": "harness",
      "steps": [
        {
          "id": "e2e-execute",
          "executor_type": "python_script",
          "command": "python run_e2e.py execute-cases --cases-file ${HARNESS_TEST_CASES_FILE}",
          "working_dir": "${HARNESS_WORK_ROOT}",
          "inputs": { "cases_file": "${HARNESS_TEST_CASES_FILE}" },
          "outputs": { "e2e_manifest": "${HARNESS_TEMP_DIR}/e2e_case_execution/manifest.json" },
          "depends_on": [{ "flow": "build_flows", "id": "default", "step_id": "build-default" }],
          "evidence_refs": [
            "${HARNESS_TEMP_DIR}/e2e_case_execution/manifest.json",
            "${HARNESS_TEMP_DIR}/e2e_case_execution/execution_summary.json"
          ],
          "test_handoff": {
            "payload_path_env": "HARNESS_TEST_CASES_FILE",
            "payload_output": "${HARNESS_TEST_CASES_FILE}",
            "test_payload_schema": {
              "$schema": "https://json-schema.org/draft/2020-12/schema",
              "type": "object",
              "required": ["run_id", "cases"],
              "properties": {
                "run_id": { "type": "string" },
                "cases": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "required": ["id"],
                    "properties": { "id": { "type": "string" } }
                  }
                }
              }
            }
          },
          "success_artifacts": ["${HARNESS_TEMP_DIR}/e2e_case_execution/manifest.json"],
          "success_criteria": {
            "artifact_assertions": [
              {
                "artifact": "@step",
                "assertions": [{ "type": "exit_code_equals", "value": 0 }]
              },
              {
                "artifact": "${HARNESS_TEMP_DIR}/e2e_case_execution/manifest.json",
                "assertions": [
                  { "type": "file_must_exist" },
                  { "type": "json_path_all_in", "path": "$.cases[*].status", "values": ["passed"] }
                ]
              },
              {
                "artifact": "${HARNESS_TEMP_DIR}/e2e_case_execution/execution_summary.json",
                "assertions": [{ "type": "file_must_exist" }]
              }
            ]
          }
        }
      ]
    }
  ],
  "shim_scripts": []
}
```

**说明**：`@step` 为 harness 约定的字面量，绑定**由执行器采集**的本步进程退出码（非项目脚本打印的「成功」文案）。

它明确了：
- 哪些原流程保留，哪些原流程被替换
- 哪些步骤由 harness 负责生成，哪些步骤由项目已有实现负责执行
- 各 step 的 `inputs` / `outputs` / `depends_on` / `evidence_refs` 如何表达通道间交接与 VERIFY 取证范围
- 哪些产物作为成功证据，以及如何通过 `artifact_assertions` 机验

**胶水代码（Shim/Glue）机制（边界）**：

- **优先不用 shim**：尽量通过通用执行器 + 标准变量 + 项目已有 CLI 完成对接。
- **必须使用时**：仅做参数/格式转换（如路径、env、stdin/stdout 包装），**禁止**在 shim 内实现业务逻辑状态机或需求级编排。
- **异步与外部任务**：允许最基础的等待/轮询（如等待外部 CI 任务完成），但**不得**把复杂多步编排塞进 shim；复杂编排应留在项目自有工具或 harness 主流程，而非 shim。
- 若需生成脚本，仍放在 `.harness/shims/` 等约定目录，保持对业务源码的**零侵入**。

**Re-learn / 防覆盖**：当仓库已存在 `project-harness-adapter.json` / `project-flow-profile.md` 时，学习命令**不得静默覆盖**；应写出候选文件（例如 `project-harness-adapter.json.new`、`project-flow-profile.md.new`），由人工 diff 后接纳或合并，再作为权威配置。

**Dry-run / Validate（必须可机执行）**：学习命令或 harness **必须**提供可调用、**机器可执行**的 validate / dry-run 能力（独立子命令、插件入口或等价 CLI 均可，但**不得**以「人工检查清单替代」）；至少应校验：adapter 与 `schema_version` 的 schema 合规、**变量闭合**（占位符集合与声明一致）、**`test_payload_schema` 作为 JSON Schema 可解析**、**`artifact_assertions` 结构合法**（已知断言类型、必填字段、`artifact` 绑定完整）。目标是在真实 `WORK` 前暴露协议错误。

**与 `project-flow-profile` / 更高层画像的关系**：`project-harness-adapter.json` 是 **执行协议**（`CLARIFY / PLAN / WORK / VERIFY` 的机器消费契约）；`project-flow-profile.md` 是 **人类摘要**（审阅、纠错入口与 Agent 速览）。二者与仓库内其他「项目画像 / 环境清单 / 工具壳说明」等**不在同一知识层次**——后者可作为学习阶段的线索，但**不得**用自然语言描述覆盖或替代 adapter 中的可执行字段，以免知识源冲突。

### 2. 人类可读摘要层

例如：`project-flow-profile.md`

作用：

- 帮助人工快速检查学习结果是否合理
- 给后续 Agent 提供快速上下文
- **人工修正入口**：明确指导用户，如果 AI 猜错了构建/测试入口，用户可以直接在这里和 `project-harness-adapter.json` 中进行手动微调。后续流程必须以当前硬盘上的配置为准；与 adapter 的 `schema_version`、通道 `id`、变量名约定保持摘要一致，便于审阅与版本对齐。

## 后续阶段如何使用该命令的产物

这是整个需求的核心闭环。各阶段对**新字段**的消费方式如下（在保持「需求分析与测试内容仍由 harness 动态生成、执行通道由学习产物提供」的前提下）。

### `CLARIFY`

不再临时猜项目怎么 build/test，而是读取项目适配结果来判断：

- 校验/读取 `schema_version`，确认 harness 支持该 adapter 版本
- 本次需求影响了哪些业务区域
- 会触发哪些 build/deploy/test **通道**（按 `build_flows` / `deploy_flows` / `test_flows` 的 `id` 与步骤描述选型，而非单体 flow 名）
- 后续需要哪类验证面，以及各通道依赖的标准变量（含 `${HARNESS_WORK_ROOT}` 等）、环境变量是否具备

### `PLAN`

基于项目适配结果，生成本次需求的：

- build 计划（对应选中的 `build_flows` 步骤与顺序）
- deploy 验证计划（`deploy_flows`）
- test 计划（`test_flows` + `test_payload_schema` 约束下的生成形态）

其中测试内容不是固化好的，而是由 harness 根据当前需求动态生成；生成结果须满足 adapter 中的 **JSON Schema** `test_payload_schema`，并序列化为 JSON 写入 `${HARNESS_TEST_CASES_FILE}`。

### `WORK`

执行时直接调用已固化好的项目流程：

- 展开标准变量（`${HARNESS_RUN_ID}`、`${HARNESS_WORK_ROOT}`、`${HARNESS_TEMP_DIR}`、`${HARNESS_TEST_CASES_FILE}`），按各 step 的 `inputs` / `depends_on` 解析上序产物，走 adapter 中选定的 build/deploy **多通道**步骤
- 按 `test_handoff` 写出符合 schema 的测试载荷，再经 `executor_type`（如 `python_script` / `shell` / `npm` / `make`）调用项目命令
- **结果解析**：收集 `success_artifacts` 与 `evidence_refs` 指向的路径，供 `VERIFY` 仅按 `success_criteria.artifact_assertions`（及 harness 对 `@step` 等约定键的采集结果）做机验

### `VERIFY`

按 adapter 中定义的证据与断言验收（**独立于**命令行自报成功）：

- 仅通过 `artifact_assertions` 执行声明式断言（如 `exit_code_equals`、`file_must_exist`、`json_path_equals`、`json_path_all_in`）；**禁止**依赖自然语言摘要规则
- 至少一类断言须绑定到 **可复核证据**（`evidence_refs`、`success_artifacts` 声明路径等 harness 可打开的落盘物），例如 manifest、summary、日志、外部 run id 记录等，避免「只信终端一行 OK」
- 不再临时猜该项目的成功证据是什么；人工改过 adapter 的，以磁盘内容为准

## 关键边界

这个需求最容易跑偏的地方有三个。

### 1. 不能把项目逻辑硬编码进 `stage-harness` 内核

`stage-harness` 仍必须是通用插件。

因此：

- OMS 的特殊性不能写死在插件源码里
- OMS 的 build/test/deploy 细节只能存在于学习命令产出的项目适配结果中

### 2. 不能只做项目分析，不做 harness 化适配

如果只是“分析出 OMS 里有哪些脚本”，那只是项目画像，不足以支撑后续稳定执行。

必须继续完成：

- 去壳
- 抽象
- 适配
- 固化为 harness 运行协议

### 3. 不能在学习阶段固化未来所有测试内容

学习阶段固化的是：

- 如何生成测试
- 如何执行测试
- 如何验收测试

而不是未来每个需求的具体 case。

具体测什么，仍然应由后续需求阶段根据当前需求动态决定。

## 一句话结论

这个新命令的本质不是“扫描项目并记录 build/test 脚本”，而是：

在 Claude Code 挂载 `stage-harness` 插件的运行方式下，先学习某个项目原有的 build/deploy/test 实现，再把这些实现翻译并改造成 `stage-harness` 可直接接管的运行协议；之后真实业务需求开发继续由 harness 做动态需求分析和测试生成，但执行通道统一走已经固化好的项目流程。
