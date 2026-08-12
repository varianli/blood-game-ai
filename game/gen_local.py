# -*- coding: utf-8 -*-
"""本地题库生成器。

每局随机抽取人物设定与数值，再由代码算出正确答案 —— 所以数学一定是对的。
输出格式与 data/default_set.json 完全一致：
    {"infos": [30 条信息], "questions": [15 道题]}
每道题：{"text", "options"(4), "answer"(索引), "explain", "uses"(用到第几条信息)}
"""

import random

from . import arrange

DISTRICTS =["浦东", "徐汇", "静安", "杨浦", "宝山", "闵行", "虹口", "长宁",
             "普陀", "松江", "青浦", "嘉定", "黄浦", "奉贤", "金山", "崇明"]

HOSPITALS = ["中心医院", "第一人民医院", "仁和医院", "东方医院", "康桥医院"]
PARKS = ["世纪公园", "滨江绿地", "中山公园", "共青森林公园"]
OFFICES = ["张江", "陆家嘴", "漕河泾", "五角场", "南京西路"]
PETS = ["两只猫", "一只柯基", "一缸金鱼", "一只鹦鹉", "三只仓鼠",
        "一只边牧", "一只布偶猫", "两只乌龟"]
DRINKS = ["美式", "拿铁", "手冲", "冰摇柠檬茶", "生椰拿铁", "抹茶", "普洱"]
FEARS = ["坐过山车", "打雷", "蟑螂", "看牙医", "高处", "早高峰地铁", "空腹开会"]
FOODS = ["小笼包", "麻辣烫", "生煎", "火锅", "烤鸭", "螺蛳粉", "羊肉串", "腌笃鲜"]
COLORS = ["红色", "蓝色", "黑色", "米白", "墨绿", "藏青", "杏色", "银灰"]
SEASONS = ["春天", "夏天", "秋天", "冬天"]
POOLS = {"pet": PETS, "fear": FEARS, "food": FOODS, "drink": DRINKS,
         "color": COLORS, "season": SEASONS}


# --------------------------------------------------------------------------
# 格式化
# --------------------------------------------------------------------------

def fmt_min(m):
    m = int(round(m))
    h, mm = divmod(m, 60)
    if h and mm:
        return "%d 小时 %d 分钟" % (h, mm)
    if h:
        return "%d 小时" % h
    return "%d 分钟" % mm


def fmt_hour(h):
    h = round(float(h), 2)
    if abs(h - round(h)) < 1e-9:
        return "%d 小时" % int(round(h))
    return ("%.1f" % h).rstrip("0").rstrip(".") + " 小时"


def fmt_money(v):
    v = round(float(v), 2)
    if abs(v - round(v)) < 1e-9:
        return "%d 元" % int(round(v))
    return ("%.2f" % v).rstrip("0").rstrip(".") + " 元"


def fmt_num(unit):
    def f(v):
        v = round(float(v), 2)
        if abs(v - round(v)) < 1e-9:
            return "%d %s" % (int(round(v)), unit)
        return ("%.1f" % v).rstrip("0").rstrip(".") + " " + unit
    return f


# --------------------------------------------------------------------------
# 选项构造
# --------------------------------------------------------------------------

def build_options(rng, correct, wrongs, fmt):
    """把正确答案和干扰项拼成 4 个互不相同的选项，返回 (options, answer_index)。"""
    texts = [fmt(correct)]
    used = set(texts)

    def try_add(v):
        if v is None or len(texts) >= 4:
            return
        try:
            v = float(v)
        except (TypeError, ValueError):
            return
        if v <= 0 or abs(v - correct) < 1e-9:
            return
        t = fmt(v)
        if t in used:
            return
        used.add(t)
        texts.append(t)

    for w in wrongs:
        try_add(w)

    # 兜底：常见的“算错”方向
    step = max(1.0, abs(correct) * 0.2)
    for w in (correct * 2, correct / 2.0, correct + step, correct - step,
              correct * 1.5, correct * 0.75, correct * 3, correct + 2 * step,
              correct - 2 * step, correct * 1.1, correct * 0.6):
        try_add(round(w, 2))

    order = list(range(4))
    rng.shuffle(order)
    options = [texts[i] for i in order]
    return options, order.index(0)


def build_choice(rng, correct_text, wrong_texts):
    texts = [correct_text]
    used = {correct_text}
    for t in wrong_texts:
        if len(texts) >= 4:
            break
        if t and t not in used:
            used.add(t)
            texts.append(t)
    while len(texts) < 4:
        texts.append("以上都不对 %d" % len(texts))
    order = list(range(4))
    rng.shuffle(order)
    return [texts[i] for i in order], order.index(0)


# --------------------------------------------------------------------------
# 人物设定（每个职业给出「事实」和「基于事实的题目」）
# --------------------------------------------------------------------------

def _p(rng, seq):
    return rng.choice(seq)


