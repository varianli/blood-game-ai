# -*- coding: utf-8 -*-
"""把信息卡打散，让同一个人的信息不要连着出现。

大模型出题时习惯把一个人的事实写成一坨（1~5 全是林岚，6~10 全是周澈），
玩家一眼就能按人分块记住，太简单了。这里把顺序重排成穿插的，
同时把题目里的 uses（引用第几条信息）跟着重新映射。

同一个人自己的事实**保持相对顺序**（先住哪、再职业、再数值），
不然会出现「每周去医院上班 5 天」排在「在医院当医生」前面这种怪句子。
"""


def owner_of(text, names):
    """这条信息讲的是谁 —— 取最先出现的那个名字（长名优先，避免子串误判）。"""
    best, best_pos = None, len(text) + 1
    for n in sorted(names, key=len, reverse=True):
        p = text.find(n)
        if p >= 0 and p < best_pos:
            best, best_pos = n, p
    return best


def interleave(infos, questions, names, rng):
    """返回重排后的 infos；questions 里的 uses 会被就地改成新编号。"""
    if not infos:
        return infos

    groups, order_of_group = {}, []
    for i, t in enumerate(infos):
        o = owner_of(t, names)
        key = o if o else "__solo_%d" % i      # 认不出主人的自成一组
        if key not in groups:
            groups[key] = []
            order_of_group.append(key)
        groups[key].append(i)

    remaining = {k: list(v) for k, v in groups.items()}
    picked, prev = [], None
    while any(remaining.values()):
        cands = [k for k in order_of_group if remaining[k] and k != prev]
        if not cands:                           # 只剩上一个人了，只能连着放
            cands = [k for k in order_of_group if remaining[k]]
        # 优先消耗剩得最多的那个人，否则最后会剩一堆同一个人的信息挤在一起
        mx = max(len(remaining[k]) for k in cands)
        top = [k for k in cands if len(remaining[k]) == mx]
        pick = rng.choice(top)
        picked.append(remaining[pick].pop(0))
        prev = pick

    new_infos = [infos[i] for i in picked]
    remap = {old + 1: new + 1 for new, old in enumerate(picked)}
    for q in questions or []:
        if q.get("uses"):
            q["uses"] = sorted(remap.get(u, u) for u in q["uses"])
    return new_infos


def adjacent_repeats(infos, names):
    """相邻两条信息讲同一个人的次数 —— 用来测效果。"""
    owners = [owner_of(t, names) for t in infos]
    return sum(1 for a, b in zip(owners, owners[1:]) if a is not None and a == b)
