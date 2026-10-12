import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "instance" / "vertexai-gemini-embedding-001"
)
INDEX_WRITE_BATCH_SIZE = 100
MAX_RETRY_ATTEMPTS = 8


def _metadata_matches_current_index(
    *,
    metadata: Any,
    expected_total_rows: int,
    expected_data_fingerprint: str,
    expected_embedding_provider: str,
    expected_embedding_model: str,
    expected_schema_version: int,
) -> bool:
    return (
        isinstance(metadata, dict)
        and metadata.get("total_rows") == expected_total_rows
        and metadata.get("data_fingerprint")
        == expected_data_fingerprint
        and metadata.get("embedding_provider")
        == expected_embedding_provider
        and metadata.get("embedding_model") == expected_embedding_model
        and metadata.get("index_schema_version")
        == expected_schema_version
    )


def _is_complete_compatible_index(
    *,
    existing_document_count: int,
    expected_document_count: int,
    metadata: Any,
    expected_total_rows: int,
    expected_data_fingerprint: str,
    expected_embedding_provider: str,
    expected_embedding_model: str,
    expected_schema_version: int,
) -> bool:
    return (
        existing_document_count == expected_document_count
        and _metadata_matches_current_index(
            metadata=metadata,
            expected_total_rows=expected_total_rows,
            expected_data_fingerprint=expected_data_fingerprint,
            expected_embedding_provider=expected_embedding_provider,
            expected_embedding_model=expected_embedding_model,
            expected_schema_version=expected_schema_version,
        )
        and metadata.get("status") in (None, "complete")
    )


def _requires_full_rebuild(
    *,
    existing_ids: set[str],
    expected_ids: set[str],
    metadata: Any,
    expected_total_rows: int,
    expected_data_fingerprint: str,
    expected_embedding_provider: str,
    expected_embedding_model: str,
    expected_schema_version: int,
) -> bool:
    if (
        isinstance(metadata, dict)
        and metadata.get("status") == "rebuild_pending"
    ):
        return True
    if existing_ids and not existing_ids.issubset(expected_ids):
        return True
    if metadata is None:
        return False
    return not _metadata_matches_current_index(
        metadata=metadata,
        expected_total_rows=expected_total_rows,
        expected_data_fingerprint=expected_data_fingerprint,
        expected_embedding_provider=expected_embedding_provider,
        expected_embedding_model=expected_embedding_model,
        expected_schema_version=expected_schema_version,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "使用 Vertex AI gemini-embedding-001 建立隔離且可續跑的 "
            "SQLite、Chroma 與 row history。"
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="索引輸出目錄；預設位於 instance/vertexai-gemini-embedding-001。",
    )
    parser.add_argument(
        "--project",
        default=os.getenv("GOOGLE_CLOUD_PROJECT"),
        help=(
            "Vertex AI 所屬 Google Cloud project；未指定時讀取 "
            "GOOGLE_CLOUD_PROJECT。"
        ),
    )
    parser.add_argument(
        "--location",
        default="global",
        help="Vertex AI location，預設為 global。",
    )
    parser.add_argument(
        "--model",
        default="gemini-embedding-001",
        help="Vertex AI embedding model。",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="續跑既有 staging 目錄；未指定時拒絕覆寫。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出來源會期與輸出位置，不建立索引。",
    )
    return parser.parse_args()


def _add_documents_with_retry(
    vector_store: Any,
    documents: list[Any],
    document_ids: list[str],
) -> None:
    from app.exceptions import RetryableAIProviderError

    for attempt in range(MAX_RETRY_ATTEMPTS):
        try:
            vector_store.add_documents(documents, ids=document_ids)
            return
        except RetryableAIProviderError:
            if attempt == MAX_RETRY_ATTEMPTS - 1:
                raise
            delay_seconds = min(15 * (2 ** attempt), 60)
            print(
                "Vertex AI 暫時無法完成請求，"
                f"{delay_seconds} 秒後重試目前 batch。",
                flush=True,
            )
            time.sleep(delay_seconds)