def make_person(rng, name, arche, district, place_pool):
    """构造一个人物。facts 按重要性排序，前面的优先进入信息池。"""
    v = {}
    f = []          # [(key, text)]
    p = {"name": name, "arche": arche, "vals": v, "facts": f,
         "district": district, "role": ""}

    if arche == "doctor":
        hosp = place_pool["hospital"]
        v["commute"] = _p(rng, [15, 20, 25, 30, 35, 40, 45])
        v["days"] = _p(rng, [4, 5, 6])
        v["hours"] = _p(rng, [6, 7, 8, 9])
        v["wage"] = _p(rng, [80, 100, 120, 150, 200])
        p["role"] = "医生"
        f += [("home", "%s住在%s。" % (name, district)),
              ("job", "%s在%s当医生。" % (name, hosp)),
              ("commute", "%s从家到医院单程要 %d 分钟。" % (name, v["commute"])),
              ("days", "%s每周去医院上班 %d 天。" % (name, v["days"])),
              ("hours", "%s每天在医院工作 %d 小时。" % (name, v["hours"])),
              ("wage", "%s在医院的时薪是 %d 元。" % (name, v["wage"]))]

    elif arche == "cafe":
        v["cups"] = _p(rng, [60, 70, 80, 90, 100, 120])
        v["price"] = _p(rng, [18, 20, 22, 25, 28, 30])
        v["days"] = _p(rng, [5, 6, 7])
        v["commute"] = _p(rng, [10, 15, 20, 25])
        p["role"] = "咖啡店老板"
        f += [("home", "%s住在%s。" % (name, district)),
              ("job", "%s开了一家咖啡店。" % name),
              ("cups", "%s的咖啡店每天卖出 %d 杯咖啡。" % (name, v["cups"])),
              ("price", "%s店里每杯咖啡卖 %d 元。" % (name, v["price"])),
              ("days", "%s的咖啡店每周营业 %d 天。" % (name, v["days"])),
              ("commute", "%s每天骑车 %d 分钟到店里。" % (name, v["commute"]))]

    elif arche == "coach":
        v["sessions"] = _p(rng, [8, 10, 12, 14, 15])
        v["smin"] = _p(rng, [45, 60, 90])
        v["fee"] = _p(rng, [200, 250, 300, 350, 400])
        v["run"] = _p(rng, [3, 5, 8, 10])
        p["role"] = "健身教练"
        f += [("home", "%s住在%s。" % (name, district)),
              ("job", "%s是健身教练。" % name),
              ("sessions", "%s每周上 %d 节私教课。" % (name, v["sessions"])),
              ("smin", "%s每节私教课 %d 分钟。" % (name, v["smin"])),
              ("fee", "%s每节私教课收费 %d 元。" % (name, v["fee"])),
              ("run", "%s每天跑步 %d 公里。" % (name, v["run"]))]

    elif arche == "coder":
        office = place_pool["office"]
        v["commute"] = _p(rng, [25, 30, 40, 45, 50, 60])
        v["days"] = _p(rng, [3, 4, 5])
        v["hours"] = _p(rng, [5, 6, 7, 8])
        v["bug"] = _p(rng, [2, 3, 4, 5])
        p["role"] = "程序员"
        f += [("home", "%s住在%s。" % (name, district)),
              ("job", "%s在%s当程序员。" % (name, office)),
              ("commute", "%s从家到公司单程要 %d 分钟。" % (name, v["commute"])),
              ("days", "%s每周去公司 %d 天。" % (name, v["days"])),
              ("hours", "%s每天写代码 %d 小时。" % (name, v["hours"])),
              ("bug", "%s平均每天修 %d 个 bug。" % (name, v["bug"]))]

    elif arche == "teacher":
        v["lessons"] = _p(rng, [15, 16, 18, 20, 24])
        v["lmin"] = _p(rng, [35, 40, 45])
        v["walk"] = _p(rng, [5, 8, 10, 12, 15])
        v["days"] = 5
        v["papers"] = _p(rng, [30, 36, 40, 45])
        p["role"] = "老师"
        f += [("home", "%s住在%s。" % (name, district)),
              ("job", "%s是小学语文老师。" % name),
              ("lessons", "%s每周上 %d 节课。" % (name, v["lessons"])),
              ("lmin", "%s每节课 %d 分钟。" % (name, v["lmin"])),
              ("walk", "%s每天步行 %d 分钟到学校。" % (name, v["walk"])),
              ("papers", "%s每天要批 %d 份作业。" % (name, v["papers"]))]

    elif arche == "courier":
        v["parcels"] = _p(rng, [80, 100, 120, 150, 180])
        v["fee"] = _p(rng, [1.5, 2, 2.5, 3])
        v["days"] = _p(rng, [5, 6, 7])
        v["km"] = _p(rng, [40, 50, 60, 80])
        p["role"] = "快递员"
        f += [("home", "%s住在%s。" % (name, district)),
              ("job", "%s是快递员。" % name),
              ("parcels", "%s每天送 %d 件快递。" % (name, v["parcels"])),
              ("fee", "%s每送一件快递赚 %s 元。" % (
                  name, ("%.1f" % v["fee"]).rstrip("0").rstrip("."))),
              ("days", "%s每周工作 %d 天。" % (name, v["days"])),
              ("km", "%s每天骑电动车跑 %d 公里。" % (name, v["km"]))]

    elif arche == "driver":
        v["orders"] = _p(rng, [15, 18, 20, 24, 30])
        v["fee"] = _p(rng, [18, 20, 25, 30])
        v["days"] = _p(rng, [5, 6, 7])
        v["hours"] = _p(rng, [8, 9, 10, 12])
        p["role"] = "网约车司机"
        f += [("home", "%s住在%s。" % (name, district)),
              ("job", "%s开网约车。" % name),
              ("orders", "%s每天跑 %d 单。" % (name, v["orders"])),
              ("fee", "%s平均每单赚 %d 元。" % (name, v["fee"])),
              ("days", "%s每周出车 %d 天。" % (name, v["days"])),
              ("hours", "%s每天在车上待 %d 小时。" % (name, v["hours"]))]

    elif arche == "streamer":
        v["hours"] = _p(rng, [2, 3, 4, 5])
        v["days"] = _p(rng, [4, 5, 6, 7])
        v["gift"] = _p(rng, [200, 300, 400, 500, 800])
        v["fans"] = _p(rng, [3000, 5000, 8000, 12000])
        p["role"] = "主播"
        f += [("home", "%s住在%s。" % (name, district)),
              ("job", "%s是一名带货主播。" % name),
              ("hours", "%s每晚直播 %d 小时。" % (name, v["hours"])),
              ("days", "%s每周直播 %d 天。" % (name, v["days"])),
              ("gift", "%s直播平均每小时收到 %d 元打赏。" % (name, v["gift"])),
              ("fans", "%s的直播间有 %d 个粉丝。" % (name, v["fans"]))]

    elif arche == "baker":
        v["loaves"] = _p(rng, [60, 80, 100, 120])
        v["price"] = _p(rng, [8, 10, 12, 15, 18])
        v["days"] = _p(rng, [5, 6, 7])
        v["wake"] = _p(rng, [3, 4, 5])
        p["role"] = "面包师"
        f += [("home", "%s住在%s。" % (name, district)),
              ("job", "%s在面包房当面包师。" % name),
              ("loaves", "%s每天烤 %d 个面包。" % (name, v["loaves"])),
              ("price", "%s烤的面包每个卖 %d 元。" % (name, v["price"])),
              ("days", "%s的面包房每周开门 %d 天。" % (name, v["days"])),
              ("wake", "%s每天凌晨 %d 点起床。" % (name, v["wake"]))]

    else:  # florist
        v["bouquets"] = _p(rng, [20, 25, 30, 40, 50])
        v["price"] = _p(rng, [39, 50, 60, 88, 99])
        v["days"] = _p(rng, [5, 6, 7])
        v["water"] = _p(rng, [2, 3, 4])
        p["role"] = "花店老板"
        f += [("home", "%s住在%s。" % (name, district)),
              ("job", "%s开了一家花店。" % name),
              ("bouquets", "%s的花店每天卖出 %d 束花。" % (name, v["bouquets"])),
              ("price", "%s店里每束花卖 %d 元。" % (name, v["price"])),
              ("days", "%s的花店每周营业 %d 天。" % (name, v["days"])),
              ("water", "%s每天给花浇 %d 次水。" % (name, v["water"]))]

    # 通用事实：人多时用不上，人少时补足信息量，其中带数字的也能出题
    v["sleep"] = _p(rng, [5, 6, 7, 8])
    v["steps"] = _p(rng, [3000, 5000, 8000, 12000, 15000])
    v["wtr"] = _p(rng, [4, 5, 6, 8])
    v["phone"] = _p(rng, [1, 2, 3, 4])
    v["movies"] = _p(rng, [1, 2, 3, 4])
    v["coffee"] = _p(rng, [1, 2, 3, 4])
    v["gaming"] = _p(rng, [1, 2, 3, 5])
    v["subway"] = _p(rng, [4, 6, 8, 10, 14])
    v["books"] = _p(rng, [1, 2, 3, 4])
    v["takeout"] = _p(rng, [2, 3, 4, 5])
    p["color"] = _p(rng, COLORS)
    p["season"] = _p(rng, SEASONS)
    p["lucky"] = rng.randint(1, 9)
    p["pet"] = _p(rng, PETS)
    p["drink"] = _p(rng, DRINKS)
    p["park"] = _p(rng, PARKS)
    p["fear"] = _p(rng, FEARS)
    p["food"] = _p(rng, FOODS)
    p["month"] = rng.randint(1, 12)
    f += [("sleep", "%s每天睡 %d 小时。" % (name, v["sleep"])),
          ("pet", "%s家里养了%s。" % (name, p["pet"])),
          ("steps", "%s每天走 %d 步。" % (name, v["steps"])),
          ("drink", "%s每天必须来一杯%s。" % (name, p["drink"])),
          ("wtr", "%s每天喝 %d 杯水。" % (name, v["wtr"])),
          ("fear", "%s最怕%s。" % (name, p["fear"])),
          ("phone", "%s每天刷 %d 小时手机。" % (name, v["phone"])),
          ("food", "%s最爱吃%s。" % (name, p["food"])),
          ("movies", "%s每周看 %d 部电影。" % (name, v["movies"])),
          ("park", "%s周末喜欢去%s散步。" % (name, p["park"])),
          ("month", "%s是 %d 月生的。" % (name, p["month"])),
          ("coffee", "%s每天喝 %d 杯咖啡。" % (name, v["coffee"])),
          ("color", "%s最喜欢的颜色是%s。" % (name, p["color"])),
          ("gaming", "%s每天打 %d 小时游戏。" % (name, v["gaming"])),
          ("season", "%s最喜欢%s。" % (name, p["season"])),
          ("subway", "%s每周坐 %d 次地铁。" % (name, v["subway"])),
          ("lucky", "%s的幸运数字是 %d。" % (name, p["lucky"])),
          ("books", "%s每月看 %d 本书。" % (name, v["books"])),
          ("takeout", "%s每周点 %d 次外卖。" % (name, v["takeout"]))]
    return p


