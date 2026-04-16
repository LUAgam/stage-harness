# Skill: project-surface

项目承载面缩圈 — 在产品/领域影响扫描之后，明确后续需要重点分析的具体落点。

## 目的

"项目承载面"不等于"代码仓库"。本 skill 负责将影响扫描的宏观影响面，落实到当前项目的具体承载面列表，并设定深挖优先级。这一步骤在 CLARIFY 阶段固定位于：

```
需求本体澄清 → 产品/领域影响扫描 → [项目承载面缩圈] → 定点深挖
```

## 承载面类型

| 类型 | 典型例子 |
|------|---------|
| `code_repository` | src/, lib/, app/ 等代码目录 |
| `api_definition` | OpenAPI spec, proto 文件, GraphQL schema |
| `configuration` | .env.example, config/, 部署 YAML |
| `documentation` | docs/, README, ARCHITECTURE.md |
| `design_artifacts` | 设计稿、交互流程、原型 |
| `data_assets` | 数据库 schema, migration 文件, 数据字典 |
| `workflow_scripts` | CI/CD 脚本, Makefile, 自动化脚本 |
| `test_fixtures` | fixtures/, mocks/, seed 数据 |

## 缩圈规则（硬性）

1. **先看索引**：入口文件、目录树、README，再决定是否深挖正文
2. **禁止无差别全量扫描**：不允许在 CLARIFY 早期对所有承载面全量读取
3. **按影响优先级排序**：impact-scan.md 中优先级 P0 的影响面优先纳入承载面
4. **代码类项目才激活 repo-router**：非代码项目（docs、infra-as-config 等）不需要 repo-router

## 缩圈过程

```
1. 读取 .harness/features/<epic-id>/impact-scan.md → 提取影响面清单（P0/P1/P2）
2. 读取 .harness/project-profile.yaml → 获取 project_type 和 primary_surfaces
3. 对照项目实际目录结构（只看根目录 + 1 层），识别哪些承载面实际存在
4. 排除不受本次 epic 影响的承载面（显式写入 excluded 列表）
5. 为每个纳入的承载面分配深挖策略：
   - index_only：只看目录名/README/索引，不读正文
   - summary_only：只读摘要/入口
   - targeted：仅读命中的文件
   - deep：全量精读（仅高风险核心依赖）
6. 若 `workspace_mode: multi-repo` 且处于 CLARIFY full mode，上游应已产出 `.harness/features/<epic-id>/cross-repo-impact-index.json`；本步骤应按其 `repos[]` / `interfaces[]` 对齐 surface，避免漏扫契约。单仓时该文件可缺省。
7. `surface-routing.json.surfaces[]` 的每个条目都必须显式包含 `type` 与 `path`；不要依赖下游猜测补齐。
8. 若项目画像 `.harness/project-profile.yaml` 声明了可选 `coupling_role_ids`，则可在对应 `surfaces[]` 条目补充 `serves_roles`，用于声明该承载面承担哪些通用联动责任；不得填写未在 `coupling_role_ids` 中登记的 role id。
```

## 输出：surface-routing.json

写入 `.harness/features/<epic-id>/surface-routing.json`：

```json
{
  "epic": "epic-name",
  "created_at": "2024-01-15T10:00:00Z",
  "surfaces": [
    {
      "type": "code_repository",
      "repo_id": "",
      "path": "src/auth/",
      "priority": "P0",
      "reason": "需求直接修改认证中间件",
      "dive_strategy": "targeted",
      "scan_budget": { "max_files": 15, "max_grep_rounds": 3 },
      "evidence_level": "source",
      "serves_roles": ["role.api_contract"],
      "assigned_to": "repo-router"
    },
    {
      "type": "api_definition",
      "path": "api/openapi.yaml",
      "priority": "P1",
      "reason": "API 契约可能变化",
      "dive_strategy": "summary_only",
      "assigned_to": "docs-scout"
    },
    {
      "type": "configuration",
      "path": ".env.example",
      "priority": "P1",
      "reason": "需要新增 JWT_SECRET 环境变量",
      "dive_strategy": "targeted",
      "assigned_to": "config-scout"
    }
  ],
  "excluded": [
    {
      "type": "design_artifacts",
      "reason": "本次需求不涉及 UI 变更"
    }
  ],
  "scout_assignments": {
    "repo-router": ["src/auth/"],
    "docs-scout": ["api/openapi.yaml", "docs/auth.md"],
    "config-scout": [".env.example"],
    "design-scout": [],
    "dependency-mapper": ["package.json"]
  },
  "total_surfaces": 3,
  "excluded_surfaces": 1
}
```

## PLAN 阶段复核

在进入 PLAN 时，`project-surface-router` 需要对 surface-routing.json 进行复核：
- 是否有新承载面在 SPEC 过程中被发现？
- 是否有任务涉及的承载面未在 routing 中登记？
- 更新 `surface-routing.json` 中的 `scout_assignments`

## 与其他 skills 的关系

| 关系 | 说明 |
|------|------|
| 前置 | `impact-scan/SKILL.md` 必须先完成 |
| 后置 | `clarify/SKILL.md` Step 3 Surface Routing 使用本 skill |
| 并行 | PLAN 阶段 `docs-scout`、`design-scout`、`config-scout` 等 scouts 以本 skill 的输出为路由依据 |

## 用法

```
Invoke skill: project-surface
Epic: <epic-name>
Input: .harness/features/<epic-id>/impact-scan.md + .harness/project-profile.yaml + optional cross-repo-impact-index.json
Output: .harness/features/<epic-id>/surface-routing.json
```

`repo_id` 在单仓可为空字符串；`multi-repo` 时填 catalog 中的 `repo_id`。`evidence_level` 可取 `catalog` | `codemap` | `source`。

`serves_roles` 是可选字段；未启用 `coupling_role_ids` 的项目不要凭空新增该字段。
