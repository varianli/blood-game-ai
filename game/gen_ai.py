# -*- coding: utf-8 -*-
"""DeepSeek 出题。

两种用法：
  generate_ai(...)  —— 让模型从零生成整套「信息 + 题目」，结构会被严格校验。
  polish(...)       —— 本地引擎先算好数值，模型只负责把句子写得更有故事感；
                       所有数字/人名必须原样保留，否则该句回退成本地版本。

任何一步失败都抛异常，由调用方降级到本地题库。
"""

import json
from pathlib import Path
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

STYLE_GUIDE_PATH = str(
    Path(__file__).resolve().parents[1] / "docs" / "memory30_style_guide.md")
_GUIDE_START = "<!-- PROMPT_REFERENCE_START -->"
_GUIDE_END = "<!-- PROMPT_REFERENCE_END -->"


def _load_style_reference():
    """读取仓库里的题型规范，让文档不是摆设而是实际 Prompt 输入。"""
    try:
        text = Path(STYLE_GUIDE_PATH).read_text(encoding="utf-8")
        return text.split(_GUIDE_START, 1)[1].split(_GUIDE_END, 1)[0].strip()
    except (OSError, IndexError):
        raise AIError("缺少或无法解析 Memory 30 题型参考文档")


STYLE_REFERENCE = _load_style_reference()

PROMPT = """你在为线下聚会制作一套原创 Memory 记忆推理题。节奏参考韩国综艺
《血之游戏 3》的 Memory 30：大屏先逐条展示看似无关、实际可被后续题目调用的
信息卡，再考记忆、应用和推理。只借鉴抽象玩法与节奏，不照抄节目原题。

参与的人物：{names}

下面是仓库内 `docs/memory30_style_guide.md` 的生成规范，必须逐条执行：
<memory30_style_reference>
{style_reference}
</memory30_style_reference>

请生成：
1. 恰好 {n_infos} 条信息卡。每条只讲一个事实，一句话、短、口语化。
2. 恰好 {n_questions} 道四选一题。答案必须能从信息卡唯一确定。

信息题材必须像被打乱的线索盒，而不是按人物写简历：
- topic 只能取：人物身份、趣味偏好、物品视觉、代码序列、日期事件、地点关系、价格数量。
- 各类都尽量出现；任意连续 4 条至少覆盖 3 种 topic，相邻两条不能同 topic。
- 同一人物不能相邻，最好至少隔 3 条；同一道题依赖的多条线索至少隔 4 条，
  推荐隔 6～12 条。
- 同一种句式骨架整套最多 2 次，不得只换人名和数字。例如连续写
  「甲上班要 30 分钟、乙上班要 20 分钟」属于不合格。
- 至少 {standalone_infos} 条不以人物姓名开头，可写颜色＋图形、短密码、牌面、
  门牌、座位、菜单、路线或星期锚点。数字可以是日期、编号和位置，不等于要计算。
- 趣味点可以用反差爱好、奇怪随身物、食物偏好、颜色图形配对、人物物品匹配、
  路线记忆、关系链、真假拼接和集合缺项；保持轻松，不写隐私羞辱或低俗内容。

题型配比（按每 15 题等比例换算）：
- 5～6 道 recall：直接回忆、人物—属性匹配；
- 3～4 道 transform：第几个字符、出现次数、哪项未出现、集合缺项；
- 约 3 道 logic：组合 2～3 条相隔较远的日期、关系、地点或事件线索；
- 纯算术最多 2 道 calculate，且算钱最多 1 道。不要把多线索题都写成乘法题。
- 同一个人物最多成为 2 道题的主角；不同 type 的题目穿插出现。

严格要求：
- 4 个选项互不相同且只有 1 个正确，干扰项必须看起来合理。
- recall/transform 的 explain 写清依据；logic/calculate 写出推理链或简短算式。
- uses 填这道题实际用到的信息编号（从 1 开始）。
- 每条信息提供仅供程序检查的 topic、family、person、template、dependency_group；
  无人物、无关联组时填空字符串。template 用短标签描述句式骨架，不能用编号规避重复。

只输出 JSON，不要任何解释文字，格式：
{{"infos": [{{"text":"信息1","topic":"趣味偏好","family":"具体内容家族",
              "person":"人物名或空字符串",
              "template":"偏好食物","dependency_group":"q07或空字符串"}}, ...],
  "questions": [{{"text": "题干", "options": ["A","B","C","D"],
                 "answer": 0, "explain": "依据或推理链", "uses": [3,4],
                 "type":"recall|transform|logic|calculate"}}]}}
answer 是正确选项在 options 里的下标（0-3）。所有文字用简体中文。"""


