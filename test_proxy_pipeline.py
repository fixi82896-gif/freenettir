import time
import unittest
from unittest.mock import Mock, patch

import main
from proxy_utils import plan_proxy_buttons, refresh_proxy_cache, normalize_proxy_link

def proxy(index):
    return normalize_proxy_link(
        f"https://t.me/proxy?server=host{index}.example.org&port=443&secret=dd0123456789abcdef0123456789abcdef"
    )

class ProxyPoolTests(unittest.TestCase):
    def test_23_links_supply_34_posts_with_two_distinct_buttons(self):
        source = [proxy(i) for i in range(23)]
        batches, cursor = plan_proxy_buttons(source, 34)
        self.assertEqual(len(batches), 34)
        self.assertEqual(sum(map(len, batches)), 68)
        self.assertTrue(all(len(set(row)) == 2 for row in batches))
        self.assertEqual(set(p for row in batches for p in row), set(source))
        self.assertEqual(cursor, 68 % 23)

    def test_two_links_supply_all_posts_and_rotate(self):
        batches, _ = plan_proxy_buttons([proxy(1), proxy(2)], 34)
        self.assertEqual(len(batches), 34)
        self.assertTrue(all(len(batch) == 2 and batch[0] != batch[1] for batch in batches))

    def test_one_link_creates_only_one_button_per_post(self):
        batches, _ = plan_proxy_buttons([proxy(1)], 34)
        self.assertTrue(all(batch == [proxy(1)] for batch in batches))

    def test_duplicates_filtered_and_empty_pool(self):
        batches, cursor = plan_proxy_buttons([proxy(1), proxy(1), "https://t.me/freenettir", None], 3)
        self.assertEqual(batches, [[proxy(1)]] * 3)
        self.assertEqual(cursor, 0)
        self.assertEqual(plan_proxy_buttons([], 3), ([[], [], []], 0))

    def test_rotation_across_cycles(self):
        source = [proxy(i) for i in range(5)]
        first, cursor = plan_proxy_buttons(source, 3, 0)
        second, new_cursor = plan_proxy_buttons(source, 3, cursor)
        self.assertNotEqual(first[0], second[0])
        self.assertEqual(new_cursor, 2)

    def test_cache_expires_and_preserves_recent_sources(self):
        now = int(time.time())
        previous = [
            {"url": proxy(2), "seen_at": now - 100},
            {"url": proxy(3), "seen_at": now - 9 * 3600},
            {"url": "https://t.me/freenettir", "seen_at": now - 10},
            {"url": proxy(5), "seen_at": "bad"},
        ]
        result = refresh_proxy_cache(previous, [proxy(1), proxy(2)], now)
        self.assertEqual([x["url"] for x in result], [proxy(1), proxy(2)])

    def test_reuses_previously_sent_links_when_new_hashes_exhausted(self):
        response = Mock(status_code=200, text=(
            '<a href="https://t.me/proxy?server=host1.example.org&amp;port=443&amp;secret=dd0123456789abcdef0123456789abcdef">A</a>'
            '<a href="https://t.me/proxy?server=host2.example.org&amp;port=443&amp;secret=dd0123456789abcdef0123456789abcdef">B</a>'
        ))
        history = {"custom_proxy_sources": [], "leftover_proxies": [], "recent_proxy_pool": []}
        hashes = {main.get_md5(proxy(1)), main.get_md5(proxy(2))}
        with patch.object(main.HTTP_SESSION, "get", return_value=response), patch.object(main, "record_source_status"), patch.object(main, "verify_mtproto_pool", side_effect=lambda c: c):
            pool = main.collect_proxies(history, hashes)
        self.assertEqual(set(pool), {proxy(1), proxy(2)})
        self.assertEqual(len(history["recent_proxy_pool"]), 2)

    def test_no_proxy_available_prevents_posting(self):
        history = {
            "leftover_configs": [], "leftover_proxies": [],
            "sent_hashes": [], "sent_ip_ports": [], "sent_proxies_hashes": [],
        }
        patches = [
            patch.object(main, "TOKEN", "dummy"),
            patch.object(main, "CHANNELS", ["@fake"]),
            patch.object(main, "load_history", return_value=history),
            patch.object(main, "send_admin_keyboard"),
            patch.object(main, "process_admin_updates"),
            patch.object(main, "collect_configs", return_value=[("vless://test", None)] * 30),
            patch.object(main, "collect_proxies", return_value=[]),
            patch.object(main, "save_history"),
            patch.object(main, "send_telegram_with_retry"),
        ]
        mocks = [p.start() for p in patches]
        try:
            main.main()
            self.assertEqual(len(history["leftover_configs"]), 30)
            mocks[-1].assert_not_called()
            mocks[-2].assert_called_once()
        finally:
            for p in reversed(patches):
                p.stop()

if __name__ == "__main__":
    unittest.main()
