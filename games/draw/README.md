# 你画我猜

玩家轮流在手机画板作画，笔迹同步到大屏，其他玩家输入答案，由画手或主持人判对。

- `prompt.md`：DeepSeek 实际使用的出词 Prompt。
- `bank.json`：未配置 AI 或调用失败时使用的本地词库。
- 画板同步、猜词和计分规则位于 `game/modes/draw.py`。
