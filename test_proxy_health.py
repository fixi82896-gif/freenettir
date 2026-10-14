import unittest
from unittest.mock import patch, Mock

import proxy_health
from proxy_health import verify_mtproto_pool, verified_buttons_for_post, is_public_mtproto

SECRET = "dd0123456789abcdef0123456789abcdef"

def mt(idx):
    return f"https://t.me/proxy?server=proxy{idx}.example.com&port=443&secret={SECRET}"

class VerifiedProxyTests(unittest.TestCase):
    def test_never_recycle_dead_endpoints(self):
        urls = [mt(1), mt(2), mt(3)]
        good = verify_mtproto_pool(urls, verifier=lambda u: u==mt(3))
        self.assertEqual(good, [mt(3)])

    def test_only_mtproto_not_untested_socks(self):
        sock = "https://t.me/socks?server=1.2.3.4&port=1080"
        pool = verify_mtproto_pool([sock,mt(1)], verifier=lambda u: True)
        self.assertEqual(pool,[mt(1)])

    def test_deduped_and_ordered(self):
        self.assertEqual(verify_mtproto_pool([mt(2),mt(1),mt(2)], verifier=lambda u: True),[mt(2),mt(1)])

    def test_on_demand_reverification_replaces_dead(self):
        now=1000
        cache={mt(1):1}
        decisions={mt(1):False,mt(2):True,mt(3):True}
        calls=[]
        def check(link):
            calls.append(link)
            return decisions[link]
        selected=verified_buttons_for_post([mt(1),mt(2)],[mt(1),mt(2),mt(3)],cache,now=now,verifier=check)
        self.assertEqual(selected,[mt(2),mt(3)])
        self.assertNotIn(mt(1),cache)
        self.assertEqual(calls,[mt(1),mt(2),mt(3)])

    def test_dont_retest_fresh_success(self):
        cache={mt(1):900}
        selected=verified_buttons_for_post([mt(1),mt(2)],[mt(3)],cache,now=1000,verifier=lambda u:u==mt(2))
        self.assertEqual(selected,[mt(1),mt(2)])

    def test_no_good_links_returns_no_buttons(self):
        self.assertEqual(verified_buttons_for_post([mt(1)],[mt(2)],{},now=1000,verifier=lambda _:False),[])

    def test_refuses_reserved_destination(self):
        with patch.object(proxy_health.socket,"getaddrinfo",return_value=[(2,1,6,'',('127.0.0.1',0))]):
            self.assertFalse(is_public_mtproto(mt(1)))
        with patch.object(proxy_health.socket,"getaddrinfo",return_value=[(2,1,6,'',('8.8.8.8',0))]):
            self.assertTrue(is_public_mtproto(mt(1)))

    def test_limit_bounds_verifications(self):
        self.assertEqual(len(verify_mtproto_pool([mt(i) for i in range(20)],max_checks=6,verifier=lambda _:True)),6)

if __name__=="__main__":
    unittest.main()
