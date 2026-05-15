---
description: "部署（多子项目感知 → 代码感知推断 → 询问用户确认 → 依次部署 → 日志采集 → 写 deploy-receipt → 失败则触发 FIX）"
argument-hint: "<epic-id>"
---

# harness-deploy

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

执行部署阶段。将整个大项目（含所有子项目）完整启动，为后续 E2E 测试提供可端到端使用的运行环境。这是**全量部署**——无论本次需求修改了哪些子项目，都必须识别并部署所有构成完整系统的子项目（前端、后端、数据库、缓存、队列等），确保系统作为整体可用。

## 角色定义

DEPLOY 阶段 orchestrator。负责验证 BUILD 前置产物、调度 deploy skill 扫描并部署所有子项目、根据结果推进或回流。不直接执行部署命令——部署由 deploy skill 负责。

## 前置检查

验证 BUILD 阶段已通过：

```bash
$HARNESSCTL stage-gate check BUILD --epic-id <epic-id>
```

必须满足：
- `build-receipt.json` 存在且 `status` 为 `PASS` 或 `SKIPPED`

若检查失败，提示先完成 `/stage-harness:harness-build <epic-id>`，终止。

## 确定部署方式

**REQUIRED SKILL:** Use `stage-harness:deploy` skill

deploy skill 内部执行以下流程：

### Step 0 — 探测运行时环境

检测当前服务器环境：
- Docker / docker compose 命令形式和版本
- Node / yarn / pnpm 等前端工具可用性
- Python / pip / virtualenv 可用性
- 系统资源（内存、磁盘、端口占用）
- 记录 `PROJECT_ROOT` 和 `DEPLOY_HOST`（本地或远程）

### Level 1 — 读取已有配置

读取 `project-profile.yaml` 中的 `sub_projects` 列表，有则直接使用；兼容旧版单条 `deploy_command`。

### Level 2 — 全量子项目扫描

对 `PROJECT_ROOT` 下**所有**子目录进行全量扫描，识别每个子项目的角色和部署方式：

- 扫描特征文件：`docker-compose.yml` / `Dockerfile` / `package.json` / `Makefile` / `deploy.sh` / `bin/` 目录 / `systemd` 配置等
- 对每个子项目标记角色：`backend` / `frontend` / `worker` / `scheduler` / `database` / `cache` / `gateway` / `other`
- 结果写回 `project-profile.yaml` 的 `sub_projects` 持久化

**关键原则**：不是只部署被修改的子项目，而是识别构成完整系统的所有组件并全部部署。

**SKIP 判定规则（严格）**：

只有同时满足以下**全部条件**的子目录才能标记为 `skip: true`：
1. 无任何可运行特征文件（无 `package.json`、无 `Dockerfile`、无 `docker-compose*.yml`、无 `Makefile`、无 `requirements.txt`、无 `go.mod`、无可执行脚本）
2. 不属于 `frontend` / `backend` / `worker` / `gateway` 角色
3. 内容为纯文档、数据、配置模板或知识库

**禁止跳过的情况**：
- 含有 `package.json` 且有 `scripts.dev` 或 `scripts.start` 或 `scripts.build` → 必须部署
- 含有 `Dockerfile` 或 `docker-compose*.yml` → 必须部署
- 含有可运行入口文件（如 `app.py`、`main.go`、`server.js`、`Application.java` 等）+ 依赖描述文件 → 必须部署
- 角色为 `frontend` 的子项目 → **绝对不允许跳过**，前端是端到端可用的必要条件

**不允许用假设替代验证**：不能因为"后端可能内嵌了前端"就跳过独立前端的部署。如果存在独立前端子项目，必须先部署它，再通过健康检查验证其可用性。

### Level 3 — 环境可部署性检查与用户交互

对每个待部署子项目执行本地可部署性检查：
- 所需工具是否已安装
- 部署脚本/配置文件是否存在
- 所需端口是否可用
- 所需 daemon（Docker、数据库等）是否可达

**全部通过**：跳过确认，直接进入部署。

**任一不通过**：
1. 尝试自动修复（安装缺失工具、释放端口）
2. 自动修复不可行时，消耗 1 次中断预算询问用户：
   - 提供远程服务器信息（host / user / project_path / SSH key）
   - 提供替代部署命令
   - 选择跳过该子项目（仅限非核心组件）

### Step 1.5 — 预检与环境适配修复

对每个待部署子项目的脚本和配置文件进行环境适配：
- 路径修复（项目根目录实际位置 vs 脚本硬编码路径）
- 命令形式统一（`docker-compose` → `docker compose` 等）
- .env 格式修正（去除空格、补齐引号）
- 不可达代理/服务地址清空或替换
- 端口冲突自动偏移

**所有修复必须记录**到 `fixes_applied` 列表，标明修复的文件、原值、新值和原因。

### Step 2 — 按序部署

对所有 `skip: false` 的子项目按依赖顺序部署：
1. 基础设施优先（database → cache → message queue）
2. 后端服务（backend → worker → scheduler）
3. 前端服务（frontend → gateway）

