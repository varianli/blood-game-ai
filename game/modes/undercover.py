# -*- coding: utf-8 -*-
"""卧底找茬：每人拿到一个词，其中一个人的不一样。

阶段：lobby → [assign(看词) → describe(线下轮流说) → question(投票) → reveal] × N → final
计分：平民投中卧底 +600；卧底没被投出来 +1000（人越多给得越多）。
词是成对的（比如「拿铁 / 美式」），差别小才好玩。
"""

import random
import time

from .. import gen_ai
from . import common

PROMPT = """出 {n} 组「谁是卧底」用的词对。每组两个词，要求：

- 两个词是同类、容易混淆的东西，但确实有区别（比如 拿铁/美式、地铁/轻轨、可乐/雪碧）。
- 都是日常生活里常见的，一句话就能描述出来的具体事物。
- 不要抽象概念，不要专业术语，不要人名地名。
- {n} 组之间不要重复，类别要铺开（吃的、喝的、用的、玩的、交通、动物都来一点）。

只输出 JSON：{{"pairs":[["词A","词B"],["词A","词B"]]}}"""

FALLBACK = [
    ["拿铁", "美式"], ["地铁", "轻轨"], ["可乐", "雪碧"], ["苹果", "梨"],
    ["火锅", "麻辣烫"], ["篮球", "排球"], ["空调", "风扇"], ["猫", "老虎"],
    ["牙刷", "梳子"], ["书包", "行李箱"], ["雨伞", "阳伞"], ["面条", "米线"],
    ["电影院", "剧场"], ["沙发", "床"], ["钢笔", "铅笔"], ["草莓", "樱桃"],
    ["微波炉", "烤箱"], ["耳机", "音箱"], ["运动鞋", "拖鞋"], ["酸奶", "牛奶"],
    ["公交车", "大巴"], ["蛋糕", "面包"], ["手表", "手环"], ["西瓜", "哈密瓜"],
    ["理发店", "美容院"], ["图书馆", "书店"], ["泳池", "海边"], ["象棋", "围棋"],
    ["奶茶", "果茶"], ["饺子", "馄饨"], ["台灯", "吊灯"], ["公园", "广场"],
    ["自行车", "电动车"], ["咖啡厅", "茶馆"], ["毛衣", "卫衣"], ["烧烤", "铁板烧"],
]


