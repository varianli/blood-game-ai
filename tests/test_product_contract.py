# -*- coding: utf-8 -*-
"""面向用户的入口、命名与主持人大屏契约。"""

from html.parser import HTMLParser
import json
from pathlib import Path
import unittest

import server
from game import catalog, engine


ROOT = Path(__file__).resolve().parents[1]


class _IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.elements[values["id"]] = (tag, values)


class ProductContractTests(unittest.TestCase):
    def test_launcher_opens_game_hall(self):
        self.assertEqual(server.startup_url(8000), "http://localhost:8000/")

    def test_memory_30_uses_the_show_name_and_rules(self):
        game = catalog.BY_ID["classic"]
        self.assertEqual(game["name"], "Memory 30 · 标准")
        self.assertEqual(game["preset"]["n_infos"], 30)
        self.assertEqual(game["preset"]["n_questions"], 15)

    def test_memory_variants_form_a_clear_three_step_challenge(self):
        games = [g for g in catalog.GAMES if g.get("series") == "memory"]

        self.assertEqual(
            [g["name"] for g in games],
            ["Memory 12 · 闪电", "Memory 30 · 标准", "Memory 40 · 极限"],
        )
        self.assertEqual([g["tier"] for g in games], [1, 2, 3])
        self.assertEqual([g["tier_name"] for g in games], ["入门", "标准", "极限"])
        self.assertEqual([g["preset"]["n_infos"] for g in games], [12, 30, 40])

    def test_host_stage_has_an_accessible_live_ranking_region(self):
        html = (ROOT / "web" / "host.html").read_text(encoding="utf-8")
        parser = _IdCollector()
        parser.feed(html)

        tag, attrs = parser.elements["liveRanking"]
        self.assertEqual(tag, "aside")
        self.assertEqual(attrs.get("aria-live"), "polite")

    def test_live_ranking_is_refreshed_from_each_room_snapshot(self):
        script = (ROOT / "web" / "host.js").read_text(encoding="utf-8")
        render_body = script.split("function render()", 1)[1].split(
            "function nextTag", 1
        )[0]
        self.assertIn("renderLiveRanking(s);", render_body)
        self.assertIn("s.board", script)

    def test_game_hall_has_its_own_atmospheric_background(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
        self.assertIn('class="hub home-atmosphere"', html)
        self.assertIn(".home-atmosphere::before", css)
        self.assertIn(".home-atmosphere::after", css)

    def test_game_hall_groups_memory_modes_as_a_difficulty_staircase(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")

        self.assertIn('id="memorySeries"', html)
        self.assertIn("Memory 挑战阶梯", html)
        self.assertIn("function memoryCard", html)
        self.assertIn("g.tier", html)
        self.assertIn(".memory-series", css)
        self.assertIn(".difficulty-meter", css)

    def test_trivia_setup_exposes_difficulty_and_each_timed_phase(self):
        html = (ROOT / "web" / "host.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "host.js").read_text(encoding="utf-8")

        self.assertIn('id="level"', html)
        self.assertIn('id="timingTitle"', html)
        self.assertIn('id="triviaTimingFlow"', html)
        self.assertIn('id="question_sec"', html)
        self.assertIn('id="reveal_sec"', html)
        self.assertIn('id="board_sec"', html)
        self.assertIn("各环节时间", script)
        self.assertIn("kind === 'trivia'", script)

    def test_host_information_and_question_cards_have_corner_timers(self):
        script = (ROOT / "web" / "host.js").read_text(encoding="utf-8")
        briefing = script.split("function renderBriefing", 1)[1].split(
            "function ring", 1
        )[0]
        question = script.split("function renderQuestion", 1)[1].split(
            "function renderVoteAsk", 1
        )[0]

        self.assertIn('class="infocard timed-card"', briefing)
        self.assertIn("ring('rg', true)", briefing)
        self.assertIn('class="question-card timed-card"', question)
        self.assertIn("ring('rg', true)", question)

    def test_phone_information_and_question_cards_have_corner_timers(self):
        script = (ROOT / "web" / "player.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")

        self.assertIn('class="pinfo timed-card"', script)
        self.assertIn('class="phone-question-card timed-card"', script)
        self.assertIn("cornerTimer('prg')", script)
        self.assertIn(".ring-corner", css)
        self.assertIn("conic-gradient", css)

    def test_timer_ring_progress_is_driven_by_the_room_deadline(self):
        host = (ROOT / "web" / "host.js").read_text(encoding="utf-8")
        player = (ROOT / "web" / "player.js").read_text(encoding="utf-8")

        self.assertIn("setProperty('--timer-progress'", host)
        self.assertIn("setProperty('--timer-progress'", player)

    def test_windows_launcher_bootstraps_the_qr_dependency(self):
        launcher_path = ROOT / "启动.bat"
        launcher = launcher_path.read_text(encoding="ascii")

        self.assertIn(r".venv\Scripts\python.exe", launcher)
        self.assertIn('-c "import qrcode"', launcher)
        self.assertIn("-m pip install", launcher)
        self.assertIn("-r requirements.txt", launcher)

    def test_qr_failure_has_a_visible_fallback_instead_of_a_blank_box(self):
        script = (ROOT / "web" / "host.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")

        self.assertIn("function showQrUnavailable", script)
        self.assertIn("二维码暂时无法生成", script)
        self.assertIn(".qr-missing", css)

    def test_room_ai_settings_are_visible_for_every_game(self):
        html = (ROOT / "web" / "host.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "host.js").read_text(encoding="utf-8")
        parser = _IdCollector()
        parser.feed(html)

        self.assertIn("roomAiBox", parser.elements)
        self.assertIn("sourceBox", parser.elements)
        self.assertEqual(parser.elements["api_key"][1].get("type"), "password")
        self.assertIn("房间 AI 设置", html)
        self.assertIn("本房间所有 AI 玩法共用", html)
        self.assertIn("$('sourceBox').classList.toggle", script)
        self.assertIn("s.api_key_set", script)
        self.assertIn("saveRoomAi", script)

    def test_room_secret_is_shared_across_games_but_never_in_snapshots(self):
        secret = "sk-room-secret-must-not-leak"
        settings = engine.default_settings(api_key=secret, model="shared-model")
        room = engine.Room("2468", settings)

        room.act("switch_game", {"game": "trivia"})

        self.assertEqual(room.settings["api_key"], secret)
        self.assertEqual(room.settings["model"], "shared-model")
        host_snapshot = room.snapshot(is_host=True)
        player_snapshot = room.snapshot()
        self.assertTrue(host_snapshot["api_key_set"])
        self.assertNotIn("api_key", host_snapshot["settings"])
        self.assertNotIn("api_key_set", player_snapshot)
        self.assertNotIn(secret, json.dumps(host_snapshot, ensure_ascii=False))
        self.assertNotIn(secret, json.dumps(player_snapshot, ensure_ascii=False))

    def test_browser_storage_never_persists_the_api_key(self):
        script = (ROOT / "web" / "host.js").read_text(encoding="utf-8")
        start = script.index("localStorage.setItem('xzyx_host'")
        end = script.index("} catch", start)

        self.assertNotIn("api_key", script[start:end])

    def test_existing_room_memory_switch_waits_for_memory_configuration(self):
        script = (ROOT / "web" / "host.js").read_text(encoding="utf-8")

        self.assertIn("function isMemoryGame", script)
        switch = script.split("function switchToGame", 1)[1].split(
            "/* ---------------- 控制", 1
        )[0]
        self.assertIn("memoryDraft.open = needsMemorySetup", switch)
        self.assertIn("if (!needsMemorySetup) return act('generate');", switch)
        self.assertIn("switchToGame(gameId)", script)
        self.assertIn("switchToGame(sw.value)", script)

    def test_memory_lobby_panel_can_update_names_and_generation_mode(self):
        script = (ROOT / "web" / "host.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")

        panel = script.split("function memorySettingsPanel", 1)[1].split(
            "function captureMemoryDraft", 1
        )[0]
        self.assertIn('id="memorySettingsPanel"', panel)
        self.assertIn("memory-name-input", panel)
        self.assertIn('id="memoryGenerator"', panel)
        self.assertIn('id="memoryInfoCount"', panel)
        self.assertIn('id="memoryQuestionCount"', panel)
        self.assertIn('id="saveMemorySettings"', panel)
        self.assertNotIn("api_key", panel)
        self.assertIn("act('settings', payload)", script)
        self.assertIn("return act('generate');", script)
        self.assertIn(".memory-lobby-panel", css)

    def test_saving_a_new_room_api_key_activates_ai_for_memory(self):
        script = (ROOT / "web" / "host.js").read_text(encoding="utf-8")

        self.assertIn("memoryPayload.generator === 'local'", script)
        self.assertIn("memoryPayload.generator = 'ai'", script)

    def test_memory_start_exposes_and_saves_next_set_prefetch_option(self):
        script = (ROOT / "web" / "host.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")

        lobby = script.split("function renderLobby", 1)[1].split(
            "function renderBriefing", 1
        )[0]
        self.assertIn('id="prefetchNext"', lobby)
        self.assertIn("开局后后台生成下一套", lobby)
        self.assertIn("prefetch_next", lobby)
        self.assertIn("return act('start');", lobby)
        self.assertIn(".prefetch-toggle", css)

    def test_room_bounds_memory_names_and_rejects_unknown_generator(self):
        room = engine.Room("1357", engine.default_settings())
        original_generator = room.settings["generator"]
        names = ["  玩家%02d名字很长很长  " % i for i in range(25)]

        room.act("settings", {"names": names, "generator": "not-a-mode"})

        self.assertEqual(room.settings["generator"], original_generator)
        self.assertEqual(len(room.settings["names"]), 20)
        self.assertTrue(all(1 <= len(name) <= 12
                            for name in room.settings["names"]))


if __name__ == "__main__":
    unittest.main()
