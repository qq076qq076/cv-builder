from __future__ import annotations

import json
from typing import Protocol
from urllib import request
from urllib.error import HTTPError, URLError

from openai import OpenAI

from app.schemas.resume import NormalizedResume


RESUME_PARSE_SYSTEM_PROMPT = """You normalize resume text into structured career data.
Rules:
- Preserve facts from the input only. Do not invent companies, dates, skills, degrees, links, or achievements.
- If a field is not present, return an empty string or empty list.
- Keep original language where possible.
- Use concise summaries.
"""


class ResumeParser(Protocol):
    def parse(self, *, extracted_text: str, source_id: str) -> NormalizedResume:
        pass


class OpenAIResumeParser:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def parse(self, *, extracted_text: str, source_id: str) -> NormalizedResume:
        completion = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": RESUME_PARSE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Source ID: {source_id}\n\n"
                        "Normalize the following resume text into the requested schema:\n\n"
                        f"{extracted_text}"
                    ),
                },
            ],
            response_format=NormalizedResume,
        )

        parsed = completion.choices[0].message.parsed
        if parsed is None:
            return NormalizedResume(sourceIds=[source_id])

        return parsed.model_copy(update={"source_ids": [source_id]})


class GeminiResumeParser:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def parse(self, *, extracted_text: str, source_id: str) -> NormalizedResume:
        payload = {
            "model": self.model,
            "input": (
                f"{RESUME_PARSE_SYSTEM_PROMPT}\n\n"
                f"Source ID: {source_id}\n\n"
                "Normalize the following resume text into the requested schema:\n\n"
                f"{extracted_text}"
            ),
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": NormalizedResume.model_json_schema(by_alias=True),
            },
        }
        response_text = self._post_interaction(payload)
        parsed = NormalizedResume.model_validate_json(response_text)
        return parsed.model_copy(update={"source_ids": [source_id]})

    def _post_interaction(self, payload: dict) -> str:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini API HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Gemini API request failed: {exc.reason}") from exc

        output_text = data.get("output_text")
        if not isinstance(output_text, str) or not output_text.strip():
            raise RuntimeError("Gemini API response missing output_text")
        return output_text
