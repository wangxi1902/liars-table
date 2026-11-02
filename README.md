# Liar's Table

> 多智能体社交推理竞技场：九个 AI 同桌打狼人杀，撒谎、抓谎、反水，全程可回放、可复盘。

这不是一个"工具"，而是一个**机器剧场**——让一群 LLM 在硬规则约束下互相博弈，供人围观。

## 为什么值得做

- **规则用代码写死，智能用 LLM 填。** 流程由状态机控制，模型只能做决策，不能改规则，这是长期能跑稳的唯一办法。
- **一切事件化。** 每个动作都是一条不可变事件，当前局面由事件重放得出。回放、复盘、反事实推演因此免费获得。
- **可溯源。** 每条发言携带证据引用（哪条事件支撑了这句话），赛后可以画出"谁在撒谎、哪句话露的馅"。
- **可评测。** 同一套引擎换不同模型，直接对比欺骗成功率、识破率、存活率。

## 快速开始

```bash
uv sync

# 默认用 mock 模型，不需要 API key
uv run liars-table demo --seed 7

# 上帝视角（看到狼人刀口、预言家验人、女巫用药）
uv run liars-table demo --seed 7 --god

# 真实调用 DeepSeek（先在 .env 里填 DEEPSEEK_API_KEY）
uv run liars-table demo --seed 7 --live

# 只看规则引擎，用随机走子的假玩家
uv run liars-table demo --seed 7 --agent random

# 把整局事件流导出，用于回放或分析
uv run liars-table demo --seed 7 --dump out/game.jsonl

# 生成 Markdown 复盘报告（指控矩阵、谎报身份、无据发言）
uv run liars-table demo --seed 7 --report out/report.md

# 生成单文件 HTML 回放页（双击打开，不需要服务器）
uv run liars-table demo --seed 7 --html out/game.html

# 本地实时观战：浏览器打开 http://127.0.0.1:8000
uv run liars-table serve

# 亲眼看一下异步并发的收益
uv run liars-table bench --n 9 --latency 0.3

# 临时限制本局每次 AI 决策最多 3 秒、只调用一次模型
uv run liars-table demo --decision-timeout 3 --decision-max-model-calls 1
```

### 新版观战界面（React）

用两个终端：先起后端，再起前端（开发服务器会把 `/api` 和 `/ws` 代理到 8000）。

```bash
# 终端 1
uv run liars-table serve            # 后端 8000

# 终端 2
cd web
npm install
npm run dev                         # 前端 5173，打开 http://127.0.0.1:5173
```

界面特性：暗色主题、emoji 头像 + 中文代号、谁思考谁上浮、结构化判断依据卡片、
打字机逐条播放、出局头像划掉、结束后弹身份表。
带 `?id=<对局 id>` 可以回放任意一局（`GET /api/games/{id}` 返回的 id）。

两种运行模式：

| 模式 | 命令 | 需要 key | 用途 |
|---|---|---|---|
| mock | 默认 | 不需要 | 跑通链路、跑测试、演示并发 |
| live | `--live` | 需要 | 真实对局，观察模型撒谎 |

`--latency` 控制 mock 模式模拟的网络延迟，用来观察"发言串行、投票并发"的差别。

## 架构

```
┌─────────────────────────── Engine ───────────────────────────┐
│  规则状态机  Night → Dawn → Discussion → Vote → Settle        │
│  每个动作 = 一条不可变 Event，状态 = fold(events)              │
└───────────────┬──────────────────────────────┬───────────────┘
                │ DecisionRequest              │ Event
        ┌───────▼────────┐              ┌──────▼───────┐
        │  Agent Runtime │              │  Replay/分析  │
        │ LangGraph      │              │ 复盘·矛盾检测 │
        │ 上下文→模型→校验│              │ 反事实推演    │
        │ 动态预算·Trace │              └──────────────┘
        └───────┬────────┘
                │
        ┌───────▼────────┐
        │ LangChain Model│
        │  DeepSeek API  │
        └────────────────┘
```

