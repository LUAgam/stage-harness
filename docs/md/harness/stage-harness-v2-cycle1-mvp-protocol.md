# 第一周期 (Cycle 1)：MVP 与协议骨架

**定位**：搭骨架、通管线、跑空转
**原则**：绝不触碰真实业务逻辑代码，只负责确立标准、建立沙箱、打通状态机。

## 核心目标
本周期的核心是将原先基于 Epic 的全局状态管理，下沉为支持并发的 `run_id` 级沙箱隔离，并确立 `EXECUTE` 及之后阶段的标准数据交互契约。

## 开发任务清单

### 1. 协议与数据结构 (Data Models)
*目标：确立后半段所有流转数据的标准契约，消除字段定义分歧。*
- [ ] 定义 `ExecutionSummary` 模型 (对应 `execution-summary.json`)。
- [ ] 定义 `Verification` 模型 (对应 `verification.json`)，**必须包含强类型的 `evidence_refs` 字段**。
- [ ] 定义 `FixSummary` 模型 (对应 `fix-summary.json`)。
- [ ] 定义 `DeliveryManifest` 模型 (对应 `delivery-manifest.json`)。
- [ ] 定义 `RunContext` (上下文)、`StageOutputs` (输出串联) 和 `ResourceRegistry` (清理清单) 模型；**设计时即按最终态的项目知识层边界**（环境清单、数据源契约、密钥引用拆分等）约束字段与挂载点，避免后续为“补拆分”返工协议。
- [ ] **红线**：确保环境变量/密钥设计为传递 Reference ID，禁止明文落盘。

### 1.1 项目知识层拆分（边界与契约先行）
*目标：与上文的 `RunContext` / 注册表模型对齐，一次性冻结文件形态与职责，第二周期只在真实仓库中落地填充。*
- [ ] 将 `.harness/project-profile.yaml` 的职责收缩为仅记录：项目画像、archetype 和路由策略。
- [ ] 新建 `.harness/environment-manifest.yaml`：记录环境部署方式、服务入口、依赖服务。
- [ ] 新建 `.harness/data-source-contract.yaml`：记录数据源类型、可 mock 策略。
- [ ] 新建 `.harness/secret-references.yaml`：集中管理 Secret ID。
- [ ] 新建 `.harness/bootstrap-notes.md`：记录一次性知识注入。

### 2. 运行时隔离与目录架构 (Runtime Isolation)
*目标：建立基于 `run_id` 的并发沙箱。*
- [ ] 改造 `harnessctl` 状态路由：进入 `EXECUTE` 阶段时分配唯一 `run_id`。
- [ ] 初始化 `.harness/runs/<run_id>/` 目录结构。
- [ ] 封装 Artifact I/O 模块：强制后半段所有工件的读写路由到对应的 `run_id` 目录下。

### 3. 控制面增强与生命周期 (Control & Lifecycle)
*目标：引入挂起、恢复和异步清理的基础框架。*
- [ ] `harnessctl` 增加 `--run-id` 参数支持，并保持对旧命令（无 `run_id`）的兼容。
- [ ] 实现 `harnessctl pause --reason <类型>`，记录现场快照。
- [ ] 实现 `harnessctl resume <run_id>`，校验并恢复现场。
- [ ] 搭建 `harnessctl gc` / `teardown` 的命令骨架，能够读取 `resource-registry.json` 并对 **Dummy 阶段登记的虚拟资源**执行幂等清理（与下节 Dummy 联动，而非仅“空跑脚本”）。

### 4. 空转执行器 (Dummy Provider)
*目标：打通管线“空转”的伪执行器，并为 `gc/teardown` 提供可验证的“假资源”。*
- [ ] 定义极简的 Provider 接口约束（基于文件系统的 I/O 契约）。
- [ ] 实现 `DummyProvider`：消费 `context.json`，产出合法的伪造协议 JSON（包含虚拟的 `evidence_refs`）。
- [ ] **必须**至少登记并制造**一种可观测、可清理的虚拟资源**（例如：`run_id` 作用域下的临时锁文件、可回收子进程、或等价的占位句柄），写入 `resource-registry.json`（或与协议一致的清单），使 `gc` / `teardown` 能针对真实存在的资源做幂等回收验证——**禁止**仅生成假 JSON 而不留下任何清理对象。

### 5. 门禁卡点与灰度双写 (Gates & Compat)
*目标：植入严苛门禁逻辑，但以不阻断的兼容模式运行。*
- [ ] 编写第五、六、七、八、九阶段的新门禁校验器代码（特别是对 `evidence_refs` 的强校验）。
- [ ] 在 `harnessctl` 中植入 `compat`（兼容）模式开关：校验新 JSON，若不合法但存在旧 `receipts`，则记录 Warning 放行；若合法则记录 Success。

## 验收标准 (Definition of Done)
1. **成功空跑**：能用 `harnessctl` 驱动 DummyProvider 从 `PLAN` 顺畅流转到 `DONE`，产出符合规范。
2. **状态隔离**：`.harness/runs/` 目录下按 `run_id` 完美隔离。
3. **平滑挂起**：`pause` 后杀掉进程，能通过 `resume` 完美恢复。
4. **门禁拦截**：清空 mock 的 `evidence_refs`，门禁能精准拦截报错。
5. **知识层边界就绪**：`.harness` 下知识层文件职责与 Cycle 1 协议中的 `RunContext`/引用关系一致（可在文档或模板中验收），第二周期只做仓库内落地。
6. **清理链路可证**：对一次 Dummy 运行执行 `gc` / `teardown` 后，上述虚拟资源被移除或恢复至干净状态；重复执行清理仍幂等。