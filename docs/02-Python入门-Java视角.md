# 从 Java 到 Python：拿 v0.2 的代码当教材

> 前提：你会 Java（类、接口、泛型、异常、线程池都懂），但没系统写过 Python。
> 目标：读完能独立看懂 `src/liars_table/llm/` 下那四个文件，并且知道每一行为什么这么写。

## 0. 先建立一个总印象

同一件事，Java 和 Python 的代码量大概是 5:1。省下来的不是"魔法"，是三样东西：

1. **不用声明类型**（类型靠注解提示，运行时不检查）
2. **不用写样板**（`@dataclass` 自动生成构造器/getter/equals）
3. **不用编译**（改完直接跑，错了才报）

代价是：**编译器原来帮你抓的错误，现在要靠测试和 `ruff` 抓**。所以这个项目里 `pytest` 和 `ruff` 不是可选项。

## 1. 目录结构对照

Java 的包是"目录 + package 声明"；Python 的包就是"目录"，模块就是"文件"。

| Java | Python | 本项目实例 |
|---|---|---|
| `com.example.llm` 包 | 目录 `llm/` | `src/liars_table/llm/` |
| `Client.java` 类文件 | `client.py` 模块 | `src/liars_table/llm/client.py` |
| `package com.example.llm;` | 不需要声明 | — |
| `import com.example.llm.Client;` | `from ..llm.client import ChatClient` | 见 `llm_agent.py` |
| `pom.xml` | `pyproject.toml` | 依赖、脚本入口、lint 配置都在这 |
| `mvn install` | `uv sync` | 装依赖、建虚拟环境 |
| `mvn test` | `uv run pytest` | 跑测试 |
| `mvn exec:java` | `uv run liars-table demo` | 跑命令行 |
| `src/test/java` | `tests/` | 测试目录，靠命名约定发现 |

一个 Java 类文件里通常只有一个 public 类；**一个 Python 文件里可以放任意多个类**，`client.py` 里就有 `ChatMessage`、`ChatResult`、`ChatClient`、`MockClient`、`DeepSeekClient` 五个。

## 2. 第一段代码：先看懂这 8 行

打开 `src/liars_table/llm/client.py`，最上面是：

```python
@dataclass(frozen=True, slots=True)
class ChatMessage:
    """一条对话消息。role 只有 system / user / assistant 三种。"""

    role: str
    content: str
```

对应的 Java（Java 16+ 的 record）：

```java
public record ChatMessage(String role, String content) {}
```

四个要点：

| 写法 | 含义 | Java 对应 |
|---|---|---|
| `class ChatMessage:` | 定义一个类 | `class ChatMessage` |
| 冒号 + 缩进 | 类体靠缩进，不靠 `{}` | `{ }` |
| `role: str` | 声明字段并加类型注解 | `private final String role;` |
| `@dataclass(...)` | 自动生成构造器、`__repr__`、`__eq__` | Lombok `@Value` / `record` |

`frozen=True` 表示创建后不能改（≈ `final` 字段），`slots=True` 表示属性白名单（≈ 不允许动态加字段）。

用起来：

```python
msg = ChatMessage(role="system", content="你好")   # 不用 new
print(msg.role)                                    # 不用 getRole()
```

**没有 `new`**，类名加括号就是构造。**没有 getter/setter**，直接点属性。

## 3. 语法对照表（一张表过完基础）

