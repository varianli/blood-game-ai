# -*- coding: utf-8 -*-
"""首页的游戏目录。

每个条目 = 一个玩法。engine 决定用哪套规则（目前只有 deduce 这一种），
preset 是进主持人页面时预填的参数。想加新玩法就往 GAMES 里加一条；
如果规则本身不同（不只是参数不同），再新增一个 engine 并在 engine.py 里分流。
"""

DEDUCE = "deduce"          # 放信息 → 推理抢答
TRIVIA = "trivia"          # 百科抢答
VOTE = "vote"              # 谁最可能
UNDERCOVER = "undercover"  # 卧底找茬
DRAW = "draw"              # 你画我猜

GAMES = [
    {
        "id": "classic",
        "engine": DEDUCE,
        "emoji": "🩸",
        "name": "血之游戏 · 经典",
        "tag": "记忆推理",
        "desc": "30 条信息一条条闪过，放完开始出题 —— 每题都要把好几条串起来才算得出答案。",
        "players": "2~20 人",
        "time": "约 20 分钟",
        "ready": True,
        "preset": {"n_infos": 30, "n_questions": 15, "info_sec": 8,
                   "question_sec": 20, "reveal_sec": 8, "board_sec": 6},
    },
    {
        "id": "blitz",
        "engine": DEDUCE,
        "emoji": "⚡",
        "name": "闪电局",
        "tag": "快节奏",
        "desc": "12 条信息、8 道题，信息闪得快、答题时间短。热身或者赶时间的时候用。",
        "players": "2~20 人",
        "time": "约 8 分钟",
        "ready": True,
        "preset": {"n_infos": 12, "n_questions": 8, "info_sec": 5,
                   "question_sec": 12, "reveal_sec": 5, "board_sec": 4},
    },
    {
        "id": "hardcore",
        "engine": DEDUCE,
        "emoji": "🔥",
        "name": "地狱难度",
        "tag": "硬核",
        "desc": "40 条信息只闪 6 秒一条，20 道题。信息量大、时间紧，记不住就只能靠猜。",
        "players": "3~20 人",
        "time": "约 30 分钟",
        "ready": True,
        "preset": {"n_infos": 40, "n_questions": 20, "info_sec": 6,
                   "question_sec": 25, "reveal_sec": 7, "board_sec": 5},
    },
    {
        "id": "trivia",
        "engine": TRIVIA,
        "emoji": "🧠",
        "name": "知识抢答",
        "tag": "百科",
        "desc": "DeepSeek 现场出题，四选一抢答。主题和难度可以自己挑，答得越快分越高。",
        "players": "2~20 人",
        "time": "约 15 分钟",
        "ready": True,
        "preset": {"n_questions": 15, "question_sec": 15, "reveal_sec": 6,
                   "board_sec": 5, "topic": "综合", "level": "中等"},
    },
    {
        "id": "mostlikely",
        "engine": VOTE,
        "emoji": "🫵",
        "name": "谁最可能",
        "tag": "投票",
        "desc": "「谁最可能睡过头迟到？」全员手机投票选人，得票最多的亮相。跟大多数走的人得分。",
        "players": "3~20 人",
        "time": "约 12 分钟",
        "ready": True,
        "preset": {"n_questions": 12, "question_sec": 15, "reveal_sec": 8,
                   "board_sec": 5},
    },
    {
        "id": "undercover",
        "engine": UNDERCOVER,
        "emoji": "🕵️",
        "name": "卧底找茬",
        "tag": "推理",
        "desc": "每人手机上收到一个词，有一个人拿到的不一样。轮流描述后投票，找出那个卧底。",
        "players": "4~12 人",
        "time": "约 15 分钟",
        "ready": True,
        "preset": {"n_questions": 6, "describe_sec": 90, "question_sec": 30,
                   "reveal_sec": 10, "board_sec": 5},
    },
    {
        "id": "draw",
        "engine": DRAW,
        "emoji": "🎨",
        "name": "你画我猜",
        "tag": "手绘",
        "desc": "轮流当画手，在手机上画，笔迹实时同步到大屏，其他人打字抢答。",
        "players": "3~12 人",
        "time": "约 20 分钟",
        "ready": True,
        "preset": {"n_questions": 8, "question_sec": 75, "reveal_sec": 7,
                   "board_sec": 5},
    },
]

BY_ID = {g["id"]: g for g in GAMES}


def engine_of(game_id):
    g = BY_ID.get(game_id)
    return g["engine"] if g else DEDUCE


def public_list():
    """首页和主持人页面都用这份 —— 带上 preset，方便前端预填表单。"""
    return [dict(g) for g in GAMES]


def preset_of(game_id):
    g = BY_ID.get(game_id)
    return dict(g["preset"]) if g else {}


def name_of(game_id):
    g = BY_ID.get(game_id)
    return g["name"] if g else ""
