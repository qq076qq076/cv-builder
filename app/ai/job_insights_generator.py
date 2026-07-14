from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol
from urllib import request
from urllib.error import HTTPError, URLError

from openai import OpenAI

from app.ai import AI_REQUEST_TIMEOUT_SECONDS
from app.ai.cover_letter_generator import _extract_gemini_text
from app.ai.resume_parser import _debug_log_ai_payload
from app.schemas.job import TrackedJob
from app.schemas.resume import NormalizedResume


class JobInsightsGenerator(Protocol):
    def evaluate(self, *, resume: NormalizedResume, job: TrackedJob, job_page_text: str = "") -> dict: ...
    def generate_suggestions(self, *, resume: NormalizedResume, job: TrackedJob, job_page_text: str = "") -> str: ...
    def generate_interview_prep(self, *, resume: NormalizedResume, job: TrackedJob, job_page_text: str = "") -> str: ...


SYSTEM_PROMPT = """你是求職顧問。所有輸出使用繁體中文。只能根據提供的職缺與履歷，不得捏造經歷。
評估時回傳 JSON：{"score": 0到100的整數}。
建議時回傳 JSON：{"interview_preparation": 五個字串, "resume_adjustments": 五個字串}。兩個陣列都必須剛好五項。"""

INTERVIEW_PREP_SYSTEM_PROMPT = """你是資深面試教練。所有輸出使用繁體中文，只能根據提供的履歷與職缺，不得捏造經歷。
請產生 8 題面試題，每個分類 2 題：technical、behavioral、management、project_deep_dive。
每題都必須包含 question、why_it_matters，以及 star_answer；star_answer 必須包含 situation、task、action、result。
如果履歷沒有足夠資料，對應 STAR 欄位請明確寫「需要候選人補充」，不要自行編造。
只回傳 JSON，格式為四個分類各自包含兩個題目。"""


def build_insights_prompt(*, action: str, resume: NormalizedResume, job: TrackedJob, job_page_text: str = "") -> str:
    return (
        f"請執行 action={action}。職缺資料：{json.dumps(job.model_dump(mode='json', by_alias=True), ensure_ascii=False, default=str)}\n"
        f"職缺頁面內容：{job_page_text.strip() or '(無法擷取)'}\n"
        f"履歷資料：{json.dumps(resume.model_dump(mode='json', by_alias=True), ensure_ascii=False, default=str)}\n"
        "只回傳要求的 JSON，不要 markdown。"
    )


def build_interview_prep_prompt(*, resume: NormalizedResume, job: TrackedJob, job_page_text: str = "") -> str:
    return build_insights_prompt(action="interview_prep", resume=resume, job=job, job_page_text=job_page_text)


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
        self.client, self.model, self.log_path = (
            OpenAI(
                api_key=api_key,
                timeout=AI_REQUEST_TIMEOUT_SECONDS,
                max_retries=2,
            ),
            model,
            log_path,
        )

    def _json(self, *, action: str, resume, job, job_page_text, system_prompt: str = SYSTEM_PROMPT) -> dict:
        messages = [
            {"role": "system", "content": system_prompt},
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

    def generate_interview_prep(self, *, resume, job, job_page_text="") -> str:
        data = self._json(
            action="interview_prep",
            resume=resume,
            job=job,
            job_page_text=job_page_text,
            system_prompt=INTERVIEW_PREP_SYSTEM_PROMPT,
        )
        return _build_interview_prep_markdown(data)


class GeminiJobInsightsGenerator(OpenAIJobInsightsGenerator):
    def __init__(self, *, api_key: str, model: str, log_path: Path | None = None) -> None:
        self.api_key, self.model, self.log_path = api_key, model, log_path

    def _json(
        self,
        *,
        action: str,
        resume,
        job,
        job_page_text,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> dict:
        payload = {
            "model": self.model,
            "input": f"{system_prompt}\n{build_insights_prompt(action=action, resume=resume, job=job, job_page_text=job_page_text)}",
        }
        _debug_log_ai_payload("Gemini job insights input", payload, self.log_path)
        req = request.Request(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=AI_REQUEST_TIMEOUT_SECONDS) as response:
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


def _build_interview_prep_markdown(data: dict) -> str:
    category_labels = {
        "technical": "技術問題",
        "behavioral": "行為問題",
        "management": "管理能力問題",
        "project_deep_dive": "專案深挖問題",
    }
    sections: list[str] = []
    for category, label in category_labels.items():
        questions = data.get(category)
        if not isinstance(questions, list) or len(questions) != 2:
            raise RuntimeError(f"AI 面試準備的{label}必須剛好提供兩題")
        lines = [f"## {label}", ""]
        for index, item in enumerate(questions, 1):
            if not isinstance(item, dict):
                raise RuntimeError("AI 面試準備的題目格式無效")
            question = str(item.get("question", "")).strip()
            why = str(item.get("why_it_matters", "")).strip()
            star = item.get("star_answer")
            if not question or not why or not isinstance(star, dict):
                raise RuntimeError("AI 面試準備的題目內容不完整")
            lines.extend(
                [
                    f"### {index}. {question}",
                    "",
                    f"**考察重點：** {why}",
                    "",
                    "**STAR 回答草稿**",
                    f"- **Situation：** {str(star.get('situation', '')).strip() or '需要候選人補充'}",
                    f"- **Task：** {str(star.get('task', '')).strip() or '需要候選人補充'}",
                    f"- **Action：** {str(star.get('action', '')).strip() or '需要候選人補充'}",
                    f"- **Result：** {str(star.get('result', '')).strip() or '需要候選人補充'}",
                    "",
                ]
            )
        sections.append("\n".join(lines).rstrip())
    return "\n\n".join(sections) + "\n"
