import unittest

from app.importers.text import can_extract_text, extract_text_from_bytes


class TextImporterTest(unittest.TestCase):
    def test_can_extract_text_for_txt_and_markdown(self) -> None:
        self.assertTrue(can_extract_text("resume.txt"))
        self.assertTrue(can_extract_text("resume.md"))
        self.assertTrue(can_extract_text("resume.markdown"))
        self.assertFalse(can_extract_text("resume.pdf"))

    def test_extract_text_from_utf8_bytes(self) -> None:
        self.assertEqual(extract_text_from_bytes("你好\nHello".encode()), "你好\nHello")


if __name__ == "__main__":
    unittest.main()

