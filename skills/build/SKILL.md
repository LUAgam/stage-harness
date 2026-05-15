# SKILL: build

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

BUILD 阶段编译执行技能。通过三级推断链确定编译命令（已有配置 → 代码感知自动推断 → 询问用户），执行编译，捕获输出，写 build-receipt.json，返回 PASS 或 FAIL。

---

## 触发条件

- 当前 epic state = `BUILD`
- 收到 `/stage-harness:harness-build` 命令
- 从 FIX 阶段回流后重新编译

---

## 执行流程

### Step 1 — 三级推断链：确定编译命令

#### Level 1 — 读取已有配置

```bash
BUILD_CMD=$(python3 -c "
import yaml, sys
try:
    with open('.harness/project-profile.yaml') as f:
        profile = yaml.safe_load(f)
    cmd = profile.get('build_command', '').strip()
    print(cmd if cmd else 'MISSING')
except Exception as e:
    print('MISSING')
")
```

若 `BUILD_CMD` 非空且非 `MISSING`，直接跳到 Step 2。

#### Level 2 — 代码感知自动推断

扫描项目根目录特征文件，按以下优先级依次匹配：

```python
import json, os, subprocess

def detect_build_command():
    cwd = os.getcwd()

    # 1. package.json — Node.js 项目
    if os.path.exists("package.json"):
        with open("package.json") as f:
            pkg = json.load(f)
        scripts = pkg.get("scripts", {})
        if "build" in scripts:
            # 检测包管理器
            if os.path.exists("yarn.lock"):
                return "yarn build"
            elif os.path.exists("pnpm-lock.yaml"):
                return "pnpm run build"
            else:
                return "npm run build"
        else:
            # 无 build script，仅安装依赖
            return "npm install"

    # 2. go.mod — Go 项目
    if os.path.exists("go.mod"):
        return "go build ./..."

    # 3. pom.xml — Maven/Java 项目
    if os.path.exists("pom.xml"):
        return "mvn package -DskipTests"

    # 4. build.gradle / build.gradle.kts — Gradle 项目
    if os.path.exists("build.gradle") or os.path.exists("build.gradle.kts"):
        wrapper = "./gradlew" if os.path.exists("gradlew") else "gradle"
        return f"{wrapper} build -x test"

    # 5. Cargo.toml — Rust 项目
    if os.path.exists("Cargo.toml"):
        return "cargo build --release"

    # 6. CMakeLists.txt — C/C++ 项目
    if os.path.exists("CMakeLists.txt"):
        return "cmake -B build && cmake --build build/"

    # 7. Makefile（含 build target）
    if os.path.exists("Makefile"):
        try:
            out = subprocess.check_output(["make", "-n", "build"], stderr=subprocess.DEVNULL, text=True)
            return "make build"
        except Exception:
            pass

    # 8. pyproject.toml / setup.py — Python 项目
    if os.path.exists("pyproject.toml") or os.path.exists("setup.py"):
        return "pip install -e ."

    # 9. Dockerfile — 容器化项目（兜底）
    if os.path.exists("Dockerfile"):
        # 推断项目名（取目录名）
        project_name = os.path.basename(cwd).lower().replace(" ", "-")
        return f"docker build -t {project_name} ."

    return None

cmd = detect_build_command()
if cmd:
    print(cmd)
else:
    print("MISSING")
```

推断成功时：
1. 将命令写回 `.harness/project-profile.yaml` 的 `build_command` 字段（持久化，避免下次重复推断）
2. 输出：`[AUTO-DETECTED] build_command = "<cmd>"`
3. 继续执行 Step 2

#### Level 3 — 询问用户（消耗中断预算）

仅在 Level 1 和 Level 2 均失败时触发。展示已扫描到的项目特征，向用户提问：

```
无法自动推断编译命令。

已扫描项目根目录，未发现已知构建系统特征文件
（package.json / go.mod / pom.xml / build.gradle / Cargo.toml / Makefile / Dockerfile 等）。

请提供以下信息之一：
  1. 编译命令（例如：npm run build / go build ./... / make all）
  2. 输入 "skip" 跳过编译，直接进入部署阶段
```