# --------------------------------------------------------------------------
# 每个人可以出的题
# --------------------------------------------------------------------------

def person_questions(rng, p):
    """返回 [(needs, builder)]，builder(idx) -> question dict。"""
    v, n, out = p["vals"], p["name"], []

    def add(needs, fn):
        out.append((needs, fn))

    def U(idx, keys):
        return sorted(idx[k] for k in keys)

    a = p["arche"]

    if a in ("doctor", "coder"):
        place = "医院" if a == "doctor" else "公司"

        def q_commute(idx):
            c, d = v["commute"], v["days"]
            ans = c * 2 * d
            return dict(
                text="%s每周花在上下班路上（往返）的时间一共是多久？" % n,
                _c=ans, _f=fmt_min,
                _w=[c * d, c * 2 * 7, c * 2 * (d + 1), c * 2 * (d - 1)],
                explain="单程 %d 分钟 → 往返 %d 分钟；每周 %d 天 → %d × %d = %d 分钟。"
                        % (c, c * 2, d, c * 2, d, ans),
                uses=U(idx, ["commute", "days"]))
        add(["commute", "days"], q_commute)

        def q_hours(idx):
            ans = v["hours"] * v["days"]
            return dict(
                text="%s每周在%s待多少小时？" % (n, place),
                _c=ans, _f=fmt_hour,
                _w=[v["hours"] * 7, v["hours"] * (v["days"] + 1),
                    v["hours"] * (v["days"] - 1)],
                explain="每天 %d 小时 × 每周 %d 天 = %d 小时。"
                        % (v["hours"], v["days"], ans),
                uses=U(idx, ["hours", "days"]))
        add(["hours", "days"], q_hours)

        def q_day_total(idx):
            c, h = v["commute"], v["hours"]
            ans = c * 2 + h * 60
            return dict(
                text="上班这天，%s从出门到回家一共要花掉多少时间？" % n,
                _c=ans, _f=fmt_min,
                _w=[c + h * 60, h * 60, c * 2],
                explain="往返通勤 %d 分钟 + 工作 %d 小时（%d 分钟）= %d 分钟。"
                        % (c * 2, h, h * 60, ans),
                uses=U(idx, ["commute", "hours"]))
        add(["commute", "hours"], q_day_total)

    if a == "doctor":
        def q_pay(idx):
            ans = v["wage"] * v["hours"] * v["days"]
            return dict(
                text="%s一周能拿到多少工资？" % n,
                _c=ans, _f=fmt_money,
                _w=[v["wage"] * v["hours"] * 7, v["wage"] * v["hours"],
                    v["wage"] * v["days"]],
                explain="时薪 %d 元 × 每天 %d 小时 × 每周 %d 天 = %d 元。"
                        % (v["wage"], v["hours"], v["days"], ans),
                uses=U(idx, ["wage", "hours", "days"]))
        add(["wage", "hours", "days"], q_pay)

    if a == "coder":
        def q_bug(idx):
            ans = v["bug"] * v["days"]
            return dict(
                text="%s一周大概能修掉多少个 bug？" % n,
                _c=ans, _f=fmt_num("个"),
                _w=[v["bug"] * 7, v["bug"] * 5, v["bug"] * (v["days"] + 2)],
                explain="每天 %d 个 × 每周上班 %d 天 = %d 个。"
                        % (v["bug"], v["days"], ans),
                uses=U(idx, ["bug", "days"]))
        add(["bug", "days"], q_bug)

    if a in ("cafe", "baker", "florist"):
        cfg = {"cafe": ("cups", "price", "杯", "咖啡店", "咖啡"),
               "baker": ("loaves", "price", "个", "面包房", "面包"),
               "florist": ("bouquets", "price", "束", "花店", "花")}[a]
        ck, pk, unit, shop, thing = cfg

        def q_day_rev(idx):
            ans = v[ck] * v[pk]
            return dict(
                text="%s的%s一天能卖出多少钱的%s？" % (n, shop, thing),
                _c=ans, _f=fmt_money,
                _w=[v[ck] + v[pk], v[ck] * v[pk] / 2.0, v[ck] * v[pk] * 2],
                explain="%d %s × %d 元 = %d 元。" % (v[ck], unit, v[pk], ans),
                uses=U(idx, [ck, pk]))
        add([ck, pk], q_day_rev)

        def q_week_rev(idx):
            ans = v[ck] * v[pk] * v["days"]
            return dict(
                text="%s的%s一周的营业额是多少？" % (n, shop),
                _c=ans, _f=fmt_money,
                _w=[v[ck] * v[pk] * 7, v[ck] * v[pk],
                    v[ck] * v[pk] * (v["days"] - 1)],
                explain="%d %s × %d 元 = %d 元/天；每周营业 %d 天 → %d 元。"
                        % (v[ck], unit, v[pk], v[ck] * v[pk], v["days"], ans),
                uses=U(idx, [ck, pk, "days"]))
        add([ck, pk, "days"], q_week_rev)

        def q_week_cnt(idx):
            ans = v[ck] * v["days"]
            return dict(
                text="%s的%s一周一共卖出多少%s%s？" % (n, shop, unit, thing),
                _c=ans, _f=fmt_num(unit),
                _w=[v[ck] * 7, v[ck] * (v["days"] - 1), v[ck] * (v["days"] + 1)],
                explain="每天 %d %s × 每周 %d 天 = %d %s。"
                        % (v[ck], unit, v["days"], ans, unit),
                uses=U(idx, [ck, "days"]))
        add([ck, "days"], q_week_cnt)

    if a == "coach":
        def q_time(idx):
            ans = v["sessions"] * v["smin"]
            return dict(
                text="%s一周上私教课的总时长是多少？" % n,
                _c=ans, _f=fmt_min,
                _w=[v["sessions"] * 60, v["sessions"] * v["smin"] / 2.0,
                    (v["sessions"] + 2) * v["smin"]],
                explain="%d 节 × %d 分钟 = %d 分钟。"
                        % (v["sessions"], v["smin"], ans),
                uses=U(idx, ["sessions", "smin"]))
        add(["sessions", "smin"], q_time)

        def q_income(idx):
            ans = v["sessions"] * v["fee"]
            return dict(
                text="%s一周靠私教课能挣多少钱？" % n,
                _c=ans, _f=fmt_money,
                _w=[v["fee"] * 7, v["sessions"] * v["fee"] / 2.0,
                    (v["sessions"] - 2) * v["fee"]],
                explain="%d 节 × %d 元 = %d 元。" % (v["sessions"], v["fee"], ans),
                uses=U(idx, ["sessions", "fee"]))
        add(["sessions", "fee"], q_income)

        def q_hourly(idx):
            # 算出来不是整数就不出这道题，免得让人在派对上选小数
            if (v["fee"] * 60) % v["smin"] != 0:
                return None
            ans = v["fee"] * 60 // v["smin"]
            return dict(
                text="算下来，%s上私教课平均每小时挣多少钱？" % n,
                _c=ans, _f=fmt_money,
                _w=[v["fee"], v["fee"] * v["smin"] / 60.0, v["fee"] * 2],
                explain="每节 %d 分钟收 %d 元 → %d ÷ (%d/60) = %s。"
                        % (v["smin"], v["fee"], v["fee"], v["smin"], fmt_money(ans)),
                uses=U(idx, ["smin", "fee"]))
        add(["smin", "fee"], q_hourly)

        def q_run(idx):
            ans = v["run"] * 7
            return dict(
                text="%s一周（7 天）一共跑多少公里？" % n,
                _c=ans, _f=fmt_num("公里"),
                _w=[v["run"] * 5, v["run"] * 6, v["run"] * 30],
                explain="每天 %d 公里 × 7 天 = %d 公里。" % (v["run"], ans),
                uses=U(idx, ["run"]))
        add(["run"], q_run)

    if a == "teacher":
        def q_class(idx):
            ans = v["lessons"] * v["lmin"]
            return dict(
                text="%s一周站在讲台上的时间一共多久？" % n,
                _c=ans, _f=fmt_min,
                _w=[v["lessons"] * 60, v["lessons"] * v["lmin"] / 2.0,
                    (v["lessons"] - 4) * v["lmin"]],
                explain="%d 节 × %d 分钟 = %d 分钟。"
                        % (v["lessons"], v["lmin"], ans),
                uses=U(idx, ["lessons", "lmin"]))
        add(["lessons", "lmin"], q_class)

        def q_walk(idx):
            ans = v["walk"] * 2 * 5
            return dict(
                text="%s一周（按 5 个上学日算）往返走路要花多少时间？" % n,
                _c=ans, _f=fmt_min,
                _w=[v["walk"] * 5, v["walk"] * 2 * 7, v["walk"] * 2],
                explain="单程 %d 分钟 → 往返 %d 分钟；5 天 → %d 分钟。"
                        % (v["walk"], v["walk"] * 2, ans),
                uses=U(idx, ["walk"]))
        add(["walk"], q_walk)

        def q_papers(idx):
            ans = v["papers"] * 5
            return dict(
                text="%s一周（5 个工作日）要批多少份作业？" % n,
                _c=ans, _f=fmt_num("份"),
                _w=[v["papers"] * 7, v["papers"] * 6, v["papers"] * 4],
                explain="每天 %d 份 × 5 天 = %d 份。" % (v["papers"], ans),
                uses=U(idx, ["papers"]))
        add(["papers"], q_papers)

    if a == "courier":
        def q_day(idx):
            ans = v["parcels"] * v["fee"]
            return dict(
                text="%s送一天快递能赚多少钱？" % n,
                _c=ans, _f=fmt_money,
                _w=[v["parcels"], v["parcels"] * v["fee"] * 2,
                    v["parcels"] * v["fee"] / 2.0],
                explain="%d 件 × %s 元 = %s。"
                        % (v["parcels"],
                           ("%.1f" % v["fee"]).rstrip("0").rstrip("."),
                           fmt_money(ans)),
                uses=U(idx, ["parcels", "fee"]))
        add(["parcels", "fee"], q_day)

        def q_week(idx):
            ans = v["parcels"] * v["fee"] * v["days"]
            return dict(
                text="%s一周送快递能赚多少钱？" % n,
                _c=ans, _f=fmt_money,
                _w=[v["parcels"] * v["fee"] * 7, v["parcels"] * v["fee"],
                    v["parcels"] * v["fee"] * (v["days"] - 1)],
                explain="每天 %s × 每周 %d 天 = %s。"
                        % (fmt_money(v["parcels"] * v["fee"]), v["days"],
                           fmt_money(ans)),
                uses=U(idx, ["parcels", "fee", "days"]))
        add(["parcels", "fee", "days"], q_week)

        def q_cnt(idx):
            ans = v["parcels"] * v["days"]
            return dict(
                text="%s一周一共要送多少件快递？" % n,
                _c=ans, _f=fmt_num("件"),
                _w=[v["parcels"] * 7, v["parcels"] * (v["days"] - 1),
                    v["parcels"] * 30],
                explain="每天 %d 件 × 每周 %d 天 = %d 件。"
                        % (v["parcels"], v["days"], ans),
                uses=U(idx, ["parcels", "days"]))
        add(["parcels", "days"], q_cnt)

    if a == "driver":
        def q_orders(idx):
            ans = v["orders"] * v["days"]
            return dict(
                text="%s一周一共跑多少单？" % n,
                _c=ans, _f=fmt_num("单"),
                _w=[v["orders"] * 7, v["orders"] * (v["days"] - 1),
                    v["orders"] * 30],
                explain="每天 %d 单 × 每周 %d 天 = %d 单。"
                        % (v["orders"], v["days"], ans),
                uses=U(idx, ["orders", "days"]))
        add(["orders", "days"], q_orders)

        def q_money(idx):
            ans = v["orders"] * v["fee"] * v["days"]
            return dict(
                text="%s一周开网约车能赚多少钱？" % n,
                _c=ans, _f=fmt_money,
                _w=[v["orders"] * v["fee"] * 7, v["orders"] * v["fee"],
                    v["orders"] * v["fee"] * (v["days"] - 1)],
                explain="每天 %d 单 × %d 元 = %d 元；× %d 天 = %d 元。"
                        % (v["orders"], v["fee"], v["orders"] * v["fee"],
                           v["days"], ans),
                uses=U(idx, ["orders", "fee", "days"]))
        add(["orders", "fee", "days"], q_money)

        def q_hours(idx):
            ans = v["hours"] * v["days"]
            return dict(
                text="%s一周在车上待多少小时？" % n,
                _c=ans, _f=fmt_hour,
                _w=[v["hours"] * 7, v["hours"] * (v["days"] - 1), v["hours"] * 5],
                explain="每天 %d 小时 × %d 天 = %d 小时。"
                        % (v["hours"], v["days"], ans),
                uses=U(idx, ["hours", "days"]))
        add(["hours", "days"], q_hours)

    if a == "streamer":
        def q_hours(idx):
            ans = v["hours"] * v["days"]
            return dict(
                text="%s一周一共直播多少小时？" % n,
                _c=ans, _f=fmt_hour,
                _w=[v["hours"] * 7, v["hours"] * (v["days"] - 1), v["hours"] * 5],
                explain="每晚 %d 小时 × 每周 %d 天 = %d 小时。"
                        % (v["hours"], v["days"], ans),
                uses=U(idx, ["hours", "days"]))
        add(["hours", "days"], q_hours)

        def q_gift(idx):
            ans = v["hours"] * v["days"] * v["gift"]
            return dict(
                text="%s一周能收到多少打赏？" % n,
                _c=ans, _f=fmt_money,
                _w=[v["hours"] * 7 * v["gift"], v["hours"] * v["gift"],
                    v["days"] * v["gift"]],
                explain="每周直播 %d 小时 × 每小时 %d 元 = %d 元。"
                        % (v["hours"] * v["days"], v["gift"], ans),
                uses=U(idx, ["hours", "days", "gift"]))
        add(["hours", "days", "gift"], q_gift)

    if a == "baker":
        def q_wake(idx):
            ans = v["wake"] * v["days"]
            return dict(
                text="如果 %s每次都在凌晨 %d 点起床，一周要这样起床几次？"
                     % (n, v["wake"]),
                _c=v["days"], _f=fmt_num("次"),
                _w=[7, v["days"] - 1, v["days"] + 1],
                explain="面包房每周开门 %d 天，所以起床 %d 次。"
                        % (v["days"], v["days"]),
                uses=U(idx, ["wake", "days"]))
        add(["wake", "days"], q_wake)

    if a == "florist":
        def q_water(idx):
            ans = v["water"] * 7
            return dict(
                text="%s一周（7 天）一共给花浇多少次水？" % n,
                _c=ans, _f=fmt_num("次"),
                _w=[v["water"] * 5, v["water"] * v["days"], v["water"] * 30],
                explain="每天 %d 次 × 7 天 = %d 次。" % (v["water"], ans),
                uses=U(idx, ["water"]))
        add(["water"], q_water)

    # ---- 通用事实衍生的题 ----
    def q_sleep(idx):
        ans = v["sleep"] * 7
        return dict(text="%s一周一共睡多少小时？" % n, _c=ans, _f=fmt_hour,
                    _w=[v["sleep"] * 5, v["sleep"] * 6, v["sleep"] * 30],
                    explain="每天 %d 小时 × 7 天 = %d 小时。" % (v["sleep"], ans),
                    uses=U(idx, ["sleep"]))
    add(["sleep"], q_sleep)

    def q_awake(idx):
        ans = (24 - v["sleep"]) * 7
        return dict(text="%s一周醒着的时间一共是多少小时？" % n, _c=ans, _f=fmt_hour,
                    _w=[24 * 7, (24 - v["sleep"]), v["sleep"] * 7],
                    explain="每天醒着 24-%d = %d 小时；× 7 天 = %d 小时。"
                            % (v["sleep"], 24 - v["sleep"], ans),
                    uses=U(idx, ["sleep"]))
    add(["sleep"], q_awake)

    def q_steps(idx):
        ans = v["steps"] * 7
        return dict(text="%s一周一共走多少步？" % n, _c=ans, _f=fmt_num("步"),
                    _w=[v["steps"] * 5, v["steps"] * 6, v["steps"] * 30],
                    explain="每天 %d 步 × 7 天 = %d 步。" % (v["steps"], ans),
                    uses=U(idx, ["steps"]))
    add(["steps"], q_steps)

    def q_water2(idx):
        ans = v["wtr"] * 7
        return dict(text="%s一周一共喝多少杯水？" % n, _c=ans, _f=fmt_num("杯"),
                    _w=[v["wtr"] * 5, v["wtr"] * 30, v["wtr"] * 2],
                    explain="每天 %d 杯 × 7 天 = %d 杯。" % (v["wtr"], ans),
                    uses=U(idx, ["wtr"]))
    add(["wtr"], q_water2)

    def q_phone(idx):
        ans = v["phone"] * 7
        return dict(text="%s一周花在刷手机上的时间是多少？" % n, _c=ans, _f=fmt_hour,
                    _w=[v["phone"] * 5, v["phone"] * 30, v["phone"]],
                    explain="每天 %d 小时 × 7 天 = %d 小时。" % (v["phone"], ans),
                    uses=U(idx, ["phone"]))
    add(["phone"], q_phone)

    def q_movies(idx):
        ans = v["movies"] * 4
        return dict(text="%s一个月（按 4 周算）能看多少部电影？" % n,
                    _c=ans, _f=fmt_num("部"),
                    _w=[v["movies"] * 7, v["movies"] * 30, v["movies"] * 12],
                    explain="每周 %d 部 × 4 周 = %d 部。" % (v["movies"], ans),
                    uses=U(idx, ["movies"]))
    add(["movies"], q_movies)

    def q_coffee(idx):
        ans = v["coffee"] * 7
        return dict(text="%s一周一共喝多少杯咖啡？" % n, _c=ans, _f=fmt_num("杯"),
                    _w=[v["coffee"] * 5, v["coffee"] * 30, v["coffee"]],
                    explain="每天 %d 杯 × 7 天 = %d 杯。" % (v["coffee"], ans),
                    uses=U(idx, ["coffee"]))
    add(["coffee"], q_coffee)

    def q_gaming(idx):
        ans = v["gaming"] * 7
        return dict(text="%s一周打多少小时游戏？" % n, _c=ans, _f=fmt_hour,
                    _w=[v["gaming"] * 5, v["gaming"] * 30, v["gaming"]],
                    explain="每天 %d 小时 × 7 天 = %d 小时。" % (v["gaming"], ans),
                    uses=U(idx, ["gaming"]))
    add(["gaming"], q_gaming)

    def q_subway(idx):
        ans = v["subway"] * 4
        return dict(text="%s一个月（按 4 周算）坐多少次地铁？" % n,
                    _c=ans, _f=fmt_num("次"),
                    _w=[v["subway"] * 7, v["subway"] * 30, v["subway"] * 12],
                    explain="每周 %d 次 × 4 周 = %d 次。" % (v["subway"], ans),
                    uses=U(idx, ["subway"]))
    add(["subway"], q_subway)

    def q_books(idx):
        ans = v["books"] * 12
        return dict(text="%s一年能看多少本书？" % n, _c=ans, _f=fmt_num("本"),
                    _w=[v["books"] * 4, v["books"] * 52, v["books"] * 7],
                    explain="每月 %d 本 × 12 个月 = %d 本。" % (v["books"], ans),
                    uses=U(idx, ["books"]))
    add(["books"], q_books)

    def q_takeout(idx):
        ans = v["takeout"] * 4
        return dict(text="%s一个月（按 4 周算）点多少次外卖？" % n,
                    _c=ans, _f=fmt_num("次"),
                    _w=[v["takeout"] * 7, v["takeout"] * 30, v["takeout"]],
                    explain="每周 %d 次 × 4 周 = %d 次。" % (v["takeout"], ans),
                    uses=U(idx, ["takeout"]))
    add(["takeout"], q_takeout)

    def q_coffee_money(idx):
        ans = v["coffee"] * 7 * 25
        return dict(text="%s一周喝咖啡按每杯 25 元算，要花多少钱？" % n,
                    _c=ans, _f=fmt_money,
                    _w=[v["coffee"] * 25, v["coffee"] * 5 * 25, v["coffee"] * 30 * 25],
                    explain="每天 %d 杯 × 7 天 = %d 杯；× 25 元 = %d 元。"
                            % (v["coffee"], v["coffee"] * 7, ans),
                    uses=U(idx, ["coffee"]))
    add(["coffee"], q_coffee_money)

    def q_sleep_phone(idx):
        ans = (v["sleep"] + v["phone"]) * 7
        return dict(text="%s一周花在「睡觉 + 刷手机」上的时间一共多少？" % n,
                    _c=ans, _f=fmt_hour,
                    _w=[(v["sleep"] + v["phone"]), v["sleep"] * 7, v["phone"] * 7],
                    explain="每天 %d + %d = %d 小时；× 7 天 = %d 小时。"
                            % (v["sleep"], v["phone"], v["sleep"] + v["phone"], ans),
                    uses=U(idx, ["sleep", "phone"]))
    add(["sleep", "phone"], q_sleep_phone)

    return out