关键点：Agent 拿到的不是 `GameState`，而是一个裁剪过的 `DecisionRequest`（自己的身份、公开记录、私有笔记、合法目标）。**它无法读到别人的身份**，所以不能作弊。

## 目录

```
src/liars_table/
├── core/
│   ├── roles.py     身份、阵营、9 人板子
│   ├── events.py    不可变事件定义
│   ├── state.py     状态 + fold/replay
│   └── rules.py     胜负判定、票型统计（纯函数）
├── agents/
│   ├── base.py      Agent 接口：DecideRequest → Decision（异步）
│   ├── prompts.py   prompt 拼装
│   ├── decision_graph.py  LangGraph 决策节点、条件路由与失败重试
│   ├── decision_runtime.py 动态预算、选择策略、安全 Trace 与运行结果
│   ├── llm_agent.py LLM 玩家：运行决策图、转换领域结果
│   └── random_agent.py  合法随机走子，用于压测规则
├── llm/
│   ├── base.py      项目内模型协议与消息类型
│   ├── client.py    客户端工厂与兼容入口
│   ├── mock.py      离线 Mock 模型
│   ├── langchain_client.py  LangChain 模型适配器
│   └── schema.py    模型输出解析
├── memory/
│   ├── models.py    记忆单元：从事件翻译成"玩家视角"
│   └── store.py     记忆存取 + 检索打分（新近度/重要性/相关性）
├── engine.py        回合调度、事件发射、并发控制、可见性裁决
└── cli.py           命令行观战台 + 并发基准
```

## 当前规则（v0.1）

| 项 | 规则 |
|---|---|
| 板子 | 3 狼人 / 预言家 / 女巫 / 猎人 / 3 村民 |
| 夜晚 | 狼人各自提议，多数决；预言家查验；女巫可救人**或**毒人（同一夜不能同时） |
| 白天 | 依次发言 → 全体投票 → 最高票出局 |
| 平票 | 无人出局（简化规则，后续可加 PK） |
| 猎人 | 被狼杀 / 被投出 / 被毒杀时开枪带走一人 |
| 胜负 | 狼人全灭则好人胜；狼人数量 ≥ 好人则狼人胜 |

## 路线图

- [x] v0.1 规则引擎 + 事件溯源 + 随机 agent 压测
- [x] v0.2 LLM agent（异步、JSON 结构化输出、失败重试、mock 模式）
- [x] v0.3a 记忆系统（事件→记忆、打分检索、可见性隔离）
- [x] v0.3b 事件编号 + 发言证据引用（引擎校验，编造的编号被丢弃）
- [x] v0.4 结构化断言 + 赛后矛盾检测 + Markdown 复盘报告
- [x] v0.5a 单文件 HTML 回放页（时间线 / 指控矩阵 / 上帝视角开关）
- [x] v0.5b 实时观战（FastAPI + WebSocket，服务端内嵌首屏 + 增量推送）
- [x] v0.5c React 观战界面（暗色、头像上浮、打字机、回放链接）
- [x] v0.6a LangChain 模型适配层（标准 ChatModel、Pydantic 输出校验、离线 Fake 测试）
- [x] v0.6b 最小 LangGraph 决策图（状态、节点、条件边、失败修复循环）
- [x] v0.6c 动态决策预算（超时/步骤/调用/token）+ 安全结构化 Trace
- [x] v0.6d 结构化决策依据（怀疑度/公开事件引用）+ WebSocket实时头像卡片
- [x] v0.6e 跨回合怀疑度账本（确定性更新、变化原因、事件溯源）
- [x] v0.6f 身份硬规则与可选策略拆分（允许无策略状态）
- [x] v0.6g 个体化对话记忆（最近原文、旧发言压缩、自我承诺、来源编号）
- [ ] v0.6 反事实推演、多模型对抗排行榜
- [ ] v0.7 Docker 部署 + CI

## 开发

```bash
uv run pytest      # 规则与集成测试
uv run ruff check .
```

## License

MIT
