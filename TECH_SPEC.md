# AI Career Copilot - 技術規格文件

本文件對應 `PRD.md` 的 local-first MVP 方向，採用方案 A：

> Python + FastAPI + Pydantic + file-based JSON storage + Jinja/HTMX

目標是讓使用者 clone 專案後，可以在自己的電腦上用最少環境建置成本啟動，不需要登入、不需要外部資料庫、不需要 Docker Compose 才能使用核心功能。

---

# 技術目標

## 核心原則

- Local-first：資料預設只存在使用者本機。
- No database server：第一版不使用 Postgres、MySQL、MongoDB 等外部資料庫。
- File-based storage：使用 JSON / Markdown / 原始上傳檔案作為資料儲存格式。
- Simple setup：以 `pip install` / `uv sync` + `uvicorn` 啟動為主。
- Server-rendered UI first：第一版不做前後端分離，降低建置與部署成本。
- AI provider replaceable：AI 呼叫需包在 adapter 後面，避免綁死單一 provider。
- Schema-first：核心資料結構用 Pydantic model 定義，檔案資料需包含 `schemaVersion`。

---

# 技術選型

## Runtime

- Python 3.12+

## Web Framework

- FastAPI
- Uvicorn
- Jinja2
- HTMX

## Data Model

- Pydantic v2

## Storage

- 本機檔案系統
- JSON：結構化資料
- Markdown：生成輸出、可讀履歷內容
- 原始檔案：上傳履歷、作品集、來源文件

## 文件解析

- PDF：`pypdf`，必要時再評估 `pdfplumber`
- DOCX：`python-docx`
- Markdown：直接讀取文字
- TXT：直接讀取文字

## AI

- OpenAI SDK 作為第一個 provider
- AI 呼叫需經過 `AIClient` interface
- Prompt template 不直接散落在 route handler 中

## Export

- Markdown：直接輸出 `.md`
- PDF：MVP 可先使用 HTML template 轉 PDF；若環境複雜，第一階段可先提供 Markdown，再將 PDF 放到後續
- DOCX：第二階段再加入

## Dev Tooling

- Package manager：建議使用 `uv`
- Formatting：`ruff format`
- Lint：`ruff check`
- Test：`pytest`
- Type check：`mypy` 或 `pyright`，可在核心穩定後加入

---

# 專案目錄結構

```txt
cv-builder/
  app/
    __init__.py
    main.py
    config.py

    routes/
      __init__.py
      dashboard.py
      workspace.py
      import_files.py
      career.py
      jobs.py
      generate.py
      export.py

    schemas/
      __init__.py
      career.py
      evidence.py
      job.py
      resume.py
      workspace.py

    storage/
      __init__.py
      paths.py
      repository.py
      atomic.py
      workspace.py

    importers/
      __init__.py
      base.py
      pdf.py
      docx.py
      markdown.py
      text.py

    ai/
      __init__.py
      client.py
      openai_client.py
      prompts/
        parse_career.md
        analyze_job.md
        generate_resume.md
        generate_cover_letter.md
        generate_interview_prep.md

    services/
      __init__.py
      career_service.py
      import_service.py
      job_service.py
      generation_service.py
      export_service.py

    templates/
      base.html
      dashboard.html
      workspace.html
      import.html
      career.html
      jobs.html
      resume_preview.html

    static/
      css/
        app.css
      js/
        app.js

  tests/
    storage/
    importers/
    services/

  workspace.example/
    career.json
    evidence/
      sources.json
      files/
    jobs/
    outputs/
    versions/

  PRD.md
  TECH_SPEC.md
  README.md
  pyproject.toml
  .env.example
```

---

# 本機工作區規格

## 預設位置

第一版可以使用專案根目錄下的 `workspace/` 作為預設工作區。

未來可支援使用者指定任意資料夾，例如：

```bash
CV_BUILDER_WORKSPACE=/Users/me/career-workspace
```

---

## 工作區結構

