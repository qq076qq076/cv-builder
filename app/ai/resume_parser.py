from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib import request
from urllib.error import HTTPError, URLError

from openai import OpenAI

from app.schemas.resume import NormalizedResume


RESUME_PARSE_SYSTEM_PROMPT = """You normalize resume text into structured career data.
Rules:
- Preserve facts from the input only.
- Do not invent companies, dates, skills, degrees, links, or achievements.
- If a field is not present, return an empty string or empty list.
- Keep original language where possible.
- Use concise summaries.
- Extract every visible section. Do not stop after the header.
- If the resume contains SKILLS, EXPERIENCE, EDUCATION, PROJECTS, or Languages sections,
  the corresponding JSON arrays must not be empty.
"""

RESUME_JSON_TEMPLATE = """Return a JSON object with this exact shape:
{
  "schemaVersion": 1,
  "sourceIds": ["<provided source id>"],
  "name": "",
  "title": "",
  "summary": "",
  "autobiography": "",
  "contact": {
    "email": "",
    "phone": "",
    "location": "",
    "links": []
  },
  "skills": [],
  "experiences": [
    {
      "company": "",
      "title": "",
      "startDate": "",
      "endDate": "",
      "summary": "",
      "achievements": [],
      "technologies": []
    }
  ],
  "projects": [
    {
      "name": "",
      "role": "",
      "description": "",
      "technologies": [],
      "outcomes": []
    }
  ],
  "education": [
    {
      "school": "",
      "degree": "",
      "major": "",
      "startDate": "",
      "endDate": ""
    }
  ],
  "certificates": [],
  "languages": [
    {
      "name": "",
      "proficiency": ""
    }
  ],
  "updatedAt": null
}
"""

RESUME_EXTRACTION_CHECKLIST = """Extraction checklist:
- Header: name, title, professional summary, location, email, phone, links.
- Skills: include every listed skill, including Frontend, Backend, Tools, Languages,
  testing, DevOps, AI tools, and design tools.
- Experience: create one item per job. Preserve company, title, dates, summaries,
  achievements, and technologies when mentioned.
- Projects: create one item per project. Preserve URLs inside links/outcomes/description.
- Education: create one item per school/degree/major.
- Languages: extract human language proficiency such as Mandarin (Native), English (Intermediate).
"""


class ResumeParser(Protocol):
    def parse(self, *, extracted_text: str, source_id: str) -> NormalizedResume:
        pass

    def parse_file(
        self,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
        source_id: str,
    ) -> NormalizedResume:
        pass


