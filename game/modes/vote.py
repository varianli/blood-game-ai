# -*- coding: utf-8 -*-
"""谁最可能：大屏出一句「谁最可能…」，全员投票选人。

没有标准答案，跟大多数走的人得分 —— 得票最多那个人自己也得分（被点名奖励）。
阶段：lobby → [question(投票) → reveal(票数) → scoreboard] × N → final
"""

import random
import time

from .. import content as game_content, gen_ai
from . import common

PROMPT = game_content.load_prompt("mostlikely")
FALLBACK = game_content.load_bank("mostlikely")["prompts"]


def build(room):
    s = room.settings
    n = int(s.get("n_questions") or 12)
    names = s.get("names") or []
    rng = random.Random()

    if not s.get("api_key"):
        qs = _wrap(common.pick_n(rng, FALLBACK, n))
        return ({"title": "内置题库 · 谁最可能 · 未启用 AI", "source": "bank",
                 "infos": [], "questions": qs},
                "未配置 DeepSeek，使用内置题库")

    content = gen_ai.chat(
        s.get("api_key"), s.get("model"),
        [{"role": "user",
          "content": game_content.render_prompt(
              PROMPT, n=n, names="、".join(names) or "一群朋友")}],
        timeout=gen_ai.QUALITY_TIMEOUT,
        max_tokens=gen_ai.GEN_TOKENS, temperature=1.2)
    obj = gen_ai._loads(content)
    raw = [str(x).strip() for x in (obj.get("prompts") or []) if str(x).strip()]
    raw = [x for x in raw if len(x) <= 40]
    if len(raw) < max(3, n // 2):
        raise gen_ai.AIError("可用题目太少（%d 句）" % len(raw))
    qs = _wrap(raw[:n])
    return ({"title": "DeepSeek 出题 · 谁最可能", "source": "deepseek",
             "infos": [], "questions": qs}, "DeepSeek 出题成功")


def _wrap(texts):
    return [{"text": t, "options": [], "answer": -1, "explain": "", "uses": [],
             "no": i + 1} for i, t in enumerate(texts)]


# --------------------------------------------------------------------------

def start(room):
    room.q_i = 0
    _begin(room, 0)


def _begin(room, i):
    room.q_i = i
    for p in room.players.values():
        p.gain = 0
    room.set_phase("question", room.settings["question_sec"])


def advance(room, forced=False):
    s = room.settings
    if room.phase == "question":
        _tally(room)
        room.set_phase("reveal", s["reveal_sec"])
    elif room.phase == "reveal":
        auto = s.get("auto", True)
        room.set_phase("scoreboard", s["board_sec"] if auto else None)
    elif room.phase == "scoreboard":
        if room.q_i + 1 >= len(room.set["questions"]):
            room.finish()
        else:
            _begin(room, room.q_i + 1)
    elif room.phase in ("lobby", "final"):
        # 大厅里别自己开局 —— 主持人按「跳过」不该把游戏重新拉起来
        room.set_phase("lobby")
    else:
        start(room)


def _counts(room):
    c = {}
    for p in room.players.values():
        v = p.answers.get(room.q_i)
        if v and v.get("target") in room.players:
            c[v["target"]] = c.get(v["target"], 0) + 1
    return c


def _tally(room):
    """算分：跟大多数走 +500，被票最多 +300（一人一次，重复调用不会重复加）。"""
    if room.extra_flag("tallied_%d" % room.q_i):
        return
    c = _counts(room)
    if not c:
        return
    top = max(c.values())
    winners = [pid for pid, v in c.items() if v == top]
    for p in room.players.values():
        v = p.answers.get(room.q_i)
        gain = 0
        if v and v.get("target") in winners:
            gain += 500
        if p.pid in winners:
            gain += 300
        if gain:
            p.score += gain
            p.gain = gain
    room.mark_flag("tallied_%d" % room.q_i)


def submit(room, player, payload):
    if room.phase != "question":
        return
    target = payload.get("target")
    if target not in room.players or room.q_i in player.answers:
        return
    player.answers[room.q_i] = {"target": target}
    player.seen = int(time.time() * 1000)
    room.touch()
    if room.players and all(room.q_i in q.answers for q in room.players.values()):
        _tally(room)
        room.set_phase("reveal", room.settings["reveal_sec"])


def snapshot(room, snap, pid, is_host):
    if not room.set or room.phase not in ("question", "reveal"):
        return
    qs = room.set["questions"]
    if not (0 <= room.q_i < len(qs)):
        return
    q = qs[room.q_i]
    voted = sum(1 for p in room.players.values() if room.q_i in p.answers)
    snap["q"] = {"no": room.q_i + 1, "total": len(qs), "text": q["text"],
                 "options": [], "answered": voted}
    snap["candidates"] = [{"pid": p["pid"], "name": p["name"]}
                          for p in snap["board"]]
    if room.phase == "reveal":
        c = _counts(room)
        top = max(c.values()) if c else 0
        rows = sorted(({"pid": b["pid"], "name": b["name"],
                        "votes": c.get(b["pid"], 0),
                        "win": c.get(b["pid"], 0) == top and top > 0}
                       for b in snap["board"]),
                      key=lambda r: -r["votes"])
        snap["vote_result"] = {"rows": rows, "top": top}
    if pid and pid in room.players:
        v = room.players[pid].answers.get(room.q_i)
        snap["you"]["target"] = v.get("target") if v else None
