# AI-Programmer-OMS 流程梳理

本文整理仓库 `../ai-programmer/ai-programmer-oms` 当前实现的主流程，重点说明它是如何把一个需求推进成：

- PRD 草稿与最终 PRD
- 多仓技术方案与跨仓收敛
- 代码落地执行
- 构建、热更、失败后自动修复
- E2E 用例生成、执行与失败后自动修复

## 一句话结论

`ai-programmer-oms` 不是业务代码仓，而是一套围绕 OMS 场景的自动化工作流系统。

和 `stage-harness` 的统一阶段状态机不同，这个仓库更像三条串联流水线：

1. **需求侧 PRD 流程**
2. **技术侧方案/执行/构建流程**
3. **测试侧 E2E 生成/执行/修复流程**

这三条流程共享同一套 `session` 目录与运行产物。

## 1. 仓库定位与技术栈

从入口和依赖看，这个仓库的主运行方式是：

- Python 脚本编排
- Cursor `agent` 作为核心执行引擎
- 多代码仓工作目录由 `.env` 中的 `WORKING_DIR` 和 `CODE_REPOSITORY_URLS` 指定
- Playwright 主要用于页面类 E2E

关键入口：

- `generate_prd.py`
- `generate_code.py`
- `run_e2e.py`

核心任务目录：

- `app/tasks/`

关键基础配置：

- `.env`
- `build_deploy.json`

## 2. 总体分层

### 2.1 编排入口层

入口脚本负责把一系列 task 串起来：

- `generate_prd.py` 串需求侧流程
- `generate_code.py` 串技术侧流程
- `run_e2e.py` 串测试侧流程

### 2.2 任务执行层

`app/tasks/` 下每个文件代表一段稳定任务：

- `precheck.py`
- `init.py`
- `clarification.py`
- `draft_prd.py`
- `discussion.py`
- `summary_effect.py`
- `finalize_prd.py`
- `repo_tech_design.py`
- `cross_repo_tech_design.py`
- `execute_tech_design.py`
- `build_deploy.py`
- `generate_e2e_case_list.py`
- `execute_e2e_cases.py`
- `auto_repair.py`

### 2.3 执行引擎层

绝大部分高层分析、文档生成、代码修改、失败修复都不是 Python 代码自己完成，而是通过：

- `run_cursor_agent(...)`
- `run_cursor_agent_session(...)`

把 prompt 交给 Cursor Agent。

所以这个项目的 Python 代码主要负责：

- 组织输入输出路径
- 检查前置条件
- 串联阶段顺序
- 读写 `manifest.json`
- 管理失败后的自动重试和自动修复循环

## 3. 运行时核心概念

### 3.1 Session

每次运行以一个 session 为中心，目录位于 `RUNS_DIR` 下，例如：

```text
runs_xxx/
```

每个 session 下按阶段生成子目录，比如：

- `clarification/`
- `prd/`
- `discussion/`
- `summary_effect/`
- `code/`
- `code_review/`
- `execution/`
- `build_deploy/`
- `e2e_test_case_list/`
- `e2e_case_execution/`

### 3.2 工作区

代码不是在当前仓库里改，而是在 `.env` 指定的：

- `WORKING_DIR`

下克隆/切换目标代码仓库。

### 3.3 知识库

知识库目录由 `.env` 中的：

- `KNOWLEDGE_BASE_DIR`

指定，默认就是仓库内的 `knowladge/`。几乎所有 PRD、方案、E2E 生成任务都要求优先使用其中的：

- `官方文档`
- `迁移链路各环节现状说明`
- `部分代码特殊机制说明`
- `工程约束与注意事项`

## 4. 流程一：PRD 需求侧流程

入口：

```bash
python generate_prd.py start
python generate_prd.py apply-clarification --reply-file answer.md
python generate_prd.py merge-final --product-reply-file answer.md
python generate_prd.py auto
```

这条流程的目标是把原始需求收敛成最终 PRD。

### 4.1 `precheck`

入口在 `generate_prd.py start` 中首先执行。

作用：

- 检查 `.env` 是否存在
- 检查关键配置是否齐全
- 检查 `agent`、`git`、必要时 `ssh` 是否存在
- 检查 `WORKING_DIR` 父目录可写
- 检查 `ORIGINAL_REQUIREMENT_FILE_PATH` 是否有效
- 检查知识库目录是否有效

失败时直接阻断，不进入后续流程。

### 4.2 `init`

`run_init_task()` 负责：

- 读取 `CODE_REPOSITORY_URLS`
- 克隆目标仓库到 `WORKING_DIR`
- 切换到 `WORKING_BRANCH`
- `fetch + checkout + pull --ff-only`

所以 PRD 流程虽然叫“需求侧”，但会提前把代码仓准备好，供后续需求分析和 PRD 生成参考。

