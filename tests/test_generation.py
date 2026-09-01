# -*- coding: utf-8 -*-
"""Offline checks for the hybrid content-generation pipeline."""

import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

import server
from game import engine, gen_ai, gen_local
from game.modes import trivia


SAMPLE_NAMES = ["林岚", "周澈", "陈星", "苏禾", "顾言", "唐悦"]


class LocalGenerationTests(unittest.TestCase):
    def test_bundled_demo_set_loads(self):
        game_set = engine.load_default_set(shuffle=False)

        self.assertEqual(len(game_set["infos"]), 30)
        self.assertEqual(len(game_set["questions"]), 15)

    def test_local_generator_builds_a_complete_valid_set(self):
        game_set = gen_local.generate(
            SAMPLE_NAMES, n_infos=30, n_questions=15, seed=20260812)

        self.assertEqual(len(game_set["infos"]), 30)
        self.assertEqual(len(game_set["questions"]), 15)
        for number, question in enumerate(game_set["questions"], start=1):
            self.assertEqual(question["no"], number)
            self.assertEqual(len(question["options"]), 4)
            self.assertEqual(len(set(question["options"])), 4)
            self.assertIn(question["answer"], range(4))
            self.assertTrue(question["uses"])
            self.assertTrue(all(1 <= idx <= 30 for idx in question["uses"]))


class AIGuardrailTests(unittest.TestCase):
    def test_polish_rejects_changed_numbers_but_keeps_valid_rewrite(self):
        source = {
            "title": "本地题库",
            "source": "local",
            "infos": ["林岚每天跑 5 公里。", "周澈每天卖 20 杯咖啡。"],
            "questions": [],
        }
        model_output = json.dumps({
            "infos": [
                "林岚每天迎着风跑 6 公里。",
                "周澈每天能卖出整整 20 杯咖啡。",
            ]
        }, ensure_ascii=False)

        with mock.patch("game.gen_ai.chat", return_value=model_output):
            result = gen_ai.polish(source, ["林岚", "周澈"], api_key="test")

        self.assertEqual(result["infos"][0], source["infos"][0])
        self.assertEqual(result["infos"][1], "周澈每天能卖出整整 20 杯咖啡。")
        self.assertEqual(result["source"], "local+deepseek")


class GenerationRaceTests(unittest.TestCase):
    def test_finished_generation_cannot_overwrite_a_new_game(self):
        room = engine.Room("2468", engine.default_settings())
        old_started = threading.Event()
        release_old = threading.Event()

        old_set = {"title": "旧知识问答", "source": "test",
                   "infos": [], "questions": []}
        new_set = {"title": "新 Memory 题库", "source": "test",
                   "infos": [], "questions": []}

        def build_for_current_game(current_room):
            if current_room.game == "trivia":
                old_started.set()
                release_old.wait(1)
                return old_set, "旧玩法出题完成"
            return new_set, "新玩法出题完成"

        with mock.patch.object(engine.Room, "_build", build_for_current_game):
            room.act("switch_game", {"game": "trivia"})
            room.generate_async()
            self.assertTrue(old_started.wait(1))

            room.act("switch_game", {"game": "classic"})
            room.generate_async()
            deadline = time.time() + 1
            while room.gen["status"] == "running" and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(room.set["title"], "新 Memory 题库")

            release_old.set()
            time.sleep(0.1)

        self.assertEqual(room.game, "classic")
        self.assertEqual(room.set["title"], "新 Memory 题库")


class TriviaDifficultyTests(unittest.TestCase):
    def test_each_difficulty_has_an_enforceable_prompt_contract(self):
        easy = trivia.prompt_for(15, "综合", "简单")
        medium = trivia.prompt_for(15, "综合", "中等")
        hard = trivia.prompt_for(15, "综合", "困难")

        self.assertIn("多数普通成年人", easy)
        self.assertIn("一步联想", medium)
        self.assertIn("至少 60%", hard)
        self.assertIn("同一类别", hard)
        self.assertIn("禁止送分题", hard)
        self.assertIn("difficulty", hard)

    def test_hard_build_rejects_model_questions_below_hard_score(self):
        candidates = []
        for i, score in enumerate([1, 4, 5, 4], start=1):
            candidates.append({
                "text": "候选题 %d" % i,
                "options": ["选项 A", "选项 B", "选项 C", "选项 D"],
                "answer": 0,
                "explain": "可核验的答案依据。",
                "difficulty": score,
            })
        output = json.dumps({"questions": candidates}, ensure_ascii=False)
        room = mock.Mock(settings={
            "n_questions": 3,
            "topic": "历史",
            "level": "困难",
            "api_key": "test-key",
            "model": "test-model",
        })

        with mock.patch("game.modes.trivia.gen_ai.chat", return_value=output) as chat:
            game_set, _ = trivia.build(room)

        messages = chat.call_args.args[2]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("难度是硬性产品参数", messages[0]["content"])
        self.assertIn("至少 60%", messages[1]["content"])
        self.assertEqual(game_set["source"], "deepseek")
        self.assertTrue(game_set["difficulty_guaranteed"])
        self.assertEqual(len(game_set["questions"]), 3)
        self.assertTrue(all(q["difficulty"] >= 4
                            for q in game_set["questions"]))

    def test_trivia_fallback_discloses_that_difficulty_is_not_guaranteed(self):
        room = mock.Mock(settings={
            "n_questions": 3,
            "topic": "综合",
            "level": "困难",
            "api_key": "test-key",
            "model": "test-model",
        })

        with mock.patch("game.modes.trivia.gen_ai.chat",
                        side_effect=gen_ai.AIError("offline")):
            game_set, message = trivia.build(room)

        self.assertEqual(game_set["source"], "bank")
        self.assertFalse(game_set["difficulty_guaranteed"])
        self.assertIn("难度降级", game_set["title"])
        self.assertIn("未保证「困难」难度", message)


class ConfigurationTests(unittest.TestCase):
    def test_environment_overrides_local_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = os.path.join(directory, "config.json")
            with open(config_path, "w", encoding="utf-8") as stream:
                json.dump({
                    "port": 8000,
                    "deepseek_api_key": "local-value",
                    "open_browser": True,
                }, stream)

            env = {
                "DEEPSEEK_API_KEY": "environment-value",
                "DEEPSEEK_MODEL": "test-model",
                "BLOOD_GAME_PORT": "8137",
                "BLOOD_GAME_OPEN_BROWSER": "false",
            }
            with mock.patch.object(server, "CONFIG_PATH", config_path):
                with mock.patch.dict(os.environ, env, clear=False):
                    config = server.load_config()

        self.assertEqual(config["deepseek_api_key"], "environment-value")
        self.assertEqual(config["deepseek_model"], "test-model")
        self.assertEqual(config["port"], 8137)
        self.assertFalse(config["open_browser"])


if __name__ == "__main__":
    unittest.main()