```txt
workspace/
  career.json
  metadata.json
  evidence/
    sources.json
    files/
      original-resume.pdf
      resume.docx
  jobs/
    frontend-engineer-2026-06-30.json
  outputs/
    frontend-engineer-resume.md
    frontend-engineer-cover-letter.md
    frontend-engineer-interview-prep.md
  versions/
    2026-06-30T120000-career.json
    2026-06-30T121500-resume.json
```

---

## 寫入規則

所有重要 JSON 寫入都必須：

- 使用 atomic write。
- 寫入前通過 Pydantic validation。
- 包含 `schemaVersion`。
- 寫入失敗時保留原檔。
- 生成重要輸出前建立版本快照。

Atomic write 流程：

1. 寫入同目錄暫存檔。
2. flush。
3. fsync。
4. rename 覆蓋正式檔案。

---

# 啟動與首頁狀態流程

專案啟動後，首頁 `/` 不應只是靜態頁面，而是根據本機工作區資料狀態決定畫面。

## 啟動檢查流程

```txt
啟動 FastAPI app
  ↓
讀取 CV_BUILDER_WORKSPACE，沒有設定時使用 ./workspace
  ↓
檢查 workspace 目錄是否存在
  ↓
不存在：顯示 NO_WORKSPACE 狀態，提示建立本機工作區
  ↓
存在：檢查 career.json、evidence/sources.json、jobs/、outputs/
  ↓
沒有使用者資料：顯示 EMPTY_WORKSPACE 狀態，提示上傳履歷或手動輸入
  ↓
有職涯資料：顯示 HAS_CAREER_DATA 狀態，呈現職涯知識庫摘要與可用功能
  ↓
有生成輸出：顯示 HAS_GENERATED_OUTPUTS 狀態，額外呈現已生成履歷、推薦信、面試準備
```

---

## Workspace 狀態

系統需定義明確狀態，供 Dashboard、routes、tests 共用。

```python
class WorkspaceStatus(str, Enum):
    NO_WORKSPACE = "no_workspace"
    EMPTY_WORKSPACE = "empty_workspace"
    HAS_CAREER_DATA = "has_career_data"
    HAS_GENERATED_OUTPUTS = "has_generated_outputs"
```

狀態判斷規則：

- `NO_WORKSPACE`：workspace 目錄不存在，或必要資料夾無法建立。
- `EMPTY_WORKSPACE`：workspace 存在，但沒有可用的 `career.json`，也沒有已匯入的 evidence source。
- `HAS_CAREER_DATA`：存在有效 `career.json`，且至少有個人資訊、工作經歷、專案、技能其中一種資料。
- `HAS_GENERATED_OUTPUTS`：符合 `HAS_CAREER_DATA`，且 `outputs/` 或版本紀錄中存在已生成履歷、推薦信或面試準備。

---

## 首頁行為

`GET /` 應透過 `DashboardService` 取得 workspace status，並依狀態顯示不同內容。

### NO_WORKSPACE

顯示：

- 目前找不到本機工作區
- 建立預設工作區按鈕
- 選擇既有工作區說明

主要 CTA：

- 建立工作區

---

### EMPTY_WORKSPACE

顯示：

- 工作區已建立，但尚未有職涯資料
- 支援匯入格式：PDF / DOCX / TXT / Markdown
- 可改用手動輸入建立資料

主要 CTA：

- 上傳履歷
- 手動輸入職涯資料

---

### HAS_CAREER_DATA

顯示：

- 個人資訊摘要
- 工作經歷數量
- 專案數量
- 技能數量
- 已匯入來源列表
- 最近更新時間

主要 CTA：

- 編輯職涯知識庫
- 貼上目標職缺
- 生成履歷

---

### HAS_GENERATED_OUTPUTS

在 `HAS_CAREER_DATA` 的內容之外，額外顯示：

- 已生成履歷列表
- 已生成 Cover Letter 列表
- 已生成面試準備列表
- 最近生成時間
- 下載 / 預覽入口

主要 CTA：

- 預覽履歷
- 下載輸出
- 針對新職缺生成版本

---

# 核心資料模型

## Career Knowledge Base