### 4.3 `clarification`

这一段先做“前置澄清”，不是直接写 PRD。

产物目录：

- `runs_xxx/clarification/`

核心产物：

- `questions.md`
- `questions.json`
- `answer_template.md`
- `answer.md`
- `reply_coverage_report.md`
- `clarified_requirement.md`
- `manifest.json`

分两步：

1. `run_clarification_task()`  
   生成必须先确认的问题列表，暂停等待人工回复。

2. `run_apply_clarification_task()`  
   校验人工回复是否覆盖问题；若不完整，会把“AI 补充待确认项”追加到回复文件末尾；若完整，再生成 `clarified_requirement.md`。

这个阶段的本质是：

- 先缩范围
- 先把会改变 PRD 结论的问题问清
- 避免直接基于模糊需求写 PRD

### 4.4 `draft_prd`

在前置澄清完成后执行。

产物目录：

- `runs_xxx/prd/`

核心产物：

- `requirements.md`

`draft_prd.py` 先判断知识库是否缺失关键链路说明，然后再让 agent 生成一份“需求规格型”的 PRD 草稿，并额外做一次完整性复审、原地补齐。

这里有两个特点：

1. PRD 结构被强约束为规范化需求文档，不是方案说明。
2. 输出会尽量收敛为：
   - `简介`
   - `术语表`
   - `需求`
   - `非目标 / 不纳入范围`
   - `正确性属性（用于测试）`

### 4.5 `discussion`

这是一个可选阶段，由 `DISABLE_DISCUSSION` 控制。

作用：

- 围绕“影响面分析”开启一个议会式讨论
- 角色固定为：议长、议员、评审员
- 每次只讨论一个议题
- 每个议题最多 3 轮
- 每轮产物都落到 `discussion/` 目录

这个流程的目标不是写代码，而是继续补强 PRD 里的影响面分析。

它的特点是：

- 贴项目上下文
- 强制引用知识库
- 强制使用官方术语
- 评审员不通过就继续下一轮
- 单个议题超过最大轮次就要求人工介入

### 4.6 `summary_effect`

这一步不是改 PRD，而是从已生成的 PRD 中提取“还需要产品拍板的问题”。

产物目录：

- `runs_xxx/summary_effect/`

核心产物：

- `questions.md`
- `questions.json`
- `manifest.json`

其目标是：

- 只保留真正需要产品确认的问题
- 把技术实现背景改写成产品能读懂的表达
- 不输出研发自己能拍板的实现细节

### 4.7 `finalize_prd`

最后根据产品回复生成最终 PRD。

核心产物：

- `final_prd.md`
- `merge_report.md`
- `reply_coverage_report.md`
- `manifest.json`

流程是：

1. 校验产品回复是否覆盖全部待确认问题
2. 若不完整，回写待补充项并阻断
3. 若完整，合并生成 `final_prd.md`
4. 再做一次最终 PRD 完整性复审与原地补齐

### 4.8 PRD 流程总结

这条链可以概括为：

```text
precheck
-> init
-> clarification(生成前置澄清问题)
-> apply-clarification(合并前置澄清回复)
-> draft_prd
-> discussion(可选)
-> summary_effect(整理待产品确认问题)
-> finalize_prd
```

如果走 `generate_prd.py auto`，它会自动推进到：

- 找不到前置澄清回复时暂停
- 找不到最终产品回复时暂停
- 或直到最终 PRD 完成

## 5. 流程二：技术方案、执行、构建与热更

入口：

```bash
python generate_code.py plan
python generate_code.py apply-tech-reply --reply-file answer.md
python generate_code.py execute
python generate_code.py build-deploy
python generate_code.py auto
```

这条流程的输入前提是：

- `summary_effect/final_prd.md` 已经存在

### 5.1 `repo_tech_design`

先按仓库逐个生成技术方案。

产物目录：

- `runs_xxx/code/`

输出形式：

- `<repo>_tech_design.md`

任务要求：

- 每个仓库都要单独判断是否需要改动
- 即便不需要改，也要写清楚排除理由
- 需要改时，要写出改动目标、涉及模块、实现思路、风险和测试建议

这个阶段是并发执行的，使用线程池同时处理多个仓库。

### 5.2 `cross_repo_tech_design`

按仓技术方案出来后，再做跨仓收敛。

产物目录：

- `runs_xxx/code_review/`

核心产物：

- `all_questions.md`
- `all_questions.json`
- `pending_questions.md`
- `pending_questions.json`
- `review_report.md`
- `manifest.json`

这一层的职责是：

- 从“跨组件交互”和“整体链路一致性”重新检查各仓方案
- 自动消化低风险、可默认的问题
- 只保留“强烈建议人工技术确认”的问题
- 直接回写原始技术方案文档，使各仓方案保持一致

