import unittest

from app.services.pdf_export_service import _render_markdown_subset


class PdfExportServiceTest(unittest.TestCase):
    def test_markdown_renderer_formats_resume_pdf_content(self) -> None:
        content = _render_markdown_subset(
            "# Walker Lin\n\n"
            "## 工作經歷\n\n"
            "### CakeResume / Senior Frontend Engineer\n"
            "**2021/01 - 2024/06**\n\n"
            "- 負責 **Angular** 前端架構與履歷編輯流程\n\n"
            "---\n\n"
            "作品集：[CakeResume](https://cake.me/walker)\n"
            "專案網址：[Portfolio](https://example.com/project)\n"
            "## 聯絡方式\n\n"
            "- Email: walker@example.com\n"
            "- LinkedIn: https://www.linkedin.com/in/walker\n"
            "- 個人檔案連結：https://www.cakeresume.com/walker\n"
        )

        self.assertIn('class="experience-heading"', content)
        self.assertIn("<span>2021/01 - 2024/06</span>", content)
        self.assertIn("<strong>Angular</strong>", content)
        self.assertIn("https://example.com/project", content)
        self.assertIn("walker@example.com", content)
        self.assertNotIn("https://cake.me/walker", content)
        self.assertNotIn("linkedin.com/in/walker", content)
        self.assertNotIn("cakeresume.com/walker", content)
        self.assertNotIn("---", content)
        self.assertNotIn("[CakeResume]", content)
        self.assertNotIn("<a ", content)


if __name__ == "__main__":
    unittest.main()