```json
{
  "schemaVersion": 1,
  "profile": {
    "name": "string",
    "title": "string",
    "email": "string",
    "phone": "string",
    "location": "string"
  },
  "experiences": [],
  "projects": [],
  "skills": [],
  "education": [],
  "certificates": [],
  "languages": [],
  "updatedAt": "2026-06-30T12:00:00+08:00"
}
```

---

## Evidence Source

```json
{
  "schemaVersion": 1,
  "sources": [
    {
      "id": "src_001",
      "type": "uploaded_file",
      "label": "104 resume PDF",
      "path": "evidence/files/resume.pdf",
      "createdAt": "2026-06-30T12:00:00+08:00"
    }
  ]
}
```

---

## Job

```json
{
  "schemaVersion": 1,
  "id": "job_frontend_engineer_20260630",
  "title": "Frontend Engineer",
  "company": "Example Inc.",
  "description": "原始職缺描述",
  "requiredSkills": [],
  "niceToHaveSkills": [],
  "responsibilities": [],
  "keywords": [],
  "seniority": "Senior",
  "createdAt": "2026-06-30T12:00:00+08:00"
}
```

---

## Generated Resume

```json
{
  "schemaVersion": 1,
  "id": "resume_frontend_engineer_20260630",
  "jobId": "job_frontend_engineer_20260630",
  "language": "zh-TW",
  "style": "professional",
  "sections": [],
  "evidenceRefs": [],
  "markdownPath": "outputs/frontend-engineer-resume.md",
  "createdAt": "2026-06-30T12:00:00+08:00"
}
```

---

# 模組設計

## Routes Layer

負責 HTTP request / response，不直接讀寫檔案，不直接組 prompt。

範例：

- `GET /`：Dashboard，根據 workspace status 顯示建立工作區、上傳資料或既有資料摘要
- `GET /workspace`：工作區設定
- `POST /workspace/create`：建立工作區
- `GET /import`：匯入頁
- `POST /import/files`：上傳履歷文件
- `GET /career`：職涯知識庫編輯
- `POST /career`：儲存職涯資料
- `GET /jobs`：職缺列表
- `POST /jobs/analyze`：分析職缺
- `POST /generate/resume`：生成履歷
- `POST /generate/cover-letter`：生成推薦信
- `POST /generate/interview-prep`：生成面試準備
- `GET /export/{output_id}`：下載輸出檔

---

## Services Layer

負責業務流程。

- `DashboardService`：檢查 workspace status，組合首頁需要的摘要資料與 CTA。
- `ImportService`：解析上傳檔案，建立 evidence source。
- `CareerService`：讀寫職涯知識庫，合併 AI 解析結果。
- `JobService`：儲存職缺，呼叫 AI 解析職缺需求。
- `GenerationService`：根據 career + job 生成履歷、推薦信、面試準備。
- `ExportService`：輸出 Markdown / PDF。

---

## Storage Layer

負責本機檔案讀寫。

設計重點：

- route 不直接存取 `Path`。
- service 透過 repository 讀寫資料。
- repository 負責 schema validation。
- 所有寫入集中使用 atomic write helper。

範例 repository：

- `CareerRepository`
- `EvidenceRepository`
- `JobRepository`
- `OutputRepository`
- `VersionRepository`

---

## Importers

每種檔案格式獨立處理，對外回傳統一格式：

```python
class ImportedDocument(BaseModel):
    source_id: str
    filename: str
    content_type: str
    text: str
```

支援：

- PDF
- DOCX
- Markdown
- TXT

OCR 暫不列入 MVP 必做，可在後續新增 `ocr.py`。

---

## AI Layer

AI layer 只做三件事：

- 管理 provider client。
- 載入 prompt template。
- 將輸入與輸出轉成 Pydantic schema。

不可在 route handler 直接呼叫 OpenAI。

建議 interface：

```python
class AIClient(Protocol):
    def generate_json(self, *, prompt: str, schema: type[BaseModel]) -> BaseModel:
        ...

    def generate_text(self, *, prompt: str) -> str:
        ...
```

第一版 provider：

- `OpenAIClient`

未來可擴充：

- `AnthropicClient`
- `LocalModelClient`

---