| 概念 | Java | Python |
|---|---|---|
| 变量 | `int x = 1;` | `x = 1`（无类型、无分号） |
| 常量 | `static final int N = 9;` | `N = 9`（全大写是约定，不是强制） |
| 字符串 | `"abc"` | `"abc"` / `'abc'` 都可以 |
| 字符串插值 | `"a" + x` / `String.format` | `f"a{x}"` |
| 列表 | `new ArrayList<String>()` | `[]`，类型写 `list[str]` |
| 字典 | `new HashMap<String, Integer>()` | `{}`，类型写 `dict[str, int]` |
| 集合 | `new HashSet<>()` | `set()`，类型写 `set[str]` |
| 不可变列表 | `List.of(...)` | `tuple`，写 `(1, 2)` |
| 空值 | `null` | `None` |
| 条件 | `if (x > 0) { }` | `if x > 0:` + 缩进 |
| 循环 | `for (String s : list)` | `for s in list:` |
| 三元 | `a ? b : c` | `b if a else c` |
| 方法 | `int f(int x) { return x; }` | `def f(x: int) -> int:` + `return x` |
| 构造器 | `public Foo() { }` | `def __init__(self, ...):` |
| this | `this.x` | `self.x`（`self` 必须写在参数第一位） |
| 接口 | `interface A { void f(); }` | `class A(Protocol)`（见第 4 节） |
| 实现接口 | `class B implements A` | 不用写，有方法就算实现 |
| 访问控制 | `private` / `public` | 约定：`_x` 表示内部使用（**不强制**） |
| 异常 | `try/catch/throw` | `try/except/raise` |
| 受检异常 | `throws IOException` | **不存在**，所有异常都是运行时 |
| 泛型 | `List<String>` | `list[str]` |
| Lambda | `x -> x + 1` | `lambda x: x + 1` |
| Stream | `list.stream().filter(...).collect()` | `[x for x in list if ...]` |
| try-with-resources | `try (var f = ...) { }` | `with open(...) as f:` |
| 打印 | `System.out.println` | `print(...)` |
| main 方法 | `public static void main` | `if __name__ == "__main__":` |

## 4. 精读：`llm/client.py`

### 4.1 `Protocol` ≈ 接口，但更松

```python
class ChatClient(Protocol):
    async def complete(self, messages, *, meta=None, ...) -> ChatResult: ...
```

Java 里写：

```java
interface ChatClient {
    ChatResult complete(List<ChatMessage> messages, ...);
}
// 然后 class MockClient implements ChatClient
```

Python 里**不需要 `implements`**。只要你的类有 `complete` 方法，它就自动算 `ChatClient`。

这叫"结构化子类型"。好处：测试时随手写个假类就能替换，不用改生产代码的继承关系。代价：拼错方法名编译器不会提醒你，跑起来才炸。

> 类比：Java 的 `implements` 是"登记制"，Python 的 `Protocol` 是"长得像就行"。

### 4.2 `def` 和参数

```python
async def complete(
    self,
    messages: Sequence[ChatMessage],
    *,
    meta: dict[str, Any] | None = None,
    json_mode: bool = True,
    max_tokens: int = 400,
) -> ChatResult:
```

逐项：

| 写法 | 含义 |
|---|---|
| `self` | 等价 `this`，但必须显式写 |
| `messages: Sequence[ChatMessage]` | 参数 + 类型注解；`Sequence` 表示"列表或元组都行" |
| `*` | **它后面的参数必须用名字传**，不能按位置传 |
| `meta: dict[str, Any] \| None = None` | 可空字典，默认 `None`（≈ `Map<String, Object>`，可为 null） |
| `json_mode: bool = True` | 有默认值，调用时可省略 |
| `-> ChatResult` | 返回值类型 |

`*` 有什么用？调用时必须写：

```python
await client.complete(messages, meta={"kind": "vote"})   # 对
await client.complete(messages, {"kind": "vote"})        # 报错
```

这和 Java 的 Builder 是一个目的：**参数一多，按位置传必然传错**。

### 4.3 `async def` 和 `await`

```python
async def complete(self, ...):
    if self.latency > 0:
        await asyncio.sleep(self.latency)
```

- `async def` 定义**协程函数**。直接调用 `complete(...)` 不会执行，只是返回一个"待执行的协程对象"。
- `await` 才是"开始执行，并且在这里等"。

Java 对照：

```java
CompletableFuture<ChatResult> f = CompletableFuture.supplyAsync(() -> ...);
ChatResult r = f.get();   // 阻塞当前线程等待
```

`await` 像 `f.get()`，但**不阻塞线程**——它把控制权交还给事件循环，循环去跑别的协程。这是关键区别，第 7 节展开。

### 4.4 重试循环

```python
for attempt in range(self.max_retries + 1):
    try:
        response = await self._client.chat.completions.create(**kwargs)
    except Exception as exc:
        last_error = exc
        if attempt < self.max_retries:
            await asyncio.sleep(0.8 * (2**attempt))
        continue
```

