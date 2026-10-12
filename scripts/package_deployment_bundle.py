import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "驗證來源並建立包含 SQLite、Chroma 與 runtime metadata "
            "的 Cloud Run deployment bundle。"
        )
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="新的版本化 bundle 目錄；如果已存在則拒絕覆蓋。",
    )
    parser.add_argument(
        "--instance-dir",
        type=Path,
        default=PROJECT_ROOT / "instance",
        help=(
            "要封裝的 SQLite、Chroma 與 row history 目錄；"
            "預設為專案 instance/。"
        ),
    )
    parser.add_argument(
        "--embedding-provider",
        choices=("openai", "vertexai"),
        help="覆寫要驗證及寫入 metadata 的 embedding provider。",
    )
    parser.add_argument(
        "--embedding-model",
        help="覆寫要驗證及寫入 metadata 的 embedding model。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    instance_dir = args.instance_dir.resolve()
    if bool(args.embedding_provider) != bool(args.embedding_model):
        raise ValueError(
            "--embedding-provider 與 --embedding-model 必須一起設定"
        )

    os.environ["INDEX_REBUILD_POLICY"] = "verify_only"
    os.environ["CHROMA_DIR"] = str(instance_dir / "chroma_db")
    os.environ["DB_PATH"] = str(instance_dir / "legislature.db")
    os.environ["ROW_COUNT_HISTORY_PATH"] = str(
        instance_dir / "row_count_tracker.json"
    )
    if args.embedding_provider is not None:
        os.environ["CHAT_PROVIDER"] = args.embedding_provider
        os.environ["EMBEDDING_PROVIDER"] = args.embedding_provider
        if args.embedding_provider == "openai":
            os.environ["OPENAI_EMBEDDING_MODEL"] = args.embedding_model
        else:
            os.environ["VERTEX_EMBEDDING_MODEL"] = args.embedding_model
    os.chdir(SRC_DIR)
    sys.path.insert(0, str(SRC_DIR))

    from nodes.maintenance import INDEX_SCHEMA_VERSION
    from services.deployment_bundle import (
        discover_session_files,
        package_deployment_bundle,
    )
    from services.llm_client import EMBEDDING_MODEL, EMBEDDING_PROVIDER
    from workflows.rag_workflow import prepare_local_session

    data_dir = PROJECT_ROOT / "data" / "sessions"
    session_files = discover_session_files(data_dir)

    for session_id, excel_path in sorted(session_files.items()):
        prepare_local_session(str(excel_path), session_id)

    bundle_path = package_deployment_bundle(
        data_dir=data_dir,
        instance_dir=instance_dir,
        output_dir=output_dir,
        embedding_provider=EMBEDDING_PROVIDER,
        embedding_model=EMBEDDING_MODEL,
        index_schema_version=INDEX_SCHEMA_VERSION,
    )
    print(f"Deployment bundle 已建立：{bundle_path}")


if __name__ == "__main__":
    main()
