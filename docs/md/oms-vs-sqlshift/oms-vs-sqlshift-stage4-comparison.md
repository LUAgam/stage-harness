# OMS vs SQLShift 阶段4对比

本文继续对比两套流程在**阶段4**的实现差异：

- `ai-programmer-oms`
- `ai-programmer-sqlshift`

这里的“阶段4”按你要求，明确采用**按阶段对齐**方式定义，也就是看：

- 最终需求与技术方案已经收敛后
- 系统如何真正进入**方案执行 / 代码落地 / 构建部署**阶段

## 一句话结论

如果按阶段顺序继续往后看，阶段4确实应该对齐到“**方案执行**”。

两边在这个阶段的共同主线都是：

1. `execute_tech_design`
2. `build_deploy`

但两边实现哲学不完全一样：

- `oms`：执行链更细，主入口支持 `plan / auto / execute / build-deploy / apply-tech-reply` 多种推进方式
- `sqlshift`：执行链更短，主入口偏 `full-run`，但 `build_deploy` 背后会根据 `profile=sqlshift` 分发到专用部署实现

所以更准确地说：

- `oms` 的阶段4是“**细粒度编排的执行与构建热更阶段**”
- `sqlshift` 的阶段4是“**主入口更紧凑，但后端切到 SQLShift 专用执行/部署机制的执行阶段**”

## 一、为什么阶段4应该是执行

从阶段顺序看：

- 阶段1、2、3都还在处理“需求文档”和“技术方案/最终定稿”
- 到了下一阶段，合理的顺序就不再是继续做文档，而是开始真正执行方案

这点在两边代码结构里也很明显：

- 两边都有独立的 `generate_code.py`
- 两边都把执行链拆成：
  - 技术方案执行
  - 构建/热更/部署

所以这次按阶段对齐，阶段4就应该落在：

- **方案执行阶段**

## 二、阶段4映射

### `ai-programmer-oms`

阶段4主链：

1. `execute_tech_design`
2. `build_deploy`

对应入口主要在 `generate_code.py`：

- `auto`
- `execute`
- `build-deploy`
- `apply-tech-reply`

如果前面的技术收敛没有阻塞，`auto` 会自然推进到：

- 执行技术方案
- 构建
- 失败修复
- 热更

### `ai-programmer-sqlshift`

阶段4主链同样也是：

1. `execute_tech_design`
2. `build_deploy`

对应入口主要在 `generate_code.py`：

- `full-run`
- `apply-tech-reply`
- `build-deploy`

也就是说，阶段4在两边**确实是直接对应的**。

但差异在于：

- `oms` 把执行阶段拆成更多显式命令
- `sqlshift` 更倾向从 `full-run` 一路往后推

## 三、`oms` 阶段4实现流程

### 1. `execute_tech_design`

这一阶段会读取：

- 最终 PRD
- 每个仓库的技术方案
- 知识库
- 实际仓库代码

然后按仓库逐个执行。

执行要求很清楚：

- 如果该仓库不需要改动，就输出“跳过执行”报告
- 如果需要改动，就必须直接改代码，而不是只写计划
- 每个仓库都输出一份 `execution_report.md`

最终会生成：

- `execution/manifest.json`
- 各仓库执行报告

这说明 `oms` 的执行层不是“把所有仓库一把梭”，而是：

- **按仓库分别落地，并显式记录每仓是否真的执行**

### 2. `build_deploy`

这一阶段会读取 `execution/manifest.json`，只对其中：

- 状态为 `executed`

的仓库继续进行后续处理。

它支持：

- 只构建不热更
- 指定环境
- 强制重建
- 失败仓库重试
- 指定仓库模块单独构建

同时还内置：

- 编译失败识别
- AI 自动修复循环
- 本地/远程构建
- 热更或部署
- 构建结果与部署结果落盘

因此 `oms` 的阶段4本质上是：

- **代码执行 + 定向构建 + 失败修复 + 热更部署**

## 四、`sqlshift` 阶段4实现流程

### 1. `execute_tech_design`

`sqlshift` 的执行层与 `oms` 框架非常接近：

- 同样读取最终 PRD、仓库技术方案、知识库、仓库代码
- 同样按仓库生成执行报告
- 同样输出 `execution/manifest.json`

但它有几个额外特点：

- 明确指定使用 `CursorModel.GPT_5_4_MEDIUM`
- 对 SQLShift 数据库文档扩展增加了专门技能约束
- 每个仓库执行时默认不复用已有报告，而是直接推进执行

所以它仍然是“按仓库执行”，但执行 prompt 里加入了更强的项目约束。

### 2. `build_deploy`

`sqlshift` 的 `generate_code.py` 并不是直接固定调用某一种部署逻辑，而是先走：

- `run_build_deploy_task_dispatched`

然后根据配置里的 `profile` 决定：

- 若不是 `sqlshift`，走通用 `run_build_deploy_task`
- 若是 `sqlshift`，走 `run_sqlshift_build_deploy_task`

这意味着：

- 对外入口是共享的
- 对内实现是 SQLShift 专用的

### 3. SQLShift 专用部署机制

`run_sqlshift_build_deploy_task()` 不是简单复用 OMS 的热更脚本，而是基于 SQLShift 场景做了专门处理：

- 读取 `sqlshift_repos`
- 读取 `sqlshift_deploy_env`
- 根据仓库配置决定部署策略

当前能看到的典型策略包括：

- `git pull + restart`
- `upload dist + reload`