对照 Java：

```java
for (int attempt = 0; attempt <= maxRetries; attempt++) {
    try {
        response = client.create(kwargs);
        return ...;
    } catch (Exception e) {
        lastError = e;
        if (attempt < maxRetries) Thread.sleep(800L * (1 << attempt));
    }
}
```

三个新东西：

- `range(n)` ≈ `for (int i = 0; i < n; i++)`
- `except Exception as exc` ≈ `catch (Exception e)`
- `0.8 * (2**attempt)`：`**` 是幂运算，`2**3 == 8`
- `**kwargs`（注意是两个星号）：把字典**展开成关键字参数**。等价于 Java 里手动拼参数，Python 一行搞定

### 4.5 `MockClient` 是什么

它是"测试替身"（Java 里叫 Mock/Stub）。生产走 `DeepSeekClient`，本地开发和测试走 `MockClient`。

**这就是为什么你现在不需要 API key 也能跑完整一局。** 依赖接口而不是实现，替换成本才是零。

## 5. 精读：`llm/schema.py`

```python
def parse_action(text: str) -> ActionPayload | None:
    candidate = _extract_json(text)
    if not candidate:
        return None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
```

- `ActionPayload | None` ≈ `Optional<ActionPayload>`，表示"要么是结果，要么是 None"。
- `json.loads(...)` ≈ Jackson 的 `readValue(...)`，但返回的是 `dict` 而不是对象。
- **返回 `None` 而不是抛异常**：因为"模型输出不合法"是预期内的常态，不是异常情况。Java 里你可能会定义一个 `ParseResult`，这里直接用 `None` 更轻。

`classmethod` 是什么：

```python
@classmethod
def from_dict(cls, data: dict[str, Any]) -> ActionPayload:
```

- 第一个参数是 `cls`（类本身），不是 `self`（实例）。≈ Java 的 `static` 工厂方法，但能拿到类。
- 调用方式：`ActionPayload.from_dict(d)`。

## 6. 精读：`llm_agent.py`

```python
for attempt in range(self.max_retries + 1):
    result = await self.client.complete(messages, meta={...}, temperature=self.temperature)
    payload = parse_action(result.text)
    if payload is not None:
        return Decision(...)

    if attempt < self.max_retries:
        messages = [
            *messages,                                       # 解包，把旧列表展开
            ChatMessage(role="assistant", content=result.text[:300]),
            ChatMessage(role="user", content=_RETRY_HINT),
        ]
```

三个语法点：

- `[*messages, a, b]`：`*` 把原列表摊平，组成新列表。≈ `new ArrayList<>(old); add(a); add(b);`
- `result.text[:300]`：切片，取前 300 个字符。`[:n]` 是"从头到 n"，`[-5:]` 是"最后 5 个"。
- 重新赋值 `messages = [...]`：Python 没有 `final`，变量只是"标签"，可以随时贴到新对象上。

## 7. async 到底是什么（和 Java 线程池的区别）

**Java 的并发**：开线程，每个线程有自己的栈，靠操作系统调度，是**真并行**（多核）。

**Python 的 asyncio**：一个线程，一个事件循环，协程之间**协作式**切换。同一时刻只有一个协程在跑，但它 `await` 等 IO 时会主动让位。

```
Java:   线程1 等 IO（阻塞，但线程被占着）
Python: 协程1 await（让出，循环去跑协程2）
```

所以：

| 场景 | async 有用吗 |
|---|---|
| 等 HTTP 响应、等数据库 | **有用**，等待时能跑别的 |
| 纯 CPU 计算（加密、推理） | **没用**，没有等待可让，还得用多进程 |
| 大量并发连接 | **非常有用**（一个线程扛几千连接） |

对应到本项目：调用 DeepSeek 是等网络，所以 async 有用；以后本地跑 embedding 推理是 CPU 密集，async 帮不上忙——这也是建议 embedding 走 API 的原因之一。

**最容易犯的错**：

```python
await asyncio.sleep(0.3)   # 对：让出控制权
time.sleep(0.3)            # 错：整个事件循环卡死，其他协程全停
```

## 8. 十个必踩的坑

