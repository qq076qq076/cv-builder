import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from app.ai.resume_parser import (
    GeminiResumeParser,
    _debug_log_ai_payload,
    _extract_gemini_response_json,
    _resume_response_schema,
    build_resume_file_prompt,
    build_resume_parse_prompt,
)


class GeminiResponseParserTest(unittest.TestCase):
    def test_extracts_rest_structured_output_direct_json(self) -> None:
        payload = {
            "name": "Walker Lin",
            "skills": ["Python"],
            "summary": "Engineer",
        }

        result = _extract_gemini_response_json(payload)

        self.assertEqual(json.loads(result)["name"], "Walker Lin")

    def test_extracts_output_text_wrapper(self) -> None:
        result = _extract_gemini_response_json({"output_text": '{"name":"Walker"}'})

        self.assertEqual(result, '{"name":"Walker"}')

    def test_extracts_text_from_steps_wrapper(self) -> None:
        result = _extract_gemini_response_json(
            {
                "steps": [
                    {
                        "content": [
                            {"type": "text", "text": '{"name":'},
                            {"type": "text", "text": '"Walker"}'},
                        ]
                    }
                ]
            }
        )

        self.assertEqual(result, '{"name":"Walker"}')

    def test_rejects_unknown_response_shape(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "missing structured JSON output"):
            _extract_gemini_response_json({"id": "interaction-1"})

    def test_resume_prompt_includes_format_and_extraction_checklist(self) -> None:
        prompt = build_resume_parse_prompt("src_1", "Walker Lin\nSKILLS\nAngular")

        self.assertIn('"experiences"', prompt)
        self.assertIn('"projects"', prompt)
        self.assertIn("Skills: include every listed skill", prompt)
        self.assertIn("Experience: create one item per job", prompt)
        self.assertIn("Projects: create one item per project", prompt)
        self.assertIn("Return every top-level JSON key", prompt)
        self.assertIn("Walker Lin", prompt)

    def test_resume_prompt_includes_target_language_instruction(self) -> None:
        prompt = build_resume_parse_prompt(
            "src_1",
            "Walker Lin\nSKILLS\nAngular",
            target_language="en",
        )

        self.assertIn("output all human-readable resume fields in English", prompt)
        self.assertIn("Preserve names, company names", prompt)

    def test_resume_response_schema_requires_all_resume_sections(self) -> None:
        schema = _resume_response_schema()

        self.assertIn("name", schema["required"])
        self.assertIn("skills", schema["required"])
        self.assertIn("experiences", schema["required"])
        self.assertIn("projects", schema["required"])
        self.assertIn("languages", schema["required"])
        self.assertIn("email", schema["$defs"]["ResumeContact"]["required"])

    def test_resume_file_prompt_includes_supplemental_text(self) -> None:
        prompt = build_resume_file_prompt(
            "src_1",
            "Walker Lin\nSKILLS\nAngular",
            target_language="zh",
        )

        self.assertIn("Supplemental extracted text", prompt)
        self.assertIn("Traditional Chinese", prompt)
        self.assertIn("Walker Lin", prompt)
        self.assertIn("Angular", prompt)

    def test_gemini_file_parser_uses_required_response_schema(self) -> None:
        parser = GeminiResumeParser(api_key="test-key", model="test-model")
        captured_payloads = []

        def fake_post_interaction(payload: dict) -> str:
            captured_payloads.append(payload)
            return '{"sourceIds":["src_1"],"name":"Walker Lin","skills":["Angular"]}'

        parser._post_interaction = fake_post_interaction

        with redirect_stdout(StringIO()):
            parser.parse_file(
                filename="resume.pdf",
                content_type="application/pdf",
                content=b"%PDF",
                extracted_text="Walker Lin\nSKILLS\nAngular",
                source_id="src_1",
            )

        schema = captured_payloads[0]["response_format"]["schema"]
        self.assertIn("skills", schema["required"])
        self.assertIn("Supplemental extracted text", captured_payloads[0]["input"][1]["text"])

    def test_debug_logger_writes_jsonl_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "logs/ai-parser.jsonl"

            with redirect_stdout(StringIO()):
                _debug_log_ai_payload("AI input", {"model": "test"}, log_path)
                _debug_log_ai_payload("AI output", '{"name":"Walker"}', log_path)

            entries = [
                json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(entries[0]["label"], "AI input")
        self.assertEqual(entries[0]["payload"], {"model": "test"})
        self.assertEqual(entries[1]["label"], "AI output")
        self.assertEqual(entries[1]["payload"], '{"name":"Walker"}')


if __name__ == "__main__":
    unittest.main()
