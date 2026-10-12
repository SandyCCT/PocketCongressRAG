# Cloud Run 部署指南

本文件說明以 Vertex AI、Cloud Build 與 deployment bundle 部署 private Cloud Run candidate revision 的流程。

## 操作前準備

- 依 [README 安裝環境](../README.md#1-安裝環境)完成專案下載與 Poetry 安裝。
- 依 [README 準備資料](../README.md#3-準備資料)確認 `data/sessions/` 中有會期 Excel。
- 安裝並啟動 [Docker](https://docs.docker.com/get-started/get-docker/)，安裝 [Google Cloud CLI](https://docs.cloud.google.com/sdk/docs/install)。
- 在 [GCP Console](https://console.cloud.google.com/) 建立 project 並連結 billing account，記下 project ID。

下列指令使用 macOS／Linux shell，請在同一個終端機、專案根目錄依序執行。Vertex-only 部署不需要 OpenAI API key。

## 部署設計

Cloud Run 使用不可變 deployment bundle，runtime 不解析 Excel 或重建 index。

Deployment bundle 包含：

- SQLite database
- Chroma index
- `runtime_metadata.json`
- 含 SHA-256 的 `manifest.json`

Bundle 不包含原始 Excel、`.env`、API key、`row_count_tracker.json` 與本機 log。

## 1. GCP 前置條件

本節由 project Owner 或具有資源建立、API 啟用與 IAM 授權權限的管理者執行。已有的資源可跳過建立指令，但仍需設定以下 shell 變數。

### 設定 project 與啟用 API

```bash
gcloud auth login
GCP_PROJECT_ID=YOUR_PROJECT_ID
gcloud config set project "$GCP_PROJECT_ID"
DEPLOY_USER_EMAIL=YOUR_GOOGLE_ACCOUNT_EMAIL

gcloud services enable \
  aiplatform.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  run.googleapis.com \
  iam.googleapis.com \
  cloudresourcemanager.googleapis.com \
  logging.googleapis.com \
  storage.googleapis.com
```

### 建立 Artifact Registry 與 runtime service account

名稱與 `cloudbuild.yaml` 的預設設定一致：

```bash
gcloud artifacts repositories create pocket-congress-rag \
  --project="$GCP_PROJECT_ID" \
  --repository-format=docker \
  --location=asia-east1

gcloud artifacts repositories describe pocket-congress-rag \
  --project="$GCP_PROJECT_ID" \
  --location=asia-east1
```

建立 runtime service account，並設定後續指令使用的完整 email：

```bash
gcloud iam service-accounts create pocket-congress-rag-runtime \
  --project="$GCP_PROJECT_ID" \
  --display-name="PocketCongressRAG runtime"

RUNTIME_SERVICE_ACCOUNT="pocket-congress-rag-runtime@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
```

建立後執行以下唯讀指令確認帳號已可查詢。若回傳找不到帳號，稍後再重試相同的 `describe` 指令；不要重跑 `create`，也不要先執行後續 IAM 授權：

```bash
gcloud iam service-accounts describe "$RUNTIME_SERVICE_ACCOUNT" \
  --project="$GCP_PROJECT_ID"
```

確認成功後，再授予 runtime service account Vertex AI 權限：

```bash
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role=roles/aiplatform.user
```

參考：[建立 service account](https://docs.cloud.google.com/iam/docs/service-accounts-create)。

### 設定 Cloud Build 權限

建立專用 build 帳號，與 runtime 帳號分開：

```bash
gcloud iam service-accounts create pocket-congress-rag-build \
  --project="$GCP_PROJECT_ID" \
  --display-name="PocketCongressRAG build"
BUILD_SERVICE_ACCOUNT="pocket-congress-rag-build@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
```

建立後執行以下唯讀指令確認帳號已可查詢。若回傳找不到帳號，稍後再重試相同的 `describe` 指令；不要重跑 `create`，也不要先執行授權：

```bash
gcloud iam service-accounts describe "$BUILD_SERVICE_ACCOUNT" \
  --project="$GCP_PROJECT_ID"
```

確認成功後，再執行 build service account 的授權：

```bash
gcloud artifacts repositories add-iam-policy-binding pocket-congress-rag \
  --project="$GCP_PROJECT_ID" \
  --location=asia-east1 \
  --member="serviceAccount:${BUILD_SERVICE_ACCOUNT}" \
  --role=roles/artifactregistry.writer

gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:${BUILD_SERVICE_ACCOUNT}" \
  --role=roles/run.admin

gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:${BUILD_SERVICE_ACCOUNT}" \
  --role=roles/logging.logWriter

gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:${BUILD_SERVICE_ACCOUNT}" \
  --role=roles/serviceusage.serviceUsageConsumer

gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SERVICE_ACCOUNT" \
  --project="$GCP_PROJECT_ID" \
  --member="serviceAccount:${BUILD_SERVICE_ACCOUNT}" \
  --role=roles/iam.serviceAccountUser
```

建立來源檔案暫存 bucket，讓 build 帳號讀取上傳的專案：

```bash
BUILD_SOURCE_BUCKET="${GCP_PROJECT_ID}-pocketcongress-build-source"
gcloud storage buckets create "gs://${BUILD_SOURCE_BUCKET}" \
  --location=asia-east1 \
  --uniform-bucket-level-access

gcloud storage buckets add-iam-policy-binding "gs://${BUILD_SOURCE_BUCKET}" \
  --member="serviceAccount:${BUILD_SERVICE_ACCOUNT}" \
  --role=roles/storage.objectViewer
```

### 設定部署使用者權限

同一個使用者負責本機建立 Vertex AI embedding index、提交 build、驗收與切換流量：

```bash
for iam_role in roles/aiplatform.user roles/serviceusage.serviceUsageConsumer roles/cloudbuild.builds.editor roles/logging.viewer roles/run.admin; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member="user:${DEPLOY_USER_EMAIL}" \
    --role="$iam_role"
done

gcloud storage buckets add-iam-policy-binding "gs://${BUILD_SOURCE_BUCKET}" \
  --member="user:${DEPLOY_USER_EMAIL}" \
  --role=roles/storage.objectAdmin

gcloud storage buckets add-iam-policy-binding "gs://${BUILD_SOURCE_BUCKET}" \
  --member="user:${DEPLOY_USER_EMAIL}" \
  --role=roles/storage.bucketViewer

gcloud iam service-accounts add-iam-policy-binding "$BUILD_SERVICE_ACCOUNT" \
  --member="user:${DEPLOY_USER_EMAIL}" \
  --role=roles/iam.serviceAccountUser
```

`storage.objectAdmin` 用於上傳來源檔案；`storage.bucketViewer` 提供提交 build 前檢查 bucket 所需的 `storage.buckets.get` 權限。參考：[Cloud Storage 權限](https://docs.cloud.google.com/iam/docs/roles-permissions/storage)。

後續以 `DEPLOY_USER_EMAIL` 指定的帳號登入 gcloud 與 ADC。參考：[Cloud Build 部署權限](https://docs.cloud.google.com/build/docs/deploying-builds/deploy-cloud-run)、[專用 build 帳號](https://docs.cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts)。

## 2. 建立 Vertex AI embedding index

Cloud Run 已部署後，若新增會期 Excel，或既有會期的筆數、內容改變，請從本節重新執行到第 8 節：更新 Vertex AI index、建立新 bundle、建置與提交 image、驗收 candidate，再切換正式流量。除非 project、API 或 IAM 設定改變，否則不需重做第 1 節。

完成 ADC 登入：

```bash
gcloud auth login "$DEPLOY_USER_EMAIL"
gcloud auth application-default login --project="$GCP_PROJECT_ID"
gcloud auth application-default set-quota-project "$GCP_PROJECT_ID"
```

```bash
poetry run python scripts/rebuild_vertex_embedding_index.py \
  --project="$GCP_PROJECT_ID" \
  --resume
```

`--resume` 會沿用資料 fingerprint、Vertex AI embedding model 與 index schema 相同的完整本機索引；固定文件 ID 的未完成會期會從缺少的文件繼續建立。某會期的資料或索引設定改變時，只完整重建該會期。只有建立缺少文件或重建變更會期時才會呼叫 Vertex AI Embedding API。

## 3. 建立 deployment bundle

從專案根目錄建立新版本的 bundle：

```bash
BUNDLE_PATH=deployment_bundles/YYYY-MM-DD-vN
GOOGLE_CLOUD_PROJECT="$GCP_PROJECT_ID" \
poetry run python scripts/package_deployment_bundle.py \
  "$BUNDLE_PATH" \
  --instance-dir instance/vertexai-gemini-embedding-001 \
  --embedding-provider vertexai \
  --embedding-model gemini-embedding-001
```

工具會以 `verify_only` 驗證資料與 index，並建立 runtime metadata。更新 Excel、embedding model 或 index schema 後，請建立新的 bundle。

將 `YYYY-MM-DD-vN` 換成本次版本名稱，例如 `2026-10-07-v1`；日期與版本號由你指定，不會自動更新。後續指令沿用 `BUNDLE_PATH`。

每次使用新的 bundle 版本，只需同步設定兩處：

1. 本節的 `BUNDLE_PATH`。
2. 第 5 節的 `.gcloudignore` bundle 白名單。

Dockerfile 與 `cloudbuild.yaml` 中的 bundle 路徑是預設值。下方 Docker 指令以 `--build-arg` 覆寫，第 6 節以 `--substitutions` 覆寫，因此不需修改這兩個檔案中的日期。

## 4. 本機建置 cloud image

```bash
docker build \
  --platform linux/amd64 \
  --target cloud \
  --build-arg DEPLOYMENT_BUNDLE_PATH="$BUNDLE_PATH" \
  -t pocket-congress-rag:cloud-run .
```

`cloud` target 會複製 deployment bundle，並使用 `INDEX_REBUILD_POLICY=verify_only`。

## 5. 檢查 Cloud Build 設定

[`cloudbuild.yaml`](../cloudbuild.yaml) 會驗證 bundle、建置並推送 `linux/amd64` image，再部署 private Cloud Run service。

先修改 [`.gcloudignore`](../.gcloudignore) 最後兩行，讓白名單與 `BUNDLE_PATH` 一致，例如：

```text
!deployment_bundles/2026-10-07-v1/
!deployment_bundles/2026-10-07-v1/**
```

檢查上傳清單，確認包含本次 bundle 的 `manifest.json`、`runtime_metadata.json`、SQLite 與 Chroma 檔案：

```bash
gcloud meta list-files-for-upload
```

### 首次建立 service

`--no-traffic` 只適用於更新既有 service。首次部署先複製設定：

```bash
cp cloudbuild.yaml cloudbuild.first-deploy.yaml
BUILD_CONFIG=cloudbuild.first-deploy.yaml
```

用編輯器打開 `cloudbuild.first-deploy.yaml`，刪除 `- --no-traffic` 這一行。保留 `--no-allow-unauthenticated` 與 `--tag`。首次建立的 revision 會接收 100% 流量，但仍需授權才能存取。這份副本僅供首次部署，不需提交 Git。

### 後續更新 service

已有 `pocket-congress-rag` service 時，使用原本設定建立零流量 candidate：

```bash
BUILD_CONFIG=cloudbuild.yaml
```

## 6. 提交 Cloud Build

```bash
gcloud config get-value project

gcloud builds submit \
  --region=asia-east1 \
  --config="$BUILD_CONFIG" \
  --service-account="projects/${GCP_PROJECT_ID}/serviceAccounts/${BUILD_SERVICE_ACCOUNT}" \
  --gcs-source-staging-dir="gs://${BUILD_SOURCE_BUCKET}/source" \
  --substitutions="_DEPLOYMENT_BUNDLE_PATH=${BUNDLE_PATH}" \
  .
```

等待 build 狀態為 `SUCCESS`，再執行驗收。Image 使用 Cloud Build 的 `$BUILD_ID` 作為 tag。

## 7. Candidate revision 驗收

服務建立後，授予驗收帳號 Cloud Run Invoker 權限：

```bash
VALIDATION_ACCOUNT="$DEPLOY_USER_EMAIL"
gcloud run services add-iam-policy-binding pocket-congress-rag \
  --region=asia-east1 \
  --member="user:${VALIDATION_ACCOUNT}" \
  --role=roles/run.invoker
```

可先查看驗收問題：

```bash
poetry run python scripts/validate_vertex_chat.py --dry-run
```

取得 candidate URL：

```bash
gcloud run services describe pocket-congress-rag \
  --region=asia-east1 \
  --format="yaml(status.traffic)"
```

將輸出中 `tag: candidate` 對應的 `url` 填入 `CANDIDATE_URL`，查詢可用會期：

```bash
CANDIDATE_URL=https://candidate---SERVICE_IDENTIFIER.run.app
curl --fail-with-body "${CANDIDATE_URL}/api/v1/sessions" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

從回應選擇會期的 `id`，填入 `SESSION_ID`。例如資料包含 `S_11_1` 時：

```bash
SESSION_ID=S_11_1
```

執行線上驗收：

```bash
poetry run python scripts/validate_vertex_chat.py \
  --base-url="$CANDIDATE_URL" \
  --session-id="$SESSION_ID"
```

驗收會檢查 liveness、readiness、sessions，並送出 SQL 與 Vector 問題。確認回答內容符合所選會期的來源資料。

## 8. 切換正式流量

Candidate 驗收通過後，切換正式流量：

```bash
gcloud run services update-traffic pocket-congress-rag \
  --region=asia-east1 \
  --to-tags candidate=100
```

## 9. 開啟問答網頁

服務為 private，透過登入帳號建立本機 proxy：

```bash
gcloud run services proxy pocket-congress-rag \
  --project="$GCP_PROJECT_ID" \
  --region=asia-east1 \
  --port=18000
```

保持此終端機執行，瀏覽器開啟 <http://127.0.0.1:18000/>。完成後按 `Ctrl+C` 停止 proxy。參考：[存取 private Cloud Run](https://docs.cloud.google.com/run/docs/authenticating/developers)。

## 費用

下列項目可能產生費用：

- Vertex AI Embedding 與 Chat requests
- Cloud Build build minutes
- Artifact Registry 儲存
- Cloud Run CPU、memory 與 requests