并且它同样带有：

- 构建失败日志提取
- AI 自动修复循环
- 远程 SSH 操作
- 部署日志记录

最终 manifest 阶段名也不是通用的：

- `sqlshift_build_deploy_completed`

这说明 `sqlshift` 的阶段4不是普通地“执行同一套部署逻辑”，而是：

- **共用入口，但切入专用部署后端**

## 五、差异总表

| 对比项 | `ai-programmer-oms` | `ai-programmer-sqlshift` | 我的判断 |
|---|---|---|---|
| 阶段4是否直接对应 | 是 | 是 | 这一阶段两边终于重新对齐了，都是方案执行阶段。 |
| 阶段4主链 | `execute_tech_design -> build_deploy` | `execute_tech_design -> build_deploy` | 主线一致，可以按同一阶段比较。 |
| 主入口风格 | 多命令细粒度推进 | `full-run` 为主，入口更紧凑 | `oms` 更适合分步控制，`sqlshift` 更适合快速顺推。 |
| 执行粒度 | 按仓库执行，并支持跳过 | 按仓库执行，并加入更强项目约束 | 两边都按仓库落地，但 `sqlshift` 更强调场景专属规范。 |
| 构建部署后端 | 通用构建/热更体系，可本地或远程 | 共享入口，但命中 `sqlshift` profile 后切专用部署实现 | `sqlshift` 的差异重点不在入口，而在后端专用实现。 |
| 自动修复 | 有，且和构建/热更深度集成 | 有，且与 SQLShift 专用部署策略结合 | 两边都有自动修复，但修复后的落地方式不同。 |
| 重试与定向能力 | 支持 `--repo`、`--failed-only` 等细粒度重试 | 当前主入口参数更少 | `oms` 在执行控制面上更强。 |

## 六、产物差异表

| 类别 | `ai-programmer-oms` | `ai-programmer-sqlshift` | 我的判断 |
|---|---|---|---|
| 执行清单 | `execution/manifest.json` | `execution/manifest.json` | 这一层非常接近，说明两边执行层骨架一致。 |
| 仓库执行报告 | 各仓库 `*_execution_report.md` | 各仓库 `*_execution_report.md` | 报告机制一致，但 `sqlshift` 的执行约束更强。 |
| 构建部署清单 | `build_repair_deploy_completed` 或 `targeted_build_deploy_completed` | `sqlshift_build_deploy_completed` | `sqlshift` 已经明确把自己从通用部署流程中分叉出来。 |
| 部署日志 | 有 | 有 | 两边都保留部署侧证据。 |
| 自动修复产物 | `ai_result.json`、修复报告等 | 同类产物存在 | 产物思路一致，但 SQLShift 的部署后动作更专用。 |

## 七、推进逻辑差异

### `ai-programmer-oms`

更像：

```text
最终技术方案
-> execute_tech_design
-> execution manifest
-> build_deploy
-> 编译失败自动修复
-> 热更/部署
```

它强调的是：

- 分阶段可控推进
- 哪个仓库执行、哪个仓库重试，都能精确控制

### `ai-programmer-sqlshift`

更像：

```text
最终技术方案
-> execute_tech_design
-> execution manifest
-> build_deploy dispatch
-> sqlshift 专用构建/部署
-> 编译失败自动修复
-> 远程部署/重载
```

它强调的是：

- 主入口尽量短
- 真正复杂的差异收敛到 SQLShift 专用部署后端里

## 八、我的总体判断

### 1. 这次阶段4确实应该定义为执行阶段

如果继续按阶段顺序走，而不是按能力切片走，那么：

- 阶段4最合理的定义就是“方案执行”

这一点现在可以确定。

### 2. `oms` 的执行阶段更像“控制台式编排”

它的特点是：

- 命令拆得更细
- 可以分步跑
- 可以指定仓库、失败重试、只构建不热更

所以更像一套：

- **面向工程控制的执行编排系统**

### 3. `sqlshift` 的执行阶段更像“短入口 + 专用后端”

它的特点是：

- 入口更紧凑
- 执行 prompt 更项目化
- 构建部署在后端做 profile 分流
- 真正部署动作更贴近 SQLShift 实际环境

所以更像一套：

- **面向特定产品形态定制过的执行链**

### 4. 如果必须做一句最准确的概括

我的判断是：

- `oms` 的阶段4是“可细粒度控制的通用执行与构建热更阶段”
- `sqlshift` 的阶段4是“按相同阶段推进，但在部署后端切入了 SQLShift 专用实现的执行阶段”

## 九、适用场景判断

| 场景 | 更适合 `oms` | 更适合 `sqlshift` | 我的判断 |
|---|---|---|---|
| 需要按仓库精细控制执行与重试 | 是 | 一般 | `oms` 更适合。 |
| 需要快速一键顺推主链 | 一般 | 是 | `sqlshift` 当前入口更像这种风格。 |
| 需要适配产品专属部署策略 | 一般 | 是 | `sqlshift` 的专用部署后端更贴近真实场景。 |
| 需要统一的多仓执行控制台 | 是 | 一般 | `oms` 的控制面更强。 |

## 十、最终结论

如果继续按阶段对齐，阶段4最合理的定义就是：

- **方案执行阶段**

而在这个阶段里，两边确实重新对齐到了同一主线：

- `execute_tech_design`
- `build_deploy`

但两边的分化点也很明确：

- `oms` 更强调执行控制面的完整性
- `sqlshift` 更强调入口简化与部署后端专用化
