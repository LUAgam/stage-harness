# Stage-Harness V2 MVP 开发实施清单 (第一周期)

这份清单基于“不动前半段、正式化后半段”的架构原则，严格限定在 **MVP 边界** 内。第一周期的核心目标是：**搭骨架、通管线、跑空转**，绝对不涉及具体项目（如 OMS / SQLShift）的真实业务逻辑集成。

建议直接将以下 Checklist 转化为项目管理工具（如 GitHub Issues）的任务进行分配与跟踪。

---

## 阶段一：协议与数据结构 (Data Models)
**目标**：确立后半段所有流转数据的标准契约，避免后续对接时的字段口水战。

- [ ] **Task 1.1: 定义核心产物 Schema**
  - [ ] 新建 `scripts/models/artifacts.py` (或类似模块，推荐使用 `pydantic`)。
  - [ ] 定义 `ExecutionSummary` 模型 (对应 `execution-summary.json`)。
  - [ ] 定义 `Verification` 模型 (对应 `verification.json`)，**必须包含强类型的 `evidence_refs` 字段**。
  - [ ] 定义 `FixSummary` 模型 (对应 `fix-summary.json`)。
  - [ ] 定义 `DeliveryManifest` 模型 (对应 `delivery-manifest.json`)。
- [ ] **Task 1.2: 定义运行时上下文 Schema**
  - [ ] 定义 `RunContext` 模型 (对应 `context.json`，处理跨阶段只读变量传递)。
  - [ ] 定义 `StageOutputs` 模型 (对应 `stage-outputs.json`，处理阶段间输出串联)。
  - [ ] 定义 `ResourceRegistry` 模型 (对应 `resource-registry.json`，记录需清理的资源清单)。
  - [ ] *红线检查：确保环境变量/密钥设计为传递 Reference ID，而非明文存放。*

## 阶段二：运行时隔离与目录架构 (Runtime Isolation)
**目标**：将原先基于 Epic 的全局状态管理，下沉为支持并发的 `run_id` 级沙箱隔离。

- [ ] **Task 2.1: `harnessctl` 核心状态路由改造**
  - [ ] 修改状态机流转逻辑：当进入 `EXECUTE` 阶段时，自动生成/分配一个唯一的 `run_id`。
  - [ ] 实现 `.harness/runs/<run_id>/` 目录结构的自动初始化。
- [ ] **Task 2.2: 读写路径重定向**
  - [ ] 封装统一的 Artifact I/O 模块：在后半段 (`EXECUTE` 及之后) 强制所有工件的读取和写入路由到 `.harness/runs/<run_id>/`。
  - [ ] *红线检查：全局搜索 `.harness/` 根目录的写操作，确保后半段逻辑不会引发并发写冲突（全局污染）。*

## 阶段三：控制面增强与生命周期 (Control & Lifecycle)
**目标**：引入挂起、恢复和异步清理机制，让框架具备容错和人机协同基础。

- [ ] **Task 3.1: CLI 参数演进与兼容**
  - [ ] `scripts/harnessctl.py` 新增 `--run-id` 参数支持。
  - [ ] 确保不带 `--run-id` 的旧命令在前半段 (`CLARIFY` -> `PLAN`) 正常工作。
- [ ] **Task 3.2: 挂起与恢复机制 (Handoff)**
  - [ ] 实现 `harnessctl pause --reason <decision|knowledge|auth|recovery>`：记录挂起状态和现场快照。
  - [ ] 实现 `harnessctl resume <run_id>`：校验并恢复现场，重新拉起对应阶段的执行。
- [ ] **Task 3.3: 异步清理基础 (GC / Teardown)**
  - [ ] 实现 `harnessctl gc` (或 `teardown <run_id>`) 命令基础框架。
  - [ ] 解析对应的 `resource-registry.json`，执行（模拟的）幂等清理操作。
  - [ ] *红线检查：清理操作必须是可重入的，严禁依赖单一脚本进程的 `try...finally`。*

## 阶段四：空转执行器 (Dummy Provider)
**目标**：提供一个没有任何真实业务逻辑的执行器，专门用来产生“合法”的假数据，打通管线。

- [ ] **Task 4.1: 定义极简 Provider 接口**
  - [ ] 基于文件系统的输入输出契约，定义 Provider 需实现的方法（如 `execute(context_path)`, `verify(context_path)`）。不要过度设计复杂的 OOP 类继承。
- [ ] **Task 4.2: 实现 `DummyProvider`**
  - [ ] 实现假执行 (`execute`)：读取 `context.json`，输出格式合法的 `execution-summary.json`。
  - [ ] 实现假验证 (`verify`)：输出格式合法的 `verification.json`，其中 `evidence_refs` 填入虚拟的日志链接或哈希值。
  - [ ] 实现假交付 (`deliver`)：输出格式合法的 `delivery-manifest.json`。

## 阶段五：门禁卡点与灰度双写 (Gates & Compat)
**目标**：在不破坏现有正在运行项目的前提下，悄无声息地上线严苛的防篡改新门禁。

- [ ] **Task 5.1: 实现严苛的新门禁校验器**
  - [ ] 第五门禁 (EXECUTE -> VERIFY)：严格校验 `ExecutionSummary` 格式与必填项。
  - [ ] 第六/七门禁 (VERIFY -> FIX/DONE)：**核心红线**。必须校验 `evidence_refs` 的存在性与有效性（哪怕目前只针对 Dummy 数据做 mock 校验）。
  - [ ] 第八门禁 (FIX -> VERIFY)：校验 `FixSummary` 格式。
  - [ ] 第九门禁 (DONE -> 交付)：校验 `DeliveryManifest` 格式。
- [ ] **Task 5.2: 植入 Compat (兼容) 模式**
  - [ ] 在 `harnessctl` 的门禁判定逻辑中引入开关。
  - [ ] 当处于 `compat` 模式时：校验新 JSON，若新 JSON 不合法/不存在，但存在旧的 `receipts`，则**记录 Warning 日志但允许放行**。
  - [ ] 若新 JSON 合法，记录 Success。

---

## 验收标准 (Definition of Done)

整个 MVP 周期结束时，可以通过以下测试证明开发成功：
1. **成功空跑**：能用 `harnessctl` 驱动 DummyProvider 从 `PLAN` 顺畅流转到 `DONE`，中途产生的所有新 JSON 均完全符合 Schema 规范。
2. **状态隔离**：在 `.harness/runs/` 目录下能看到按 `run_id` 完美隔离的沙箱目录，且多次并行执行互不干扰。
3. **平滑挂起**：能在 `EXECUTE` 中途调用 `pause` 中断流转，杀掉进程后，使用 `resume` 完美恢复执行。
4. **门禁拦截**：手动去 `.harness/runs/<run_id>/` 下把 `verification.json` 里的 `evidence_refs` 清空，再次触发状态流转时，门禁能精准拦截并报错。