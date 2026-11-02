# LangChain 模型接入：先学会模型边界，再进入 LangGraph

这一阶段只解决一个问题：**怎样让 Agent 使用 LangChain 的标准模型接口，同时不让框架侵入游戏规则。**

## 一、为什么现在引入 LangChain

原来的调用链是：

```text
LLMAgent → 项目 ChatClient → OpenAI SDK → DeepSeek
```

它可以运行，但真实客户端直接绑定了一个 SDK。以后增加其他模型、Tracing、统一消息类型时，
这些工作都要继续堆进同一个文件。

现在的调用链是：

```text
LLMAgent
   ↓ 只认识项目协议
ChatClient
   ├── MockClient                  离线测试
   └── LangChainChatClient        框架适配
           ↓
      LangChain BaseChatModel
           ↓
      ChatOpenAI → DeepSeek
```

LangChain 在这里承担“模型适配层”，不是游戏规则，也不是 Agent 的思考流程。

## 二、先理解四个基础概念

### 1. Protocol：项目自己的插座

`llm/base.py` 中的 `ChatClient` 是一个很小的异步协议。只要一个对象实现了
`complete()`，`LLMAgent` 就能使用它。

它的意义是让上层依赖“能力”而不是某个框架：

- 测试插入 `MockClient`；
- 真实运行插入 `LangChainChatClient`；
- 将来即使不用 LangChain，也不需要修改 `LLMAgent`。

### 2. Adapter：把两种接口翻译成彼此认识的形状

`LangChainChatClient` 是适配器。它负责：

1. 把项目的 `ChatMessage` 转成 LangChain 的 `SystemMessage`、`HumanMessage` 和
   `AIMessage`；
2. 异步调用 `BaseChatModel.ainvoke()`；
3. 把 LangChain 返回值转换回项目的 `ChatResult`；
4. 统计单次和累计 token。

Agent 不需要知道这些转换细节。

### 3. BaseChatModel：统一模型接口

LangChain 的聊天模型都实现相近的调用方式。项目只需要给适配器一个
`BaseChatModel`，不需要在业务层判断它究竟来自哪个提供商。

DeepSeek 提供 OpenAI 兼容接口，所以这里用 `ChatOpenAI`，并把 `base_url` 指向
DeepSeek。`extra_body` 继续承载 DeepSeek 特有的思考模式参数。

### 4. 结构化输出：模型文本仍然不可信

“要求模型输出 JSON”不等于结果一定正确。返回值仍可能是：

- 非 JSON 文本；
- 字段缺失；
- 字段类型错误；
- Markdown 代码块包裹的 JSON。

`llm/schema.py` 先抽取 JSON，再交给 Pydantic `ActionPayload` 校验。
例如 `save` 使用严格布尔类型，所以字符串 `"false"` 会被拒绝，而不会因为
Python 的真值规则被错误地当成 `True`。

解析失败后，`LLMAgent` 会提示模型修正并重试一次；再次失败则返回空决策，由
规则引擎从合法目标中兜底。

## 三、为什么不让 LLMAgent 直接依赖 LangChain

直接把 `BaseChatModel` 传给 `LLMAgent` 代码更少，但会带来三个问题：

1. 所有 Agent 测试都必须理解 LangChain 消息类型；
2. 框架升级会沿依赖链影响业务层；
3. Mock、计量和提供商特有参数缺少统一边界。

当前多一层适配器，换来清楚的依赖方向：

```text
core ← engine ← agents ← llm 协议 ← LangChain 基础设施
```

## 四、怎样运行

默认 Mock 模式不需要 API Key：

```bash
uv run liars-table demo --seed 7
```

真实模式读取 `.env`：

```dotenv
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_THINKING=false
DEEPSEEK_MAX_TOKENS=800
```

```bash
uv run liars-table demo --seed 7 --live
```

## 五、怎样测试

`tests/test_llm.py` 使用 LangChain 自带的 Fake ChatModel 验证适配器，不会发出网络请求。
目前重点覆盖：

- 项目消息能转换并完成异步调用；
- token 用量能回收到 `ChatResult`；
- 非法消息角色会在请求前被拒绝；
- 非法 JSON 和字段类型触发重试或降级；
- Mock 模式能跑完整局。

## 六、这一阶段没有解决什么

- 还没有 LangGraph 节点和图状态；
- 还没有向量 Embedding、Retriever 和向量数据库；
- 还没有提升 Agent 的实际博弈能力；
- 还没有跨进程持久化模型调用记录。

下一阶段会在这个统一模型边界之上，把 Agent 的一次决策拆成可测试的 LangGraph
节点，而不是让 LangGraph 接管游戏规则。
