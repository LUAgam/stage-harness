# SKILL: deploy

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

DEPLOY 阶段部署执行技能。将整个大项目（含所有需要部署的子项目）完整启动，为后续 E2E 测试提供运行环境。支持多子项目结构，每个子项目独立推断部署方式，不需要部署的子项目可标记跳过。

---

## 触发条件

- 当前 epic state = `DEPLOY`
- 收到 `/stage-harness:harness-deploy` 命令
- 从 FIX 阶段回流后重新部署

---

## 核心概念：子项目列表

一个大项目可能由多个子项目构成（后端、前端、知识库、worker 等），每个子项目有自己的部署方式，部分子项目不需要部署（如纯静态知识库、文档站）。

`project-profile.yaml` 中用 `sub_projects` 列表描述各子项目的部署配置：

```yaml
sub_projects:
  - name: backend          # 子项目标识（唯一）
    path: ./SQLShift       # 相对于 PROJECT_ROOT 的路径
    deploy_command: "bash /abs/path/to/start.sh start"
    deploy_type: custom-script
    skip: false            # true = 不需要部署，跳过
    skip_reason: ""        # 跳过原因（可选，便于理解）

  - name: frontend
    path: ./SQLShift-ui
    deploy_command: "yarn --cwd /abs/path/to/SQLShift-ui dev"
    deploy_type: node
    skip: false

  - name: knowledge-base
    path: ./sqlshift_knowladge
    deploy_command: ""
    deploy_type: ""
    skip: true
    skip_reason: "静态知识库，无需部署"
```

`workspace_mode: multi-repo` 时强制走子项目扫描逻辑；单仓项目（`workspace_mode: single-repo` 或未设置）退化为单子项目，行为与旧版一致。

---

## 执行流程

### Step 0 — 探测运行时环境

在任何推断之前，先探测当前环境的工具可用性，供后续所有子项目推断使用：

- 检测 `docker compose`（插件形式）vs `docker-compose`（独立二进制），记录实际可用形式
- 检测 `node` / `npm` / `yarn` / `pnpm` 可用性
- 检测 `kubectl` / `make` / `flyctl` / `vercel` / `heroku` 可用性
- 记录 `PROJECT_ROOT`（当前工作目录绝对路径）

输出环境探测摘要：
```
[ENV] PROJECT_ROOT: /abs/path/to/project
[ENV] docker compose: docker compose（插件形式）
[ENV] node: 18.x  yarn: 1.22.x
```

---

### Step 1 — 确定各子项目的部署方式

对每个子项目依次执行以下四级推断链，得到该子项目的 `deploy_command`。

#### Level 1 — 读取已有配置

读取 `project-profile.yaml` 中的 `sub_projects` 列表：

- 若列表存在且非空，以此为基础，对每个 `skip: false` 且 `deploy_command` 非空的子项目直接使用已有命令，跳过后续推断
- 若列表不存在或为空，进入 Level 2 全量扫描

兼容旧格式：若只有顶层 `deploy_command`（无 `sub_projects`），将其视为单子项目，`name = "main"`，`path = "."`。

#### Level 2 — 代码感知自动扫描

**扫描目标**：`PROJECT_ROOT` 下的所有直接子目录（深度 = 1），以及根目录本身。

对每个候选目录，按以下优先级推断其部署方式：

1. `bin/` 或 `scripts/` 下含 `start` / `deploy` / `ctl` / `run` / `up` 关键词的可执行脚本
2. `docker-compose.yml` / `docker-compose.yaml`（含 `config/`、`deploy/` 子目录）
3. `k8s/` / `kubernetes/` / `manifests/` 目录（需 kubectl 可用）
4. 云平台特征文件（`fly.toml` / `vercel.json` / `Procfile`）
5. `Makefile` 含 `deploy` target
6. `package.json` 含 `start` / `dev` / `serve` script（前端/Node 服务）
7. `Dockerfile`（兜底，生成 build + run 命令）

**跳过判断**：若某子目录不含任何上述特征文件，且不是根目录，则将该子项目标记为 `skip: true`，并记录 `skip_reason: "未发现部署特征文件"`。

**生成命令规则**：
- 所有路径使用绝对路径（基于 `PROJECT_ROOT`）
- docker compose 命令形式与 Step 0 探测结果保持一致
- 前端项目（含 `package.json`）优先使用项目自身的包管理器（yarn / pnpm / npm）

扫描完成后，将结果写入 `project-profile.yaml` 的 `sub_projects` 字段持久化，并输出扫描摘要：

