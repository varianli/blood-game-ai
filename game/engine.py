# -*- coding: utf-8 -*-
"""房间状态机、计分、快照。

阶段流转：
  lobby → briefing（逐条闪信息）→ [question → reveal → scoreboard] × N → final
服务端持有唯一的时钟：所有倒计时都由 deadline（毫秒时间戳）驱动，
客户端只负责显示，避免各台手机计时不一致。
"""

import json
import random
import threading
import time
import uuid

from . import arrange, catalog, content, gen_ai, gen_local, modes

DEFAULT_SET_PATH = str(content.content_path("memory", "default_set.json"))

DEFAULT_NAMES = ["林岚", "周澈", "陈星", "苏禾", "顾言", "唐悦"]

_COND = threading.Condition()
ROOMS = {}


def now_ms():
    return int(time.time() * 1000)


def bump():
    """状态有变化 —— 叫醒所有长轮询的客户端。"""
    with _COND:
        _COND.notify_all()


def wait_change(timeout):
    with _COND:
        _COND.wait(timeout)


def load_default_set(shuffle=True):
    # utf-8-sig accepts both plain UTF-8 and editors that add a BOM.
    with open(DEFAULT_SET_PATH, "r", encoding="utf-8-sig") as f:
        s = json.load(f)
    for i, q in enumerate(s["questions"]):
        q["no"] = i + 1
    if shuffle:
        # 文件里是按人分块写的，方便手改；放给玩家之前打散
        s["infos"] = arrange.interleave(
            s["infos"], s["questions"], s.get("players") or DEFAULT_NAMES, random)
    return s


class Player(object):
    def __init__(self, pid, name):
        self.pid = pid
        self.name = name
        self.score = 0             # 本局（当前这个游戏）的分
        self.total = 0             # 整晚累计 —— 换游戏也不清零
        self.streak = 0
        self.gain = 0
        self.answers = {}          # q_index -> {"choice","correct","gain","ms"}
        self.extra = {}            # 各玩法自己用的临时状态
        self.seen = now_ms()

    def reset_round(self):
        self.score = 0
        self.streak = 0
        self.gain = 0
        self.answers = {}
        self.extra = {}

    @property
    def online(self):
        return now_ms() - self.seen < 20000


