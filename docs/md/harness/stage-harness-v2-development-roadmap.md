# Stage-Harness V2 开发全景路线图

本文档是 `stage-harness` 后续阶段通用化改造的总体开发路线图。为了保证工程落地不失控，整个改造被划分为三个渐进的开发周期。

核心指导原则：**不动前半段，正式化后半段；协议先行，能力后置；先跑通空转，再接驳真实业务。**

## 周期概览

| 周期 | 定位 | 核心目标 | 详细实施清单 |
| :--- | :--- | :--- | :--- |
| **第一周期 (Cycle 1)** | **MVP 与协议骨架** | 搭骨架、通管线、跑空转。建立 `run_id` 隔离；**先行冻结项目知识层边界**（与 `RunContext` 等协议对齐），确立四大核心协议 JSON，实现挂起/恢复机制；Dummy Provider 除假 JSON 外须制造可清理的虚拟资源以验证 `gc/teardown`；用 Dummy 跑通 `compat` 双写。**绝不触碰真实业务逻辑。** | [查看第一周期详情](./stage-harness-v2-cycle1-mvp-protocol.md) |
| **第二周期 (Cycle 2)** | **真实能力落地与项目接入** | 在标杆仓库中**落地** Cycle 1 的知识层文件；实现真实的资源回收 (GC)，为标杆项目 (`oms`, `sqlshift`) 手写官方 Provider Adapter，替换 Dummy Provider；**验收要求标杆项目在 `strict` 模式下至少一次完整跑通**，在真实场景中闭环。 | [查看第二周期详情](./stage-harness-v2-cycle2-project-integration.md) |
| **第三周期 (Cycle 3)** | **高阶演进与全面收紧** | 将 `strict` **从标杆级要求升级为全局/工作区默认**（不再承担“首次证明 strict 可用”）；沉淀可复用的能力插件池 (Capability Packs)；AI 自动生成 Adapter 仅作**外围探索**，不纳入核心运行时交付。 | [查看第三周期详情](./stage-harness-v2-cycle3-advanced-evolution.md) |

## 演进策略
- **灰度迁移**：通过 `legacy -> compat -> strict` 三态模型，保证现有老项目的稳定运行，平滑过渡到新协议。
- **解耦思想**：`stage-harness` 仅保留框架控制权（状态推进、门禁、证据归档），所有具体动作（构建、部署、测试）必须下沉到 Provider Adapter 中。