```
[SCAN] 发现 3 个子项目：
  ✔ backend   (./SQLShift)        → bash /abs/.../start.sh start  [custom-script]
  ✔ frontend  (./SQLShift-ui)     → yarn --cwd /abs/.../SQLShift-ui dev  [node]
  ⊘ knowledge (./sqlshift_knowladge) → 跳过（未发现部署特征文件）
```

#### Level 3 — 条件性用户询问（仅不可本地部署时触发）

Level 2 扫描完成后，对每个 `skip: false` 的子项目执行**本地可部署性检查**：

1. 推断出的 `deploy_command` 所依赖的工具在 Step 0 探测中均可用
2. 命令引用的脚本/配置文件在本地文件系统存在
3. 若依赖 docker compose，对应 `docker-compose.yml` 存在且 docker daemon 可达

**判定规则**：
- 若所有待部署子项目均通过本地可部署性检查 → **跳过用户确认**，直接输出扫描摘要并进入 Step 1.5，不消耗中断预算
- 若任一子项目不可本地部署（工具缺失、脚本不存在、daemon 不可达等） → 触发用户询问，消耗 1 次中断预算

**不可本地部署时的用户提示**：

```
以下子项目在当前环境无法本地部署：

  [1] backend   → 缺少: docker daemon 不可达
  [2] frontend  → 通过（本地可部署）

是否需要远程部署不可用的子项目？
  A. 提供远程服务器信息（SSH）进行远程部署
  B. 为该子项目提供替代的本地命令
  C. 将该子项目标记为跳过
  D. 全部跳过，直接进入 E2E
```

用户选择远程部署时，收集该子项目的 SSH 连接信息（host / user / auth / project_path / service_type），写入对应子项目的 `remote_deploy` 配置块。

用户确认后将最终配置写回 `project-profile.yaml`。

---

### Step 1.5 — 预检与自动修复（Pre-flight Inspection）

对每个 `skip: false` 的子项目，在执行前检查其部署脚本和配置文件：

- **脚本文件（.sh）**：硬编码绝对路径不存在时，尝试在 `PROJECT_ROOT` 下找到同名相对路径并替换；docker compose 命令形式与探测结果不一致时统一替换
- **配置文件（.env / .env.*）**：修正 `KEY = value` 格式；检测并清空不可达的代理 URL

修改前自动备份（`*.preflight.bak`），修复记录写入 receipt 的 `fixes_applied` 字段。

---

### Step 2 — 按子项目顺序执行部署

对 `sub_projects` 列表中所有 `skip: false` 的子项目，**按列表顺序依次部署**（后端通常先于前端，因为前端可能依赖后端服务）：

```
[1/2] 部署 backend ...
[2/2] 部署 frontend ...
```

每个子项目：
1. 执行 `deploy_command`，捕获 stdout / stderr / exit_code
2. 超时控制：单个子项目超过 60 分钟强制终止，标记为 FAIL
3. 部署后验证服务状态（根据 deploy_type 自动选择验证命令）
4. 若服务状态验证失败，进入**运行时故障自动恢复循环**（见 Step 2.1）
5. 恢复循环耗尽后仍失败 → 立即停止后续子项目部署，进入失败处理流程

`skip: true` 的子项目直接记录为 SKIPPED，不执行任何命令。

---

### Step 2.1 — 运行时故障自动恢复循环

当部署命令本身成功（exit_code=0）但服务随后崩溃或健康检查失败时，**必须自主执行诊断-修复-重试循环**，不得中断等待用户。此循环最多执行 3 轮。

#### 触发条件

以下任一情况触发自动恢复：
- 容器/进程启动后在稳定性窗口（10 秒）内退出或重启
- 健康检查端口不可达
- HTTP 端点返回 5xx 或连接拒绝
- 启动日志中出现 FATAL / CRITICAL / panic / Traceback 级别错误

#### 每轮恢复流程

```
诊断 → 分类 → 修复 → 重试 → 验证
```

**1. 诊断（自主执行，不中断）**：
- 采集服务日志（docker logs / journalctl / pm2 logs / 进程 stderr 输出）
- 提取错误关键信息（最后 100 行日志中的异常堆栈、错误消息）
- 检查退出码含义

**2. 分类**：将错误归入以下类别之一：

