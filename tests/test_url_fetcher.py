import asyncio
import unittest
from unittest.mock import patch

from app.services.url_fetcher import fetch_url_text, render_fetched_url_evidence


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self.body


class FakeBodyLocator:
    def inner_text(self, timeout: int):
        return "Walker Lin\nSenior Python Engineer\nFastAPI"


class FakePage:
    def __init__(self) -> None:
        self.goto_calls = []

    def goto(self, url: str, wait_until: str, timeout: int) -> None:
        self.goto_calls.append((url, wait_until, timeout))

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        return None

    def title(self) -> str:
        return "Walker Cake Profile"

    def locator(self, selector: str) -> FakeBodyLocator:
        return FakeBodyLocator()


class FakeBrowser:
    def __init__(self) -> None:
        self.page = FakePage()
        self.closed = False

    def new_page(self, user_agent: str, viewport: dict) -> FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser

    def launch(self, headless: bool) -> FakeBrowser:
        return self.browser


class FakePlaywrightContext:
    def __init__(self, browser: FakeBrowser) -> None:
        self.chromium = FakeChromium(browser)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class UrlFetcherTest(unittest.TestCase):
    def test_fetch_url_text_extracts_readable_html(self) -> None:
        html = b"""
        <html>
          <head>
            <title>Walker Profile</title>
            <style>.hidden { display: none; }</style>
          </head>
          <body>
            <h1>Walker Lin</h1>
            <script>window.secret = "ignore";</script>
            <p>Senior Python Engineer</p>
          </body>
        </html>
        """

        with patch("app.services.url_fetcher.request.urlopen", return_value=FakeResponse(html)):
            result = fetch_url_text("https://example.com/profile")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.title, "Walker Profile")
        self.assertIn("Walker Lin", result.text)
        self.assertIn("Senior Python Engineer", result.text)
        self.assertNotIn("window.secret", result.text)

        rendered = render_fetched_url_evidence(result)
        self.assertIn("Source URL: https://example.com/profile", rendered)
        self.assertIn("Fetch Status: completed", rendered)
        self.assertIn("Fetched Content:", rendered)

    def test_fetch_url_text_rejects_non_http_urls(self) -> None:
        result = fetch_url_text("file:///etc/passwd")

        self.assertEqual(result.status, "failed")
        self.assertIn("http/https", result.message)

    def test_fetch_cake_url_uses_playwright_rendered_text(self) -> None:
        browser = FakeBrowser()

        with patch(
            "app.services.url_fetcher.sync_playwright",
            return_value=FakePlaywrightContext(browser),
        ):
            with patch("app.services.url_fetcher.request.urlopen") as urlopen:
                result = fetch_url_text("https://www.cake.me/walker")

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.title, "Walker Cake Profile")
        self.assertIn("Walker Lin", result.text)
        self.assertIn("Senior Python Engineer", result.text)
        self.assertTrue(browser.closed)
        self.assertEqual(
            browser.page.goto_calls,
            [("https://www.cake.me/walker", "domcontentloaded", 20000)],
        )
        urlopen.assert_not_called()

    def test_fetch_104_profile_url_uses_playwright_rendered_text(self) -> None:
        browser = FakeBrowser()

        with patch(
            "app.services.url_fetcher.sync_playwright",
            return_value=FakePlaywrightContext(browser),
        ):
            with patch("app.services.url_fetcher.request.urlopen") as urlopen:
                result = fetch_url_text(
                    "https://pda.104.com.tw/profile/share/bIlwxi8AyBCFkSqkQLwU6mj6qWsheRmu"
                )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.title, "Walker Cake Profile")
        self.assertIn("Walker Lin", result.text)
        self.assertEqual(
            browser.page.goto_calls,
            [
                (
                    "https://pda.104.com.tw/profile/share/bIlwxi8AyBCFkSqkQLwU6mj6qWsheRmu",
                    "domcontentloaded",
                    20000,
                )
            ],
        )
        urlopen.assert_not_called()

    def test_fetch_yourator_url_uses_playwright_rendered_text(self) -> None:
        browser = FakeBrowser()

        with patch(
            "app.services.url_fetcher.sync_playwright",
            return_value=FakePlaywrightContext(browser),
        ):
            with patch("app.services.url_fetcher.request.urlopen") as urlopen:
                result = fetch_url_text("https://www.yourator.co/users/walker")

        self.assertEqual(result.status, "completed")
        self.assertIn("Walker Lin", result.text)
        self.assertEqual(
            browser.page.goto_calls,
            [("https://www.yourator.co/users/walker", "domcontentloaded", 20000)],
        )
        urlopen.assert_not_called()

    def test_fetch_linkedin_profile_url_uses_playwright_rendered_text(self) -> None:
        browser = FakeBrowser()

        with patch(
            "app.services.url_fetcher.sync_playwright",
            return_value=FakePlaywrightContext(browser),
        ):
            with patch("app.services.url_fetcher.request.urlopen") as urlopen:
                result = fetch_url_text("https://www.linkedin.com/in/walker-lin")

        self.assertEqual(result.status, "completed")
        self.assertIn("Walker Lin", result.text)
        self.assertEqual(
            browser.page.goto_calls,
            [("https://www.linkedin.com/in/walker-lin", "domcontentloaded", 20000)],
        )
        urlopen.assert_not_called()

    def test_fetch_cake_url_reports_missing_playwright(self) -> None:
        with patch("app.services.url_fetcher.sync_playwright", None):
            with patch("app.services.url_fetcher.request.urlopen") as urlopen:
                result = fetch_url_text("https://www.cake.me/walker")

        self.assertEqual(result.status, "failed")
        self.assertIn("缺少 playwright", result.message)
        urlopen.assert_not_called()

    def test_fetch_cake_url_can_run_from_async_context(self) -> None:
        browser = FakeBrowser()

        async def fetch_from_async_context():
            return fetch_url_text("https://www.cake.me/walker")

        with patch(
            "app.services.url_fetcher.sync_playwright",
            return_value=FakePlaywrightContext(browser),
        ):
            result = asyncio.run(fetch_from_async_context())

        self.assertEqual(result.status, "completed")
        self.assertIn("Walker Lin", result.text)
        self.assertTrue(browser.closed)


if __name__ == "__main__":
    unittest.main()
