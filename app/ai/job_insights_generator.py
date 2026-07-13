from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol
from urllib import request
from urllib.error import HTTPError, URLError

from openai import OpenAI

from app.ai.cover_letter_generator import _extract_gemini_text
from app.ai.resume_parser import _debug_log_ai_payload
from app.schemas.job import TrackedJob
from app.schemas.resume import NormalizedResume


class JobInsightsGenerator(Protocol):
    def evaluate(self, *, resume: NormalizedResume, job: TrackedJob, job_page_text: str = "") -> dict: ...
    def generate_suggestions(self, *, resume: NormalizedResume, job: TrackedJob, job_page_text: str = "") -> str: ...


SYSTEM_PROMPT = """你是求職顧問。所有輸出使用繁體中文。只能根據提供的職缺與履歷，不得捏造經歷。
評估時回傳 JSON：{"score": 0到100的整數}。
建議時回傳 JSON：{"interview_preparation": 五個字串, "resume_adjustments": 五個字串}。兩個陣列都必須剛好五項。"""


def build_insights_prompt(*, action: str, resume: NormalizedResume, job: TrackedJob, job_page_text: str = "") -> str:
    return (
        f"請執行 action={action}。職缺資料：{json.dumps(job.model_dump(mode='json', by_alias=True), ensure_ascii=False, default=str)}\n"
        f"職缺頁面內容：{job_page_text.strip() or '(無法擷取)'}\n"
        f"履歷資料：{json.dumps(resume.model_dump(mode='json', by_alias=True), ensure_ascii=False, default=str)}\n"
        "只回傳要求的 JSON，不要 markdown。"
    )


def _parse_json_response(content: str) -> dict:
    normalized = content.strip().removeprefix("```json").removesuffix("```").strip()
    try:
        data = json.loads(normalized)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("AI 回傳的職缺分析格式無效") from exc
    if not isinstance(data, dict):
        raise RuntimeError("AI 回傳的職缺分析格式無效")
    return data


class OpenAIJobInsightsGenerator:
    def __init__(self, *, api_key: str, model: str, log_path: Path | None = None) -> None:
        self.client, self.model, self.log_path = OpenAI(api_key=api_key), model, log_path

    def _json(self, *, action: str, resume, job, job_page_text) -> dict:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_insights_prompt(
                    action=action,
                    resume=resume,
                    job=job,
                    job_page_text=job_page_text,
                ),
            },
        ]
        _debug_log_ai_payload("OpenAI job insights input", {"model": self.model, "messages": messages}, self.log_path)
        result = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        content = result.choices[0].message.content or ""
        _debug_log_ai_payload("OpenAI job insights output", content, self.log_path)
        return _parse_json_response(content)

    def evaluate(self, *, resume, job, job_page_text="") -> dict:
        data = self._json(action="evaluate", resume=resume, job=job, job_page_text=job_page_text)
        try:
            score = max(0, min(100, int(data["score"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("AI 回傳的職缺吻合度格式無效") from exc
        return {"score": score}

    def generate_suggestions(self, *, resume, job, job_page_text="") -> str:
        data = self._json(action="suggestions", resume=resume, job=job, job_page_text=job_page_text)
        interview = [str(item) for item in data.get("interview_preparation", [])][:5]
        adjustments = [str(item) for item in data.get("resume_adjustments", [])][:5]
        if len(interview) != 5 or len(adjustments) != 5:
            raise RuntimeError("AI 建議必須各提供五項內容")
        return (
            "## 面試建議準備項目\n\n"
            + "\n".join(f"{i}. {item}" for i, item in enumerate(interview, 1))
            + "\n\n## 履歷＆經歷建議調整項目\n\n"
            + "\n".join(f"{i}. {item}" for i, item in enumerate(adjustments, 1))
        )


class GeminiJobInsightsGenerator(OpenAIJobInsightsGenerator):
    def __init__(self, *, api_key: str, model: str, log_path: Path | None = None) -> None:
        self.api_key, self.model, self.log_path = api_key, model, log_path

    def _json(self, *, action: str, resume, job, job_page_text) -> dict:
        payload = {
            "model": self.model,
            "input": f"{SYSTEM_PROMPT}\n{build_insights_prompt(action=action, resume=resume, job=job, job_page_text=job_page_text)}",
        }
        _debug_log_ai_payload("Gemini job insights input", payload, self.log_path)
        req = request.Request(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            with request.urlopen(req) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            _debug_log_ai_payload("Gemini job insights error output", detail, self.log_path)
            raise RuntimeError(f"Gemini API HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Gemini API request failed: {exc.reason}") from exc
        content = _extract_gemini_text(data)
        _debug_log_ai_payload("Gemini job insights output", content, self.log_path)
        return _parse_json_response(content)
