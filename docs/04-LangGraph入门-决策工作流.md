# LangGraph 入门：把一次 Agent 决策拆成可观察的步骤

本阶段的目标不是“把项目改成 LangGraph 项目”，而是先学会怎样用一张小图表达
**一个 AI 玩家的一次决策**。

## 一、不用 LangGraph 时，普通 Python 会怎样写

一次决策最直观的伪代码是：

```python
messages = prepare_context(request)
raw_output = await call_model(messages)
payload = validate_output(raw_output)

if payload is None:
    messages = prepare_retry(messages, raw_output)
    raw_output = await call_model(messages)
    payload = validate_output(raw_output)
```

这个写法没有错。LangGraph 并不会让模型突然更聪明，它解决的是：

- 步骤越来越多时，流程仍然清楚；
- 每一步可以单独测试和记录；
- 失败后可以明确回到某个节点；
- 后续可以加入持久化、流式事件和人工介入。

## 二、State：在节点之间传递的数据

`DecisionState` 使用 `TypedDict` 描述：

```python
class DecisionState(TypedDict):
    request: DecisionRequest
    messages: list[ChatMessage]
    raw_output: str
    payload: ActionPayload | None
    attempt: int
    error: str
```

运行时它仍然是普通字典：

```python
state["attempt"]
state["payload"]
```

`TypedDict` 的作用是告诉 IDE 和阅读代码的人：这张字典应该有哪些键，每个键是什么类型。

为什么状态里同时保存 `raw_output` 和 `payload`？

- `raw_output` 是模型原文，用于调试和失败修复；
- `payload` 是校验后的结构，只有它能进入后续业务逻辑。

## 三、Node：本质上是普通函数

例如验证节点：

```python
def validate_output(self, state: DecisionState) -> dict[str, object]:
    payload = parse_action(state["raw_output"])
    if payload is None:
        return {"payload": None, "error": "模型输出不是合法的 Action JSON"}
    return {"payload": payload, "error": ""}
```

节点接收完整状态，但只返回需要更新的字段。LangGraph 会把返回值合并回共享状态。

当前有四个节点：

| 节点 | 输入重点 | 输出重点 | 是否调用模型 |
|---|---|---|---|
| `prepare_context` | 请求、记忆、事实 | 消息列表 | 否 |
| `call_model` | 消息列表 | 模型原文、调用次数 | 是 |
| `validate_output` | 模型原文 | Pydantic Payload 或错误 | 否 |
| `prepare_retry` | 错误原文、旧消息 | 增加纠错提示后的消息 | 否 |

只让一个节点调用模型，有助于区分确定性代码和不确定的 LLM 行为。

## 四、Edge：节点之间的路线

普通边表示固定下一步：

```python
graph.add_edge("prepare_context", "call_model")
graph.add_edge("call_model", "validate_output")
```

条件边表示根据状态选择路线：

```python
graph.add_conditional_edges(
    "validate_output",
    self.route_after_validation,
    {"finish": END, "retry": "prepare_retry"},
)
```

`route_after_validation()` 不修改数据，只回答下一步走哪里：

```text
payload 存在                  → finish
payload 不存在且还有重试次数 → retry
payload 不存在且次数已耗尽   → finish（返回 None）
```

## 五、为什么 attempt 的判断是 `<= max_retries`

假设 `max_retries = 1`，含义是“首次调用失败后，再试一次”：

| 时刻 | attempt | 是否还能重试 |
|---|---:|---|
| 尚未调用 | 0 | — |
| 第一次调用失败 | 1 | 可以 |
| 第二次调用失败 | 2 | 不可以 |

所以判断是：

```python
if state["attempt"] <= self.max_retries:
    return "retry"
```

这类边界很容易多调用一次或少调用一次，因此测试必须覆盖两个数字。

## 六、图怎样接回 LLMAgent

`LLMAgent` 初始化时编译一次图：

```python
self.workflow = DecisionWorkflow(client, self.memory, self.facts, ...)
```

每次需要决策时只做：

```python
payload = await self.workflow.run(request)
```

图输出的是通用 `ActionPayload`。`LLMAgent` 再负责：

- 把玩家名字换算成座位号；
- 合并文本中遗漏的身份声称和指控；
- 转成游戏领域的 `Decision`。

最终合法性仍由 `Engine` 检查，因此 LangGraph 没有获得修改游戏规则的权力。

## 七、怎样测试图

测试分成两层：

1. 节点测试：直接调用 `prepare_context()`、`route_after_validation()`，不运行整张图；
2. 图测试：让假客户端第一次返回垃圾、第二次返回 JSON，确认执行路径真的经过重试。

```text
坏结果 → validate_output → prepare_retry → 好结果 → END
```

这种测试不需要 API Key，也不会产生模型费用。

## 八、目前还没有使用的 LangGraph 能力

- 没有 Checkpointer，单次决策中断后不能跨进程恢复；
- 没有节点级流式事件展示；
- 没有人工介入；
- 没有子图；
- 没有向量 RAG；
- 图只改善流程结构，不会自动提高博弈能力。

下一阶段应先给图增加可观察的决策摘要和执行轨迹，再把
`prepare_context` 中的词面记忆逐步替换成带视角过滤的向量检索。

## 九、学习检查点

读完后应该能回答：

1. `DecisionState` 和普通字典有什么关系？
2. 哪个节点是不确定的 LLM 节点？
3. 为什么解析失败不是直接抛异常结束游戏？
4. 条件边在什么情况下进入 `prepare_retry`？
5. 为什么游戏规则没有放进这张图？

可选练习：把 `max_retries` 改成 0，先猜测试中的客户端会被调用几次，再运行
`tests/test_decision_graph.py` 验证答案。
