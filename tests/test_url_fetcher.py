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


if __name__ == "__main__":
    unittest.main()