如果还有待确认问题，就暂停等待人工技术回复。

### 5.3 `apply-tech-reply`

技术侧人工回复后，执行：

- 覆盖校验
- 不完整则回写补充待确认项并阻断
- 完整则把结论回写到各仓技术方案

这一步完成后，技术方案才算真正定稿。

### 5.4 `execute_tech_design`

技术方案定稿后，开始真正落代码。

产物目录：

- `runs_xxx/execution/`

核心产物：

- `<repo>_execution_report.md`
- `manifest.json`

执行规则：

- 每个仓库单独执行
- 若仓库技术方案明确“不需要变更”，则直接写“跳过执行”报告
- 若需要变更，则必须在仓库中直接修改代码
- 单元测试只要求“撰写即可，不需要执行”

这说明这一层强调的是：

- 真正修改代码
- 落盘执行报告
- 但不把测试执行作为这一阶段的硬门禁

### 5.5 `build_deploy`

这是技术侧真正的“编译/构建/热更/构建失败修复”闭环。

产物目录：

- `runs_xxx/build_deploy/`

每个仓库会有自己的子目录与报告。

#### 构建配置来源

构建与部署规则来自：

- `build_deploy.json`

它为每个仓库定义：

- 构建脚本
- 构建参数
- 产物 glob
- 组件类型
- 产物版本识别方式

#### 构建触发范围

默认只对 `execution` 阶段里状态为 `executed` 的仓库做构建/热更。

支持：

- `--repo` / `--module` 指定仓库
- `--build-only`
- `--force-rebuild`
- `--failed-only`

#### 构建前版本对比

如果满足条件，会先做本地产物与远端版本对比：

- 一致则直接跳过
- 不一致才继续构建

#### 构建失败自动修复

这是该仓库最有特点的一段。

当构建失败时：

1. 从 build log 提取错误摘要
2. 调 agent 分析失败根因
3. 允许 agent：
   - 修当前 repo 代码
   - 修项目里的构建脚本
   - 更新知识库
4. 生成：
   - `ai_result.json`
   - `fix_report.md`
5. 再决定是否重试构建

自动修复循环由 `run_auto_repair_loop()` 控制：

- 成功则退出
- 不建议重试则停止
- 达到最大轮次则停止

#### 构建成功后的热更

如果不是 `build-only`：

- 本地模式下调用热更脚本
- 远程模式下通过 `remote-build.sh` / `remote-deploy.sh` 完成远端构建与热更

#### 构建流程总结

这条链可以概括为：

```text
repo_tech_design
-> cross_repo_tech_design
-> apply-tech-reply(如需要)
-> execute_tech_design
-> build_deploy
   -> build
   -> fail 时自动修复
   -> build 成功后 deploy/hot-load
```

### 5.6 `generate_code.py auto`

自动模式会这样推进：

```text
plan
-> 如果有待技术确认问题，尝试读取默认回复文件
-> apply-tech-reply
-> execute
-> build-deploy
```

如果缺回复文件，就暂停并提示人工补充。

## 6. 流程三：E2E 用例生成、执行与自动修复

入口：

```bash
python run_e2e.py generate-case-list
python run_e2e.py execute-cases
```

### 6.1 `generate_e2e_case_list`

输入来源：

- 最终 PRD
- 仓库技术方案目录
- 跨仓技术方案收敛报告
- 知识库

产物目录：

- `runs_xxx/e2e_test_case_list/`

核心产物：

- `generated_test_case_list.md`
- `manifest.json`

要求输出的是“完整测试 case 列表”，不是测试代码。

文档会按稳定结构组织，例如：

- 控制面与配置准入
- 数据面
- 全量校验、复检与自动订正
- 切换、可观测性与协议校验
- 暂不支持与知识缺口保留项

### 6.2 `execute_e2e_cases`

这一段负责按 case list 执行单 case。

产物目录：

- `runs_xxx/e2e_case_execution/`

实际单 case 产物在：

- `oms_test/ai-e2e/cases/caseX.Y/`

每个 case 至少产出：

- `test_steps.md`
- `test_report.md`
- `execution_result.json`

执行规则：

- 页面类测试必须优先用 Playwright
- 非页面测试优先用 `oms_e2e_tools`
- 不允许伪造结果
- 失败时必须先做日志分析
- 不做 cleanup，保留现场

### 6.3 E2E 失败后的自动修复

当 case 执行失败时，会进入 case 级自动修复判断。

这里并不是所有失败都会修：

- 只有明确判断为 `oms_code_bug`，才允许修改 OMS 代码并继续
- 如果是：
  - 测试资产问题
  - 工具链问题
  - 环境问题
  - 非 OMS 行为
  - 根因未知
  则不修复，不建议继续重试

自动修复成功后，要求：

