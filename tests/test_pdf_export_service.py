import unittest

from app.schemas.job import TrackedJob
from app.services.pdf_export_service import (
    STANDARD_LAYOUT,
    TECHNICAL_LAYOUT,
    _render_markdown_subset,
    _select_layout_variant,
)


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
        self.assertIn("工作經歷 / Work Experience", content)
        self.assertIn("聯絡方式 / Contact", content)
        self.assertIn("<span> | 2021/01 - 2024/06</span>", content)
        self.assertIn("<strong>Angular</strong>", content)
        self.assertIn("https://example.com/project", content)
        self.assertIn("walker@example.com", content)
        self.assertNotIn("https://cake.me/walker", content)
        self.assertNotIn("linkedin.com/in/walker", content)
        self.assertNotIn("cakeresume.com/walker", content)
        self.assertNotIn("---", content)
        self.assertNotIn("[CakeResume]", content)
        self.assertNotIn("<a ", content)

    def test_technical_layout_moves_skills_before_experience(self) -> None:
        content = _render_markdown_subset(
            "# Walker Lin\n\n"
            "## 專業摘要\n\n"
            "Frontend engineer.\n\n"
            "## 工作經歷\n\n"
            "### SaaS Co / Frontend Engineer\n"
            "**2021 - 2024**\n"
            "- Built web applications.\n\n"
            "## 核心技能\n\n"
            "- React\n"
            "- TypeScript\n",
            layout_variant=TECHNICAL_LAYOUT,
        )

        summary_index = content.index('data-section="專業摘要"')
        skills_index = content.index('data-section="核心技能"')
        experience_index = content.index('data-section="工作經歷"')
        self.assertLess(summary_index, skills_index)
        self.assertLess(skills_index, experience_index)
        self.assertIn("resume-section-featured", content)
        self.assertIn("專業摘要 / Summary", content)
        self.assertIn("核心技能 / Skills", content)

    def test_standard_layout_keeps_generated_section_order(self) -> None:
        content = _render_markdown_subset(
            "# Walker Lin\n\n"
            "## 專業摘要\n\n"
            "Operations leader.\n\n"
            "## 工作經歷\n\n"
            "- Led service delivery.\n\n"
            "## 核心技能\n\n"
            "- Stakeholder management\n",
            layout_variant=STANDARD_LAYOUT,
        )

        experience_index = content.index('data-section="工作經歷"')
        skills_index = content.index('data-section="核心技能"')
        self.assertLess(experience_index, skills_index)
        self.assertNotIn("resume-section-featured", content)

    def test_layout_classifier_detects_software_roles(self) -> None:
        job = TrackedJob(
            id="job_1",
            title="Senior Frontend Engineer",
            company="Example",
            url="https://jobs.example.com/frontend",
            description="React TypeScript platform role",
            createdAt="2026-07-07T00:00:00Z",
        )

        variant = _select_layout_variant(
            markdown="## 核心技能\n\n- React\n- TypeScript",
            job=job,
        )

        self.assertEqual(variant, TECHNICAL_LAYOUT)


if __name__ == "__main__":
    unittest.main()