# --------------------------------------------------------------------------
# 跨人物的题
# --------------------------------------------------------------------------

def weekly_commute(p):
    v = p["vals"]
    if "commute" in p["idx"] and "days" in p["idx"] and "commute" in v:
        return v["commute"] * 2 * v["days"]
    return None


INCOME_KEYS = ("wage", "hours", "days", "sessions", "fee", "parcels",
               "orders", "gift")


def income_fact_idx(p):
    return [p["idx"][k] for k in INCOME_KEYS if k in p["idx"]]


def weekly_income(p):
    v, a, idx = p["vals"], p["arche"], p["idx"]
    have = lambda *ks: all(k in idx for k in ks)
    if a == "doctor" and have("wage", "hours", "days"):
        return v["wage"] * v["hours"] * v["days"]
    if a == "coach" and have("sessions", "fee"):
        return v["sessions"] * v["fee"]
    if a == "courier" and have("parcels", "fee", "days"):
        return v["parcels"] * v["fee"] * v["days"]
    if a == "driver" and have("orders", "fee", "days"):
        return v["orders"] * v["fee"] * v["days"]
    if a == "streamer" and have("hours", "days", "gift"):
        return v["hours"] * v["days"] * v["gift"]
    return None


def cross_questions(rng, people):
    out = []

    # 1. 两人周通勤时间比较
    with_commute = [p for p in people if weekly_commute(p) is not None]
    for i in range(len(with_commute)):
        for j in range(i + 1, len(with_commute)):
            a, b = with_commute[i], with_commute[j]
            ta, tb = weekly_commute(a), weekly_commute(b)
            if ta == tb:
                continue

            def mk(a=a, b=b, ta=ta, tb=tb):
                hi, lo = (a, b) if ta > tb else (b, a)
                d = abs(ta - tb)
                opts, ai = build_choice(
                    rng,
                    "%s多 %s" % (hi["name"], fmt_min(d)),
                    ["%s多 %s" % (lo["name"], fmt_min(d)),
                     "%s多 %s" % (hi["name"], fmt_min(max(5, d // 2))),
                     "两个人一样多"])
                return dict(
                    text="%s和%s，谁每周花在路上（往返）的时间更多？多多少？"
                         % (a["name"], b["name"]),
                    options=opts, answer=ai,
                    explain="%s：%d×2×%d = %d 分钟；%s：%d×2×%d = %d 分钟；相差 %s。"
                            % (a["name"], a["vals"]["commute"], a["vals"]["days"], ta,
                               b["name"], b["vals"]["commute"], b["vals"]["days"], tb,
                               fmt_min(d)),
                    uses=sorted([a["idx"]["commute"], a["idx"]["days"],
                                 b["idx"]["commute"], b["idx"]["days"]]))
            out.append(mk)

    # 2. 谁的单程通勤最长
    cm = [p for p in people if "commute" in p["idx"] and "commute" in p["vals"]]
    if len(cm) >= 3:
        def mk_longest(cm=cm):
            sel = sorted(cm, key=lambda p: -p["vals"]["commute"])[:3]
            if sel[0]["vals"]["commute"] == sel[1]["vals"]["commute"]:
                return None
            names = [p["name"] for p in sel]
            rng.shuffle(names)
            opts, ai = build_choice(
                rng, sel[0]["name"],
                [n for n in names if n != sel[0]["name"]] + ["三个人一样"])
            return dict(
                text="在%s、%s、%s 三个人中，谁单程花在路上的时间最长？"
                     % (sel[0]["name"], sel[1]["name"], sel[2]["name"]),
                options=opts, answer=ai,
                explain="；".join("%s %d 分钟" % (p["name"], p["vals"]["commute"])
                                 for p in sel) + "。",
                uses=sorted(p["idx"]["commute"] for p in sel))
        out.append(mk_longest)

    # 3. 两人周收入比较
    with_income = [p for p in people if weekly_income(p) is not None]
    for i in range(len(with_income)):
        for j in range(i + 1, len(with_income)):
            a, b = with_income[i], with_income[j]
            ia, ib = weekly_income(a), weekly_income(b)
            if abs(ia - ib) < 1:
                continue

            def mk(a=a, b=b, ia=ia, ib=ib):
                hi, lo = (a, b) if ia > ib else (b, a)
                d = abs(ia - ib)
                opts, ai = build_choice(
                    rng,
                    "%s高 %s" % (hi["name"], fmt_money(d)),
                    ["%s高 %s" % (lo["name"], fmt_money(d)),
                     "%s高 %s" % (hi["name"], fmt_money(round(d / 2.0, 2))),
                     "%s高 %s" % (lo["name"], fmt_money(round(d * 2, 2))),
                     "两个人挣得一样多"])
                used = set(income_fact_idx(a)) | set(income_fact_idx(b))
                return dict(
                    text="一周下来，%s和%s谁挣得更多？多多少？" % (a["name"], b["name"]),
                    options=opts, answer=ai,
                    explain="%s 一周 %s；%s 一周 %s；相差 %s。"
                            % (a["name"], fmt_money(ia), b["name"], fmt_money(ib),
                               fmt_money(d)),
                    uses=sorted(used))
            out.append(mk)

    # 4. 住址配对
    homes = [p for p in people if "home" in p["idx"]]
    if len(homes) >= 3:
        def mk_match(homes=homes):
            sel = rng.sample(homes, 3)
            right = "，".join("%s-%s" % (p["name"], p["district"]) for p in sel)
            ds = [p["district"] for p in sel]
            w1 = "，".join(["%s-%s" % (sel[0]["name"], ds[1]),
                           "%s-%s" % (sel[1]["name"], ds[0]),
                           "%s-%s" % (sel[2]["name"], ds[2])])
            w2 = "，".join(["%s-%s" % (sel[0]["name"], ds[0]),
                           "%s-%s" % (sel[1]["name"], ds[2]),
                           "%s-%s" % (sel[2]["name"], ds[1])])
            w3 = "，".join(["%s-%s" % (sel[0]["name"], ds[2]),
                           "%s-%s" % (sel[1]["name"], ds[0]),
                           "%s-%s" % (sel[2]["name"], ds[1])])
            opts, ai = build_choice(rng, right, [w1, w2, w3])
            return dict(
                text="把「住的地方」和「人」对上号，下面哪一组全部正确？",
                options=opts, answer=ai,
                explain="正确对应：" + right + "。",
                uses=sorted(p["idx"]["home"] for p in sel))
        out.append(mk_match)

    # 5. 谁挣得最多
    if len(with_income) >= 3:
        def mk_top(with_income=with_income):
            sel = sorted(with_income, key=lambda p: -weekly_income(p))[:3]
            if abs(weekly_income(sel[0]) - weekly_income(sel[1])) < 1:
                return None
            opts, ai = build_choice(
                rng, sel[0]["name"],
                [sel[1]["name"], sel[2]["name"], "三个人挣得一样多"])
            used = set()
            for p in sel:
                used |= set(income_fact_idx(p))
            return dict(
                text="在%s、%s、%s 三个人里，谁一周挣得最多？"
                     % (sel[0]["name"], sel[1]["name"], sel[2]["name"]),
                options=opts, answer=ai,
                explain="；".join("%s %s" % (p["name"], fmt_money(weekly_income(p)))
                                 for p in sel) + "。",
                uses=sorted(used))
        out.append(mk_top)

    return out


def identity_questions(rng, people):
    """兜底题：只需要 1 条信息，保证永远能凑够题量。"""
    out = []
    for p in people:
        if "home" in p["idx"]:
            def mk(p=p):
                others = [q["district"] for q in people if q is not p]
                rng.shuffle(others)
                opts, ai = build_choice(rng, p["district"], others + DISTRICTS)
                return dict(text="%s住在哪里？" % p["name"], options=opts, answer=ai,
                            explain="%s住在%s。" % (p["name"], p["district"]),
                            uses=[p["idx"]["home"]])
            out.append(mk)
        if "job" in p["idx"] and p["role"]:
            def mk2(p=p):
                others = [q["role"] for q in people if q is not p and q["role"]]
                rng.shuffle(others)
                opts, ai = build_choice(
                    rng, p["role"],
                    others + ["消防员", "面包师", "花店老板", "程序员"])
                return dict(text="%s是做什么的？" % p["name"], options=opts, answer=ai,
                            explain="%s是%s。" % (p["name"], p["role"]),
                            uses=[p["idx"]["job"]])
            out.append(mk2)
    for key, label, attr in (("pet", "养了什么", "pet"), ("fear", "最怕什么", "fear"),
                             ("food", "最爱吃什么", "food"),
                             ("color", "最喜欢什么颜色", "color"),
                             ("season", "最喜欢哪个季节", "season")):
        for p in people:
            if key in p["idx"]:
                def mk3(p=p, key=key, label=label, attr=attr):
                    others = [q[attr] for q in people if q is not p]
                    rng.shuffle(others)
                    opts, ai = build_choice(rng, p[attr], others + POOLS[attr])
                    return dict(text="%s%s？" % (p["name"], label),
                                options=opts, answer=ai,
                                explain="信息里写着：%s" % p["facts"][
                                    [k for k, _ in p["facts"]].index(key)][1],
                                uses=[p["idx"][key]])
                out.append(mk3)
    return out


# --------------------------------------------------------------------------
# 主入口
# --------------------------------------------------------------------------

ARCHES = ["doctor", "cafe", "coach", "coder", "teacher", "courier",
          "driver", "streamer", "baker", "florist"]


def generate(names, n_infos=30, n_questions=15, seed=None):
    rng = random.Random(seed)
    names = [n.strip() for n in names if n and n.strip()]
    if not names:
        names = ["林岚", "周澈", "陈星", "苏禾", "顾言", "唐悦"]

    arches = ARCHES[:]
    rng.shuffle(arches)
    districts = DISTRICTS[:]
    rng.shuffle(districts)

    people = []
    for i, nm in enumerate(names):
        pool = {"hospital": rng.choice(HOSPITALS), "office": rng.choice(OFFICES)}
        people.append(make_person(rng, nm, arches[i % len(arches)],
                                  districts[i % len(districts)], pool))

    # 轮流从每个人身上取事实，直到凑够 n_infos 条
    infos, meta = [], []
    for p in people:
        p["idx"] = {}
    cursor, guard = 0, 0
    while len(infos) < n_infos and guard < n_infos * 20:
        guard += 1
        p = people[cursor % len(people)]
        cursor += 1
        k = len(p["idx"])
        if k >= len(p["facts"]):
            if all(len(q["idx"]) >= len(q["facts"]) for q in people):
                break
            continue
        key, text = p["facts"][k]
        infos.append(text)
        p["idx"][key] = len(infos)          # 1-based
        meta.append((p["name"], key))

    made = []
    seen_text = set()

    def emit(q):
        if not q:
            return
        if "_c" in q:
            opts, ai = build_options(rng, q.pop("_c"), q.pop("_w"), q.pop("_f"))
            q["options"], q["answer"] = opts, ai
        if q["text"] in seen_text:
            return
        seen_text.add(q["text"])
        made.append(q)

    person_bs = []
    for p in people:
        for needs, fn in person_questions(rng, p):
            if all(k in p["idx"] for k in needs):
                person_bs.append((p, needs, fn))
    rng.shuffle(person_bs)

    cross_bs = cross_questions(rng, people)
    rng.shuffle(cross_bs)

    # 目标：约 2/3 单人题 + 1/3 组合题，组合题优先保证有一定数量
    n_cross = min(len(cross_bs), max(3, n_questions // 3))
    for fn in cross_bs[:n_cross]:
        emit(fn())
    for p, needs, fn in person_bs:
        if len(made) >= n_questions:
            break
        emit(fn(p["idx"]))
    for fn in cross_bs[n_cross:]:
        if len(made) >= n_questions:
            break
        emit(fn())
    if len(made) < n_questions:
        idq = identity_questions(rng, people)
        rng.shuffle(idq)
        for fn in idq:
            if len(made) >= n_questions:
                break
            emit(fn())

    rng.shuffle(made)
    made = made[:n_questions]
    for i, q in enumerate(made):
        q["no"] = i + 1

    # 轮流取事实本身就不会连着，但顺序太规律（P1 P2 P3 P1 P2 P3…）容易被摸清，
    # 这里再随机穿插一次
    infos = arrange.interleave(infos[:n_infos], made, names, rng)

    return {
        "title": "随机生成 · %d 人局" % len(names),
        "source": "local",
        "players": names,
        "infos": infos,
        "questions": made,
        "cast": [{"name": p["name"], "role": p["role"], "district": p["district"]}
                 for p in people],
    }


if __name__ == "__main__":
    import json
    s = generate(["林岚", "周澈", "陈星", "苏禾", "顾言", "唐悦"])
    print(json.dumps(s, ensure_ascii=False, indent=2))
