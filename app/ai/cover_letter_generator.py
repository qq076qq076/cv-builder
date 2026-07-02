from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol
from urllib import request
from urllib.error import HTTPError, URLError

from openai import OpenAI

from app.ai.resume_parser import _debug_log_ai_payload
from app.schemas.job import TrackedJob
from app.schemas.resume import NormalizedResume


class CoverLetterGenerator(Protocol):
    def generate(self, *, resume: NormalizedResume, job: TrackedJob) -> str:
        pass


class OpenAICoverLetterGenerator:
    def __init__(self, *, api_key: str, model: str, log_path: Path | None = None) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.log_path = log_path

    def generate(self, *, resume: NormalizedResume, job: TrackedJob) -> str:
        messages = [
            {"role": "system", "content": COVER_LETTER_SYSTEM_PROMPT},
            {"role": "user", "content": build_cover_letter_prompt(resume=resume, job=job)},
        ]
        _debug_log_ai_payload(
            "OpenAI cover letter input",
            {"model": self.model, "messages": messages},
            self.log_path,
        )
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        content = completion.choices[0].message.content or ""
        _debug_log_ai_payload("OpenAI cover letter output", content, self.log_path)
        return _normalize_cover_letter(content)


class GeminiCoverLetterGenerator:
    def __init__(self, *, api_key: str, model: str, log_path: Path | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.log_path = log_path

    def generate(self, *, resume: NormalizedResume, job: TrackedJob) -> str:
        payload = {
            "model": self.model,
            "input": build_cover_letter_prompt(resume=resume, job=job),
        }
        _debug_log_ai_payload("Gemini cover letter input", payload, self.log_path)
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
            _debug_log_ai_payload("Gemini cover letter error output", detail, self.log_path)
            raise RuntimeError(f"Gemini API HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Gemini API request failed: {exc.reason}") from exc

        _debug_log_ai_payload("Gemini cover letter raw output", data, self.log_path)
        content = _extract_gemini_text(data)
        _debug_log_ai_payload("Gemini cover letter output", content, self.log_path)
        return _normalize_cover_letter(content)


COVER_LETTER_SYSTEM_PROMPT = """You write concise, tailored self-recommendation letters.
Rules:
- Write in Traditional Chinese.
- Use first person.
- Keep a professional, confident, non-exaggerated tone.
- Keep the final answer within 300 Chinese characters.
- Tailor the letter to the target job URL and job metadata.
- Use resume facts only. Do not invent employers, metrics, degrees, or achievements.
- Return only the letter body. Do not use markdown headings.
"""


def build_cover_letter_prompt(*, resume: NormalizedResume, job: TrackedJob) -> str:
    resume_payload = resume.model_dump(mode="json", by_alias=True)
    job_payload = job.model_dump(mode="json", by_alias=True)
    return (
        "請根據以下履歷內容與目標職缺資訊，產生一封自我推薦信。\n"
        "需求：語氣專業、第一人稱、300字內、為該職缺量身打造、只使用履歷中的真實資訊。\n\n"
        "目標職缺資訊：\n"
        f"{json.dumps(job_payload, ensure_ascii=False, indent=2, default=str)}\n\n"
        "目標職缺網址：\n"
        f"{job.url}\n\n"
        "履歷內容：\n"
        f"{json.dumps(resume_payload, ensure_ascii=False, indent=2, default=str)}"
    )


def _extract_gemini_text(data: object) -> str:
    if isinstance(data, dict):
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        text = _extract_text_from_steps(data.get("steps"))
        if text:
            return text

    raise RuntimeError("Gemini API response missing text output")


def _extract_text_from_steps(steps: object) -> str | None:
    if not isinstance(steps, list):
        return None
    for step in reversed(steps):
        if not isinstance(step, dict):
            continue
        content = step.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts = [
                item["text"]
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            text = "".join(parts).strip()
            if text:
                return text
    return None


def _normalize_cover_letter(content: str) -> str:
    normalized = content.strip()
    if not normalized:
        raise RuntimeError("AI returned empty cover letter")
    return normalized