- 实际修改 OMS 代码
- 完成构建与热更
- 确认修复已生效

否则即使分析出了问题，也不能把 `retry_recommended` 设为 `true`

### 6.4 E2E 自动修复循环

这部分也复用了同一个自动修复循环框架：

- 执行 case
- 成功则结束
- 失败则判断是否需要修复
- 如果修复并建议重试，则进入下一轮
- 达到最大轮次后终止

支持参数：

- `--max-case-fix-loops`
- `--rerun-existing`
- `--cases`
- `--execute-only`

其中 `--execute-only` 会明确关闭失败后的自动修复。

## 7. 三条流程如何衔接

### 7.1 需求流转

```text
original_requirement.md
-> clarification
-> clarified_requirement.md
-> prd/requirements.md
-> summary_effect/questions.md
-> final_prd.md
```

### 7.2 技术流转

```text
final_prd.md
-> code/<repo>_tech_design.md
-> code_review/review_report.md + pending_questions.*
-> execution/<repo>_execution_report.md
-> build_deploy/
```

### 7.3 测试流转

```text
final_prd.md + tech_design + cross_repo_review
-> e2e_test_case_list/generated_test_case_list.md
-> e2e_case_execution/
-> 单 case 失败时 auto repair
```

## 8. 与 stage-harness 的差异

虽然两个项目都在做“需求到交付”的流程编排，但设计完全不同。

### `stage-harness`

- 核心是统一状态机
- 统一阶段：`CLARIFY / SPEC / PLAN / EXECUTE / VERIFY / FIX`
- 强调门禁、receipt、council、阶段转移

### `ai-programmer-oms`

- 核心是多入口脚本 + session 目录
- 分成三条业务流水线：
  - PRD
  - 技术方案/执行/构建
  - E2E
- 强依赖 agent prompt 驱动
- 自动修复主要落在：
  - 构建失败修复
  - E2E 失败修复

## 9. 当前实现里最重要的几个特点

### 9.1 文档驱动很强

无论 PRD、技术方案、问题清单、执行报告、E2E 步骤、测试报告，几乎每一步都先要求产出结构化文档或 JSON。

### 9.2 人工确认点很明确

人工主要出现在两个地方：

- 前置澄清 / 最终产品确认
- 技术侧跨仓收敛后的待确认问题

也就是说，它不是完全自治，而是会在高价值决策点停下。

### 9.3 “代码开发”与“测试执行”是分离的

技术侧的 `execute_tech_design` 只负责改代码和写执行报告，不要求真正跑单测。

真正的验证闭环更多落在：

- `build_deploy`
- `run_e2e.py execute-cases`

### 9.4 自动修复能力是这套系统的重点

自动修复主要有两类：

1. **构建失败自动修复**
   - 读 build log
   - 提取错误摘要
   - 修代码或脚本
   - 补知识库
   - 重试构建

2. **E2E 失败自动修复**
   - 分析是否属于 OMS 代码 bug
   - 若是，则改代码、构建、热更、重试 case
   - 若不是，则停止，不误修

## 10. 最终理解

如果按“从需求到开发、构建、测试、修复”的角度总结，`ai-programmer-oms` 的主线可以概括为：

```text
需求输入
-> precheck
-> init(准备多仓工作区)
-> clarification(前置澄清)
-> draft_prd
-> discussion(可选)
-> summary_effect
-> finalize_prd
-> repo_tech_design(按仓方案)
-> cross_repo_tech_design(跨仓收敛)
-> apply-tech-reply(如需要)
-> execute_tech_design(真正改代码)
-> build_deploy(构建/热更/构建失败自动修复)
-> generate_e2e_case_list
-> execute_e2e_cases(E2E 执行/失败后自动修复)
```

它的核心不是统一状态机，而是：

- **session 产物编排**
- **agent 驱动的文档与代码生成**
- **人工决策点 + 自动修复循环**

## 11. 关键文件索引

### 入口脚本

- `generate_prd.py`
- `generate_code.py`
- `run_e2e.py`

### 需求侧任务

- `app/tasks/precheck.py`
- `app/tasks/init.py`
- `app/tasks/clarification.py`
- `app/tasks/draft_prd.py`
- `app/tasks/discussion.py`
- `app/tasks/summary_effect.py`
- `app/tasks/finalize_prd.py`

### 技术侧任务

- `app/tasks/repo_tech_design.py`
- `app/tasks/cross_repo_tech_design.py`
- `app/tasks/execute_tech_design.py`
- `app/tasks/build_deploy.py`

### 测试与修复

- `app/tasks/generate_e2e_case_list.py`
- `app/tasks/execute_e2e_cases.py`
- `app/tasks/auto_repair.py`

### 配置与运行资产

- `build_deploy.json`
- `README.md`
- `knowladge/`