class Room(object):
    def __init__(self, code, settings):
        self.code = code
        self.host_key = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.version = 1
        self.players = {}          # pid -> Player
        self.order = []            # 加入顺序
        self.settings = settings
        self.set = None
        # 每次替换当前题库都会递增。客户端不能只看“第 1 题”，否则新题库的
        # 第 1 题会继承上一套第 1 题的本地选择或画板。
        self.set_rev = 0
        self.phase = "lobby"
        self.deadline = None
        self.phase_sec = 0
        self.paused = False
        self.pause_left = 0
        self.info_i = 0
        self.q_i = 0
        self.gen = {"status": "idle", "msg": ""}
        self.start_after_gen = False
        self.generation_rev = 0
        self.created = now_ms()
        self.game = "classic"           # 首页选的玩法
        self.game_name = ""
        self.banked = False             # 本局分是否已并入总分
        self.played = []                # 这个房间玩过的游戏名，按顺序
        self.flags = set()              # 各玩法用的一次性标记（比如「这题已结算」）
        # 你画我猜用：笔迹单独走一个轻量通道，不进房间快照
        self.strokes = []
        self.stroke_v = 0
        self.guesses = []
        self.drawer = None
        # 预生成的下一套题
        self.next_set = None
        self.next_msg = ""
        self.next_sig = None
        self.next_gen = {"status": "idle", "msg": ""}

    # ---------------- 内部 ----------------

    @property
    def kind(self):
        return catalog.engine_of(self.game)

    def touch(self):
        self.version += 1

    def set_phase(self, phase, seconds=None):
        self.phase = phase
        self.phase_sec = seconds or 0
        self.deadline = now_ms() + int(seconds * 1000) if seconds else None
        self.paused = False
        self.touch()

    def cur_q(self):
        if not self.set:
            return None
        qs = self.set["questions"]
        if 0 <= self.q_i < len(qs):
            return qs[self.q_i]
        return None

    # ---------------- 出题 ----------------

    def sig(self):
        """出题相关的设置指纹 —— 改了名单/模式，预生成的那套就作废。"""
        s = self.settings
        return (self.game, tuple(s.get("names") or ()), s.get("generator"),
                s.get("n_infos"), s.get("n_questions"), s.get("model"),
                s.get("topic"), s.get("level"),
                hash(s.get("api_key") or ""))

    def _build(self):
        """按当前设置造一套题，失败直接抛出去。"""
        m = modes.get(self.kind)
        if m:
            return m.build(self)
        s = self.settings
        names = s["names"] or DEFAULT_NAMES
        mode = s.get("generator", "local")
        if mode == "default":
            return load_default_set(), "使用内置默认题库"
        if mode == "ai":
            gs = gen_ai.generate_ai(names, s["n_infos"], s["n_questions"],
                                    api_key=s.get("api_key"),
                                    model=s.get("model"))
            return gs, "DeepSeek 出题成功"
        if mode == "polish":
            gs = gen_local.generate(names, s["n_infos"], s["n_questions"],
                                    seed=random.randrange(1 << 30))
            gs = gen_ai.polish(gs, names, api_key=s.get("api_key"),
                               model=s.get("model"))
            return gs, "本地出数值 + DeepSeek 润色（%d/%d 条改写）" % (
                gs.get("polish_kept", 0), len(gs["infos"]))
        gs = gen_local.generate(names, s["n_infos"], s["n_questions"],
                                seed=random.randrange(1 << 30))
        return gs, "本地综艺风格生成"

    def _apply(self, gs, msg, status="ok", start=False):
        """装上新题库并清零本局分数。调用前必须持有锁。"""
        self.set = gs
        self.set_rev += 1
        self.gen = {"status": status, "msg": msg}
        for p in self.players.values():
            p.reset_round()
        self.banked = False
        self.flags = set()
        self.info_i = 0
        self.q_i = 0
        if start:
            self.begin_play()
        else:
            self.touch()

    def _clear_next(self):
        """清空预生成槽位。调用前必须持有锁。"""
        self.next_set = None
        self.next_msg = ""
        self.next_sig = None
        self.next_gen = {"status": "idle", "msg": ""}

    def _take_next(self):
        """取出与当前设置匹配的下一套；过期内容直接丢弃。"""
        if self.next_set is None:
            return None
        if self.next_sig != self.sig():
            self._clear_next()
            return None
        prepared = self.next_set, self.next_msg
        self._clear_next()
        return prepared

    def _finish_prefetch(self, gs, msg, ready_msg="下一套题已就绪"):
        """保存后台题库；若主持人正在等待，则直接装载并自动开局。"""
        if self.start_after_gen:
            self.start_after_gen = False
            self._clear_next()
            self._apply(gs, msg + "（后台准备完成）", start=True)
            return True
        self.next_set, self.next_msg = gs, msg
        self.next_gen = {"status": "ok", "msg": ready_msg}
        return False

    def begin_play(self):
        """开局 —— 各玩法第一个阶段不一样。"""
        m = modes.get(self.kind)
        if m:
            m.start(self)
        else:
            self.set_phase("briefing", self.settings["info_sec"])

    def generate_async(self, start_after=False, force_fresh=False):
        with self.lock:
            if self.gen["status"] == "running":
                return
            # “开始下一局”可以接管后台缓存；“换一套题”必须重新生成并替换
            # 当前待开局题库，两个意图不能再共用同一条含糊路径。
            prepared = None if force_fresh else self._take_next()
            if prepared:
                gs, msg = prepared
                self._apply(gs, msg + "（提前出好的，秒开）", start=start_after)
                bump()
                return
            if force_fresh:
                self.start_after_gen = False
                self._clear_next()
            self.gen = {"status": "running", "msg": "正在出题…",
                        "since": now_ms()}
            self.start_after_gen = start_after
            self.generation_rev += 1
            generation_rev = self.generation_rev
            generation_sig = self.sig()
            self.touch()
        bump()
        threading.Thread(target=self._generate,
                         args=(generation_rev, generation_sig),
                         daemon=True).start()

    def _generate(self, generation_rev, generation_sig):
        try:
            gs, msg = self._build()
        except Exception as e:
            with self.lock:
                if (generation_rev != self.generation_rev or
                        generation_sig != self.sig()):
                    return
                self.start_after_gen = False
                self.gen = {
                    "status": "error",
                    "msg": ("❌ 出题失败：%s。未改用本地题库；请重试，"
                            "或由你主动选择本地出题。" % e),
                }
                # 保留当前已经确认过的题库；失败的请求不能偷偷替换它。
                self.touch()
            bump()
            return

        with self.lock:
            # 出题期间可能已经切换玩法或修改了出题设置。旧线程即使后来
            # 成功，也不能覆盖新玩法正在使用的题库与生成状态。
            if (generation_rev != self.generation_rev or
                    generation_sig != self.sig()):
                return
            start = self.start_after_gen
            self.start_after_gen = False
            self._apply(gs, msg, status="ok", start=start)
        bump()

    # ---------------- 预生成下一套 ----------------

    def prefetch_async(self):
        """开局后在后台把下一套题先出好，这样「再来一局」不用干等 DeepSeek。"""
        with self.lock:
            if (self.kind != catalog.DEDUCE or
                    not self.settings.get("prefetch_next", True)):
                return
            if self.next_gen.get("status") == "running" or self.next_set:
                return
            self.next_gen = {"status": "running", "msg": "正在预生成下一套…",
                             "since": now_ms()}
            self.next_sig = self.sig()
            self.touch()
        bump()
        threading.Thread(target=self._prefetch, daemon=True).start()

    def _prefetch(self):
        sig = self.next_sig
        started = False
        try:
            gs, msg = self._build()
            with self.lock:
                if (sig != self.sig() or     # 中途改了设置/关闭开关，这套作废
                        not self.settings.get("prefetch_next", True)):
                    self._clear_next()
                else:
                    started = self._finish_prefetch(gs, msg)
        except Exception as e:
            with self.lock:
                if (sig != self.sig() or
                        not self.settings.get("prefetch_next", True)):
                    self._clear_next()
                else:
                    self.start_after_gen = False
                    self.next_set = None
                    self.next_msg = ""
                    self.next_gen = {
                        "status": "error",
                        "msg": ("DeepSeek 预生成失败：%s。未改用本地题库；"
                                "下次开始时会重新尝试。" % e),
                    }
                    self.touch()
        bump()
        # B 已经自动开局后，继续在后台准备 C，下一局仍然不用等。
        if started:
            self.prefetch_async()

    # ---------------- 主持人操作 ----------------

    def act(self, action, payload=None):
        payload = payload or {}
        with self.lock:
            if action == "generate":
                self.generate_async(False)
                return
            if action == "regenerate":
                self.generate_async(False, force_fresh=True)
                return
            if action == "start":
                if self.gen["status"] == "running":
                    return
                # 从结算页回大厅后直接点「开始游戏」，也必须自动接管后台准备好的
                # 下一套；不能继续启动上一局的 self.set。
                prepared = self._take_next()
                if prepared:
                    gs, msg = prepared
                    self._apply(gs, msg + "（提前出好的，秒开）")
                elif self.banked:
                    if (self.next_gen.get("status") == "running" and
                            self.next_sig == self.sig()):
                        self.start_after_gen = True
                        self.next_gen["msg"] = "正在完成下一套，完成后自动开始…"
                        self.touch()
                        # 旧题已经结算，等后台的新题，绝不再次启动旧题。
                        return bump()
                    # 没有可接管的后台题库时，先生成一套全新的再自动开局。
                    self.generate_async(True)
                    return
                if not self.set:
                    self.generate_async(True)
                    return
                self.info_i = 0
                self.q_i = 0
                for p in self.players.values():
                    p.reset_round()
                self.banked = False
                self.begin_play()
                # 这一局开打了；主持人勾选后，后台把下一套先出好
                if self.settings.get("prefetch_next", True):
                    self.prefetch_async()
            elif action == "skip":
                # 大厅里「跳过」什么都不做，否则会把刚退出来的游戏又拉起来
                if self.phase != "lobby":
                    self.advance(forced=True)
            elif action == "prev_info" and self.phase == "briefing":
                self.info_i = max(0, self.info_i - 1)
                self.set_phase("briefing", self.settings["info_sec"])
            elif action == "skip_briefing" and self.phase == "briefing":
                self.begin_question(0)
            elif action == "pause":
                if self.deadline and not self.paused:
                    self.pause_left = max(0, self.deadline - now_ms())
                    self.paused = True
                    self.deadline = None
                    self.touch()
            elif action == "resume":
                if self.paused:
                    self.deadline = now_ms() + self.pause_left
                    self.paused = False
                    self.touch()
            elif action == "lobby":
                self.set_phase("lobby")
            elif action == "settings":
                old_sig = self.sig()
                for k in ("info_sec", "question_sec", "reveal_sec", "board_sec",
                          "describe_sec"):
                    if k in payload:
                        self.settings[k] = max(1, min(600, int(payload[k])))
                for k in ("topic", "level"):
                    if payload.get(k):
                        self.settings[k] = str(payload[k])[:20]
                if "names" in payload and isinstance(payload["names"], (list, tuple)):
                    names = []
                    for value in payload["names"][:20]:
                        name = str(value).strip()[:12]
                        if name:
                            names.append(name)
                    if names:
                        self.settings["names"] = names
                for k in ("n_infos", "n_questions"):
                    if k in payload:
                        self.settings[k] = max(3, min(80, int(payload[k])))
                if payload.get("generator") in ("local", "polish", "ai", "default"):
                    self.settings["generator"] = payload["generator"]
                if "auto" in payload:
                    self.settings["auto"] = bool(payload["auto"])
                if "prefetch_next" in payload:
                    self.settings["prefetch_next"] = bool(payload["prefetch_next"])
                    if not self.settings["prefetch_next"]:
                        self.start_after_gen = False
                        self._clear_next()
                if payload.get("api_key"):
                    self.settings["api_key"] = str(payload["api_key"]).strip()[:512]
                if payload.get("model"):
                    self.settings["model"] = str(payload["model"]).strip()[:100]
                if self.sig() != old_sig:
                    self.generation_rev += 1
                    self.start_after_gen = False
                    self._clear_next()
                    if self.gen.get("status") == "running":
                        self.gen = {"status": "idle", "msg": ""}
                self.touch()
            elif action == "switch_game":
                gid = str(payload.get("game") or "")
                if gid in catalog.BY_ID:
                    self.generation_rev += 1
                    self.start_after_gen = False
                    # 换游戏但留住玩家和总分：先把没结算的本局分收进总分
                    if not self.banked and self.set:
                        for p in self.players.values():
                            p.total += p.score
                        self.banked = True
                    if self.game_name and self.game_name not in self.played:
                        self.played.append(self.game_name)
                    self.game = gid
                    self.game_name = catalog.name_of(gid)
                    self.settings.update(catalog.preset_of(gid))
                    self.set = None
                    self.set_rev += 1
                    self._clear_next()
                    self.gen = {"status": "idle", "msg": ""}
                    for p in self.players.values():
                        p.reset_round()
                    self.banked = False
                    self.set_phase("lobby")
            elif action == "judge":
                m = modes.get(self.kind)
                if m and hasattr(m, "judge_by_host"):
                    m.judge_by_host(self, payload.get("guess_id"))
            elif action == "kick":
                pid = payload.get("pid")
                if pid in self.players:
                    del self.players[pid]
                    self.order = [x for x in self.order if x != pid]
                    self.touch()
        bump()

    # ---------------- 阶段推进 ----------------

    def begin_question(self, i):
        self.q_i = i
        for p in self.players.values():
            p.gain = 0
        self.set_phase("question", self.settings["question_sec"])

    def finish(self):
        """一局结束：把本局分并进整晚总分，之后换游戏也不会清零。"""
        if not self.banked:
            for p in self.players.values():
                p.total += p.score
            self.banked = True
        self.set_phase("final")

    def advance(self, forced=False):
        """deadline 到点（或主持人点了跳过）时前进一步。"""
        m = modes.get(self.kind)
        if m:
            return m.advance(self, forced)
        s = self.settings
        if self.phase == "briefing":
            self.info_i += 1
            if self.info_i >= len(self.set["infos"]):
                self.begin_question(0)
            else:
                self.set_phase("briefing", s["info_sec"])
        elif self.phase == "question":
            self.set_phase("reveal", s["reveal_sec"])
        elif self.phase == "reveal":
            # 手动模式下排行榜不设 deadline，一直等主持人点「下一题」
            auto = s.get("auto", True)
            self.set_phase("scoreboard", s["board_sec"] if auto else None)
        elif self.phase == "scoreboard":
            if self.q_i + 1 >= len(self.set["questions"]):
                self.finish()
            else:
                self.begin_question(self.q_i + 1)
        elif self.phase == "final":
            self.set_phase("lobby")

    def strokes_since(self, since):
        """画布增量 —— 画画时一秒好几十笔，不能走 version 那条路。"""
        with self.lock:
            since = max(0, min(int(since or 0), len(self.strokes)))
            return {"v": self.stroke_v, "n": len(self.strokes),
                    "strokes": self.strokes[since:],
                    "cleared": since > len(self.strokes)}

    def extra_flag(self, key):
        return key in self.flags

    def mark_flag(self, key):
        self.flags.add(key)

    def tick(self):
        with self.lock:
            if self.paused or not self.deadline or not self.set:
                return False
            if now_ms() >= self.deadline:
                self.advance()
                return True
        return False

    # ---------------- 玩家 ----------------

    def join(self, name, pid=None):
        with self.lock:
            if pid and pid in self.players:
                p = self.players[pid]
                if name:
                    p.name = name
                p.seen = now_ms()
                self.touch()
                bump()
                return p

            base = (name or "玩家").strip()[:12] or "玩家"
            # 手机换了浏览器 / localStorage 被清掉时，pid 对不上。
            # 这时如果有个同名的人已经掉线，就认定是他回来了，直接接管，
            # 分数和连对都保留 —— 否则他只能改名重来，还丢了分。
            for p in self.players.values():
                if p.name == base and not p.online:
                    p.seen = now_ms()
                    self.touch()
                    bump()
                    return p

            pid = pid or uuid.uuid4().hex
            taken = {q.name for q in self.players.values()}
            nm, k = base, 2
            while nm in taken:
                nm = "%s%d" % (base, k)
                k += 1
            p = Player(pid, nm)
            self.players[pid] = p
            self.order.append(pid)
            self.touch()
        bump()
        return p

    def score_choice(self, p, q_index, choice):
        """四选一的计分 —— 血之游戏和知识抢答共用。调用方负责加锁。"""
        q = self.cur_q()
        if not p or not q or self.phase != "question":
            return
        if q_index != self.q_i or self.q_i in p.answers:
            return
        if not isinstance(choice, int) or not (0 <= choice < 4):
            return
        left = max(0, (self.deadline or now_ms()) - now_ms())
        total = max(1, self.settings["question_sec"] * 1000)
        correct = (choice == q["answer"])
        if correct:
            p.streak += 1
            gain = 600 + int(round(400.0 * min(1.0, left / float(total))))
            gain += min(300, 100 * (p.streak - 1))
        else:
            p.streak = 0
            gain = 0
        p.score += gain
        p.gain = gain
        p.answers[self.q_i] = {"choice": choice, "correct": correct,
                               "gain": gain, "left": left}
        p.seen = now_ms()
        self.touch()

        # 全员作答完毕 → 提前揭晓，不用干等倒计时
        if self.players and all(self.q_i in q2.answers
                                for q2 in self.players.values()):
            self.set_phase("reveal", self.settings["reveal_sec"])

    def answer(self, pid, q_index, choice):
        with self.lock:
            m = modes.get(self.kind)
            p = self.players.get(pid)
            if not p:
                return
            if m:
                m.submit(self, p, {"q": q_index, "choice": choice})
            else:
                self.score_choice(p, q_index, choice)
        bump()

    def submit(self, pid, payload):
        """通用提交入口：投票、猜词、笔画都走这里。"""
        with self.lock:
            m = modes.get(self.kind)
            p = self.players.get(pid)
            if not p:
                return
            if m:
                m.submit(self, p, payload or {})
            elif "choice" in (payload or {}):
                self.score_choice(p, payload.get("q"), payload.get("choice"))
        bump()

    # ---------------- 快照 ----------------

    def ranking(self, by_total=False):
        """by_total=True 时按整晚总分排（总分 = 已结算的 total + 本局还没结算的 score）。"""
        def val(p):
            return p.total + (0 if self.banked else p.score) if by_total else p.score

        ps = sorted(self.players.values(),
                    key=lambda p: (-val(p), self.order.index(p.pid)))
        out, rank, prev = [], 0, None
        for i, p in enumerate(ps):
            v = val(p)
            if v != prev:
                rank = i + 1
                prev = v
            out.append({"pid": p.pid, "name": p.name, "score": p.score,
                        "total": p.total + (0 if self.banked else p.score),
                        "value": v, "gain": p.gain, "rank": rank,
                        "online": p.online, "streak": p.streak})
        return out

    def fill_choice_snapshot(self, snap, pid):
        """四选一玩法的题面 / 揭晓数据 —— 血之游戏和知识抢答共用。"""
        q = self.cur_q()
        if not q or self.phase not in ("question", "reveal"):
            return
        answered = sum(1 for p in self.players.values()
                       if self.q_i in p.answers)
        snap["q"] = {"no": self.q_i + 1,
                     "total": len(self.set["questions"]),
                     "text": q["text"], "options": q["options"],
                     "answered": answered}
        if self.phase == "reveal":
            counts = [0, 0, 0, 0]
            for p in self.players.values():
                a = p.answers.get(self.q_i)
                if a:
                    counts[a["choice"]] += 1
            infos = self.set.get("infos") or []
            snap["reveal"] = {
                "answer": q["answer"],
                "explain": q.get("explain", ""),
                "counts": counts,
                "uses": q.get("uses", []),
                "uses_texts": [infos[u - 1] for u in q.get("uses", [])
                               if 1 <= u <= len(infos)],
            }

    def snapshot(self, pid=None, is_host=False):
        with self.lock:
            s = self.settings
            board = self.ranking()
            total_board = self.ranking(by_total=True)
            snap = {
                "v": self.version,
                "room": self.code,
                "game": self.game,
                "game_name": self.game_name,
                "kind": self.kind,
                "phase": self.phase,
                "now": now_ms(),
                "deadline": self.deadline,
                "phase_sec": self.phase_sec,
                "paused": self.paused,
                "gen": self.gen,
                "next_gen": self.next_gen,
                "next_ready": self.next_set is not None,
                "set_rev": self.set_rev,
                "start_pending": bool(
                    self.start_after_gen and
                    self.next_gen.get("status") == "running"),
                "board": board,
                "total_board": total_board,
                "played": self.played,
                "count": len(self.players),
                "settings": {k: s[k] for k in
                             ("info_sec", "question_sec", "reveal_sec",
                              "board_sec", "n_infos", "n_questions",
                              "generator", "auto", "prefetch_next", "names", "model",
                             "describe_sec", "topic", "level")
                             if k in s},
                "has_set": bool(self.set),
                "set_title": (self.set or {}).get("title", ""),
                "set_source": (self.set or {}).get("source", ""),
                "difficulty_guaranteed":
                    (self.set or {}).get("difficulty_guaranteed"),
                "n_info_total": len((self.set or {}).get("infos", [])),
                "n_q_total": len((self.set or {}).get("questions", [])),
            }
            if is_host:
                snap["host"] = True
                snap["api_key_set"] = bool(s.get("api_key"))

            if self.set and self.phase == "briefing":
                infos = self.set["infos"]
                i = min(self.info_i, len(infos) - 1)
                snap["info"] = {"i": i + 1, "total": len(infos), "text": infos[i]}

            if self.phase == "scoreboard" and self.set:
                snap["q_done"] = self.q_i + 1
                snap["q_left"] = len(self.set["questions"]) - self.q_i - 1

            if pid and pid in self.players:
                p = self.players[pid]
                p.seen = now_ms()
                me = next((b for b in board if b["pid"] == pid), None)
                a = p.answers.get(self.q_i)
                snap["you"] = {
                    "pid": pid, "name": p.name, "score": p.score,
                    "rank": me["rank"] if me else 0,
                    "gain": p.gain, "streak": p.streak,
                    # 各玩法存的作答记录结构不同（选项 / 投票 / 猜词），这里都用 get
                    "choice": a.get("choice") if a else None,
                    "correct": a.get("correct") if a else None,
                }
            else:
                snap["you"] = None

            # 玩法专属数据放最后填 —— 有些玩法要往 snap["you"] 里补东西
            m = modes.get(self.kind)
            if m:
                m.snapshot(self, snap, pid, is_host)
            else:
                self.fill_choice_snapshot(snap, pid)
            if snap.get("you") is None:
                snap.pop("you", None)
            return snap