# UI 設計方向

第一版使用 Jinja + HTMX，避免建立完整 SPA。

## 主要頁面

- Dashboard：依 workspace status 顯示首次使用引導、上傳提示、職涯資料摘要、最近生成履歷與最近職缺。
- Workspace：建立 / 選擇 / 匯出工作區。
- Import：上傳檔案並預覽解析文字。
- Career KB：編輯個人資訊、經歷、技能、專案。
- Jobs：貼上職缺描述，查看 AI 解析結果。
- Generate：選擇職缺與風格，生成履歷 / Cover Letter / 面試準備。
- Preview：預覽 Markdown / HTML。

## 前端依賴

- HTMX：局部更新與表單提交。
- 原生 CSS：先不導入大型 UI framework。
- 少量 vanilla JS：只處理檔案上傳狀態、preview toggle 等互動。

---

# 設定與環境變數

`.env.example`：

```env
CV_BUILDER_WORKSPACE=./workspace
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash
```

規則：

- `.env` 不提交 git。
- API Key 不寫入 workspace。
- `OPENAI_API_KEY` 與 `GEMINI_API_KEY` 任一存在即可啟用 AI 解析；兩者都存在時優先使用 OpenAI。
- UI 需提示 AI API 會送出哪些資料。

---

# pyproject 建議

```toml
[project]
name = "cv-builder"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi",
  "uvicorn[standard]",
  "jinja2",
  "python-multipart",
  "pydantic",
  "pydantic-settings",
  "python-dotenv",
  "openai",
  "pypdf",
  "python-docx",
]

[dependency-groups]
dev = [
  "pytest",
  "ruff",
]
```

---

# 啟動方式

建議 README 提供：

```bash
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload
```

瀏覽器開啟：

```txt
http://127.0.0.1:8000
```

---

# 測試策略

MVP 優先測核心邏輯，不追求高覆蓋率。

## 必測

- workspace status 判斷正確涵蓋 `NO_WORKSPACE`、`EMPTY_WORKSPACE`、`HAS_CAREER_DATA`、`HAS_GENERATED_OUTPUTS`。
- Dashboard 在沒有資料時顯示上傳 / 手動輸入 CTA。
- Dashboard 在有資料時顯示個人資訊、經歷、技能、專案與已生成輸出摘要。
- atomic write 不破壞原檔。
- JSON repository 可讀寫並通過 schema validation。
- importers 能處理 PDF / DOCX / TXT / Markdown。
- AI prompt 輸入組合不包含不必要資料。
- generation service 能產生 Markdown output。

## 可後補

- route integration tests。
- UI snapshot。
- PDF export visual test。

---

# MVP 實作順序

1. 建立 FastAPI app skeleton。
2. 建立 workspace path 與 atomic write。
3. 建立 workspace status 判斷與 DashboardService。
4. 建立 Pydantic schemas。
5. 建立 repositories。
6. 建立 Dashboard / Workspace 基本頁，先完成 `NO_WORKSPACE` 與 `EMPTY_WORKSPACE`。
7. 建立檔案匯入與文字抽取。
8. 建立 Career KB 編輯頁，完成 `HAS_CAREER_DATA` Dashboard。
9. 建立 Job Description 貼上與 AI 分析。
10. 建立履歷生成與 Markdown 輸出，完成 `HAS_GENERATED_OUTPUTS` Dashboard。
11. 建立 Cover Letter 與 Interview Prep 生成。
12. 建立版本快照。
13. 補基本測試與 README。

---

# 暫不處理項目

- 使用者登入
- 外部資料庫
- Docker Compose 必要化
- 多裝置同步
- 付款訂閱
- LinkedIn / 104 / CakeResume 自動登入抓取
- OCR
- 多 AI Agent 協作
- 完整 SPA 前端

---

# 未來擴充方向

若 MVP 驗證成功，可逐步加入：

- SQLite optional backend，但不可成為必要依賴。
- OCR importer。
- DOCX export。
- PDF template system。
- GitHub repo analyzer。
- 多語系 UI。
- Local LLM provider。
- Cloud sync optional mode。