1. **缩进就是语法**。多一个空格可能就报 `IndentationError`。统一用 4 个空格，别用 Tab。
2. **可变默认参数**：`def f(x=[])` 里那个列表只创建一次，所有调用共享。要用 `None` 再判断。
3. **`if x:` 不等于 `if x is not None:`**。空列表、空字符串、`0`、`None` 都算 False。
4. **忘了 `await`**：不报错，只是拿到一个协程对象，然后什么都不发生。
5. **`is` 比的是身份，`==` 比的是值**。判断 `None` 用 `is None`，其他用 `==`。
6. **赋值不分拷贝**：`b = a` 只是给同一个对象起别名，改 `b` 会影响 `a`。
7. **边遍历边删列表**会漏元素，要遍历副本 `for x in list(a):`。
8. **字符串不可变**（和 Java 一样），拼接多时用 `"".join(...)`。
9. **GIL**：多线程跑 Python 字节码不能真并行，CPU 密集要用 `multiprocessing`。
10. **`except Exception: pass`** 是最坏的习惯，会把 bug 吞掉。至少要 log。
11. **有默认值的字段必须写在没默认值的字段后面**（`dataclass` 和普通函数都一样）。

### 补充：为什么必须这样

`@dataclass` 会按字段声明顺序生成一个构造器：

```python
def __init__(self, text, cost=0.0, prompt_tokens=0, completion_tokens=0): ...
```

调用 `ChatResult("ok", 0.1, 3)` 时，那个 `3` 到底给 `prompt_tokens` 还是 `completion_tokens`？
Python 按位置绑定，无法判断，所以在**定义阶段**就禁止：

```
TypeError: non-default argument 'prompt_tokens' follows default argument
```

同样的规则适用于普通函数：

```python
def f(a, b=1): ...     # 对
def f(a=1, b): ...     # SyntaxError: non-default argument follows default argument
```

两种解法：

```python
# 解法一：必填的写在前面（本项目采用）
class ChatResult:
    text: str
    cost: float = 0.0

# 解法二：全部改成关键字参数，顺序就自由了（Python 3.10+）
@dataclass(kw_only=True)
class ChatResult:
    text: str
    cost: float = 0.0
# 调用：ChatResult(text="ok", cost=0.1)
```

Java 没有这个问题，因为 Java 根本没有"参数默认值"——要么写重载，要么用 Builder。
这也解释了为什么你加 `cost` 字段时，**已有的调用点一行都不用改**：默认值就是为兼容而生的。

## 9. 现在就能做的三个练习

**练习 1（10 分钟）**：给 `ChatResult` 加一个 `cost: float = 0.0` 字段。
- 会遇到什么？`ChatResult(text=...)` 的其他调用点会不会报错？为什么？
- 验收：`uv run pytest` 全绿。

**练习 2（20 分钟）**：写一个 `EchoClient`，实现 `complete`，原样返回 `messages[-1].content`。
- 目的：体会"不用 implements 也能当 ChatClient"。
- 验收：`LLMAgent("P1", Role.VILLAGER, EchoClient())` 能构造出来，`decide` 返回空 Decision（因为回显不是 JSON）。

**练习 3（30 分钟）**：把 `engine.py` 里投票的并发改成串行，跑 `demo --latency 0.2`。
- 目的：亲眼看到耗时变化，理解"并发省的是等待时间"。
- 验收：耗时明显变长，但测试仍然全绿（说明并发不影响正确性，只影响速度）。

做完这三个，Python 的基本盘就稳了。下一步（v0.3 的 RAG）会用到：列表推导、字典、`sorted(key=...)`、以及一个叫"生成器"的东西。

## 10. 接下来两周怎么学

| 阶段 | 内容 | 对应代码 |
|---|---|---|
| 第 1 周 | 语法 + 读代码 | 本文档 + `docs/01-代码导读.md` |
| 第 2 周 | 自己改 | 上面三个练习 + 加一个"骑士"角色 |
| 之后 | 异步深入 | `asyncio.TaskGroup`、`Semaphore` 限流 |

不要去看"Python 从入门到精通"那种书。**读你项目的代码，改它，跑测试**，是唯一有效的路径。
