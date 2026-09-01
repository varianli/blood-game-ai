# 卧底找茬

每轮给平民和一名卧底分发相近但不同的词，玩家依次描述，再投票找出卧底。

- `prompt.md`：DeepSeek 实际使用的词对 Prompt。
- `bank.json`：未配置 AI 或调用失败时使用的本地词对。
- 发词、描述、投票和结算规则位于 `game/modes/undercover.py`。
