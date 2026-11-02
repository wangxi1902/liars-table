# 动态决策预算与安全 Trace

这一阶段解决两个实际问题：AI 不能无限思考；前端以后需要知道 AI 正在做什么，
但不能展示模型的隐藏思维链。

## 1. 先理解数据流

一次投票请求现在按下面的顺序流动：

```text
.env / CLI / 创建对局 API
        ↓
DecisionBudget（本局默认上限）
        ↓
DecisionBudgetPolicy（按座位和决策类型选择）
        ↓
LLMAgent.decide
        ↓
LangGraph DecisionWorkflow
        ↓
DecisionRunResult（行动、耗时状态、计数、Trace）
        ↓
Engine 再做最终合法性检查
```

规则引擎仍然不依赖 LangGraph。超时只会让本次 Agent 返回空决策，Engine 会按已有
规则兜底，AI 不能借超时跳过游戏阶段或直接修改 `GameState`。

## 2. Python 基础：dataclass 和不可变配置

`DecisionBudget` 使用 `@dataclass(frozen=True, slots=True)`：

- `dataclass` 自动生成初始化方法，适合“主要用于装数据”的类；
- `frozen=True` 表示创建后不能改字段，防止决策执行到一半规则突然变化；
- `slots=True` 限制可用字段，拼错属性名时会尽早报错。

它包含五个上限：

| 字段 | 含义 |
|---|---|
| `max_seconds` | 整次决策最多耗时 |
| `max_steps` | 最多完成多少个认知节点 |
| `max_model_calls` | 最多请求几次模型 |
| `max_completion_tokens` | 单次模型回复长度上限 |
| `max_retries` | 输出格式错误后最多重试几次 |

这些是“最多允许多少”，不是“必须思考多久”。模型提前完成就立即返回。

## 3. 动态选择：Policy

`DecisionBudgetPolicy.resolve(request)` 的优先级是：

```text
座位 + 决策类型 > 决策类型 > 座位 > 本局默认值
```

例如可以让所有投票最多 2 秒、所有发言最多 8 秒，同时让 P3 的发言单独使用
12 秒。这里使用普通 Python 字典完成选择，LangGraph 不需要知道配置来自哪里。

当前 CLI 和 API 先开放“本局默认值”；按座位/类型覆盖的后端能力和单元测试已经
存在，后续设置页面确定交互形式后再开放接口，避免过早固定 API 数据结构。

## 4. async/await 和硬超时

模型请求是网络 I/O。`await client.complete(...)` 表示等待返回时把执行权交给事件
循环，因此其他 HTTP、WebSocket 或 Agent 任务仍能继续运行。

工作流外层使用：

```python
async with asyncio.timeout(budget.max_seconds):
    state = await graph.ainvoke(initial_state)
```

达到时间上限后，当前异步执行会被取消，工作流返回 `timed_out=True`。程序错误没有
被当成超时吞掉，仍会抛出并记录失败状态，便于发现真实 Bug。

## 5. Trace 为什么不是“思维链”

`DecisionTrace` 只包含：座位、决策类型、节点、状态、简短摘要、耗时、步骤数、
模型调用次数和可见级别。它不包含：

- Prompt；
- 模型原始回复；
- 隐藏推理文本；
- 其他角色的私密信息。

因此前端以后可以显示“P3 正在检索记忆 → 请求模型 → 校验行动”，但不会暴露
不适合存储和展示的内部推理。当前 API 的 `GET /api/games/{id}` 已返回
`decision_traces`；WebSocket实时推送和React头像卡片已在下一阶段完成，详见
`06-结构化决策依据与实时展示.md`。

## 6. 如何运行

环境默认值写在 `.env`：

```dotenv
DECISION_TIMEOUT_SECONDS=5
DECISION_MAX_STEPS=8
DECISION_MAX_MODEL_CALLS=2
DECISION_MAX_COMPLETION_TOKENS=800
DECISION_MAX_RETRIES=1
```

只覆盖一次 CLI 演示：

```bash
uv run liars-table demo --decision-timeout 3 --decision-max-model-calls 1
```

创建一局时覆盖：

```text
POST /api/games?seed=7&decision_timeout=3&decision_max_retries=0
```

## 7. 学习检查点

完成本节后，应该能回答：

1. 为什么预算是不可变对象，而运行计数器可以变化？
2. `max_retries=1` 为什么可能产生两次模型调用？
3. 超时后为什么由 Engine 兜底，而不是让 LangGraph 修改规则状态？
4. Trace 与模型隐藏思维链有什么区别？

可选练习：在测试中增加一条 `by_kind={"speech": ...}` 配置，验证发言与投票拿到
不同时间预算，不需要修改任何图节点。
