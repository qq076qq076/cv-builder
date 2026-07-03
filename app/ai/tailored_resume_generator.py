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


class TailoredResumeGenerator(Protocol):
    def generate(
        self,
        *,
        resume: NormalizedResume,
        job: TrackedJob,
        job_page_text: str = "",
    ) -> str:
        pass


class OpenAITailoredResumeGenerator:
    def __init__(self, *, api_key: str, model: str, log_path: Path | None = None) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.log_path = log_path

    def generate(
        self,
        *,
        resume: NormalizedResume,
        job: TrackedJob,
        job_page_text: str = "",
    ) -> str:
        messages = [
            {"role": "system", "content": TAILORED_RESUME_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_tailored_resume_prompt(
                    resume=resume,
                    job=job,
                    job_page_text=job_page_text,
                ),
            },
        ]
        _debug_log_ai_payload(
            "OpenAI tailored resume input",
            {"model": self.model, "messages": messages},
            self.log_path,
        )
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        content = completion.choices[0].message.content or ""
        _debug_log_ai_payload("OpenAI tailored resume output", content, self.log_path)
        return _normalize_tailored_resume(content)


class GeminiTailoredResumeGenerator:
    def __init__(self, *, api_key: str, model: str, log_path: Path | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.log_path = log_path

    def generate(
        self,
        *,
        resume: NormalizedResume,
        job: TrackedJob,
        job_page_text: str = "",
    ) -> str:
        payload = {
            "model": self.model,
            "input": build_tailored_resume_prompt(
                resume=resume,
                job=job,
                job_page_text=job_page_text,
            ),
        }
        _debug_log_ai_payload("Gemini tailored resume input", payload, self.log_path)
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
            _debug_log_ai_payload("Gemini tailored resume error output", detail, self.log_path)
            raise RuntimeError(f"Gemini API HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Gemini API request failed: {exc.reason}") from exc

        _debug_log_ai_payload("Gemini tailored resume raw output", data, self.log_path)
        content = _extract_gemini_text(data)
        _debug_log_ai_payload("Gemini tailored resume output", content, self.log_path)
        return _normalize_tailored_resume(content)


TAILORED_RESUME_SYSTEM_PROMPT = """You write concise, truthful, tailored resumes.
Rules:
- Write in Traditional Chinese.
- Return Markdown only.
- Tailor the resume to the target job description, company/product traits, and job metadata.
- Use resume facts only. Do not invent employers, metrics, degrees, achievements, certificates, dates, or contact details.
- If a resume section has no source facts, omit that section instead of fabricating content.
- Prefer the most relevant skills, experiences, projects, education, certificates, and languages for the target job.
- Keep the result scannable for recruiters and ATS-friendly.
"""


def build_tailored_resume_prompt(
    *,
    resume: NormalizedResume,
    job: TrackedJob,
    job_page_text: str = "",
) -> str:
    resume_payload = resume.model_dump(mode="json", by_alias=True)
    job_payload = job.model_dump(mode="json", by_alias=True)
    normalized_job_page_text = job_page_text.strip()
    return (
        "請根據以下履歷內容與目標職缺資訊，產生一份專用履歷 Markdown。"
        "需求：繁體中文、專業、精簡、容易掃讀，且必須為該職缺量身挑選內容。"
        "請根據職缺頁面內容判斷職責、技術棧、產業、產品與公司需求，再從履歷中挑選最相關的摘要、技能、經歷與專案。"
        "嚴格限制：只能使用履歷內容中已存在的真實資訊；不得新增不存在的公司、職稱、年資、量化成果、學歷、證照、語言或聯絡方式。"
        "如果某個履歷區塊沒有資料，請直接省略該區塊，不要補寫。"
        "建議輸出結構：# 姓名、## 專業摘要、## 核心技能、## 工作經歷、## 專案經驗、## 學歷、## 證照、## 語言能力、## 聯絡方式。"
        "目標職缺資訊："
        f"{json.dumps(job_payload, ensure_ascii=False, indent=2, default=str)}"
        "目標職缺網址："
        f"{job.url}"
        "職缺頁面擷取內容（若為空，代表系統無法讀取頁面，仍需根據 URL、公司與職缺標題盡量客製）："
        f"{normalized_job_page_text or '(未能擷取職缺頁面內容)'}"
        "履歷內容："
        f"{json.dumps(resume_payload, ensure_ascii=False, indent=2, default=str)}"
    )


def _normalize_tailored_resume(content: str) -> str:
    normalized = content.strip()
    if not normalized:
        raise RuntimeError("AI returned empty tailored resume")
    return normalized
