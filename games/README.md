# 游戏内容总目录

这里按玩法收纳实际运行时使用的 Prompt、规则说明和本地兜底内容。修改这里的
`prompt.md` 或 `bank.json` 后，重启服务即可生效，不需要再去 Python 文件里寻找
隐藏文案。

| 首页游戏 | 内容目录 | 规则代码 |
| --- | --- | --- |
| Memory 12 · 闪电 | [`memory/`](memory/) | `game/gen_local.py`、`game/gen_ai.py` |
| Memory 30 · 标准 | [`memory/`](memory/) | `game/gen_local.py`、`game/gen_ai.py` |
| Memory 40 · 极限 | [`memory/`](memory/) | `game/gen_local.py`、`game/gen_ai.py` |
| 知识抢答 | [`trivia/`](trivia/) | `game/modes/trivia.py` |
| 谁最可能 | [`mostlikely/`](mostlikely/) | `game/modes/vote.py` |
| 卧底找茬 | [`undercover/`](undercover/) | `game/modes/undercover.py` |
| 你画我猜 | [`draw/`](draw/) | `game/modes/draw.py` |

每个目录中的 `README.md` 会说明各文件用途。Markdown Prompt 和 JSON 题库都由
`game/content.py` 直接读取，因此这里不是备忘录，而是内容源。
