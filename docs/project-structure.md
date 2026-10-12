# 專案結構

```text
PocketCongressRAG/
├── .dockerignore                   # Docker build context 忽略規則
├── .env.example                    # 環境變數範例
├── .gcloudignore                   # Cloud Build 上傳白名單
├── .gitignore                      # Git 忽略規則
├── .github/
│   └── workflows/
│       ├── ci.yml                  # Push／Pull Request 離線 CI
│       └── rag-cli.yml             # 手動 OpenAI CLI 示範
├── Dockerfile                      # FastAPI application image
├── cloudbuild.yaml                 # Vertex AI 與 Cloud Run 正式部署設定
├── compose.yaml                    # 本機 FastAPI service
├── compose.vertexai.yaml           # Vertex ADC 唯讀掛載 override
├── pyproject.toml                  # 專案 metadata 與依賴
├── poetry.lock                     # 鎖定直接及間接依賴版本
├── poetry.toml                     # 專案內 `.venv` 設定
├── data/
│   └── sessions/                   # 原始會期 Excel
├── deployment_bundles/             # 不提交 Git 的版本化部署資料
├── docs/
│   ├── examples/
│   │   └── QA_example.xlsx          # QA 問答展示範例
│   ├── cloud-run-deployment.md     # Cloud Run 部署與驗收
│   ├── configuration.md            # 環境變數與索引行為
│   ├── data-contract.md            # Excel 資料契約
│   └── project-structure.md        # 完整專案結構
├── instance/                       # 本機持久化資料
│   ├── chroma_db/                  # OpenAI Chroma index
│   ├── legislature.db              # SQLite database
│   ├── row_count_tracker.json      # Fingerprint、model 與 index 紀錄
│   └── vertexai-gemini-embedding-001/
│       └── ...                     # Vertex AI provider 隔離 index
├── scripts/
│   ├── package_deployment_bundle.py
│   ├── rebuild_vertex_embedding_index.py
│   └── validate_vertex_chat.py
├── src/
│   ├── api.py                      # FastAPI、health checks 與網頁入口
│   ├── run_workflow.py             # CLI 入口
│   ├── web/
│   │   ├── index.html              # 問答頁面
│   │   ├── app.js                  # API 呼叫與畫面互動
│   │   └── style.css               # 頁面樣式
│   ├── adapters/
│   │   └── cli_inputs.py           # CLI 輸入介面
│   ├── app/
│   │   ├── config.py               # 路徑與環境設定
│   │   ├── exceptions.py           # 預期的應用程式錯誤
│   │   ├── logging_config.py       # Console 與輪替檔案 log
│   │   ├── router.py               # SQL／Vector 路由
│   │   └── state.py                # Workflow state
│   ├── nodes/
│   │   ├── input_transform.py      # 使用者輸入正規化
│   │   ├── vector_search.py        # Chroma 檢索節點
│   │   ├── sql_query.py            # SQL 生成、執行與回答
│   │   ├── maintenance.py          # 資料與 index 維護
│   │   └── chat_control.py         # CLI 對話流程控制
│   ├── services/
│   │   ├── document_ids.py         # 可重現的 Chroma 文件 ID
│   │   ├── llm_client.py           # Chat 與 Embedding clients
│   │   ├── normalizers.py          # 自然語言條件正規化
│   │   ├── filters.py              # 共用查詢 filters
│   │   ├── filter_utils.py         # Filter 輔助函式
│   │   ├── deployment_bundle.py    # Bundle manifest 與完整性驗證
│   │   ├── deployment_metadata.py  # Cloud runtime metadata
│   │   ├── doc_converter.py        # DataFrame 轉 LangChain Documents
│   │   ├── excel_io.py             # Excel 讀取與統計
│   │   ├── history_store.py        # JSON index 紀錄存取
│   │   ├── preprocessing.py        # Excel 前處理與合併
│   │   ├── provider_factory.py     # Chat／Embedding provider 建立
│   │   ├── vertex_chat.py          # Vertex Chat 非串流請求 timeout adapter
│   │   ├── sql_tools.py            # SQLite 工具
│   │   ├── vector_store.py         # Chroma 工具
│   │   └── vertex_embeddings.py    # Vertex AI embedding adapter
│   └── workflows/
│       └── rag_workflow.py         # LangGraph workflow
└── tests/                          # 離線 unittest suite
```

## 主要執行入口

- CLI：`src/run_workflow.py`
- FastAPI／Web：`src/api.py`
- Workflow：`src/workflows/rag_workflow.py`
- 正式 Cloud Build：`cloudbuild.yaml`

## Runtime 資料邊界

- `data/sessions/`：來源 Excel；本機 Compose 以唯讀方式掛載。
- `instance/`：可重建但需持久化的 SQLite、Chroma 與 index metadata。
- `deployment_bundles/`：Cloud image 使用的不可變資料，保持在 Git 之外。
- `.env`：本機 secret 與 runtime 設定，不提交 Git。
