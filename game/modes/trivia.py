# -*- coding: utf-8 -*-
"""知识抢答：DeepSeek 现场出百科题，四选一，答得快分高。

阶段：lobby → [question → reveal → scoreboard] × N → final
和「血之游戏」比就是少了放信息那一段。
"""

import random

from .. import gen_ai
from . import common

PROMPT = """出 {n} 道中文四选一的知识抢答题，主题「{topic}」，难度「{level}」。

要求：
- 题干一句话，短，读出来顺口，适合在聚会大屏上念。
- 4 个选项互不相同，只有 1 个正确；错误选项要像那么回事，不能一眼排除。
- 避免过于冷门的专业名词，也别出有争议或者会随时间变化的答案。
- explain 用一句话说清为什么。
- 15 道题里主题要铺开，别全挤在一个小方向上。

只输出 JSON：
{{"questions":[{{"text":"题干","options":["A","B","C","D"],"answer":0,
                "explain":"一句话解释"}}]}}
answer 是正确选项在 options 里的下标（0-3）。"""

TOPICS = ["综合", "影视", "音乐", "历史", "地理", "科学", "体育", "美食",
          "动漫", "网络热梗"]
LEVELS = ["简单", "中等", "困难"]


def build(room):
    s = room.settings
    n = int(s.get("n_questions") or 15)
    topic = s.get("topic") or "综合"
    level = s.get("level") or "中等"
    rng = random.Random()

    try:
        content = gen_ai.chat(
            s.get("api_key"), s.get("model"),
            [{"role": "user",
              "content": PROMPT.format(n=n, topic=topic, level=level)}],
            timeout=420, max_tokens=gen_ai.GEN_TOKENS, temperature=1.1)
        obj = gen_ai._loads(content)
        qs = _clean(obj.get("questions"), n, rng)
        if len(qs) < max(3, n // 2):
            raise gen_ai.AIError("可用题目太少（%d 道）" % len(qs))
        return ({"title": "DeepSeek 出题 · %s · %s" % (topic, level),
                 "source": "deepseek", "infos": [], "questions": qs},
                "DeepSeek 出题成功（%s / %s）" % (topic, level))
    except Exception as e:
        qs = _from_bank(n, topic, rng)
        return ({"title": "内置题库 · %s" % topic, "source": "bank",
                 "infos": [], "questions": qs},
                "%s —— 已改用内置题库" % e)


def _clean(raw, n, rng):
    out = []
    for q in raw or []:
        if not isinstance(q, dict):
            continue
        text = str(q.get("text", "")).strip()
        opts = q.get("options")
        if not text or not isinstance(opts, list) or len(opts) != 4:
            continue
        opts = [str(o).strip() for o in opts]
        if any(not o for o in opts) or len(set(opts)) != 4:
            continue
        ans = gen_ai._norm_answer(q)
        if ans is None or not (0 <= ans < 4):
            continue
        item = {"text": text, "options": opts, "answer": ans,
                "explain": str(q.get("explain", "")).strip(), "uses": []}
        out.append(common.shuffle_options(item, rng))
        if len(out) >= n:
            break
    for i, q in enumerate(out):
        q["no"] = i + 1
    return out


def _from_bank(n, topic, rng):
    bank = common.load_bank("trivia_bank.json")
    pool = [q for q in bank["questions"]
            if topic in ("综合", "", None) or q.get("topic") == topic]
    if len(pool) < n:
        pool = list(bank["questions"])
    picked = common.pick_n(rng, pool, n)
    out = []
    for i, q in enumerate(picked):
        item = {"text": q["text"], "options": list(q["options"]),
                "answer": q["answer"], "explain": q.get("explain", ""),
                "uses": [], "no": i + 1}
        out.append(common.shuffle_options(item, rng))
    return out


# --------------------------------------------------------------------------
# 阶段机 —— 除了没有 briefing，其余和血之游戏一样
# --------------------------------------------------------------------------

def start(room):
    room.q_i = 0
    room.begin_question(0)


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
            room.begin_question(room.q_i + 1)
    elif room.phase in ("lobby", "final"):
        # 大厅里别自己开局 —— 主持人按「跳过」不该把游戏重新拉起来
        room.set_phase("lobby")
    else:
        start(room)


def submit(room, player, payload):
    room.score_choice(player, payload.get("q"), payload.get("choice"))


def snapshot(room, snap, pid, is_host):
    room.fill_choice_snapshot(snap, pid)
