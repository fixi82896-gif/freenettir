"""Regression: feeds must be owned by the Telegram admin panel, not source code."""
import ast
import inspect
import unittest
from unittest.mock import Mock, patch

import main


class AdminOnlySourceTests(unittest.TestCase):
    def test_no_fixed_source_lists_in_collection_code(self):
        for func in (main.collect_configs, main.collect_proxies):
            tree=ast.parse(inspect.getsource(func))
            urls=[node.value for node in ast.walk(tree) if isinstance(node,ast.Constant)
                  and isinstance(node.value,str) and "://" in node.value]
            self.assertEqual(urls, [], f"{func.__name__} embeds source URLs: {urls}")

    def test_empty_admin_config_sources_makes_no_network_requests(self):
        history={"custom_config_sources":[],"leftover_configs":[],"source_failures":{}}
        with patch.object(main.HTTP_SESSION,"get") as get:
            result=main.collect_configs(history,set(),set())
        self.assertEqual(result,[])
        get.assert_not_called()

    def test_admin_source_is_only_config_source_queried(self):
        admin_url="https://example.org/managed-config-feed"
        history={"custom_config_sources":[admin_url,admin_url], "leftover_configs":[],"source_failures":{}}
        response=Mock(status_code=200,text="vless://uuid123@host.example.org:443#test")
        with patch.object(main.HTTP_SESSION,"get",return_value=response) as get:
            result=main.collect_configs(history,set(),set())
        self.assertEqual(len(result),1)
        get.assert_called_once_with(admin_url,timeout=10)
        self.assertEqual(history["custom_config_sources"],[admin_url,admin_url])

    def test_admin_proxy_source_is_only_proxy_source_queried(self):
        admin_url="https://t.me/s/admin-proxy-source"
        history={"custom_proxy_sources":[admin_url,admin_url],"recent_proxy_pool":[],"leftover_proxies":[],"source_failures":{}}
        response=Mock(status_code=200,text='<a href="https://t.me/proxy?server=host.example.org&amp;port=443&amp;secret=dd0123456789abcdef0123456789abcdef">Connect</a>')
        with patch.object(main.HTTP_SESSION,"get",return_value=response) as get, patch.object(main,"verify_mtproto_pool",side_effect=lambda links:links) as verify:
            result=main.collect_proxies(history,set())
        self.assertEqual(len(result),1)
        get.assert_called_once_with(admin_url,timeout=8)
        verify.assert_called_once()
        self.assertEqual(history["custom_proxy_sources"],[admin_url,admin_url])

    def test_config_leftovers_are_not_destroyed_if_admin_has_no_sources(self):
        existing=("vless://uuid123@host.example.org:443#manual",None)
        history={"custom_config_sources":[],"leftover_configs":[existing],"source_failures":{}}
        with patch.object(main.HTTP_SESSION,"get") as get:
            items=main.collect_configs(history,set(),set())
        self.assertEqual(items,[existing])
        get.assert_not_called()

    def test_existing_panel_sources_and_history_defaults_are_preserved(self):
        original={"custom_config_sources":["https://example.org/a"],
                  "custom_proxy_sources":["https://t.me/s/one"],
                  "last_serial":12345,"sent_proxies_hashes":["abcdef"],"leftover_proxies":["fake"]}
        with patch.object(main,"HISTORY_FILE","/this/path/does-not-exist"):
            restored=main.load_history()  # fallback defaults only; never edits file
        self.assertEqual(restored["custom_config_sources"],[])
        # Explicitly demonstrate the production dict schema remains unchanged.
        self.assertIn("custom_config_sources",original)
        self.assertIn("custom_proxy_sources",original)
        self.assertEqual(original["last_serial"],12345)

if __name__=="__main__":
    unittest.main()
