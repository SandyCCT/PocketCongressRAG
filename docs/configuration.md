# 環境設定與索引行為

## 建立 `.env`

在專案根目錄執行：

```bash
# macOS / Linux
cp .env.example .env

# Windows PowerShell
copy .env.example .env
```

## AI provider

Chat 與 Embedding provider 可分別選擇 `openai` 或 `vertexai`：

| 變數 | 預設值 | 說明 |
|---|---|---|
| `CHAT_PROVIDER` | `openai` | 回答與路由使用的模型供應商。 |
| `EMBEDDING_PROVIDER` | `openai` | 建立與查詢向量 index 的供應商。 |
| `OPENAI_API_KEY` | 無 | OpenAI provider 必填。 |
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` | OpenAI Chat model。 |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI Embedding model。 |
| `GOOGLE_CLOUD_PROJECT` | 無 | Vertex AI provider 必填。 |
| `GOOGLE_CLOUD_LOCATION` | `global` | Vertex AI location。 |
| `VERTEX_CHAT_MODEL` | `gemini-2.5-flash` | Vertex AI Chat model。 |
| `VERTEX_EMBEDDING_MODEL` | `gemini-embedding-001` | Vertex AI Embedding model。 |
| `AI_REQUEST_TIMEOUT_SECONDS` | `60` | OpenAI／Vertex AI 的 Chat 與 Embedding 單次請求 timeout，單位為秒，不是整個問答或索引建置的總時限。 |
| `AI_MAX_RETRIES` | `2` | OpenAI／Vertex AI Chat 與 Embedding 額外重試次數；`2` 表示首次請求加最多 2 次重試，`0` 表示不重試。只針對可重試的錯誤，整體等待時間可能超過單次 timeout。 |

目前問答使用非串流請求；Vertex AI Chat 的 timeout 也套用於 Router、SQL 工具呼叫與回答生成。Vertex 索引建置腳本會將 client 重試設定覆寫為 `0`，由腳本控制每個 batch 最多嘗試 8 次。

OpenAI 範例：

```ini
CHAT_PROVIDER=openai
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=your_api_key_here
OPENAI_CHAT_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

### Vertex AI 的 GCP 前置設定

第一次使用 Vertex AI 時，依序完成以下設定：

1. 登入 [Google Cloud Console](https://console.cloud.google.com/)，從專案選擇器建立 project，並記下 **Project ID**。
2. 在 Billing 頁面將 project 連結至 Billing account。
3. 在 **APIs & Services > Library** 搜尋並啟用 **Vertex AI API**，服務名稱為 `aiplatform.googleapis.com`。
4. 在 **IAM & Admin > IAM**，將執行本機程式的 Google 帳號設為 **Vertex AI User**（`roles/aiplatform.user`）。IAM 不需另外啟用。

費用主要來自實際的 Vertex AI 模型請求：提問時會呼叫 Chat model，首次建立或重建 Chroma index 時會呼叫 Embedding model。建立 project、啟用 API、設定 IAM 與建立 ADC 本身不會產生模型用量費。

安裝 [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) 後執行：

```bash
gcloud init
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default login --project=YOUR_PROJECT_ID
```

最後一個指令會建立本機 Application Default Credentials（ADC）。macOS／Linux 的預設路徑為：

```text
~/.config/gcloud/application_default_credentials.json
```

完成後設定 `.env`：

```ini
CHAT_PROVIDER=vertexai
EMBEDDING_PROVIDER=vertexai
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=global
VERTEX_CHAT_MODEL=gemini-2.5-flash
VERTEX_EMBEDDING_MODEL=gemini-embedding-001
```

Chat 與 Embedding 可使用不同 provider；更換 Embedding provider 或 model 時，需要相容的 index。

## 路徑設定

| 變數 | 預設使用方式 | 說明 |
|---|---|---|
| `DATA_FOLDER_PATH` | `../data/sessions` | 來源 Excel 目錄。 |
| `INSTANCE_DIR` | provider 對應目錄 | 同時覆寫 index 相關路徑。 |
| `ROW_COUNT_HISTORY_PATH` | instance 下的 JSON | 資料 fingerprint、model、schema 與筆數紀錄。 |
| `CHROMA_DIR` | instance 下的 `chroma_db/` | Chroma 儲存位置。 |
| `DB_PATH` | instance 下的 `legislature.db` | SQLite 儲存位置。 |

相對路徑以 `src/` 為基準。只有自訂資料位置時才設定路徑，優先順序為個別路徑、`INSTANCE_DIR`、provider 預設值。

Provider 預設隔離 index：

- OpenAI：`instance/`
- Vertex AI：`instance/vertexai-gemini-embedding-001/`

## 索引重建策略

`INDEX_REBUILD_POLICY` 支援：

- `verify_only`：只驗證相容性，不自動重建。
- `auto`：建立或更新 SQLite 與 Chroma index。

Index 依會期分別建立。本機初始化使用 `auto`；Cloud Run 使用 `verify_only`。建立 Chroma index 會呼叫 Embedding API。

本機與部署腳本共用固定的文件 ID。同一份資料若已用相同的 Embedding provider、model 與 index schema 完整建立，可直接打包部署，不需重新產生 embedding。OpenAI 與 Vertex AI index 不可共用。

Vertex AI index 建置腳本搭配 `--resume` 時，未變更的會期會略過，固定文件 ID 的未完成會期會續跑；資料 fingerprint、provider、model 或 schema 改變的會期會完整重建。

## Logging

| 變數 | 預設值 | 說明 |
|---|---|---|
| `TZ` | `Asia/Taipei` | 每日 log 輪替使用的 timezone。 |
| `LOG_DIR` | `../logs` | 檔案 log 目錄。 |
| `LOG_LEVEL` | `INFO` | 可用 `DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL`。 |
| `LOG_RETENTION_DAYS` | `14` | 輪替檔案保留天數。 |
| `LOG_FILE_ENABLED` | `true` | 是否在 console 之外寫入檔案。 |

Cloud image 預設 `LOG_FILE_ENABLED=false`，由 Cloud Run 收集 stdout／stderr。

## Docker Compose 與 Vertex AI

Docker Compose 使用 `local` target，掛載主機的 `data/sessions/` 與 `instance/`；Cloud Build 使用包含 deployment bundle 的 `cloud` target。

OpenAI 模式：

```bash
docker compose up -d --build
```

Vertex AI 模式需在 `.env` 提供 ADC 檔案的絕對路徑：

```ini
GOOGLE_ADC_PATH=/absolute/path/to/application_default_credentials.json
```

再套用只負責掛載 ADC 的 override：

```bash
docker compose -f compose.yaml -f compose.vertexai.yaml up -d --build
```

ADC 與 `data/sessions/` 以唯讀方式掛載；`instance/` 用於保存 index。

本機尚未建立 index 時，`/health/ready` 會回傳 503；第一次提問後由 `auto` 建立 index。

## Health check 與 runtime 行為

- `/health/live`：確認 FastAPI 程序可回應。
- `/health/ready`：唯讀檢查必要資料與 index。
- Cloud runtime：讀取 deployment metadata、SQLite 與 Chroma。