每个子项目部署后立即执行健康检查，通过后再部署下一个。

**部署后服务崩溃的自动恢复**：当部署命令成功但服务随后崩溃（容器退出、进程终止、健康检查失败）时，**必须自主执行诊断-修复-重试循环**（最多 3 轮），不得中断等待用户：

1. **诊断**：采集服务日志（最后 100 行），提取错误堆栈和关键消息
2. **分类**：判断是环境配置问题（外部依赖不可达、代理/DNS 错误、env 缺失、端口冲突、权限）还是代码逻辑问题（import error、syntax error、未归入配置类的异常）
3. **配置问题 → 就地修复并重试**：修改 .env / 配置文件 / 启动脚本，记录到 `fixes_applied`，force-recreate 服务
4. **代码问题 → 立即终止循环**：标记 FAIL，进入失败处理流程

此循环全程自主执行，不消耗中断预算。连续两轮相同错误且修复无效时升级为代码问题。

任一子项目最终 FAIL → 立即停止后续子项目部署。

### Step 3 — 整体健康验证

所有子项目部署完成后，执行整体健康验证：
- 所有服务进程存活
- 所有核心端口可达
- HTTP 端点返回预期状态码（2xx 或 3xx 重定向到登录页）
- 前后端联通性验证（前端能访问后端 API）

**前端强制验证（存在前端子项目时必须执行）**：

| 验证项 | 方法 | 失败处理 |
|--------|------|---------|
| 前端入口可访问 | `curl <frontend_url>` 返回 HTTP 200 且 Content-Type 含 `text/html` | 标记前端 FAIL |
| 前端返回有效 HTML | 响应体包含框架入口标签（如 `<div id="...">`、`<script type="module">`）或非空 HTML 结构 | 标记前端 FAIL |
| API 代理联通 | 通过前端端口访问 `/api/...` 返回 HTTP 200 | 标记前端 FAIL |
| 前端独立于后端 | 前端端口 ≠ 后端端口（确认是独立进程而非后端内嵌） | 若相同则需要额外验证前端路由确实可用 |

**验证时序**：先验证每个子项目独立可用，再验证整体联通。不允许跳过任何已部署子项目的验证。

**SKIPPED 子项目的回溯验证**：对于标记为 SKIPPED 的子项目，如果其角色是 `frontend`，必须证明前端功能已被其他子项目覆盖（例如后端确实在同一端口服务了完整的前端页面，且 HTTP 200 + 有效 HTML）。无法证明则必须回退，将该子项目改为部署。

## 远程部署流程

当本地环境无法部署时，支持远程服务器部署：

1. **获取远程信息**：向用户询问 `remote_host`、`remote_user`、`remote_project_path`、SSH 认证方式
2. **连接验证**：SSH 连通性测试 + 目标路径可写性验证
3. **代码同步**：通过 rsync/scp 将项目代码同步到远程
4. **远程执行**：通过 SSH 在远程执行部署命令
5. **日志回传**：将远程部署日志拉回本地存储到 receipt
6. **健康检查**：通过远程端口转发或直连验证服务状态

远程部署的 receipt 必须额外记录 `deploy_mode: "remote"` 及远程连接信息。

## 健康检查标准

部署成功的判定必须同时满足：

| 检查项 | 通过标准 |
|--------|---------|
| 进程存活 | 所有核心服务进程 PID 存在且非 zombie |
| 端口可达 | 所有声明的服务端口 TCP 连接成功 |
| HTTP 响应 | 至少一个 HTTP 端点返回 2xx 或 3xx（重定向到登录页也算通过） |
| 启动稳定性 | 服务启动后 10 秒内无退出/重启 |
| 日志无致命错误 | 启动日志中无 FATAL/CRITICAL/panic 级别错误 |
| **前端可用性** | **前端入口 URL 返回 HTTP 200 + 有效 HTML（非 404/502/空白页）** |
| **前后端联通** | **通过前端代理访问后端 API 返回 HTTP 200** |

**关于 HTTP 302 的判定**：
- 后端根路径 `/` 返回 302 → 正常（重定向到登录页）
- 前端入口路径返回 302 → **不算通过**，必须追踪重定向目标确认最终返回 200 + HTML
- 任何路径返回 404 → **明确失败**，说明该路由未被服务

**关于"后端内嵌前端"的判定**：
- 不允许仅凭假设认定"后端已服务前端"
- 必须实际验证：访问前端预期入口路径，确认返回 HTTP 200 + 包含有效 HTML 结构的响应体
- 如果验证失败（404 或空白），则必须部署独立前端

## 产物要求

| 产物 | 路径 |
|------|------|
| Deploy Receipt | `.harness/features/<epic-id>/deploy-receipt.json` |

`deploy-receipt.json` 必须包含：

