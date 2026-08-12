# -*- coding: utf-8 -*-
"""Offline checks for the hybrid content-generation pipeline."""

import json
import os
import tempfile
import unittest
from unittest import mock

import server
from game import engine, gen_ai, gen_local


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