def _build_session(
    excel_path: Path,
    session_id: str,
    output_dir: Path,
) -> dict[str, Any]:
    from chromadb import PersistentClient
    from langchain_chroma import Chroma
    from nodes.maintenance import (
        INDEX_SCHEMA_VERSION,
        calculate_data_fingerprint,
    )
    from services.doc_converter import convert_df_to_docs
    from services.document_ids import build_document_ids
    from services.history_store import (
        load_row_count_history,
        save_row_count_history,
    )
    from services.llm_client import (
        EMBEDDING_MODEL,
        EMBEDDING_PROVIDER,
        embeddings,
    )
    from services.preprocessing import preprocess_and_merge
    from services.sql_tools import rebuild_db

    dataframe, _, _, counts = preprocess_and_merge(str(excel_path))
    documents = convert_df_to_docs(dataframe)
    document_ids = build_document_ids(session_id, len(documents))
    data_fingerprint = calculate_data_fingerprint(dataframe)
    vector_store = Chroma(
        collection_name=session_id,
        embedding_function=embeddings,
        persist_directory=str(output_dir / "chroma_db"),
    )
    existing_ids = set(vector_store.get(include=[])["ids"])
    history_path = output_dir / "row_count_tracker.json"
    history = load_row_count_history(str(history_path))
    existing_metadata = history.get(session_id)
    if _is_complete_compatible_index(
        existing_document_count=len(existing_ids),
        expected_document_count=len(documents),
        metadata=existing_metadata,
        expected_total_rows=counts["total"],
        expected_data_fingerprint=data_fingerprint,
        expected_embedding_provider=EMBEDDING_PROVIDER,
        expected_embedding_model=EMBEDDING_MODEL,
        expected_schema_version=INDEX_SCHEMA_VERSION,
    ):
        print(
            f"會期索引已完成且相容，略過重建：session={session_id}",
            flush=True,
        )
        return existing_metadata

    expected_ids = set(document_ids)
    requires_full_rebuild = _requires_full_rebuild(
        existing_ids=existing_ids,
        expected_ids=expected_ids,
        metadata=existing_metadata,
        expected_total_rows=counts["total"],
        expected_data_fingerprint=data_fingerprint,
        expected_embedding_provider=EMBEDDING_PROVIDER,
        expected_embedding_model=EMBEDDING_MODEL,
        expected_schema_version=INDEX_SCHEMA_VERSION,
    )

    staging_metadata = {
        "total_rows": counts["total"],
        "per_sheet": counts["per_sheet"],
        "data_fingerprint": data_fingerprint,
        "embedding_provider": EMBEDDING_PROVIDER,
        "embedding_model": EMBEDDING_MODEL,
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": excel_path.name,
    }

    if requires_full_rebuild:
        history[session_id] = {
            **staging_metadata,
            "status": "rebuild_pending",
        }
        save_row_count_history(str(history_path), history)
        print(
            "資料內容或索引設定已變更，完整重建會期索引："
            f"session={session_id}",
            flush=True,
        )
        chroma_client = PersistentClient(path=str(output_dir / "chroma_db"))
        chroma_client.delete_collection(session_id)
        vector_store = Chroma(
            collection_name=session_id,
            embedding_function=embeddings,
            persist_directory=str(output_dir / "chroma_db"),
        )
        existing_ids = set()

    history[session_id] = {
        **staging_metadata,
        "status": "building",
    }
    save_row_count_history(str(history_path), history)

    missing_items = [
        (document_id, document)
        for document_id, document in zip(document_ids, documents)
        if document_id not in existing_ids
    ]
    for start in range(0, len(missing_items), INDEX_WRITE_BATCH_SIZE):
        batch = missing_items[start:start + INDEX_WRITE_BATCH_SIZE]
        _add_documents_with_retry(
            vector_store,
            [document for _, document in batch],
            [document_id for document_id, _ in batch],
        )
        completed = len(existing_ids) + min(
            start + INDEX_WRITE_BATCH_SIZE,
            len(missing_items),
        )
        print(
            f"Vertex AI embedding 進度：session={session_id} "
            f"{completed}/{len(documents)}",
            flush=True,
        )

    if vector_store._collection.count() != len(documents):
        raise RuntimeError(f"Chroma 文件筆數不一致：session={session_id}")

    rebuild_db(dataframe, session_id)
    chroma_client = PersistentClient(path=str(output_dir / "chroma_db"))
    if chroma_client.get_collection(session_id).count() != len(documents):
        raise RuntimeError(f"Chroma collection 驗證失敗：session={session_id}")
    uuid_dirs = [
        path
        for path in (output_dir / "chroma_db").iterdir()
        if path.is_dir()
    ]
    latest_uuid_dir = max(uuid_dirs, key=lambda path: path.stat().st_mtime)

    history[session_id] = {
        "status": "complete",
        "total_rows": counts["total"],
        "per_sheet": counts["per_sheet"],
        "data_fingerprint": data_fingerprint,
        "embedding_provider": EMBEDDING_PROVIDER,
        "embedding_model": EMBEDDING_MODEL,
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": excel_path.name,
        "chroma_uuid_dir_name": latest_uuid_dir.name,
    }
    save_row_count_history(str(history_path), history)
    return history[session_id]