**顶级字段（必填）**：
- `epic_id`
- `deploy_mode`：`local` 或 `remote`
- `status`：`PASS`、`FAIL` 或 `SKIPPED`
- `started_at` / `completed_at`：ISO 时间戳
- `error_summary`：失败时的错误摘要（PASS 时为空字符串）
- `fixes_applied`：环境适配修复记录列表，每项含 `file`、`description`
- `failed_sub_projects`：失败的子项目名称列表
- `skipped_sub_projects`：跳过的子项目名称列表

**远程部署额外字段**（`deploy_mode: "remote"` 时必填）：
- `remote_host`
- `remote_user`
- `remote_project_path`

**sub_projects 数组**（每个子项目一项）：
- `name`：子项目名称
- `path`：子项目相对路径
- `role`：`backend` / `frontend` / `worker` / `scheduler` / `database` / `cache` / `gateway` / `other`
- `deploy_command`：实际执行的部署命令
- `deploy_type`：部署类型（`docker-compose` / `systemd` / `npm-start` / `script` / `manual`）
- `detected_by`：`config` / `auto-detect` / `user-provided`
- `status`：`PASS` / `FAIL` / `SKIPPED`
- `exit_code`：部署进程退出码
- `service_status`：各服务组件状态（key → `running`/`healthy`/`stopped`/`error`）
- `fixes_applied`：该子项目的环境适配修复列表
- `error_summary`：失败原因
- `remote_logs`：远程部署时的日志摘要

**frontend 字段**（存在前端子项目时必填）：
- `frontend.type`：前端框架类型（通过扫描构建配置文件自动识别，如 SPA / SSR / Static）
- `frontend.source_dir`：前端源码目录
- `frontend.serve_mode`：服务方式（独立 dev server / 后端托管 / nginx 代理）
- `frontend.base_url`：可访问的前端 URL
- `frontend.routes`：可访问的路由列表
- `frontend.auth_required`：是否需要登录才能使用

整体 `status` 判定：所有需部署子项目均 PASS → `PASS`；任一 FAIL → `FAIL`；全部 SKIPPED → `SKIPPED`。

## 出口条件

### 全部成功（PASS）或跳过（SKIPPED）

```bash
$HARNESSCTL state transition <epic-id> E2E
```

提示下一步：`/stage-harness:harness-e2e <epic-id>`

### 任一子项目失败（FAIL）

根据失败类型区分回流路径：

**配置/脚本问题**（路径错误、.env 配置、端口冲突、权限问题、外部依赖不可达）：
1. 在 Step 2 的自动恢复循环中已自主完成诊断和修复
2. 若恢复循环成功修复 → 不视为 FAIL，继续部署
3. 若恢复循环 3 轮后仍失败但错误仍属配置类 → 尝试更大范围的配置修复（如禁用非核心功能模块的外部依赖初始化），记录到 `fixes_applied`，重试一次
4. 最终仍失败 → 写 FAIL receipt，触发 FIX

**代码问题**（编译产物缺失、依赖冲突、代码逻辑导致启动崩溃）：
1. 将失败子项目的错误信息和日志写入 deploy-receipt.json
2. 在终端输出失败子项目的错误摘要和日志前 50 行
3. 触发 FIX 循环：

```bash
$HARNESSCTL state transition <epic-id> FIX
```

FIX 阶段完成后，重新从 BUILD 开始，确保修复后的代码经过完整的编译 → 部署 → E2E 链路验证。

**判定标准**：如果错误信息中包含以下特征则为配置/脚本问题，否则为代码问题：
- 路径 not found / permission denied
- port already in use / address already in use
- env variable missing / invalid format
- connection refused / timeout（对外部依赖如代理、DNS、第三方 API）
- command not found（工具未安装）
- proxy error / unreachable host
- SSL/TLS handshake failure（对外部服务）

## 错误处理

| 错误场景 | 处理方式 |
|---------|---------|
| BUILD 门禁未通过 | 终止，提示先完成编译阶段 |
| Level 3 预算耗尽且仍有不可部署的核心子项目 | 终止，提示手动配置 `sub_projects` 或提供远程服务器 |
| 用户选择全部跳过 | 写 SKIPPED receipt，直接推进 E2E |
| 某子项目部署命令不存在 | 尝试自动安装，失败则写 FAIL receipt，提示检查工具安装 |
| 某子项目部署超时（> 60 分钟） | 写 FAIL receipt（timeout），触发 FIX |
| 某子项目部署命令成功但服务随后崩溃 | 自主执行诊断-修复-重试循环（最多 3 轮），不中断用户 |
| 某子项目部署失败或服务状态异常 | 按失败类型区分：配置问题就地修复重试 / 代码问题触发 FIX |
| 远程服务器连接失败 | 重试 3 次后写 FAIL，提示检查网络和 SSH 配置 |
| 远程磁盘空间不足 | 提示用户清理远程磁盘，终止 |

## 与其他阶段的关系

```
BUILD (PASS/SKIPPED) → /stage-harness:harness-deploy
                     → 全部 PASS/SKIPPED → E2E
                     → 配置问题 → 就地修复 → 重试 DEPLOY
                     → 代码问题 → FIX → BUILD → DEPLOY（重试）
```