# --------------------------------------------------------------------------

def default_settings(api_key="", model=gen_ai.DEFAULT_MODEL):
    return {"info_sec": 8, "question_sec": 20, "reveal_sec": 6, "board_sec": 6,
            "n_infos": 30, "n_questions": 15, "generator": "local",
            "auto": True, "prefetch_next": True, "names": list(DEFAULT_NAMES),
            "api_key": api_key, "model": model}


def create_room(settings):
    with _COND:
        for _ in range(200):
            code = "%04d" % random.randint(1000, 9999)
            if code not in ROOMS:
                break
        else:
            code = uuid.uuid4().hex[:4].upper()
        r = Room(code, settings)
        ROOMS[code] = r
        # 清理超过 12 小时的空房间
        cutoff = now_ms() - 12 * 3600 * 1000
        for c in [c for c, x in ROOMS.items()
                  if x.created < cutoff and not x.players]:
            if c != code:
                del ROOMS[c]
    bump()
    return r


def get_room(code):
    return ROOMS.get((code or "").strip().upper()) or \
        ROOMS.get((code or "").strip())


def ticker():
    while True:
        changed = False
        for r in list(ROOMS.values()):
            try:
                if r.tick():
                    changed = True
            except Exception:
                pass
        if changed:
            bump()
        time.sleep(0.12)


def start_ticker():
    threading.Thread(target=ticker, daemon=True).start()