消耗 1 次中断预算（`$HARNESSCTL budget consume --epic-id <epic-id>`）。

用户回答后：
- 若提供命令：写入 `project-profile.yaml` 的 `build_command` 字段，继续执行
- 若输入 `skip`：写 build-receipt.json（`status = SKIPPED`），推进到 DEPLOY

---

### Step 2 — 记录开始时间

```bash
STARTED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
BASE_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "")
```

---

### Step 3 — 执行编译

```bash
BUILD_OUTPUT=$($BUILD_CMD 2>&1)
BUILD_EXIT=$?
COMPLETED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
```

超时控制：若编译超过 30 分钟，强制终止并标记为 FAIL（timeout）。

---

### Step 4 — 解析结果

根据 `BUILD_EXIT` 判断：
- `0`：PASS
- 非 `0`：FAIL

提取错误摘要（FAIL 时），识别常见错误模式：

| 错误模式 | 分类 |
|---------|------|
| `error:` / `Error:` / `ERROR` | 编译错误 |
| `cannot find` / `not found` / `No such file` | 依赖缺失或路径错误 |
| `syntax error` / `SyntaxError` | 语法错误 |
| `permission denied` | 权限问题 |
| `out of memory` / `OOM` | 内存不足 |
| `timeout` / `timed out` | 超时 |

---

### Step 5 — 写 build-receipt.json

```python
import json, os

output_lines = BUILD_OUTPUT.splitlines()
stdout_tail = "\n".join(output_lines[-200:])

receipt = {
    "epic_id": EPIC_ID,
    "build_command": BUILD_CMD,
    "detected_by": "config" | "auto-detect" | "user-input" | "skipped",
    "status": "PASS" if BUILD_EXIT == 0 else "FAIL",
    "exit_code": BUILD_EXIT,
    "stdout": stdout_tail,
    "stderr": "",
    "started_at": STARTED_AT,
    "completed_at": COMPLETED_AT,
    "base_commit": BASE_COMMIT,
    "error_summary": "\n".join(output_lines[-20:]) if BUILD_EXIT != 0 else "",
    "error_category": "<分类>",   # 编译错误 / 依赖缺失 / 语法错误 / 权限问题 / 超时 / 未知
}

os.makedirs(f".harness/features/{EPIC_ID}/build", exist_ok=True)
with open(f".harness/features/{EPIC_ID}/build/build-receipt.json", "w") as f:
    json.dump(receipt, f, indent=2, ensure_ascii=False)
```

---

## 输出

### 成功（PASS）

```
✅ BUILD PASS
   命令: <build_command>（来源: <detected_by>）
   耗时: <duration>
   产物: .harness/features/<epic-id>/build/build-receipt.json
```

### 跳过（SKIPPED）

```
⏭️  BUILD SKIPPED（用户选择跳过编译）
   产物: .harness/features/<epic-id>/build/build-receipt.json
```

### 失败（FAIL）

```
❌ BUILD FAIL (exit_code=<n>，分类: <error_category>)
   命令: <build_command>
   错误摘要:
   <error_summary>
   产物: .harness/features/<epic-id>/build/build-receipt.json
```

---

## 阻断条件

| 条件 | 说明 |
|------|------|
| 三级推断均失败且中断预算耗尽 | 终止，提示手动配置 build_command |
| 编译退出码非 0 | 写 FAIL receipt，触发 FIX |
| 编译超时（> 30 分钟） | 写 FAIL receipt（timeout），触发 FIX |
| 写 receipt 失败 | 报告 IO 错误，终止 |

---

## 与 runtime-harness 的关系

build skill 不嵌入 runtime-harness 的 5 个检查点（那是 EXECUTE 阶段专用）。BUILD 阶段控偏规则：
- 编译成功 → 推进 DEPLOY
- 编译失败 → 触发 FIX，FIX 后重新执行 build skill（重新从 Level 1 开始，使用已持久化的命令）
