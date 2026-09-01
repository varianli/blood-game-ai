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


def _remap_uses(questions, picked):
    """把旧信息编号映射到 picked 所描述的新顺序。"""
    remap = {old + 1: new + 1 for new, old in enumerate(picked)}
    for q in questions or []:
        if q.get("uses"):
            q["uses"] = sorted(remap.get(u, u) for u in q["uses"])


def _topic_penalty(order, topics, owners, dependency_groups):
    """越小越好；题材节奏是硬目标，人物与关联线索间隔是次目标。"""
    score = 0
    ordered_topics = [topics[i] for i in order]
    ordered_owners = [owners[i] for i in order]
    for i in range(1, len(order)):
        if ordered_topics[i] == ordered_topics[i - 1]:
            score += 100
        if ordered_owners[i] and ordered_owners[i] == ordered_owners[i - 1]:
            score += 45
    for i in range(len(order) - 3):
        if len(set(ordered_topics[i:i + 4])) < 3:
            score += 80
    for i, old_index in enumerate(order):
        dep = dependency_groups[old_index]
        if dep and any(dependency_groups[order[j]] == dep
                       for j in range(max(0, i - 4), i)):
            score += 20
    return score


def interleave_topics(infos, questions, names, topics, rng,
                      owners=None, dependency_groups=None):
    """按人物和题材双重穿插，并同步改写题目引用编号。

    目标是相邻题材不同、任意连续四条至少三类；若输入分布本身做不到，
    则返回惩罚最小的顺序，而不会丢卡片。
    """
    if not infos:
        return infos, []
    if len(topics) != len(infos):
        raise ValueError("topics 必须与 infos 等长")

    owners = list(owners or [owner_of(text, names) for text in infos])
    if len(owners) != len(infos):
        raise ValueError("owners 必须与 infos 等长")
    dependency_groups = list(dependency_groups or [None] * len(infos))
    if len(dependency_groups) != len(infos):
        raise ValueError("dependency_groups 必须与 infos 等长")

    # 多跑几次带随机打破平局的贪心，把最后残留同类卡片的概率压低。
    best, best_penalty = None, None
    for _ in range(80):
        remaining = list(range(len(infos)))
        picked = []
        while remaining:
            last_topics = [topics[i] for i in picked[-3:]]
            last_owners = [owners[i] for i in picked[-3:]]
            last_deps = [dependency_groups[i] for i in picked[-4:]]
            topic_counts = {
                topic: sum(1 for i in remaining if topics[i] == topic)
                for topic in set(topics[i] for i in remaining)
            }
            scored = []
            for old_index in remaining:
                topic = topics[old_index]
                owner = owners[old_index]
                dep = dependency_groups[old_index]
                score = topic_counts[topic]
                if not last_topics or topic != last_topics[-1]:
                    score += 120
                else:
                    score -= 240
                if len(last_topics) == 3:
                    if len(set(last_topics + [topic])) >= 3:
                        score += 110
                    else:
                        score -= 180
                if owner:
                    if not last_owners or owner != last_owners[-1]:
                        score += 45
                    else:
                        score -= 90
                    if owner not in last_owners[-2:]:
                        score += 16
                if dep:
                    score += 35 if dep not in last_deps else -70
                scored.append((score, rng.random(), old_index))
            old_index = max(scored)[2]
            picked.append(old_index)
            remaining.remove(old_index)

        penalty = _topic_penalty(picked, topics, owners, dependency_groups)
        if best_penalty is None or penalty < best_penalty:
            best, best_penalty = picked, penalty
        if penalty == 0:
            break

    _remap_uses(questions, best)
    return [infos[i] for i in best], [topics[i] for i in best]


def interleave_questions(questions, rng):
    """让 recall / transform / logic / calculate 不扎堆。"""
    remaining = list(questions)
    mixed = []
    previous = None
    while remaining:
        candidates = [q for q in remaining if q.get("type") != previous]
        if not candidates:
            candidates = remaining[:]
        counts = {
            qtype: sum(1 for q in remaining if q.get("type") == qtype)
            for qtype in set(q.get("type") for q in remaining)
        }
        largest = max(counts.get(q.get("type"), 0) for q in candidates)
        candidates = [q for q in candidates
                      if counts.get(q.get("type"), 0) == largest]
        chosen = rng.choice(candidates)
        remaining.remove(chosen)
        mixed.append(chosen)
        previous = chosen.get("type")
    for i, q in enumerate(mixed):
        q["no"] = i + 1
    return mixed


def adjacent_repeats(infos, names):
    """相邻两条信息讲同一个人的次数 —— 用来测效果。"""
    owners = [owner_of(t, names) for t in infos]
    return sum(1 for a, b in zip(owners, owners[1:]) if a is not None and a == b)
