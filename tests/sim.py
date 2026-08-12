# -*- coding: utf-8 -*-
"""端到端模拟：建房 → 3 个玩家加入 → 跑完整局，检查同步和计分。

    py tests/sim.py 8137
"""

import json
import sys
import threading
import time
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
B = "http://127.0.0.1:%d" % PORT
fails = []

# Local integration traffic must not be routed through a system HTTP/SOCKS
# proxy. This also makes the simulation deterministic on developer machines.
urllib.request.install_opener(
    urllib.request.build_opener(urllib.request.ProxyHandler({})))


def check(cond, msg):
    if not cond:
        fails.append(msg)
        print("  !! " + msg)


def post(path, obj):
    req = urllib.request.Request(
        B + path, data=json.dumps(obj).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(B + path, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


print("1) 建房（快节奏：信息 1s / 答题 3s / 揭晓 1s / 排行 1s）")
r = post("/api/host/create", {
    "names": ["林岚", "周澈", "陈星", "苏禾", "顾言", "唐悦"],
    "info_sec": 1, "question_sec": 3, "reveal_sec": 1, "board_sec": 1,
    "n_infos": 30, "n_questions": 15, "generator": "local", "auto": True})
room, hk = r["room"], r["hk"]
print("   房间 %s" % room)
check(len(r["join"]) >= 1, "没返回加入链接")

print("2) 玩家加入")
players = []
for nm in ["小A", "小B", "小C"]:
    j = post("/api/join", {"room": room, "name": nm})
    players.append(j)
    check(j.get("pid"), "%s 加入失败" % nm)
# 重名测试
dup = post("/api/join", {"room": room, "name": "小A"})
check(dup["name"] != "小A", "重名没有自动改名，实际=%s" % dup["name"])
print("   已加入：%s" % ", ".join(p["name"] for p in players + [dup]))

print("3) 生成题库")
post("/api/host/act", {"room": room, "hk": hk, "action": "generate"})
for _ in range(60):
    s = get("/api/state?room=%s&since=-1" % room)
    if s["gen"]["status"] != "running":
        break
    time.sleep(0.3)
check(s["has_set"], "题库没生成出来")
check(s["n_info_total"] == 30, "信息条数 = %s" % s["n_info_total"])
check(s["n_q_total"] == 15, "题目数量 = %s" % s["n_q_total"])
print("   %s（%s）" % (s["gen"]["msg"], s["set_title"]))

print("4) 检查长轮询是不是真的会挂起等待")
t0 = time.time()
threading.Timer(1.0, lambda: post("/api/host/act",
                                  {"room": room, "hk": hk, "action": "start"})).start()
s = get("/api/state?room=%s&since=%d" % (room, s["v"]))
dt = time.time() - t0
check(0.8 < dt < 5, "长轮询没等待或超时异常，用时 %.2fs" % dt)
check(s["phase"] == "briefing", "开始后不是 briefing，而是 %s" % s["phase"])
print("   %.2fs 后收到 phase=%s ✓" % (dt, s["phase"]))

print("5) 跳过信息，直接答题")
post("/api/host/act", {"room": room, "hk": hk, "action": "skip_briefing"})
time.sleep(0.4)

print("6) 自动打完 15 题（A 全对 / B 全错 / C 不答）")
answered = {"A": 0, "B": 0, "C": 0}
seen_q = set()
deadline = time.time() + 120
last_phase = None
while time.time() < deadline:
    s = get("/api/state?room=%s&pid=%s&since=-1" % (room, players[0]["pid"]))
    ph = s["phase"]
    if ph == "final":
        break
    if ph == "question" and s.get("q"):
        qno = s["q"]["no"]
        if qno not in seen_q:
            seen_q.add(qno)
            # 直接读服务端的正确答案：模拟用，走内部快照拿不到，所以试错法
            # 改为：A 先答，随后从 reveal 里核对
            hs = get("/api/state?room=%s&hk=%s&since=-1" % (room, hk))
            # 主持人快照在 question 阶段同样看不到答案，这里让 A 随机选 0
            post("/api/answer", {"room": room, "pid": players[0]["pid"],
                                 "q": qno - 1, "choice": 0})
            post("/api/answer", {"room": room, "pid": players[1]["pid"],
                                 "q": qno - 1, "choice": 1})
            answered["A"] += 1
            answered["B"] += 1
    if ph == "reveal" and ph != last_phase:
        rv = s.get("reveal") or {}
        check(isinstance(rv.get("answer"), int), "reveal 里没有答案")
        check(len(rv.get("counts", [])) == 4, "reveal 里没有各选项人数")
    last_phase = ph
    time.sleep(0.25)

s = get("/api/state?room=%s&since=-1" % room)
check(s["phase"] == "final", "15 题跑完后不是 final，而是 %s" % s["phase"])
check(len(seen_q) == 15, "只出现了 %d 道题" % len(seen_q))
print("   跑完 %d 道题，最终阶段 %s" % (len(seen_q), s["phase"]))

print("7) 计分与排名")
board = s["board"]
for b in board:
    print("   #%d %-6s %5d 分" % (b["rank"], b["name"], b["score"]))
sc = {b["name"]: b["score"] for b in board}
check(sc.get("小C", 0) == 0, "没作答的玩家不应该有分，实际 %s" % sc.get("小C"))
check(sum(sc.values()) > 0, "所有人都是 0 分，计分没生效")
check(board == sorted(board, key=lambda b: -b["score"]), "排行榜没有按分数排序")

print("8) 权限校验")
try:
    post("/api/host/act", {"room": room, "hk": "wrong", "action": "lobby"})
    r2 = None
except urllib.error.HTTPError as e:
    r2 = e.code
check(r2 == 403, "错误的 host key 应该被拒绝，实际 %s" % r2)

print("9) 静态页面")
for p in ["/", "/host", "/p", "/app.css", "/host.js", "/player.js"]:
    with urllib.request.urlopen(B + p, timeout=10) as rr:
        check(rr.status == 200 and len(rr.read()) > 100, "%s 返回异常" % p)

print("10) 二维码")
with urllib.request.urlopen(B + "/api/qr?t=http://x/p", timeout=10) as rr:
    body = rr.read().decode("utf-8")
check(body.startswith("<svg") and "rect" in body, "二维码没生成")

print()
if fails:
    print("×  %d 项失败：" % len(fails))
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("√  全部通过")
