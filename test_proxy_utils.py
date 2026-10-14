import unittest
from proxy_utils import normalize_proxy_link, extract_proxy_links, extract_socks5_endpoints

class ProxyLinkTests(unittest.TestCase):
    def test_encoded_html_button(self):
        html = '<a href="https://t.me/proxy?port=443&amp;secret=dd0123456789abcdef0123456789abcdef&amp;server=a.example.org">Connect</a>'
        self.assertEqual(extract_proxy_links(html), ["https://t.me/proxy?server=a.example.org&port=443&secret=dd0123456789abcdef0123456789abcdef"])
    def test_tg_and_telegram_me_and_duplicates(self):
        text = ("tg://proxy?server=A.Example.org&port=443&secret=dd0123456789abcdef0123456789abcdef "
                "https://telegram.me/proxy?secret=dd0123456789abcdef0123456789abcdef&port=443&server=a.example.org")
        self.assertEqual(len(extract_proxy_links(text)), 1)
    def test_tg_alone(self):
        self.assertEqual(normalize_proxy_link("tg://proxy?port=443&server=A.Example.org&secret=dd0123456789abcdef0123456789abcdef"),
            "https://t.me/proxy?server=a.example.org&port=443&secret=dd0123456789abcdef0123456789abcdef")
    def test_socks(self):
        self.assertEqual(normalize_proxy_link("https://t.me/socks?port=1080&amp;server=1.2.3.4&amp;user=hello&amp;pass=secret"),
            "https://t.me/socks?server=1.2.3.4&port=1080&user=hello&pass=secret")
    def test_padded_base64_secret(self):
        self.assertEqual(normalize_proxy_link("https://t.me/proxy?server=host.example&port=443&secret=EERighJJvXrFGRMCIMJdCQ=="),
            "https://t.me/proxy?server=host.example&port=443&secret=EERighJJvXrFGRMCIMJdCQ%3D%3D")
    def test_bare_socks(self):
        self.assertEqual(extract_socks5_endpoints("1.2.3.4:1080\n999.2.3.4:80\n8.8.8.8:443"), [
            "https://t.me/socks?server=1.2.3.4&port=1080", "https://t.me/socks?server=8.8.8.8&port=443"])
    def test_bad_parameters(self):
        bad = (
            "https://evil.test/proxy?server=1.2.3.4&port=443&secret=dd0123456789abcdef0123456789abcdef",
            "https://t.me/proxy?server=unknown&port=443&secret=dd0123456789abcdef0123456789abcdef",
            "https://t.me/proxy?server=host.example&port=0&secret=dd0123456789abcdef0123456789abcdef",
            "https://t.me/proxy?server=host.example&port=99999&secret=dd0123456789abcdef0123456789abcdef",
            "https://t.me/proxy?server=host.example&port=443",
            "https://t.me/proxy?server=host.example&port=443&secret=abc",
            "https://t.me/webproxy?server=host.example&port=443&secret=dd0123456789abcdef0123456789abcdef",
        )
        for link in bad:
            with self.subTest(link=link):
                self.assertIsNone(normalize_proxy_link(link))
    def test_ignore_non_proxy_links(self):
        self.assertEqual(extract_proxy_links('<a href="https://t.me/ProxyMTProto">Channel</a>'), [])
    def test_direct_text_and_entities(self):
        self.assertEqual(len(extract_proxy_links("https://t.me/proxy?server=a.test&amp;port=443&amp;secret=dd0123456789abcdef0123456789abcdef")), 1)
    def test_real_channel_example(self):
        self.assertEqual(extract_proxy_links('<a href="https://t.me/proxy?port=443&amp;secret=ee68d6a83140657a1c7bf8e64d98ce9432786170692e6f7a6f6e2e7275&amp;server=a03.lovely.lat">Connect</a>'), [
            "https://t.me/proxy?server=a03.lovely.lat&port=443&secret=ee68d6a83140657a1c7bf8e64d98ce9432786170692e6f7a6f6e2e7275"
        ])
if __name__ == "__main__":
    unittest.main()