def main() -> None:
    args = parse_args()
    project = (args.project or "").strip()
    if not project:
        raise ValueError(
            "請使用 --project 或 GOOGLE_CLOUD_PROJECT 設定 GCP project"
        )

    output_dir = args.output_dir.resolve()
    instance_root = (PROJECT_ROOT / "instance").resolve()
    if not output_dir.is_relative_to(instance_root):
        raise ValueError("--output-dir 必須位於專案 instance/ 目錄內")

    data_dir = (PROJECT_ROOT / "data" / "sessions").resolve()
    os.environ.update({
        "CHAT_PROVIDER": "vertexai",
        "EMBEDDING_PROVIDER": "vertexai",
        "GOOGLE_CLOUD_PROJECT": project,
        "GOOGLE_CLOUD_LOCATION": args.location,
        "VERTEX_EMBEDDING_MODEL": args.model,
        "AI_MAX_RETRIES": "0",
        "DATA_FOLDER_PATH": str(data_dir),
        "ROW_COUNT_HISTORY_PATH": str(
            output_dir / "row_count_tracker.json"
        ),
        "CHROMA_DIR": str(output_dir / "chroma_db"),
        "DB_PATH": str(output_dir / "legislature.db"),
        "INDEX_REBUILD_POLICY": "auto",
        "LOG_FILE_ENABLED": "false",
    })
    os.chdir(SRC_DIR)
    sys.path.insert(0, str(SRC_DIR))

    from services.deployment_bundle import discover_session_files
    session_files = discover_session_files(data_dir)
    if not session_files:
        raise RuntimeError("找不到可建立索引的會期 Excel")

    if args.dry_run:
        print(f"輸出目錄：{output_dir}")
        for session_id, excel_path in sorted(session_files.items()):
            print(f"{session_id}: {excel_path.name}")
        return

    if output_dir.exists() and not args.resume:
        raise FileExistsError(f"拒絕覆寫既有索引目錄：{output_dir}")

    output_dir.mkdir(parents=True, exist_ok=args.resume)
    completed_metadata = {}
    for session_id, excel_path in sorted(session_files.items()):
        print(
            f"開始建立 Vertex AI embedding index：session={session_id}",
            flush=True,
        )
        completed_metadata[session_id] = _build_session(
            excel_path,
            session_id,
            output_dir,
        )
        print(
            f"完成 Vertex AI embedding index：session={session_id} "
            f"rows={completed_metadata[session_id]['total_rows']}",
            flush=True,
        )

    print(
        json.dumps(
            {
                session_id: {
                    "total_rows": metadata["total_rows"],
                    "embedding_provider": metadata["embedding_provider"],
                    "embedding_model": metadata["embedding_model"],
                }
                for session_id, metadata in completed_metadata.items()
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
