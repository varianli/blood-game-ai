# -*- coding: utf-8 -*-
"""Offline checks for the hybrid content-generation pipeline."""

import json
import os
from pathlib import Path
import random
import tempfile
import threading
import time
import unittest
from unittest import mock

import server
from game import arrange, engine, gen_ai, gen_local
from game.modes import draw, trivia, undercover, vote


SAMPLE_NAMES = ["林岚", "周澈", "陈星", "苏禾", "顾言", "唐悦"]


class LocalGenerationTests(unittest.TestCase):
    def test_each_game_can_build_from_its_organized_runtime_content(self):
        expected_kinds = {
            "blitz": None,
            "classic": None,
            "hardcore": None,
            "trivia": trivia,
            "mostlikely": vote,
            "undercover": undercover,
            "draw": draw,
        }

        for game_id, mode in expected_kinds.items():
            with self.subTest(game=game_id):
                room = engine.Room("2468", engine.default_settings())
                room.game = game_id
                room.settings.update(engine.catalog.preset_of(game_id))
                game_set, _message = room._build()

                self.assertTrue(game_set["questions"])
                self.assertEqual(
                    len(game_set["questions"]), room.settings["n_questions"])
                if mode is not None:
                    self.assertIn(game_set["source"], ("deepseek", "bank"))

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

    def test_local_cards_mix_topics_instead_of_grouping_one_template(self):
        game_set = gen_local.generate(
            SAMPLE_NAMES, n_infos=30, n_questions=15, seed=20260901)

        topics = game_set["info_topics"]
        self.assertGreaterEqual(len(set(topics)), 5)
        self.assertTrue(all(a != b for a, b in zip(topics, topics[1:])))
        for window_start in range(len(topics) - 3):
            self.assertGreaterEqual(
                len(set(topics[window_start:window_start + 4])), 3)
        types = [question["type"] for question in game_set["questions"]]
        self.assertLessEqual(types.count("calculate"), 2)
        self.assertGreaterEqual(types.count("logic"), 3)
        self.assertGreaterEqual(types.count("transform"), 3)

    def test_local_opening_uses_distinct_content_families_and_standalone_cards(self):
        for seed in range(8):
            game_set = gen_local.generate(
                SAMPLE_NAMES, n_infos=30, n_questions=15, seed=seed)
            families = game_set["info_families"]

            self.assertEqual(len(families), 30)
            for index, family in enumerate(families):
                self.assertNotIn(family, families[max(0, index - 3):index])
            self.assertLessEqual(families.count("通勤"), 1)
            self.assertLessEqual(families.count("饮品习惯"), 2)
            standalone = sum(
                not any(text.startswith(name) for name in SAMPLE_NAMES)
                for text in game_set["infos"])
            self.assertGreaterEqual(standalone, 8)
            opening_standalone = sum(
                not any(text.startswith(name) for name in SAMPLE_NAMES)
                for text in game_set["infos"][:12])
            self.assertGreaterEqual(opening_standalone, 3)


