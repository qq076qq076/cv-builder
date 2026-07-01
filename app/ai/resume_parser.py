from __future__ import annotations

from openai import OpenAI

from app.schemas.resume import NormalizedResume


RESUME_PARSE_SYSTEM_PROMPT = """You normalize resume text into structured career data.
Rules:
- Preserve facts from the input only. Do not invent companies, dates, skills, degrees, links, or achievements.
- If a field is not present, return an empty string or empty list.
- Keep original language where possible.
- Use concise summaries.
"""


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