class OpenAIResumeParser:
    def __init__(self, *, api_key: str, model: str, log_path: Path | None = None) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.log_path = log_path

    def parse(self, *, extracted_text: str, source_id: str) -> NormalizedResume:
        messages = [
            {"role": "system", "content": RESUME_PARSE_SYSTEM_PROMPT},
            {"role": "user", "content": build_resume_parse_prompt(source_id, extracted_text)},
        ]
        _debug_log_ai_payload(
            "OpenAI input",
            {"model": self.model, "messages": messages},
            self.log_path,
        )
        completion = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=messages,
            response_format=NormalizedResume,
        )

        parsed = completion.choices[0].message.parsed
        if parsed is None:
            _debug_log_ai_payload("OpenAI output", None, self.log_path)
            return NormalizedResume(sourceIds=[source_id])

        _debug_log_ai_payload(
            "OpenAI output",
            parsed.model_dump(mode="json", by_alias=True),
            self.log_path,
        )
        return parsed.model_copy(update={"source_ids": [source_id]})

    def parse_file(
        self,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
        source_id: str,
    ) -> NormalizedResume:
        prompt = build_resume_file_prompt(source_id)
        file_data = _file_data_url(content_type, content)
        messages = [
            {"role": "system", "content": RESUME_PARSE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "file",
                        "file": {
                            "filename": filename,
                            "file_data": file_data,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            },
        ]
        _debug_log_ai_payload(
            "OpenAI input",
            {"model": self.model, "messages": messages},
            self.log_path,
        )
        completion = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=messages,
            response_format=NormalizedResume,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            _debug_log_ai_payload("OpenAI output", None, self.log_path)
            return NormalizedResume(sourceIds=[source_id])

        _debug_log_ai_payload(
            "OpenAI output",
            parsed.model_dump(mode="json", by_alias=True),
            self.log_path,
        )
        return parsed.model_copy(update={"source_ids": [source_id]})


class GeminiResumeParser:
    def __init__(self, *, api_key: str, model: str, log_path: Path | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.log_path = log_path

    def parse(self, *, extracted_text: str, source_id: str) -> NormalizedResume:
        payload = {
            "model": self.model,
            "input": build_resume_parse_prompt(source_id, extracted_text),
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": NormalizedResume.model_json_schema(by_alias=True),
            },
        }
        _debug_log_ai_payload("Gemini input", payload, self.log_path)
        response_text = self._post_interaction(payload)
        _debug_log_ai_payload("Gemini extracted output", response_text, self.log_path)
        parsed = NormalizedResume.model_validate_json(response_text)
        return parsed.model_copy(update={"source_ids": [source_id]})

    def parse_file(
        self,
        *,
        filename: str,
        content_type: str | None,
        content: bytes,
        source_id: str,
    ) -> NormalizedResume:
        prompt = build_resume_file_prompt(source_id)
        payload = {
            "model": self.model,
            "input": [
                {
                    "type": "document",
                    "data": base64.b64encode(content).decode("utf-8"),
                    "mime_type": content_type or _guess_content_type(filename),
                },
                {"type": "text", "text": prompt},
            ],
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": NormalizedResume.model_json_schema(by_alias=True),
            },
        }
        _debug_log_ai_payload("Gemini input", payload, self.log_path)
        response_text = self._post_interaction(payload)
        _debug_log_ai_payload("Gemini extracted output", response_text, self.log_path)
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
                _debug_log_ai_payload("Gemini raw output", data, self.log_path)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            _debug_log_ai_payload("Gemini error output", detail, self.log_path)
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


def build_resume_parse_prompt(source_id: str, extracted_text: str) -> str:
    return (
        f"Source ID: {source_id}\n\n"
        f"{RESUME_JSON_TEMPLATE}\n"
        f"{RESUME_EXTRACTION_CHECKLIST}\n"
        "Normalize the following resume text into the requested JSON schema. "
        "Return only JSON, no markdown.\n\n"
        f"{extracted_text}"
    )


def build_resume_file_prompt(source_id: str) -> str:
    return (
        f"Source ID: {source_id}\n\n"
        f"{RESUME_JSON_TEMPLATE}\n"
        f"{RESUME_EXTRACTION_CHECKLIST}\n"
        "Analyze the attached resume file directly. "
        "Use the visual document content and text in the file. "
        "Return only JSON, no markdown."
    )


def _debug_log_ai_payload(label: str, payload: object, log_path: Path | None = None) -> None:
    print(f"\n[AI DEBUG] {label}", flush=True)
    if isinstance(payload, str):
        print(payload, flush=True)
        serializable_payload = payload
    else:
        serializable_payload = payload
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), flush=True)

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as file:
            file.write(
                json.dumps(
                    {
                        "createdAt": datetime.now(timezone.utc).isoformat(),
                        "label": label,
                        "payload": serializable_payload,
                    },
                    ensure_ascii=False,
                    default=str,
                )
            )
            file.write("\n")


def _file_data_url(content_type: str | None, content: bytes) -> str:
    encoded_content = base64.b64encode(content).decode("utf-8")
    return f"data:{content_type or 'application/octet-stream'};base64,{encoded_content}"


def _guess_content_type(filename: str) -> str:
    if filename.lower().endswith(".pdf"):
        return "application/pdf"
    return "text/plain"
