# -*- coding: utf-8 -*-
"""知识抢答：DeepSeek 现场出百科题，四选一，答得快分高。

阶段：lobby → [question → reveal → scoreboard] × N → final
和「血之游戏」比就是少了放信息那一段。
"""

import random

from .. import content as game_content, gen_ai
from . import common

SYSTEM_PROMPT = game_content.load_prompt("trivia", "system_prompt.md")

DIFFICULTY_GUIDES = {
    "简单": "多数普通成年人无需专业训练即可直接回忆作答，约 70% 为直接常识；difficulty 只能为 1 或 2。",
    "中等": "需要扎实的通识储备或一步联想，干扰项应来自相邻概念；difficulty 只能为 2 或 3。",
    "困难": (
        "至少 60% 的题目必须考精确年代顺序、概念边界、因果关系、细节辨析，"
        "或需要两步联想；选项须属于同一类别、年代相近或顺序接近。禁止送分题，"
        "例如水的化学式、足球队上场人数、奥运会间隔、主角姓名、国家首都等；"
        "difficulty 只能为 4 或 5。"
    ),
}

SCORE_RANGES = {"简单": (1, 2), "中等": (2, 3), "困难": (4, 5)}

PROMPT = game_content.load_prompt("trivia")

TOPICS = ["综合", "影视", "音乐", "历史", "地理", "科学", "体育", "美食",
          "动漫", "网络热梗"]
LEVELS = ["简单", "中等", "困难"]


def prompt_for(n, topic, level):
    topic = topic if topic in TOPICS else "综合"
    level = level if level in LEVELS else "中等"
    candidate_n = min(40, max(n + 6, n * 2))
    return game_content.render_prompt(
        PROMPT,
        candidate_n=candidate_n,
        n=n,
        topic=topic,
        level=level,
        difficulty_guide=DIFFICULTY_GUIDES[level],
    )


def build(room):
    s = room.settings
    n = int(s.get("n_questions") or 15)
    topic = s.get("topic") if s.get("topic") in TOPICS else "综合"
    level = s.get("level") if s.get("level") in LEVELS else "中等"
    rng = random.Random()

    try:
        content = gen_ai.chat(
            s.get("api_key"), s.get("model"),
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": prompt_for(n, topic, level)}],
            timeout=420, max_tokens=gen_ai.GEN_TOKENS, temperature=1.1)
        obj = gen_ai._loads(content)
        qs = _clean(obj.get("questions"), n, rng, level)
        if len(qs) < n:
            raise gen_ai.AIError("可用题目太少（%d 道）" % len(qs))
        return ({"title": "DeepSeek 严格出题 · %s · %s" % (topic, level),
                 "source": "deepseek", "requested_level": level,
                 "difficulty_guaranteed": True,
                 "infos": [], "questions": qs},
                "DeepSeek 出题成功（%s / %s）" % (topic, level))
    except Exception as e:
        qs = _from_bank(n, topic, rng)
        return ({"title": "内置基础题库 · %s · 难度降级" % topic,
                 "source": "bank", "requested_level": level,
                 "difficulty_guaranteed": False,
                 "infos": [], "questions": qs},
                "%s —— 已改用内置基础题库，未保证「%s」难度" % (e, level))


def _clean(raw, n, rng, level="中等"):
    low, high = SCORE_RANGES.get(level, SCORE_RANGES["中等"])
    out = []
    seen = set()
    for q in raw or []:
        if not isinstance(q, dict):
            continue
        text = str(q.get("text", "")).strip()
        opts = q.get("options")
        if (not text or text in seen or not isinstance(opts, list)
                or len(opts) != 4):
            continue
        opts = [str(o).strip() for o in opts]
        if any(not o for o in opts) or len(set(opts)) != 4:
            continue
        ans = gen_ai._norm_answer(q)
        if ans is None or not (0 <= ans < 4):
            continue
        difficulty = q.get("difficulty")
        if isinstance(difficulty, bool) or not isinstance(difficulty, int):
            continue
        if not low <= difficulty <= high:
            continue
        item = {"text": text, "options": opts, "answer": ans,
                "explain": str(q.get("explain", "")).strip(),
                "difficulty": difficulty, "uses": []}
        seen.add(text)
        out.append(common.shuffle_options(item, rng))
        if len(out) >= n:
            break
    for i, q in enumerate(out):
        q["no"] = i + 1
    return out


def _from_bank(n, topic, rng):
    bank = common.load_bank("trivia")
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
