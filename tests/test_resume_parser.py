import json
import unittest

from app.ai.resume_parser import _extract_gemini_response_json


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


if __name__ == "__main__":
    unittest.main()