| 类别 | 特征模式 | 处理方式 |
|------|---------|---------|
| 环境配置 | connection refused（外部依赖）、proxy/DNS 不可达、env variable missing、invalid URL/host | 修复配置文件后重试 |
| 端口冲突 | address already in use、port occupied | 释放端口或偏移端口后重试 |
| 权限问题 | permission denied、access denied、EACCES | 修复文件权限后重试 |
| 依赖服务未就绪 | connection refused（内部依赖如 DB/Redis）、timeout waiting for | 等待依赖服务就绪后重试 |
| 代码逻辑错误 | import error、syntax error、type error、未归入上述类别的异常 | 标记为代码问题，终止恢复循环 |

**3. 修复（仅配置类问题）**：
- 修改 .env / 配置文件 / 启动脚本中的问题值
- 所有修改记录到 `fixes_applied`，标明文件、原值、新值、原因
- 修改前自动备份

**4. 重试**：
- 重新执行部署命令（或 force-recreate 容器）
- 等待稳定性窗口

**5. 验证**：
- 重新执行健康检查
- 通过 → 标记 PASS，继续下一个子项目
- 失败 → 若未达 3 轮上限，回到步骤 1 继续下一轮

#### 循环终止条件

| 条件 | 结果 |
|------|------|
| 健康检查通过 | 标记 PASS |
| 错误分类为"代码逻辑错误" | 立即终止循环，标记 FAIL |
| 达到 3 轮上限仍未恢复 | 标记 FAIL |
| 连续两轮相同错误且修复无效 | 升级为代码问题，标记 FAIL |

#### 关键原则

- **全程自主**：整个恢复循环不消耗中断预算，不等待用户确认
- **日志驱动**：所有诊断基于实际日志输出，不凭假设判断
- **修复可追溯**：每次修复都记录到 `fixes_applied`，确保可审计
- **快速失败**：代码逻辑错误不浪费重试次数，立即上报

---

### Step 3 — 日志采集

部署失败或服务状态验证失败时，对失败的子项目自动采集日志，策略与部署类型对应（docker compose logs / journalctl / pm2 logs / kubectl logs 等）。

---

### Step 4 — 写 deploy-receipt.json

**写入路径**：`.harness/features/<epic-id>/deploy/deploy-receipt.json`（写入前确保 `deploy/` 子目录存在）

```json
{
  "epic_id": "<epic-id>",
  "status": "PASS | FAIL | SKIPPED",
  "started_at": "<iso8601>",
  "completed_at": "<iso8601>",
  "sub_projects": [
    {
      "name": "backend",
      "path": "./SQLShift",
      "deploy_command": "<cmd>",
      "deploy_type": "<type>",
      "detected_by": "config | auto-detect | user-input | skipped",
      "status": "PASS | FAIL | SKIPPED",
      "exit_code": 0,
      "service_status": "<验证结果>",
      "stdout": "<最后200行>",
      "error_summary": "",
      "remote_logs": "",
      "fixes_applied": []
    }
  ],
  "failed_sub_projects": ["<name>"],
  "skipped_sub_projects": ["<name>"]
}
```

整体 `status`：所有需部署子项目均 PASS → `PASS`；任一 FAIL → `FAIL`；全部 SKIPPED → `SKIPPED`。

---

## 输出

### 成功（PASS）

```
✅ DEPLOY PASS
   后端 (backend):   PASS  [custom-script]  耗时 45s
   前端 (frontend):  PASS  [node]           耗时 12s
   知识库:           SKIPPED（无需部署）
   产物: .harness/features/<epic-id>/deploy/deploy-receipt.json
```

### 失败（FAIL）

```
❌ DEPLOY FAIL
   后端 (backend):   PASS
   前端 (frontend):  FAIL (exit_code=1)
     错误摘要: <error_summary>
     === 日志 ===
     <前50行>
   产物: .harness/features/<epic-id>/deploy/deploy-receipt.json
```

---

## 阻断条件

| 条件 | 说明 |
|------|------|
| 任一子项目部署退出码非 0 | 写 FAIL receipt，停止后续子项目，触发 FIX |
| 任一子项目服务状态验证失败 | 写 FAIL receipt（含日志），触发 FIX |
| 任一子项目部署超时（> 60 分钟） | 写 FAIL receipt（timeout），触发 FIX |
| Level 3 预算耗尽且仍有未确认子项目 | 终止，提示手动配置 sub_projects |
| 写 receipt 失败 | 报告 IO 错误，终止 |

所有子项目均 SKIPPED 视为正常（用户主动选择），推进 E2E。

---

## 安全注意事项

- SSH 密码仅保存在会话内存中，不写入任何文件
- 采集到的日志写入 receipt 前自动屏蔽常见敏感模式（密码、token、secret 等）
- SSH 远程连接使用 `-o StrictHostKeyChecking=accept-new`
