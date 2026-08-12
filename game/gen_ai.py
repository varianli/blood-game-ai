# -*- coding: utf-8 -*-
"""DeepSeek 出题。

两种用法：
  generate_ai(...)  —— 让模型从零生成整套「信息 + 题目」，结构会被严格校验。
  polish(...)       —— 本地引擎先算好数值，模型只负责把句子写得更有故事感；
                       所有数字/人名必须原样保留，否则该句回退成本地版本。

任何一步失败都抛异常，由调用方降级到本地题库。
"""

import json
import random
import re
import urllib.error
import urllib.request

from . import arrange

API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"

# v4 系列是推理模型，思考本身要烧掉一两万 token，
# max_tokens 给小了会出现 finish_reason=length 而 content 为空。
GEN_TOKENS = 32000
# 润色本身很轻（实测有时 10 秒就好了），但推理长度波动极大，
# 给 16000 时踩到过一次「思考烧光、没输出」，所以这里也给足。
POLISH_TOKENS = 32000


class AIError(Exception):
    pass


def chat(api_key, model, messages, timeout=120, json_mode=True,
         max_tokens=8000, temperature=1.1):
    if not api_key:
        raise AIError("没有配置 DeepSeek API Key")
    body = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + api_key,
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        if e.code == 402:
            raise AIError("DeepSeek 账户余额不足（402），请先充值")
        if e.code in (401, 403):
            raise AIError("DeepSeek API Key 无效或无权限（%d）" % e.code)
        raise AIError("DeepSeek 返回 %d：%s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise AIError("连不上 DeepSeek：%s" % e.reason)
    except Exception as e:
        raise AIError("调用 DeepSeek 失败：%s" % e)

    try:
        ch = data["choices"][0]
        content = ch["message"]["content"]
    except (KeyError, IndexError):
        raise AIError("DeepSeek 返回格式异常")

    if not (content or "").strip():
        if ch.get("finish_reason") == "length":
            used = ((data.get("usage") or {})
                    .get("completion_tokens_details") or {}).get("reasoning_tokens")
            raise AIError("模型把 %s token 全用在思考上了，没来得及输出结果"
                          % (used or max_tokens))
        raise AIError("DeepSeek 返回了空内容")
    return content


def _loads(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise AIError("DeepSeek 没有返回合法 JSON")
        return json.loads(m.group(0))


# --------------------------------------------------------------------------
# 全量生成
# --------------------------------------------------------------------------

PROMPT = """你在为一个线下聚会的记忆推理游戏出题，玩法参考韩国综艺：
先用大屏一条一条闪出关于几个人物的「信息」，全部放完后再考观众，
题目必须把 2~4 条信息串起来才能算出答案。

参与的人物：{names}

请生成：
1. 恰好 {n_infos} 条信息。每条只讲一个事实，一句话，短，口语化，带具体数字。
   每个人物的信息数量要大致均匀。
2. 恰好 {n_questions} 道四选一的题。其中至少一半必须组合 2 条以上的信息
   （例如「单程 30 分钟 + 每周 5 天 → 一周往返花多久」）。

必须保证的多样性（很重要，否则整场会很无聊）：
- 职业不要全是「靠单价×数量赚钱」那一类。至少 3 个人的信息要围绕
  时间和距离，比如住在哪个区、单程通勤多少分钟、每节课多少分钟、
  每天走多少步、每天睡几小时。
- 题目不要清一色算钱。要有算时间的、算距离的、算次数的。
- 至少 4 道题必须是**跨人物**的：比较谁花的时间更长 / 谁挣得更多 / 差多少，
  或者把「人」和「住的地方」配对。
- 同一个人物最多只能出 2 道题，不要连着出同一个人的题。

严格的计算要求（非常重要）：
- 每道题的正确答案必须能由你给出的信息严格算出来，你要在心里逐步算一遍再写。
- 4 个选项互不相同，只有 1 个正确；错误选项要像「常见的算错结果」
  （比如忘了乘 2、按 7 天算、少乘一步）。
- explain 里写出完整算式。
- uses 填写这道题用到的信息编号（从 1 开始，对应上面信息数组的顺序）。

只输出 JSON，不要任何解释文字，格式：
{{"infos": ["信息1", "信息2", ...],
  "questions": [{{"text": "题干", "options": ["A","B","C","D"],
                 "answer": 0, "explain": "算式", "uses": [3,4]}}]}}
answer 是正确选项在 options 里的下标（0-3）。所有文字用简体中文。"""


def _norm_answer(q):
    a = q.get("answer")
    if isinstance(a, str):
        s = a.strip().upper()
        if s in ("A", "B", "C", "D"):
            return "ABCD".index(s)
        if s in q.get("options", []):
            return q["options"].index(s)
        try:
            return int(s)
        except ValueError:
            return None
    if isinstance(a, bool):
        return None
    if isinstance(a, int):
        return a
    return None


def validate(obj, n_infos, n_questions, names=()):
    """结构校验；数值对不对无法机器验证，由 explain 供主持人肉眼把关。"""
    if not isinstance(obj, dict):
        raise AIError("返回的不是对象")
    infos = obj.get("infos")
    qs = obj.get("questions")
    if not isinstance(infos, list) or not isinstance(qs, list):
        raise AIError("缺少 infos 或 questions")
    infos = [str(x).strip() for x in infos if str(x).strip()]
    if len(infos) < max(6, n_infos // 2):
        raise AIError("信息条数太少（%d）" % len(infos))
    infos = infos[:n_infos]

    good = []
    for q in qs:
        if not isinstance(q, dict):
            continue
        text = str(q.get("text", "")).strip()
        opts = q.get("options")
        if not text or not isinstance(opts, list) or len(opts) != 4:
            continue
        opts = [str(o).strip() for o in opts]
        if any(not o for o in opts) or len(set(opts)) != 4:
            continue
        ans = _norm_answer(q)
        if ans is None or not (0 <= ans < 4):
            continue
        uses = [u for u in (q.get("uses") or [])
                if isinstance(u, int) and 1 <= u <= len(infos)]
        # 模型很爱把正确答案放在 A（实测 15 题里 8 题是 A），
        # 这里统一重排一次，保证 ABCD 的分布是均匀的。
        order = [0, 1, 2, 3]
        random.shuffle(order)
        good.append({"text": text,
                     "options": [opts[i] for i in order],
                     "answer": order.index(ans),
                     "explain": str(q.get("explain", "")).strip(),
                     "uses": sorted(set(uses))})
        if len(good) >= n_questions:
            break
    if len(good) < max(3, n_questions // 2):
        raise AIError("可用题目太少（%d 道）" % len(good))
    for i, q in enumerate(good):
        q["no"] = i + 1
    # 模型爱把同一个人的事实写成连续一坨，打散一下（uses 会跟着重映射）
    if names:
        infos = arrange.interleave(infos, good, list(names), random)
    return infos, good


def generate_ai(names, n_infos=30, n_questions=15,
                api_key=None, model=DEFAULT_MODEL, timeout=420):
    prompt = PROMPT.format(names="、".join(names), n_infos=n_infos,
                           n_questions=n_questions)
    content = chat(api_key, model,
                   [{"role": "system", "content": "你是一个严谨的出题人，算术必须准确。"},
                    {"role": "user", "content": prompt}],
                   timeout=timeout, max_tokens=GEN_TOKENS)
    infos, qs = validate(_loads(content), n_infos, n_questions, names)
    return {"title": "DeepSeek 生成 · %d 人局" % len(names),
            "source": "deepseek", "players": list(names),
            "infos": infos, "questions": qs, "cast": []}


# --------------------------------------------------------------------------
# 润色：数字由本地引擎保证，模型只改文风
# --------------------------------------------------------------------------

POLISH_PROMPT = """下面是一个聚会游戏的信息卡，每行一条。
请把每一句改写得更有画面感、更像在讲这群人的八卦，但是：
- 所有数字必须一字不差地保留（包括单位）；
- 所有人名必须保留，不能换人；
- 每条仍然只讲这一个事实，一句话，不超过 30 个字；
- 条数和顺序完全不变。

原文：
{lines}

只输出 JSON：{{"infos": ["改写后第1条", "改写后第2条", ...]}}"""

_NUM = re.compile(r"\d+(?:\.\d+)?")


def polish(game_set, names, api_key=None, model=DEFAULT_MODEL, timeout=300):
    """返回润色后的 set；任何一条校验不过就保留本地原句。"""
    infos = game_set["infos"]
    lines = "\n".join("%d. %s" % (i + 1, t) for i, t in enumerate(infos))
    content = chat(api_key, model,
                   [{"role": "user",
                     "content": POLISH_PROMPT.format(lines=lines)}],
                   timeout=timeout, max_tokens=POLISH_TOKENS, temperature=1.3)
    obj = _loads(content)
    new = obj.get("infos")
    if not isinstance(new, list):
        raise AIError("润色返回格式异常")

    out, kept = [], 0
    for i, orig in enumerate(infos):
        cand = str(new[i]).strip() if i < len(new) else ""
        cand = re.sub(r"^\d+[.、)]\s*", "", cand)
        ok = bool(cand) and len(cand) <= 60
        if ok and sorted(_NUM.findall(cand)) != sorted(_NUM.findall(orig)):
            ok = False
        if ok:
            for nm in names:
                if (nm in orig) != (nm in cand):
                    ok = False
                    break
        if ok:
            out.append(cand)
            kept += 1
        else:
            out.append(orig)
    if kept < len(infos) // 2:
        raise AIError("润色结果大部分没通过校验")

    res = dict(game_set)
    res["infos"] = out
    res["title"] = game_set.get("title", "") + " · DeepSeek 润色"
    res["source"] = "local+deepseek"
    res["polish_kept"] = kept
    return res
