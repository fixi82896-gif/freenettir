"""Offline regression tests for the Telegram admin's collapsible source menu."""
import html
import json
import unittest
from unittest.mock import Mock, patch

import main

CFG = "https://example.org/config-subscription"
PRX = "https://t.me/s/ProxyMTProto"


def sample_history():
    return {"custom_config_sources": [CFG, "https://t.me/s/OtherConfigs"],
            "custom_proxy_sources": [PRX, "https://t.me/s/TelMTProto"],
            "last_update_id": 0, "bot_state": None}


def callback_update(data, from_user=123, message_id=5678):
    return {"update_id": 17, "callback_query": {
        "id": "callback-id", "from": {"id": from_user},
        "data": data, "message": {"message_id": message_id}
    }}


def run_callback(data, history, from_user=123):
    answer = Mock(status_code=200)
    answer.json.return_value = {"ok": True}
    updates = Mock()
    updates.json.return_value = {"ok": True, "result": [
        callback_update(data, from_user=from_user)
    ]}
    with (
        patch.object(main, "TOKEN", "fake-token"),
        patch.object(main, "ADMIN_ID", "123"),
        patch.object(main.HTTP_SESSION, "get", return_value=updates),
        patch.object(main.HTTP_SESSION, "post", return_value=answer) as sent,
    ):
        main.process_admin_updates(history)
    return sent.call_args_list


class CollapsibleSourceMenuTests(unittest.TestCase):
    def test_initial_sections_both_collapsed_with_counts(self):
        text, data = main.build_sources_deletion_menu(sample_history())
        labels = [row[0]["text"] for row in data["inline_keyboard"]]
        callbacks = [row[0]["callback_data"] for row in data["inline_keyboard"]]
        self.assertEqual(len(labels), 2)
        self.assertEqual(callbacks, ["src_menu_1", "src_menu_2"])
        self.assertIn("منابع کانفیگ (2)", labels[0])
        self.assertIn("منابع پروکسی (2)", labels[1])
        self.assertIn("\n", text)
        self.assertNotIn("\\n", text)

    def test_config_expands_without_expanding_proxy(self):
        _, menu = main.build_sources_deletion_menu(sample_history(), expanded=1)
        callbacks = [row[0]["callback_data"] for row in menu["inline_keyboard"]]
        self.assertEqual(callbacks[0], "src_menu_0")
        self.assertEqual(callbacks[-1], "src_menu_3")
        self.assertEqual(sum(c.startswith("src_del_cfg_") for c in callbacks), 2)
        self.assertFalse(any(c.startswith("src_del_prx_") for c in callbacks))

    def test_proxy_expands_without_expanding_config(self):
        _, menu = main.build_sources_deletion_menu(sample_history(), expanded=2)
        callbacks = [row[0]["callback_data"] for row in menu["inline_keyboard"]]
        self.assertEqual(callbacks[0], "src_menu_3")
        self.assertEqual(callbacks[1], "src_menu_0")
        self.assertFalse(any(c.startswith("src_del_cfg_") for c in callbacks))
        self.assertEqual(sum(c.startswith("src_del_prx_") for c in callbacks), 2)

    def test_both_open_can_be_closed_independently(self):
        _, menu = main.build_sources_deletion_menu(sample_history(), expanded=3)
        callbacks = [row[0]["callback_data"] for row in menu["inline_keyboard"]]
        self.assertIn("src_menu_2", callbacks)
        self.assertIn("src_menu_1", callbacks)
        self.assertEqual(sum(c.startswith("src_del_") for c in callbacks), 4)

    def test_empty_category_can_expand(self):
        _, menu = main.build_sources_deletion_menu({
            "custom_config_sources": [], "custom_proxy_sources": [PRX]
        }, expanded=1)
        labels = [row[0]["text"] for row in menu["inline_keyboard"]]
        self.assertIn("— هنوز منبعی ثبت نشده است —", labels)
        self.assertEqual(len(labels), 3)

    def test_token_based_deletion_avoids_index_drift(self):
        history = sample_history()
        target = history["custom_config_sources"][1]
        token = main.source_menu_token(target)
        history["custom_config_sources"].insert(0, "https://test.example.net/new")
        deleted = main.delete_source_by_token(history, "cfg", token)
        self.assertEqual(deleted, target)
        self.assertEqual(history["custom_config_sources"], ["https://test.example.net/new", CFG])
        self.assertEqual(history["custom_proxy_sources"][0], PRX)
        self.assertIsNone(main.delete_source_by_token(history, "cfg", token))

    def test_rejects_duplicate_token_and_invalid_kind(self):
        history = sample_history()
        history["custom_config_sources"] = [CFG, CFG]
        self.assertIsNone(main.delete_source_by_token(history, "cfg", main.source_menu_token(CFG)))
        self.assertIsNone(main.delete_source_by_token(history, "unknown", main.source_menu_token(CFG)))
        self.assertEqual(history["custom_config_sources"], [CFG, CFG])

    def test_callback_data_below_telegram_limit(self):
        _, menu = main.build_sources_deletion_menu(sample_history(), expanded=3)
        for row in menu["inline_keyboard"]:
            self.assertLessEqual(len(row[0]["callback_data"].encode("utf-8")), 64)

    def test_edit_same_message_when_toggling(self):
        history = sample_history()
        calls = run_callback("src_menu_1", history)
        posts = [(x.args[0], x.kwargs["data"]) for x in calls]
        edits = [x for x in posts if x[0].endswith("/editMessageText")]
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0][1]["message_id"], 5678)
        self.assertTrue(any(x[0].endswith("/answerCallbackQuery") for x in posts))
        self.assertFalse(any(x[0].endswith("/sendMessage") for x in posts))
        self.assertEqual(history["custom_config_sources"][0], CFG)

    def test_callback_deletion_keeps_open_section_and_other_sources(self):
        history = sample_history()
        token = main.source_menu_token(CFG)
        calls = run_callback("src_del_cfg_1_" + token, history)
        self.assertEqual(history["custom_config_sources"], ["https://t.me/s/OtherConfigs"])
        self.assertEqual(len(history["custom_proxy_sources"]), 2)
        edits = [x for x in calls if x.args[0].endswith("/editMessageText")]
        self.assertEqual(len(edits), 1)
        text = edits[0].kwargs["data"]["text"]
        self.assertIn("✅", text)
        menu = json.loads(edits[0].kwargs["data"]["reply_markup"])
        self.assertTrue(any(x[0]["callback_data"].startswith("src_del_cfg_") for x in menu["inline_keyboard"]))

    def test_old_index_buttons_cannot_delete_unrelated_sources(self):
        history = sample_history()
        calls = run_callback("del_cfg_0", history)
        self.assertEqual(history["custom_config_sources"][0], CFG)
        self.assertTrue(any(x.args[0].endswith("/editMessageText") for x in calls))

    def test_non_admin_callback_is_ignored(self):
        history = sample_history()
        run_callback("src_del_cfg_1_" + main.source_menu_token(CFG), history, from_user=999)
        self.assertEqual(history["custom_config_sources"][0], CFG)

    def test_notice_escapes_html_in_untrusted_source(self):
        text, _ = main.build_sources_deletion_menu(sample_history(), notice="<script>danger</script>")
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script>", text)


if __name__ == "__main__":
    unittest.main()
