# -*- coding: utf-8 -*-
"""你画我猜：轮流当画手，手机上画，笔迹同步到大屏，其他人打字猜。

判对错是**人工**的 —— 猜词会实时滚到大屏和画手手机上，
主持人或画手点一下就判对。省掉了模糊匹配那堆麻烦事（"长颈鹿"/"长劲鹿"）。

阶段：lobby → [question(画+猜) → reveal → scoreboard] × N → final

笔迹不走房间快照：画画时每秒几十笔，全塞进 version 会把所有人的长轮询冲垮。
单独走 /api/draw?since=N，只有大屏在画画阶段才去拉。
"""

import random
import time

from .. import content as game_content, gen_ai
from . import common

PROMPT = game_content.load_prompt("draw")
FALLBACK = game_content.load_bank("draw")["words"]


def build(room):
    s = room.settings
    n = int(s.get("n_questions") or 8)
    rng = random.Random()
    if not s.get("api_key"):
        return ({"title": "内置词库 · 你画我猜 · 未启用 AI", "source": "bank",
                 "infos": [], "questions": _wrap(common.pick_n(rng, FALLBACK, n))},
                "未配置 DeepSeek，使用内置词库")

    content = gen_ai.chat(
        s.get("api_key"), s.get("model"),
        [{"role": "user", "content": game_content.render_prompt(PROMPT, n=n)}],
        timeout=gen_ai.QUALITY_TIMEOUT,
        max_tokens=gen_ai.GEN_TOKENS, temperature=1.2)
    obj = gen_ai._loads(content)
    words = [str(w).strip() for w in (obj.get("words") or []) if str(w).strip()]
    words = [w for w in words if 2 <= len(w) <= 6]
    if len(words) < max(2, n // 2):
        raise gen_ai.AIError("可用词太少（%d 个）" % len(words))
    return ({"title": "DeepSeek 出词 · 你画我猜", "source": "deepseek",
             "infos": [], "questions": _wrap(words[:n])},
            "DeepSeek 出词成功")


def _wrap(words):
    return [{"text": "第 %d 幅" % (i + 1), "word": w, "options": [],
             "answer": -1, "explain": "", "uses": [], "no": i + 1}
            for i, w in enumerate(words)]


# --------------------------------------------------------------------------

def start(room):
    room.q_i = 0
    _begin(room, 0)


def _begin(room, i):
    room.q_i = i
    pids = [p for p in room.order if p in room.players]
    for p in room.players.values():
        p.gain = 0
    room.strokes = []
    room.guesses = []
    room.stroke_v += 1
    room.drawer = pids[i % len(pids)] if pids else None
    room.flags.discard("draw_done_%d" % i)
    room.set_phase("question", room.settings["question_sec"])


def advance(room, forced=False):
    s = room.settings
    if room.phase == "question":
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


def submit(room, player, payload):
    kind = payload.get("kind")

    if kind == "stroke" and player.pid == room.drawer:
        st = payload.get("stroke")
        if isinstance(st, dict):
            room.strokes.append(st)
            room.stroke_v += 1        # 不动 room.version，免得刷爆长轮询
        return

    if kind == "clear" and player.pid == room.drawer:
        room.strokes = []
        room.stroke_v += 1
        return

    if kind == "guess" and room.phase == "question":
        if player.pid == room.drawer:
            return
        text = str(payload.get("text") or "").strip()[:20]
        if not text:
            return
        room.guesses.append({"id": len(room.guesses) + 1, "pid": player.pid,
                             "name": player.name, "text": text,
                             "t": int(time.time() * 1000)})
        room.guesses = room.guesses[-60:]
        player.seen = int(time.time() * 1000)
        room.touch()
        return

    if kind == "judge":
        # 主持人或画手判「这条猜对了」
        if player.pid != room.drawer:
            return
        _award(room, payload.get("guess_id"))


def judge_by_host(room, guess_id):
    _award(room, guess_id)


def _award(room, guess_id):
    key = "draw_done_%d" % room.q_i
    if room.extra_flag(key) or room.phase != "question":
        return
    g = next((x for x in room.guesses if x["id"] == guess_id), None)
    if not g or g["pid"] not in room.players:
        return
    left = max(0, (room.deadline or 0) - int(time.time() * 1000))
    total = max(1, room.settings["question_sec"] * 1000)
    winner = room.players[g["pid"]]
    gain = common.speed_score(left, total, base=600, bonus=400)
    winner.score += gain
    winner.gain = gain
    if room.drawer in room.players:              # 画手也有分，画得清楚才有人猜中
        d = room.players[room.drawer]
        d.score += 500
        d.gain = 500
    q = room.set["questions"][room.q_i]
    q["_winner"] = g["pid"]
    q["_winner_name"] = winner.name
    q["_winner_text"] = g["text"]
    room.mark_flag(key)
    room.set_phase("reveal", room.settings["reveal_sec"])


def snapshot(room, snap, pid, is_host):
    if not room.set:
        return
    qs = room.set["questions"]
    if not (0 <= room.q_i < len(qs)):
        return
    q = qs[room.q_i]
    drawer_name = room.players[room.drawer].name if room.drawer in room.players else ""
    snap["draw"] = {
        "no": room.q_i + 1, "total": len(qs),
        "drawer": room.drawer, "drawer_name": drawer_name,
        "stroke_v": room.stroke_v,
        "guesses": room.guesses[-14:],
        "solved": room.extra_flag("draw_done_%d" % room.q_i),
    }
    # 词只给画手和主持人看（主持人要判对错）
    if is_host or (pid and pid == room.drawer):
        snap["draw"]["word"] = q.get("word", "")
    if room.phase == "reveal":
        snap["draw"]["answer"] = q.get("word", "")
        snap["draw"]["winner_name"] = q.get("_winner_name", "")
        snap["draw"]["winner_text"] = q.get("_winner_text", "")
    if pid and snap.get("you") is not None:
        snap["you"]["is_drawer"] = (pid == room.drawer)
