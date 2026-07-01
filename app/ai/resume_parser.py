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

        return _extract_gemini_response_json(data)


def _extract_gemini_response_json(data: object) -> str:
    if isinstance(data, dict):
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        step_text = _extract_text_from_steps(data.get("steps"))
        if step_text is not None:
            return step_text

        if _looks_like_resume_payload(data):
            return json.dumps(data)

    raise RuntimeError("Gemini API response missing structured JSON output")


def _extract_text_from_steps(steps: object) -> str | None:
    if not isinstance(steps, list):
        return None

    for step in reversed(steps):
        if not isinstance(step, dict):
            continue
        content = step.get("content")
        text = _extract_text_from_content(content)
        if text is not None:
            return text

    return None


def _extract_text_from_content(content: object) -> str | None:
    if isinstance(content, str) and content.strip():
        return content
    if not isinstance(content, list):
        return None

    parts = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    text = "".join(parts).strip()
    return text or None


def _looks_like_resume_payload(data: dict) -> bool:
    resume_fields = {
        "schemaVersion",
        "sourceIds",
        "name",
        "title",
        "summary",
        "autobiography",
        "contact",
        "skills",
        "experiences",
        "projects",
        "education",
        "certificates",
        "languages",
        "updatedAt",
    }
    return any(field in data for field in resume_fields)
