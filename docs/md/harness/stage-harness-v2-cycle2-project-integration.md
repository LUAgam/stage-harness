# 第二周期 (Cycle 2)：真实能力落地与项目接入

**定位**：落知识文件、接真实业务
**原则**：在第一周期的“空转管线”与知识层边界冻结跑通后，在标杆仓库中落地 `.harness` 清单并引入真实业务逻辑；**strict 标杆验收**在本周期完成。

## 核心目标
在标杆仓库中**落地** Cycle 1 已冻结的项目知识层文件与读取契约；实现真正的异步资源回收；为真实项目 (`oms`, `sqlshift`) 手写官方的 Provider Adapter，在真实场景中跑通流程闭环；**本周期即要求标杆项目在 `strict` 门禁下至少完成一次完整跑通**（strict 的“首次可用”验证放在本周期，而非第三周期）。

## 开发任务清单

### 1. 项目知识层在标杆项目中的落地 (Knowledge Layer Rollout)
*目标：按 Cycle 1 已定义的边界，在真实仓库中迁移/补齐文件，并与 Provider 读取路径对齐（不再在本周期做“首次架构拆分”）。*
- [ ] 在 `oms` / `sqlshift` 中落实 `.harness/project-profile.yaml` 的职责收缩及各配套清单文件（`environment-manifest`、`data-source-contract`、`secret-references`、`bootstrap-notes`）的内容与引用关系。
- [ ] 校验 Adapter 与 `harnessctl` 加载顺序、环境变量 Reference ID 解析与 Cycle 1 契约一致。

### 2. 真实的资源回收与清理 (Real Teardown & GC)
*目标：防止异常中断导致的长期资源泄漏。*
- [ ] 丰富 `resource-registry.json` 的模型定义，支持跨进程资源的描述。
- [ ] 完善 `harnessctl gc` 命令：使其能读取 registry，并针对遗留的进程、锁、临时目录执行真实的回收动作。
- [ ] 在 Provider 接口中强制定义并挂载 `cleanup` hooks，确保其逻辑为幂等。

### 3. 手写官方 Adapter (Manual Official Adapters)
*目标：在通用协议上接入真实的业务执行逻辑。*
- [ ] **针对 OMS 项目**：编写并挂载 `repo-execution` + `build-deploy` + `e2e-case` 的组合 Provider Adapter，替换第一周期的 Dummy Provider。
- [ ] **针对 SQLShift 项目**：编写并挂载针对 SQL 转换特性的 `specialized-deploy` 和 `scenario-verifier` 的 Provider Adapter。
- [ ] 确保上述真实 Provider 的输出严格符合在第一周期定义的 JSON Schema，特别是保证 `evidence_refs` 填入了真实可追溯的证据链接（如日志路径、测试报告哈希等）。

## 验收标准 (Definition of Done)
1. **项目知识落地清晰**：`oms` 与 `sqlshift` 仓库内的 `.harness` 目录结构与 Cycle 1 冻结的知识层设计一致，文件职责无回退到“单文件混杂所有事实”。
2. **资源无泄漏**：在真实执行的中途使用 `pause` 中断，再使用 `harnessctl gc` 能够稳定、幂等地清理掉所占用的锁或临时文件。
3. **真实业务跑通**：`stage-harness` 能够调用 `oms` / `sqlshift` 的专属 Adapter，完成一次真实的构建、部署、测试和修复闭环，且所有产生的协议 JSON 均合法并通过门禁。
4. **Strict 标杆验收**：`oms` 与 `sqlshift` 各至少在**一次完整流程**中于 **`strict` 门禁模式**下跑通（关闭对旧 `receipts` 的 compat Warning 兜底路径），证明强门禁在真实项目上已可用；第三周期在此基础上推进“全局默认 strict”，而非首次验证。