class AIGuardrailTests(unittest.TestCase):
    def test_quality_first_chat_uses_pro_max_thinking_and_full_output_budget(self):
        payload = {
            "choices": [{
                "message": {"content": '{"ok": true}'},
                "finish_reason": "stop",
            }],
        }

        class FakeResponse(object):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        with mock.patch("game.gen_ai.urllib.request.urlopen",
                        return_value=FakeResponse()) as urlopen:
            result = gen_ai.chat(
                "test-key", None,
                [{"role": "user", "content": "生成一套题"}],
            )

        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(result, '{"ok": true}')
        self.assertEqual(body["model"], "deepseek-v4-pro")
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertEqual(body["reasoning_effort"], "max")
        self.assertEqual(body["max_tokens"], 384000)
        self.assertNotIn("temperature", body)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 900)

    def test_quality_first_chat_retries_a_truncated_reasoning_response(self):
        truncated = {
            "choices": [{
                "message": {"content": ""},
                "finish_reason": "length",
            }],
            "usage": {
                "completion_tokens_details": {"reasoning_tokens": 383999},
            },
        }
        completed = {
            "choices": [{
                "message": {"content": '{"questions": []}'},
                "finish_reason": "stop",
            }],
        }

        class FakeResponse(object):
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        responses = [FakeResponse(truncated), FakeResponse(completed)]
        with mock.patch("game.gen_ai.urllib.request.urlopen",
                        side_effect=responses) as urlopen:
            result = gen_ai.chat(
                "test-key", None,
                [{"role": "user", "content": "生成一套题"}],
            )

        self.assertEqual(result, '{"questions": []}')
        self.assertEqual(urlopen.call_count, 2)

    def test_quality_first_chat_recovers_from_deepseek_empty_json_content(self):
        empty = {
            "choices": [{
                "message": {"content": "", "reasoning_content": "hidden"},
                "finish_reason": "stop",
            }],
            "usage": {
                "completion_tokens_details": {"reasoning_tokens": 24680},
            },
        }
        completed = {
            "choices": [{
                "message": {"content": '{"questions": []}'},
                "finish_reason": "stop",
            }],
        }

        class FakeResponse(object):
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(self.payload).encode("utf-8")

        responses = [FakeResponse(empty), FakeResponse(completed)]
        with mock.patch("game.gen_ai.urllib.request.urlopen",
                        side_effect=responses) as urlopen:
            result = gen_ai.chat(
                "test-key", None,
                [{"role": "user", "content": "生成一套 JSON 题库"}],
            )

        first_request = json.loads(
            urlopen.call_args_list[0].args[0].data.decode("utf-8"))
        recovery_request = json.loads(
            urlopen.call_args_list[1].args[0].data.decode("utf-8"))
        self.assertEqual(result, '{"questions": []}')
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(first_request["response_format"],
                         {"type": "json_object"})
        self.assertNotIn("response_format", recovery_request)
        self.assertEqual(recovery_request["thinking"], {"type": "enabled"})
        self.assertEqual(recovery_request["reasoning_effort"], "max")
        self.assertEqual(recovery_request["max_tokens"], 384000)
        self.assertIn("完整、非空的 JSON",
                      recovery_request["messages"][-1]["content"])

    def test_quality_first_chat_reports_metadata_after_two_empty_responses(self):
        empty = {
            "choices": [{
                "message": {"content": "", "reasoning_content": "hidden"},
                "finish_reason": "stop",
            }],
            "usage": {
                "completion_tokens_details": {"reasoning_tokens": 13579},
            },
        }

        class FakeResponse(object):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(empty).encode("utf-8")

        with mock.patch("game.gen_ai.urllib.request.urlopen",
                        side_effect=[FakeResponse(), FakeResponse()]):
            with self.assertRaisesRegex(
                    gen_ai.AIError,
                    "连续两次.*finish_reason=stop.*reasoning_tokens=13579"):
                gen_ai.chat(
                    "test-key", None,
                    [{"role": "user", "content": "生成一套 JSON 题库"}],
                )

    def test_prompt_is_built_from_the_repository_style_guide(self):
        guide = Path(gen_ai.STYLE_GUIDE_PATH).read_text(encoding="utf-8")
        prompt = gen_ai.build_prompt(SAMPLE_NAMES, 30, 15)

        self.assertIn("同一内容家族不得连续出现", guide)
        self.assertIn("同一内容家族不得连续出现", prompt)

    def test_prompt_uses_memory_30_style_mix_and_caps_arithmetic(self):
        self.assertIn("任意连续 4 条", gen_ai.PROMPT)
        self.assertIn("纯算术最多", gen_ai.PROMPT)
        self.assertIn('"topic"', gen_ai.PROMPT)
        self.assertIn('"type"', gen_ai.PROMPT)
        self.assertNotIn("至少一半必须组合 2 条以上", gen_ai.PROMPT)

    def test_validate_rejects_commute_variants_disguised_as_different_topics(self):
        cards = [
            ("林岚坐地铁到公司要 30 分钟。", "地点关系", "乘地铁上班"),
            ("蓝色三角形。", "物品视觉", "蓝色图形"),
            ("短码是 M7Q4。", "代码序列", "字母短码"),
            ("周澈骑自行车上班花费 20 分钟。", "价格数量", "骑车计时"),
            ("本月第二个星期四是开放日。", "日期事件", "开放日期"),
            ("林岚在银行工作。", "人物身份", "银行职业"),
            ("周澈养了一只柯基。", "趣味偏好", "宠物偏好"),
            ("陈星住在浦东。", "地点关系", "居住地点"),
            ("陈星开车从家去单位耗时 15 分钟。", "日期事件", "驾车耗时"),
            ("菜单上柚子茶卖 18 元。", "价格数量", "菜单价格"),
            ("苏禾戴着紫色帽子。", "物品视觉", "帽子颜色"),
            ("唐悦每周五去攀岩。", "日期事件", "固定活动"),
        ]
        infos = [
            {"text": text, "topic": topic, "person": "",
             "template": template, "dependency_group": ""}
            for text, topic, template in cards
        ]
        questions = []
        for index in range(8):
            qtype = ("logic" if index in (2, 5) else
                     "calculate" if index == 6 else
                     "transform" if index in (1, 4) else "recall")
            questions.append({
                "text": ("两条信息合计是多少？" if qtype == "calculate"
                         else "测试题 %d" % index),
                "options": ["甲", "乙", "丙", "丁"],
                "answer": index % 4,
                "explain": ("1+1=2" if qtype == "calculate"
                            else "依据已展示的信息。"),
                "uses": [index + 1, index + 2]
                        if qtype in ("logic", "calculate") else [index + 1],
                "type": qtype,
            })

        with self.assertRaisesRegex(gen_ai.AIError, "内容家族.*通勤"):
            gen_ai.validate(
                {"infos": infos, "questions": questions},
                n_infos=12,
                n_questions=8,
                names=SAMPLE_NAMES,
            )

    def test_validate_rejects_name_swapped_repeated_templates(self):
        infos = []
        for i in range(12):
            name = SAMPLE_NAMES[i % len(SAMPLE_NAMES)]
            verb = "要" if i % 2 else "需要"
            infos.append("%s去上班%s %d 分钟。" % (name, verb, 10 + i))
        questions = [{
            "text": "测试题 %d" % i,
            "options": ["甲", "乙", "丙", "丁"],
            "answer": i % 4,
            "explain": "依据已展示的信息。",
            "uses": [i + 1],
        } for i in range(8)]

        with self.assertRaisesRegex(gen_ai.AIError, "句式|题材"):
            gen_ai.validate(
                {"infos": infos, "questions": questions},
                n_infos=12,
                n_questions=8,
                names=SAMPLE_NAMES,
            )

    def test_question_label_cannot_disguise_a_calculation_as_recall(self):
        qtype = gen_ai._normal_question_type(
            {"type": "recall", "explain": "30×2＝60"},
            uses=[1, 2],
            text="两个人合计花了多长时间？",
        )

        self.assertEqual(qtype, "calculate")

    def test_topic_interleave_remaps_question_references(self):
        infos = ["偏好一", "偏好二", "偏好三", "日期一", "日期二", "日期三",
                 "物品一", "物品二", "物品三", "地点一", "地点二", "地点三"]
        topics = (["趣味偏好"] * 3 + ["日期事件"] * 3 +
                  ["物品视觉"] * 3 + ["地点关系"] * 3)
        questions = [{"uses": [1, 4, 7]}]

        mixed_infos, mixed_topics = arrange.interleave_topics(
            infos, questions, [], topics, random.Random(9))

        self.assertCountEqual(mixed_infos, infos)
        self.assertTrue(all(a != b
                            for a, b in zip(mixed_topics, mixed_topics[1:])))
        for window_start in range(len(mixed_topics) - 3):
            self.assertGreaterEqual(
                len(set(mixed_topics[window_start:window_start + 4])), 3)
        self.assertEqual(
            {mixed_infos[index - 1] for index in questions[0]["uses"]},
            {"偏好一", "日期一", "物品一"},
        )

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
    def test_failed_ai_generation_keeps_current_set_and_never_uses_local(self):
        room = engine.Room("2468", engine.default_settings())
        room.settings["generator"] = "ai"
        current = {"title": "当前 AI 题库", "source": "deepseek",
                   "infos": ["保留这一套"], "questions": []}
        room.set = current
        room.gen = {"status": "running", "msg": "正在出题"}
        room.generation_rev = 1
        generation_sig = room.sig()

        with mock.patch.object(
                room, "_build", side_effect=gen_ai.AIError("模型空返回")):
            with mock.patch("game.engine.gen_local.generate") as local_generate:
                room._generate(room.generation_rev, generation_sig)

        self.assertIs(room.set, current)
        self.assertEqual(room.gen["status"], "error")
        self.assertIn("模型空返回", room.gen["msg"])
        self.assertIn("未改用本地题库", room.gen["msg"])
        local_generate.assert_not_called()

    def test_failed_ai_prefetch_stays_failed_instead_of_banking_local_set(self):
        room = engine.Room("2468", engine.default_settings())
        room.settings["generator"] = "ai"
        room.settings["prefetch_next"] = True
        room.next_sig = room.sig()
        room.next_gen = {"status": "running", "msg": "正在预生成"}
        room.start_after_gen = True

        with mock.patch.object(
                room, "_build", side_effect=gen_ai.AIError("模型空返回")):
            with mock.patch("game.engine.gen_local.generate") as local_generate:
                room._prefetch()

        self.assertIsNone(room.next_set)
        self.assertFalse(room.start_after_gen)
        self.assertEqual(room.next_gen["status"], "error")
        self.assertIn("未改用本地题库", room.next_gen["msg"])
        local_generate.assert_not_called()

    def test_regenerate_replaces_current_set_for_every_game(self):
        """“换一套”始终替换当前待开局题库，不能消费或改写下一套槽位。"""
        game_ids = [
            "blitz", "classic", "hardcore", "trivia",
            "mostlikely", "undercover", "draw",
        ]

        class ImmediateThread(object):
            def __init__(self, target, args=(), **_kwargs):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        for game_id in game_ids:
            with self.subTest(game=game_id):
                room = engine.Room("2468", engine.default_settings())
                room.game = game_id
                room.game_name = engine.catalog.name_of(game_id)
                room.settings.update(engine.catalog.preset_of(game_id))
                current = {"title": "当前旧题", "source": "test",
                           "infos": [], "questions": []}
                cached_next = {"title": "后台下一套", "source": "test",
                               "infos": [], "questions": []}
                replacement = {"title": "手动换出的当前新题", "source": "test",
                               "infos": [], "questions": []}
                room.set = current
                room.next_set = cached_next
                room.next_msg = "后台缓存"
                room.next_sig = room.sig()

                with mock.patch.object(room, "_build",
                                       return_value=(replacement, "手动换题完成")):
                    with mock.patch("game.engine.threading.Thread", ImmediateThread):
                        room.act("regenerate")

                self.assertIs(room.set, replacement)
                self.assertIsNot(room.set, cached_next)

    def test_each_applied_set_gets_a_new_content_revision(self):
        room = engine.Room("2468", engine.default_settings())
        first = {"title": "第一套", "source": "test",
                 "infos": [], "questions": []}
        second = {"title": "第二套", "source": "test",
                  "infos": [], "questions": []}

        with room.lock:
            room._apply(first, "第一套完成")
        first_rev = room.snapshot(is_host=True)["set_rev"]
        with room.lock:
            room._apply(second, "第二套完成")
        second_rev = room.snapshot(is_host=True)["set_rev"]

        self.assertGreater(first_rev, 0)
        self.assertGreater(second_rev, first_rev)

    def test_start_promotes_ready_next_set_before_entering_briefing(self):
        room = engine.Room("2468", engine.default_settings())
        current = {"title": "当前 A", "source": "test",
                   "infos": ["A 的第一条"], "questions": []}
        prepared = {"title": "下一套 B", "source": "test",
                    "infos": ["B 的第一条"], "questions": []}
        room.set = current
        room.banked = True
        room.next_set = prepared
        room.next_msg = "后台准备完成"
        room.next_sig = room.sig()

        with mock.patch.object(room, "prefetch_async"):
            room.act("start")

        self.assertIs(room.set, prepared)
        self.assertEqual(room.phase, "briefing")
        self.assertEqual(room.snapshot(is_host=True)["info"]["text"], "B 的第一条")
        self.assertIsNone(room.next_set)

    def test_start_waits_for_running_prefetch_then_opens_that_set(self):
        room = engine.Room("2468", engine.default_settings())
        current = {"title": "已经玩过的 A", "source": "test",
                   "infos": ["A 的第一条"], "questions": []}
        prepared = {"title": "刚生成好的 B", "source": "test",
                    "infos": ["B 的第一条"], "questions": []}
        room.set = current
        room.banked = True
        room.next_sig = room.sig()
        room.next_gen = {"status": "running", "msg": "正在预生成下一套"}

        with mock.patch.object(room, "generate_async") as generate:
            room.act("start")

        generate.assert_not_called()
        self.assertEqual(room.phase, "lobby")
        self.assertTrue(room.start_after_gen)
        self.assertTrue(room.snapshot(is_host=True)["start_pending"])

        with mock.patch.object(room, "_build",
                               return_value=(prepared, "后台准备完成")):
            with mock.patch.object(room, "prefetch_async"):
                room._prefetch()

        self.assertIs(room.set, prepared)
        self.assertEqual(room.phase, "briefing")
        self.assertEqual(room.snapshot(is_host=True)["info"]["text"], "B 的第一条")

    def test_completed_set_without_prefetch_generates_before_starting(self):
        room = engine.Room("2468", engine.default_settings())
        room.set = {"title": "已经玩过的 A", "source": "test",
                    "infos": ["A 的第一条"], "questions": []}
        room.banked = True

        with mock.patch.object(room, "generate_async") as generate:
            room.act("start")

        generate.assert_called_once_with(True)
        self.assertEqual(room.phase, "lobby")

    def test_generate_button_promotes_ready_next_set_to_current(self):
        room = engine.Room("2468", engine.default_settings())
        room.set = {"title": "当前 A", "source": "test",
                    "infos": ["A"], "questions": []}
        prepared = {"title": "下一套 B", "source": "test",
                    "infos": ["B"], "questions": []}
        room.next_set = prepared
        room.next_msg = "后台准备完成"
        room.next_sig = room.sig()

        room.act("generate")

        self.assertIs(room.set, prepared)
        self.assertIsNone(room.next_set)

    def test_question_setting_change_discards_stale_prefetched_set(self):
        room = engine.Room("2468", engine.default_settings())
        room.next_set = {"title": "旧设置的下一套", "source": "test",
                         "infos": ["旧题"], "questions": []}
        room.next_sig = room.sig()
        room.next_gen = {"status": "ok", "msg": "下一套题已就绪"}

        room.act("settings", {"n_infos": 40})

        self.assertIsNone(room.next_set)
        self.assertIsNone(room.next_sig)
        self.assertEqual(room.next_gen["status"], "idle")

    def test_memory_start_only_prefetches_when_host_enables_it(self):
        game_set = {
            "title": "测试题库", "source": "test",
            "infos": ["一条信息"], "questions": [],
        }
        disabled = engine.Room("2468", engine.default_settings())
        disabled.set = game_set
        disabled.act("settings", {"generator": "ai", "prefetch_next": False})
        with mock.patch("game.engine.threading.Thread") as thread:
            disabled.act("start")
        thread.assert_not_called()

        enabled = engine.Room("1357", engine.default_settings())
        enabled.set = game_set
        enabled.act("settings", {"generator": "ai", "prefetch_next": True})
        with mock.patch("game.engine.threading.Thread") as thread:
            enabled.act("start")
        thread.assert_called_once()

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

    def test_trivia_without_ai_key_uses_an_explicit_local_bank(self):
        room = mock.Mock(settings={
            "n_questions": 3,
            "topic": "综合",
            "level": "困难",
            "api_key": "",
            "model": "test-model",
        })

        game_set, message = trivia.build(room)

        self.assertEqual(game_set["source"], "bank")
        self.assertFalse(game_set["difficulty_guaranteed"])
        self.assertIn("未启用 AI", game_set["title"])
        self.assertIn("未配置 DeepSeek", message)
        self.assertIn("未保证「困难」难度", message)

    def test_ai_enabled_games_raise_instead_of_silently_using_local_banks(self):
        cases = [
            (trivia, {"n_questions": 3, "topic": "综合", "level": "困难"}),
            (vote, {"n_questions": 3, "names": SAMPLE_NAMES}),
            (undercover, {"n_questions": 3}),
            (draw, {"n_questions": 3}),
        ]

        for mode, settings in cases:
            configured = dict(settings, api_key="test-key", model="test-model")
            room = mock.Mock(settings=configured)
            with self.subTest(mode=mode.__name__):
                with mock.patch.object(
                        mode.gen_ai, "chat",
                        side_effect=gen_ai.AIError("offline")):
                    with self.assertRaisesRegex(gen_ai.AIError, "offline"):
                        mode.build(room)


class ConfigurationTests(unittest.TestCase):
    def test_quality_first_model_is_the_default_everywhere(self):
        host = (Path(__file__).resolve().parents[1] /
                "web" / "host.html").read_text(encoding="utf-8")
        example = json.loads((Path(__file__).resolve().parents[1] /
                              "config.example.json").read_text(encoding="utf-8"))

        self.assertEqual(gen_ai.DEFAULT_MODEL, "deepseek-v4-pro")
        self.assertEqual(example["deepseek_model"], "deepseek-v4-pro")
        self.assertIn('value="deepseek-v4-pro"', host)

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
