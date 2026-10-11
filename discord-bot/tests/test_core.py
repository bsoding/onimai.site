import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from core import Store, PageLimit, EndpointTaken, UserError, validate_endpoint, parse_names, parse_bios, profile_html


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "pages.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_three_pages_survive_restart_and_channel_deletion(self):
        for n in range(3):
            session = self.store.reserve(123, 456, "page" + str(n))
            self.store.update(session.id, phase="published", channel_id=100+n)
            self.assertFalse(self.store.cancel(session.id))
        self.store.close()
        self.store = Store(self.path)
        with self.assertRaises(PageLimit):
            self.store.reserve(123, 789, "fourth")
        self.assertEqual(self.store.count(123), 3)
        self.assertEqual(self.store.reserve(124, 456, "anotheruser").user_id, 124)

    def test_cancellation_releases_slot_and_endpoint_but_number_increases(self):
        first = self.store.reserve(123, 456, "pollo")
        self.assertTrue(self.store.cancel(first.id))
        second = self.store.reserve(123, 456, "pollo")
        self.assertGreater(second.id, first.id)
        self.assertEqual(self.store.count(123), 1)

    def test_endpoint_reserved_for_one_creator(self):
        self.store.reserve(123, 456, "POLLO")
        with self.assertRaises(EndpointTaken):
            self.store.reserve(999, 456, "pollo")
        self.assertEqual(self.store.count(999), 0)

    def test_publishing_cannot_release_quota(self):
        session = self.store.reserve(123, 456, "pollo")
        self.store.update(session.id, phase="publishing", commit_sha="uncertain")
        self.assertFalse(self.store.cancel(session.id))
        self.assertEqual(self.store.count(123), 1)

    def test_simultaneous_fourth_page_cannot_bypass_limit(self):
        self.store.reserve(123, 456, "first")
        self.store.reserve(123, 456, "second")
        def reserve(endpoint):
            other = Store(self.path)
            try:
                return other.reserve(123, 456, endpoint).endpoint
            except PageLimit:
                return "limit"
            finally:
                other.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ["third", "fourth"]))
        self.assertEqual(results.count("limit"), 1)
        self.assertEqual(self.store.count(123), 3)

    def test_global_channel_numbers_and_snowflakes_preserved(self):
        first = self.store.reserve(1496268262135038054, 1496268262135038055, "first")
        second = self.store.reserve(999, 456, "second")
        self.assertEqual(second.id, first.id + 1)
        self.assertEqual(self.store.get(first.id).user_id, 1496268262135038054)

    def test_paths_urls_existing_system_names_and_invalid_endpoints_rejected(self):
        for endpoint in ["../jvbj", "jvbj/settings", ".git", "https://evil.example", "assets", "example", "discord-bot", "_x", "x-", "a"*33, "", "@everyone"]:
            with self.subTest(endpoint=endpoint), self.assertRaises(UserError):
                validate_endpoint(endpoint)
        self.assertEqual(validate_endpoint(" Pollo_1 "), "pollo_1")

    def test_names_blank_lines_and_duplicates(self):
        self.assertEqual(parse_names("  Pollo\r\n\r\npollo.exe\r\nPollo  "), ["Pollo","pollo.exe"])
        for text in ["", "x"*81, "\n".join(str(n) for n in range(11)), "bad\x00name"]:
            with self.assertRaises(UserError):
                parse_names(text)

    def test_bios_keep_lines_and_rotate_on_blank_lines(self):
        self.assertEqual(parse_bios("hello\nworld\n\nsecond bio"), ["hello\nworld","second bio"])
        for text in ["", "x"*601, "\n\n".join(str(n) for n in range(6))]:
            with self.assertRaises(UserError):
                parse_bios(text)

    def test_user_text_cannot_escape_script_or_sharing_attributes(self):
        template = (Path(__file__).resolve().parents[2] / "example/index.html").read_text(encoding="utf-8")
        name = '</script><script>alert("x")</script>'
        bio = '" onload="alert(1) <img src=x> & hello'
        rendered = profile_html(template, [name,"🐈"], [bio])
        self.assertEqual(rendered.count("<script>"), template.count("<script>"))
        self.assertNotIn('fallbackName: "</script>', rendered)
        self.assertIn("\\u003c/script\\u003e", rendered)
        self.assertIn("&lt;img src=x&gt;", rendered)
        self.assertIn("&quot; onload=&quot;", rendered)
        self.assertNotIn("<img src=x>", rendered)


if __name__ == "__main__":
    unittest.main()