TOPICS = ("人物身份", "趣味偏好", "物品视觉", "代码序列",
          "日期事件", "地点关系", "价格数量")
QUESTION_TYPES = ("recall", "transform", "logic", "calculate")


def build_prompt(names, n_infos=30, n_questions=15):
    return PROMPT.format(
        names="、".join(names), n_infos=n_infos, n_questions=n_questions,
        standalone_infos=max(2, n_infos // 3),
        style_reference=STYLE_REFERENCE)


def _normal_topic(raw, text):
    value = str(raw or "").strip()
    aliases = {
        "身份职业": "人物身份", "职业": "人物身份",
        "人物日常": "趣味偏好", "偏好": "趣味偏好", "日常趣事": "趣味偏好",
        "物品": "物品视觉", "颜色图形": "物品视觉", "视觉": "物品视觉",
        "编号": "代码序列", "字符": "代码序列", "密码编号": "代码序列",
        "日期时间": "日期事件", "时间事件": "日期事件",
        "地点路线": "地点关系", "人物关系": "地点关系", "关系路线": "地点关系",
        "数量": "价格数量", "价格菜单": "价格数量", "数字数量": "价格数量",
    }
    value = aliases.get(value, value)
    if value in TOPICS:
        return value
    rules = (
        ("人物身份", r"职业|从事|担任|当医生|当老师|程序员|老板|教练|主播"),
        ("物品视觉", r"颜色|图形|形状|扑克牌|卡牌|帽子|衣服|外套|耳机|物品"),
        ("代码序列", r"密码|编号|账号|数字串|车牌|门牌|座位|楼层|第.位"),
        ("日期事件", r"生日|星期|周[一二三四五六日天]|日期|\d+月|\d+日|几点|点钟"),
        ("地点关系", r"住在|地点|路线|路口|公司|医院|学校|同学|姐妹|兄弟|朋友|同事"),
        ("价格数量", r"元|价格|折扣|公里|分钟|小时|卡路里|\d+杯|\d+件|\d+次"),
    )
    for topic, pattern in rules:
        if re.search(pattern, text):
            return topic
    return "趣味偏好"


def _sentence_skeleton(text, names):
    skeleton = text
    for name in sorted(names, key=len, reverse=True):
        skeleton = skeleton.replace(name, "{人}")
    skeleton = re.sub(r"\d+(?:\.\d+)?", "{数}", skeleton)
    skeleton = re.sub(r"需要|花费|花了|耗时|要", "需", skeleton)
    skeleton = re.sub(r"[\s，。！？、；：,.!?;:]", "", skeleton)
    return skeleton


def _normal_question_type(q, uses, text):
    value = str(q.get("type") or "").strip().lower()
    aliases = {"memory": "recall", "direct": "recall", "推理": "logic",
               "计算": "calculate", "变换": "transform"}
    value = aliases.get(value, value)
    explain = str(q.get("explain") or "")
    if (re.search(r"总共|合计|相差|多多少|少多少|加起来|乘以|除以", text) or
            (len(uses) >= 2 and re.search(r"[×÷+*＝=]", explain))):
        return "calculate"
    if value == "logic" and len(uses) < 2:
        value = ""
    if value in QUESTION_TYPES:
        return value
    if re.search(r"未提到|没出现|第.个|第.位|出现几次|缺少", text):
        return "transform"
    if len(uses) >= 2:
        return "logic"
    return "recall"


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
    """校验结构与 Memory 节奏；无法机器证明的语义正确性由 explain 供复核。"""
    if not isinstance(obj, dict):
        raise AIError("返回的不是对象")
    raw_infos = obj.get("infos")
    qs = obj.get("questions")
    if not isinstance(raw_infos, list) or not isinstance(qs, list):
        raise AIError("缺少 infos 或 questions")
    infos, topics, families, owners, templates, dependencies = [], [], [], [], [], []
    for item in raw_infos:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            raw_topic = item.get("topic")
            raw_family = str(item.get("family") or "").strip()
            owner = str(item.get("person") or "").strip()
            template = str(item.get("template") or "").strip()
            dependency = str(item.get("dependency_group") or "").strip()
        else:
            text = str(item).strip()
            raw_topic = ""
            raw_family = ""
            owner = arrange.owner_of(text, names) or ""
            template = ""
            dependency = ""
        if not text:
            continue
        infos.append(text)
        topics.append(_normal_topic(raw_topic, text))
        detected_family = arrange.content_family(text, names)
        families.append(
            raw_family if detected_family.startswith("句式:") and raw_family
            else detected_family)
        owners.append(owner or arrange.owner_of(text, names) or "")
        templates.append(template or _sentence_skeleton(text, names))
        dependencies.append(dependency)
    if len(infos) < n_infos:
        raise AIError("信息条数太少（%d）" % len(infos))
    infos = infos[:n_infos]
    topics = topics[:n_infos]
    families = families[:n_infos]
    owners = owners[:n_infos]
    templates = templates[:n_infos]
    dependencies = dependencies[:n_infos]

    family_limits = {
        "通勤": 1,
        "出生月份": 1,
        "幸运数字": 1,
        "居住地点": 2,
        "职业身份": 2,
        "宠物": 2,
        "饮品习惯": 2,
        "恐惧偏好": 2,
        "食物偏好": 2,
        "休闲偏好": 2,
        "颜色偏好": 2,
        "每周频率": 2,
        "每日时长": 2,
        "每日数量": 2,
        "价格收入": 2,
    }
    for family, limit in family_limits.items():
        count = families.count(family)
        if count > limit:
            raise AIError("内容家族「%s」重复 %d 次（最多 %d 次）" %
                          (family, count, limit))

    min_topics = 5 if n_infos >= 20 else (4 if n_infos >= 12 else 3)
    if len(set(topics)) < min_topics:
        raise AIError("信息题材太单一（只有 %d 类）" % len(set(topics)))
    if max(topics.count(topic) for topic in set(topics)) > max(3, int(n_infos * .4)):
        raise AIError("某一种题材占比过高")
    if names and n_infos >= 12:
        standalone_needed = max(2, n_infos // 3)
        not_name_first = sum(
            not any(text.startswith(name) for name in names)
            for text in infos)
        if not_name_first < standalone_needed:
            raise AIError("不以人物姓名开头的独立信息太少")
    skeletons = [_sentence_skeleton(text, names) for text in infos]
    for label in set(templates + skeletons):
        count = max(templates.count(label), skeletons.count(label))
        if label and count > 2:
            raise AIError("同一种句式重复 %d 次：%s" % (count, label[:24]))

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
        if not uses:
            continue
        qtype = _normal_question_type(q, uses, text)
        # 模型很爱把正确答案放在 A（实测 15 题里 8 题是 A），
        # 这里统一重排一次，保证 ABCD 的分布是均匀的。
        order = [0, 1, 2, 3]
        random.shuffle(order)
        good.append({"text": text,
                     "options": [opts[i] for i in order],
                     "answer": order.index(ans),
                     "explain": str(q.get("explain", "")).strip(),
                     "uses": sorted(set(uses)),
                     "type": qtype})
        if len(good) >= n_questions:
            break
    if len(good) < n_questions:
        raise AIError("可用题目太少（%d 道）" % len(good))
    max_calculate = max(1, n_questions // 6)
    if sum(q["type"] == "calculate" for q in good) > max_calculate:
        raise AIError("纯算术题太多")
    if sum(q["type"] == "logic" for q in good) < max(1, n_questions // 5):
        raise AIError("跨线索推理题太少")
    if sum(q["type"] in ("recall", "transform") for q in good) < n_questions // 2:
        raise AIError("回忆与趣味变换题太少")

    infos, topics, families = arrange.interleave_topics(
        infos, good, list(names), topics, random,
        owners=owners, dependency_groups=dependencies, families=families,
        return_families=True)
    if any(a == b for a, b in zip(topics, topics[1:])):
        raise AIError("信息题材无法充分穿插")
    if any(len(set(topics[i:i + 4])) < 3 for i in range(len(topics) - 3)):
        raise AIError("连续信息的题材仍过于相似")
    if any(family in families[max(0, index - 3):index]
           for index, family in enumerate(families)):
        raise AIError("连续信息的内容家族仍过于相似")
    good = arrange.interleave_questions(good, random)
    return infos, good, topics, families


def generate_ai(names, n_infos=30, n_questions=15,
                api_key=None, model=DEFAULT_MODEL, timeout=420):
    prompt = build_prompt(names, n_infos, n_questions)
    content = chat(api_key, model,
                   [{"role": "system", "content":
                     "你是综艺记忆游戏的严谨出题人，重视题材节奏、趣味回忆和可验证推理；算术只占少数。"},
                    {"role": "user", "content": prompt}],
                   timeout=timeout, max_tokens=GEN_TOKENS)
    infos, qs, topics, families = validate(
        _loads(content), n_infos, n_questions, names)
    return {"title": "DeepSeek 生成 · %d 人局" % len(names),
            "source": "deepseek", "players": list(names),
            "infos": infos, "info_topics": topics,
            "info_families": families,
            "questions": qs, "cast": []}


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
