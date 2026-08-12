# -*- coding: utf-8 -*-
"""几个玩法都要用的小工具。"""

import json
import os
import random
import re

DATA = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "..", "data")


def load_bank(filename):
    path = os.path.normpath(os.path.join(DATA, filename))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def speed_score(left_ms, total_ms, base=600, bonus=400):
    """答对得分：底分 + 剩余时间越多加得越多。"""
    if total_ms <= 0:
        return base
    return base + int(round(bonus * max(0.0, min(1.0, left_ms / float(total_ms)))))


def shuffle_options(q, rng):
    """把四个选项重排一遍，顺便把 answer 下标跟着改 —— 防止正确答案老在 A。"""
    order = [0, 1, 2, 3]
    rng.shuffle(order)
    q["options"] = [q["options"][i] for i in order]
    q["answer"] = order.index(q["answer"])
    return q


_PUNCT = re.compile(r"[\s，。、！？!?,.·・\-—_“”\"'（）()《》〈〉【】\[\]]+")


def normalize(text):
    """猜词比对用：去掉标点空格、统一小写。"""
    return _PUNCT.sub("", str(text or "")).strip().lower()


def guess_matches(guess, answer, aliases=()):
    g = normalize(guess)
    if not g:
        return False
    cands = [answer] + list(aliases or ())
    for c in cands:
        n = normalize(c)
        if n and (g == n or (len(n) >= 3 and g == n)):
            return True
    return False


def pick_n(rng, pool, n):
    """从池子里取 n 个不重复的；池子不够就允许重复补齐。"""
    pool = list(pool)
    if not pool:
        return []
    rng.shuffle(pool)
    out = pool[:n]
    while len(out) < n:
        out.append(rng.choice(pool))
    return out
