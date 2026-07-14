# cv-builder

cv-builder 是一個本機優先的 AI 職涯資料與履歷輔助工具。它可以把履歷檔案、LinkedIn/104/Cake/Yourator 等公開資料來源整理成結構化的 career profile，並依照職缺 URL 產生客製化履歷草稿與 cover letter。

資料預設儲存在本機 `workspace/`，API key 只透過環境變數讀取，不會寫入 workspace。

## 主要功能

- 建立多個角色 profile，例如不同求職方向或不同版本履歷。
- 匯入 PDF、DOCX、TXT、Markdown 履歷檔。
- 登錄平台 profile URL，並在解析前抓取 URL 內容作為 evidence。
- 使用 OpenAI 或 Gemini 將來源資料正規化成結構化履歷。
- 在角色頁面手動編輯個人摘要、經歷、學歷、專案、技能、聯絡方式與語言能力。
- 新增職缺 URL，會讀取職缺頁內容並以 AI 計算履歷吻合度。
- 每個職缺提供「履歷」、「推薦信」、「建議」三個按鈕；建議包含五項面試準備與五項履歷／經歷調整建議，生成後可在 popup 查看並重新生成。
- LinkedIn、104、Cake、Yourator 等 URL 透過 Playwright 抓取 JS render 後的內容。

## 技術架構

- Python 3.13.14（專案 `.python-version` 指定版本；`pyproject.toml` 最低需求為 3.12）
- FastAPI
- Jinja templates
- Pydantic
- file-based JSON storage
- OpenAI / Gemini API
- Playwright for JavaScript-rendered profile pages and PDF export

## 環境變數

先複製 `.env.example`：

```bash
cp .env.example .env
```

`.env` 常用設定：

```env
CV_BUILDER_WORKSPACE=./workspace

OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini

GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash
```

說明：

- `CV_BUILDER_WORKSPACE`：本機資料儲存位置，預設可使用 `./workspace`。
- `OPENAI_API_KEY` / `GEMINI_API_KEY`：任一存在即可啟用 AI 解析與生成；兩者都存在時程式優先使用 OpenAI。

上傳檔案限制為 10 MB，支援 PDF、DOCX、TXT 與 Markdown；AI 服務呼叫有明確 timeout，OpenAI 會自動重試暫時性錯誤。

## 安裝

建議先用 `pyenv` 安裝並固定 Python 版本，避免不同專案之間的 Python 版本互相影響：

```bash
pyenv install 3.13.14
pyenv local 3.13.14
python --version
```

確認 Python 版本為 3.13.14 後，再安裝依賴。

建議使用 `uv` 管理依賴。`uv` 不是 Python 內建指令，若出現 `zsh: command not found: uv`，請先安裝：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

安裝後重新開啟 terminal，或依安裝訊息把 `uv` 加進 `PATH`，再確認：

```bash
uv --version
```

接著安裝專案依賴：

```bash
uv sync
uv run playwright install chromium
```

如果不想安裝 `uv`，也可以只用 Python 內建 venv 與 pip：

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
python -m playwright install chromium
```

若要執行測試與 lint，還需要安裝 dev dependency：

```bash
uv sync --group dev
```

若使用 pip，請另外安裝測試工具：

```bash
pip install pytest ruff httpx
```

## 啟動

使用 `uv`：

```bash
uv run uvicorn app.main:app --reload
```

使用 venv：

```bash
. .venv/bin/activate
uvicorn app.main:app --reload
```

啟動後開啟：

```txt
http://127.0.0.1:8000
```

健康檢查：

```txt
http://127.0.0.1:8000/health
```

## 使用流程

1. 開啟首頁，建立角色 profile。
2. 在角色頁新增來源：上傳履歷檔，或填入 LinkedIn、104、Cake、Yourator 等 URL。
3. 點擊解析來源，系統會抓取來源內容並呼叫 OpenAI 或 Gemini 轉成結構化履歷。
4. 在角色頁檢查並手動修正履歷內容。
5. 新增職缺 URL。
6. 新增職缺後，系統會抓取職缺頁文字並交給 AI 計算履歷吻合度。
7. 在職缺卡片點擊「履歷」、「推薦信」或「建議」生成內容；生成後按鈕會開啟 popup，popup 右上角可重新生成。專用履歷會同步輸出 PDF。

## JSON API

目前頁面仍由 FastAPI 與 Jinja server-side rendering 提供；長時間執行的生成任務已提供 JSON API，讓未來的獨立前端或其他客戶端可以共用同一個任務合約。

- `POST /roles/{role_id}/jobs/{job_id}/generation-tasks`：以 `multipart/form-data` 送出 `kind=resume` 或 `kind=cover_letter`，回傳 `202 Accepted` 與排入佇列的 `task`。
- `GET /roles/{role_id}/generation-tasks`：取得角色下全部生成任務。
- `POST /roles/{role_id}/jobs/{job_id}/generation-tasks/cancel`：以 `multipart/form-data` 送出 `kind`，取消進行中的同類任務。
- `POST /roles/{role_id}/jobs/{job_id}/generation-tasks/retry`：以 `multipart/form-data` 送出 `kind`，重新排入失敗任務。

應用程式啟動時會將上一次程序中斷而仍停留在 `queued` 或 `running` 的任務標記為失敗，避免任務永久卡住；角色頁面可直接重試失敗任務。

舊的 `POST /roles/{role_id}/jobs/{job_id}/generate` 仍保留給 HTML 表單使用，並維持 redirect 行為。

## URL 抓取注意事項

LinkedIn、104、Cake、Yourator 這類 profile 或職缺 URL 會使用 Playwright 開啟 Chromium，等待 JavaScript render 後再抓取頁面文字。若出現 timeout 或抓不到資料，優先檢查：

- 是否已執行 `python -m playwright install chromium`。
- 該頁面是否公開可讀，不需要登入或驗證。
- 網站是否有防爬、cookie consent、地區限制或其他阻擋。
- 重新解析來源，讓系統用最新抓取邏輯更新 evidence 檔。

為避免本機服務被利用去抓取內部資源，URL 抓取只接受 http/https，並拒絕 localhost、內部網域與私有／保留 IP 位址。

## 測試

```bash
uv run pytest
```

或：

```bash
. .venv/bin/activate
python -m pytest
```

也可以只跑目前核心服務相關測試：

```bash
python -m unittest tests.test_url_fetcher tests.test_resume_normalization_service
```

## Lint

```bash
uv run ruff check .
```

## 資料目錄

預設資料會存放在：

```txt
workspace/
```

每個角色會有自己的資料夾，包含 evidence、profile、解析後的 resume JSON、生成輸出等檔案。這些都是本機檔案，方便備份或用 Git 管理，但請不要提交 `.env` 或任何 API key。
