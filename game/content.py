# -*- coding: utf-8 -*-
"""读取 ``games/`` 下按玩法整理的 Prompt 与本地内容。

这里是唯一的内容入口。这样仓库里给人看的 Markdown/JSON，就是运行时真正
使用的文件，不会再出现“文档写了一套、代码里藏着另一套”的情况。
"""

import json
from functools import lru_cache
from pathlib import Path


CONTENT_ROOT = Path(__file__).resolve().parents[1] / "games"
GAME_FOLDERS = frozenset(("memory", "trivia", "mostlikely", "undercover", "draw"))


def content_path(game, filename):
    """返回受限的玩法内容路径，拒绝从 ``games/`` 越界读取。"""
    if game not in GAME_FOLDERS:
        raise ValueError("未知游戏内容目录：%s" % game)
    if Path(filename).name != filename:
        raise ValueError("内容文件名不能包含路径：%s" % filename)
    return CONTENT_ROOT / game / filename


@lru_cache(maxsize=None)
def load_text(game, filename):
    return content_path(game, filename).read_text(encoding="utf-8").strip()


def load_prompt(game, filename="prompt.md"):
    return load_text(game, filename)


@lru_cache(maxsize=None)
def load_bank(game, filename="bank.json"):
    with content_path(game, filename).open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def render_prompt(template, **values):
    """替换 ``[[NAME]]`` 占位符；JSON 大括号可原样写在 Markdown 中。"""
    rendered = template
    for name, value in values.items():
        rendered = rendered.replace("[[%s]]" % name.upper(), str(value))
    return rendered
