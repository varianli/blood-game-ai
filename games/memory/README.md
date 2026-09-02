# Memory 系列

对应首页的三个难度入口：Memory 12 · 闪电、Memory 30 · 标准、Memory 40 · 极限。
三者共用同一套内容规则，只在信息量、题量和时间压力上递进。

- `prompt.md`：DeepSeek 全量生成实际使用的主 Prompt。
- `review_prompt.md`：独立审阅 Agent 使用的闭卷必要性测试；逐题检查并重写无需
  记忆、引用虚假、答案不唯一或依据不足的题。
- `polish_prompt.md`：本地生成后交给 DeepSeek 润色时使用。
- `style_guide.md`：从节目玩法提炼的题型、题材穿插和重复限制；主 Prompt 会把
  标记区段实际注入模型。
- `default_set.json`：手工默认六人题库，仅在选择“内置默认题库”或极端兜底时使用。
- 动态本地题材池与组题算法位于 `game/gen_local.py`；语义题材判定和排列位于
  `game/arrange.py`。

Prompt 中的 `[[...]]` 是运行时占位符，请保留名称不变。