def build(room):
    s = room.settings
    n = int(s.get("n_questions") or 6)
    rng = random.Random()
    try:
        content = gen_ai.chat(
            s.get("api_key"), s.get("model"),
            [{"role": "user", "content": PROMPT.format(n=n)}],
            timeout=300, max_tokens=gen_ai.GEN_TOKENS, temperature=1.2)
        obj = gen_ai._loads(content)
        pairs = []
        for p in obj.get("pairs") or []:
            if isinstance(p, list) and len(p) == 2:
                a, b = str(p[0]).strip(), str(p[1]).strip()
                if a and b and a != b and len(a) <= 8 and len(b) <= 8:
                    pairs.append([a, b])
        if len(pairs) < max(2, n // 2):
            raise gen_ai.AIError("可用词对太少（%d 组）" % len(pairs))
        return ({"title": "DeepSeek 出词 · 卧底找茬", "source": "deepseek",
                 "infos": [], "questions": _wrap(pairs[:n])},
                "DeepSeek 出词成功")
    except Exception as e:
        pairs = common.pick_n(rng, FALLBACK, n)
        return ({"title": "内置词库 · 卧底找茬", "source": "bank",
                 "infos": [], "questions": _wrap(pairs)},
                "%s —— 已改用内置词库" % e)


def _wrap(pairs):
    return [{"text": "第 %d 轮" % (i + 1), "pair": list(p), "options": [],
             "answer": -1, "explain": "", "uses": [], "no": i + 1}
            for i, p in enumerate(pairs)]


# --------------------------------------------------------------------------

def start(room):
    room.q_i = 0
    _assign(room, 0)


def _assign(room, i):
    """发词：随机挑一个人当卧底，其余人拿另一个词。"""
    room.q_i = i
    q = room.set["questions"][i]
    pids = [p for p in room.order if p in room.players]
    for p in room.players.values():
        p.gain = 0
    if not pids:
        room.set_phase("assign", 5)
        return
    rng = random.Random()
    spy = rng.choice(pids)
    words = list(q["pair"])
    rng.shuffle(words)
    civ_word, spy_word = words[0], words[1]
    for pid in pids:
        p = room.players[pid]
        p.extra["word"] = spy_word if pid == spy else civ_word
        p.extra["spy"] = (pid == spy)
    room.flags.discard("uc_tallied_%d" % i)
    q["_spy"] = spy
    q["_civ"] = civ_word
    q["_spyword"] = spy_word
    room.set_phase("assign", 8)


def advance(room, forced=False):
    s = room.settings
    ph = room.phase
    if ph == "assign":
        room.set_phase("describe", int(s.get("describe_sec") or 90))
    elif ph == "describe":
        room.set_phase("question", s["question_sec"])
    elif ph == "question":
        _tally(room)
        room.set_phase("reveal", s["reveal_sec"])
    elif ph == "reveal":
        auto = s.get("auto", True)
        room.set_phase("scoreboard", s["board_sec"] if auto else None)
    elif ph == "scoreboard":
        if room.q_i + 1 >= len(room.set["questions"]):
            room.finish()
        else:
            _assign(room, room.q_i + 1)
    elif ph in ("lobby", "final"):
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


def _voted_out(room):
    c = _counts(room)
    if not c:
        return None, {}
    top = max(c.values())
    tied = [pid for pid, v in c.items() if v == top]
    return (tied[0] if len(tied) == 1 else None), c


def _tally(room):
    key = "uc_tallied_%d" % room.q_i
    if room.extra_flag(key):
        return
    q = room.set["questions"][room.q_i]
    spy = q.get("_spy")
    out, _ = _voted_out(room)
    caught = (out is not None and out == spy)
    for p in room.players.values():
        gain = 0
        if p.extra.get("spy"):
            if not caught:
                gain += 1000            # 藏住了
        else:
            v = p.answers.get(room.q_i)
            if v and v.get("target") == spy:
                gain += 600             # 投中了卧底
        if gain:
            p.score += gain
            p.gain = gain
    room.mark_flag(key)


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
    if not room.set:
        return
    qs = room.set["questions"]
    if not (0 <= room.q_i < len(qs)):
        return
    q = qs[room.q_i]
    snap["round"] = {"no": room.q_i + 1, "total": len(qs)}

    if room.phase == "question":
        voted = sum(1 for p in room.players.values() if room.q_i in p.answers)
        snap["q"] = {"no": room.q_i + 1, "total": len(qs),
                     "text": "投票：谁是卧底？", "options": [], "answered": voted}
        snap["candidates"] = [{"pid": b["pid"], "name": b["name"]}
                              for b in snap["board"]]

    if room.phase == "reveal":
        out, c = _voted_out(room)
        spy = q.get("_spy")
        snap["uc_reveal"] = {
            "spy": spy,
            "spy_name": room.players[spy].name if spy in room.players else "",
            "spy_word": q.get("_spyword", ""),
            "civ_word": q.get("_civ", ""),
            "voted_out": out,
            "voted_out_name": room.players[out].name if out in room.players else "",
            "caught": out is not None and out == spy,
            "rows": sorted(({"name": b["name"], "votes": c.get(b["pid"], 0)}
                            for b in snap["board"]), key=lambda r: -r["votes"]),
        }

    # 每个人只能看到自己的词；主持人大屏永远看不到，免得投屏剧透
    if pid and pid in room.players and snap.get("you") is not None:
        p = room.players[pid]
        snap["you"]["word"] = p.extra.get("word", "")
        v = p.answers.get(room.q_i)
        snap["you"]["target"] = v.get("target") if v else None
        if room.phase == "reveal":
            snap["you"]["was_spy"] = bool(p.extra.get("spy"))
