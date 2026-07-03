# cv-builder

cv-builder 是一個本機優先的 AI 職涯資料與履歷輔助工具。它可以把履歷檔案、LinkedIn/104/Cake/Yourator 等公開資料來源整理成結構化的 career profile，並依照職缺 URL 產生客製化履歷草稿與 cover letter。

資料預設儲存在本機 `workspace/`，API key 只透過環境變數讀取，不會寫入 workspace。

## 主要功能

- 建立多個角色 profile，例如不同求職方向或不同版本履歷。
- 匯入 PDF、DOCX、TXT、Markdown 履歷檔。
- 登錄平台 profile URL，並在解析前抓取 URL 內容作為 evidence。
- 使用 OpenAI 或 Gemini 將來源資料正規化成結構化履歷。
- 在角色頁面手動編輯個人摘要、經歷、學歷、專案、技能、聯絡方式與語言能力。
- 新增職缺 URL，產生專用履歷草稿或 cover letter。
- LinkedIn profile URL 透過 Apify actor 抓取，避開一般 HTTP 直接讀取容易被阻擋的問題。

## 技術架構

- Python 3.13.14（專案 `.python-version` 指定版本；`pyproject.toml` 最低需求為 3.12）
- FastAPI
- Jinja templates
- Pydantic
- file-based JSON storage
- OpenAI / Gemini API
- Apify API for LinkedIn profile crawling

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

APIFY_API_TOKEN=
APIFY_LINKEDIN_ACTOR_ID=
```

說明：

- `CV_BUILDER_WORKSPACE`：本機資料儲存位置，預設可使用 `./workspace`。
- `OPENAI_API_KEY` / `GEMINI_API_KEY`：任一存在即可啟用 AI 解析與生成；兩者都存在時程式優先使用 OpenAI。
- `APIFY_API_TOKEN`：Apify API token。
- `APIFY_LINKEDIN_ACTOR_ID`：用來抓 LinkedIn profile 的 Apify actor id，例如 `user~linkedin-profile-scraper`。
- `APIFY_LINKEDIN_INPUT_JSON`：選填。若你的 Apify actor input 不是 `profileUrls`，可用這個變數覆蓋。

例如：

```env
APIFY_LINKEDIN_INPUT_JSON={"urls":["{url}"],"proxy":{"useApifyProxy":true}}
```

`{url}` 會在執行時替換成使用者輸入的 LinkedIn profile URL。

## 安裝

建議先用 `pyenv` 安裝並固定 Python 版本，避免不同專案之間的 Python 版本互相影響：

```bash
pyenv install 3.13.14
pyenv local 3.13.14
python --version
```

確認 Python 版本為 3.13.14 後，再安裝依賴。

建議使用 `uv`：

```bash
uv sync
```

如果不用 `uv`，也可以用 Python 內建 venv：

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
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
6. 產生專用履歷草稿或 cover letter。

## LinkedIn 與 Apify 注意事項

LinkedIn URL 不再使用一般網頁請求直接抓取，而是呼叫 Apify actor。若出現 timeout 或抓不到資料，優先檢查：

- `APIFY_API_TOKEN` 是否有效。
- `APIFY_LINKEDIN_ACTOR_ID` 是否正確。
- `APIFY_LINKEDIN_INPUT_JSON` 是否符合該 actor 的 input schema。
- Apify actor 是否在 Apify console 中可以成功執行。

不同 LinkedIn actor 的 input schema 可能不同；本專案預設使用：

```json
{"profileUrls":["{url}"]}
```

如果 actor 需要 `urls` 或 `startUrls`，請用 `APIFY_LINKEDIN_INPUT_JSON` 覆蓋。

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
