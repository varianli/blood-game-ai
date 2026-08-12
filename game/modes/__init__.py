# -*- coding: utf-8 -*-
"""玩法插件。

engine.Room 只管房间、玩家、计分、倒计时这些公共的东西；
每种玩法自己的规则放在这里，实现下面几个钩子：

    build(room)                      -> (题库 dict, 提示语)   出题，失败就抛异常
    start(room)                      开局，负责设置第一个阶段
    advance(room, forced)            倒计时到点或主持人跳过时推进一步
    submit(room, player, payload)    玩家提交（选项 / 投票 / 猜词 / 笔画）
    snapshot(room, snap, pid, host)  往快照里塞这个玩法专属的数据

「血之游戏」(deduce) 的规则仍然写在 engine.py 里 —— 它是最早写的，
测试也都压在它身上，没必要为了统一而搬家。
"""

from . import draw, trivia, undercover, vote

REGISTRY = {
    "trivia": trivia,
    "vote": vote,
    "undercover": undercover,
    "draw": draw,
}


def get(kind):
    return REGISTRY.get(kind)
