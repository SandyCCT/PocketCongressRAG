import hashlib
import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from chromadb import PersistentClient
from chromadb.errors import ChromaError
from services.deployment_metadata import (
    RUNTIME_METADATA_SCHEMA_VERSION,
    SESSION_ID_PATTERN,
    RuntimeMetadata,
    RuntimeMetadataValidationError,
    load_runtime_metadata,
    validate_runtime_metadata,
)


class BundleValidationError(ValueError):
    """部署資料不完整或彼此不一致。"""


def discover_session_files(data_dir: Path) -> dict[str, Path]:
    """取得符合專案命名規則的會期 Excel。"""
    sessions = {}
    for path in sorted(data_dir.glob("*.xlsx"), key=lambda item: item.name):
        if path.name.startswith("~$"):
            continue
        match = re.match(r"第(\d+)屆第(\d+)會期", path.stem)
        if match:
            session_id = f"S_{match.group(1)}_{match.group(2)}"
            sessions.setdefault(session_id, path)
    return sessions


def calculate_file_hash(path: Path) -> str:
    """以區塊讀取檔案並計算 SHA-256。"""
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def collect_file_hashes(root: Path) -> dict[str, str]:
    """收集目錄內所有一般檔案的相對路徑與 SHA-256。"""
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise BundleValidationError(f"部署資料不可包含 symbolic link：{path}")
        if path.is_file():
            hashes[path.relative_to(root).as_posix()] = calculate_file_hash(path)
    return hashes


def load_row_count_history(path: Path) -> dict[str, dict[str, Any]]:
    """讀取 row history，並支援既有 UTF-8 BOM。"""
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            history = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleValidationError("無法讀取 row_count_tracker.json") from exc

    if not isinstance(history, dict):
        raise BundleValidationError("row_count_tracker.json 格式不正確")
    return history


def get_sqlite_row_counts(
    database_path: Path,
    session_ids: set[str],
) -> dict[str, int]:
    """以唯讀連線取得各會期資料表筆數。"""
    database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
    try:
        with sqlite3.connect(database_uri, uri=True) as connection:
            table_rows = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            table_names = {row[0] for row in table_rows}
            if table_names != session_ids:
                raise BundleValidationError("SQLite 會期資料表與 Excel 不一致")

            counts = {}
            for session_id in sorted(session_ids):
                if not SESSION_ID_PATTERN.fullmatch(session_id):
                    raise BundleValidationError(f"不合法的會期 ID：{session_id}")
                row = connection.execute(
                    f'SELECT COUNT(*) FROM "{session_id}"'
                ).fetchone()
                counts[session_id] = int(row[0])
            return counts
    except sqlite3.Error as exc:
        raise BundleValidationError("無法驗證 legislature.db") from exc


def _get_numbered_columns(
    column_names: set[str],
    prefix: str,
    session_id: str,
) -> list[str]:
    """取得連續編號的動態欄位。"""
    numbered_columns = {}
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for column_name in column_names:
        match = pattern.fullmatch(column_name)
        if match:
            numbered_columns[int(match.group(1))] = column_name

    expected_numbers = list(range(1, len(numbered_columns) + 1))
    if sorted(numbered_columns) != expected_numbers:
        raise BundleValidationError(
            f"SQLite 動態欄位編號不連續：session={session_id} prefix={prefix}"
        )
    return [numbered_columns[number] for number in expected_numbers]


def _get_unique_values(
    connection: sqlite3.Connection,
    session_id: str,
    column_names: list[str],
) -> list[str]:
    """取得指定欄位的排序唯一字串值。"""
    values = set()
    for column_name in column_names:
        rows = connection.execute(
            f'SELECT DISTINCT "{column_name}" FROM "{session_id}" '
            f'WHERE "{column_name}" IS NOT NULL '
            f'AND TRIM("{column_name}") <> \'\''
        ).fetchall()
        for row in rows:
            value = row[0]
            if not isinstance(value, str):
                raise BundleValidationError(
                    f"SQLite 篩選欄位包含非字串值：session={session_id}"
                )
            values.add(value)
    return sorted(values)


def get_sqlite_filter_metadata(
    database_path: Path,
    session_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """從 SQLite 取得 runtime 所需的篩選值與動態欄位數。"""
    required_columns = {
        "委員名字",
        "原本發言內容",
        "日期",
        "議題分類",
        "會期",
    }
    database_uri = f"{database_path.resolve().as_uri()}?mode=ro"
    try:
        with sqlite3.connect(database_uri, uri=True) as connection:
            metadata = {}
            for session_id in sorted(session_ids):
                if not SESSION_ID_PATTERN.fullmatch(session_id):
                    raise BundleValidationError(f"不合法的會期 ID：{session_id}")

                table_info = connection.execute(
                    f'PRAGMA table_info("{session_id}")'
                ).fetchall()
                column_names = {row[1] for row in table_info}
                if not required_columns.issubset(column_names):
                    raise BundleValidationError(
                        f"SQLite 缺少必要欄位：session={session_id}"
                    )

                committee_columns = _get_numbered_columns(
                    column_names,
                    "所屬委員會",
                    session_id,
                )
                geographical_scope_columns = _get_numbered_columns(
                    column_names,
                    "涵蓋層級",
                    session_id,
                )
                metadata[session_id] = {
                    "max_committee_count": len(committee_columns),
                    "max_geographical_scope_count": len(
                        geographical_scope_columns
                    ),
                    "filter_options": {
                        "member_names": _get_unique_values(
                            connection,
                            session_id,
                            ["委員名字"],
                        ),
                        "committees": _get_unique_values(
                            connection,
                            session_id,
                            committee_columns,
                        ),
                        "geographical_scopes": _get_unique_values(
                            connection,
                            session_id,
                            geographical_scope_columns,
                        ),
                    },
                }
            return metadata
    except sqlite3.Error as exc:
        raise BundleValidationError("無法讀取 SQLite 篩選 metadata") from exc


def get_chroma_collection_counts(chroma_dir: Path) -> dict[str, int]:
    """取得 Chroma collection 名稱與文件筆數。"""
    try:
        client = PersistentClient(path=str(chroma_dir))
        return {
            collection.name: collection.count()
            for collection in client.list_collections()
        }
    except (ChromaError, OSError, ValueError, TypeError) as exc:
        raise BundleValidationError("無法驗證 Chroma collections") from exc


def validate_deployment_sources(
    data_dir: Path,
    instance_dir: Path,
    embedding_provider: str,
    embedding_model: str,
    index_schema_version: int,
) -> list[dict[str, Any]]:
    """驗證 Excel、SQLite、Chroma 與 row history 是否一致。"""
    session_files = discover_session_files(data_dir)
    if not session_files:
        raise BundleValidationError("找不到可部署的會期 Excel")

    database_path = instance_dir / "legislature.db"
    history_path = instance_dir / "row_count_tracker.json"
    chroma_dir = instance_dir / "chroma_db"
    required_paths = [database_path, history_path, chroma_dir / "chroma.sqlite3"]
    if any(not path.is_file() for path in required_paths):
        raise BundleValidationError("部署所需的 SQLite、Chroma 或 row history 不完整")

    session_ids = set(session_files)
    history = load_row_count_history(history_path)
    if set(history) != session_ids:
        raise BundleValidationError("row history 會期與 Excel 不一致")

    sqlite_counts = get_sqlite_row_counts(database_path, session_ids)
    chroma_counts = get_chroma_collection_counts(chroma_dir)
    if set(chroma_counts) != session_ids:
        raise BundleValidationError("Chroma collections 與 Excel 不一致")

    sessions = []
    for session_id, source_file in sorted(session_files.items()):
        metadata = history[session_id]
        if not isinstance(metadata, dict):
            raise BundleValidationError(f"row history 格式不正確：{session_id}")
        if metadata.get("embedding_provider") != embedding_provider:
            raise BundleValidationError(f"Embedding provider 不一致：{session_id}")
        if metadata.get("embedding_model") != embedding_model:
            raise BundleValidationError(f"Embedding model 不一致：{session_id}")
        if metadata.get("index_schema_version") != index_schema_version:
            raise BundleValidationError(f"索引版本不一致：{session_id}")
        if metadata.get("total_rows") != sqlite_counts[session_id]:
            raise BundleValidationError(f"SQLite 筆數不一致：{session_id}")
        if chroma_counts[session_id] != metadata["total_rows"]:
            raise BundleValidationError(f"Chroma 筆數不一致：{session_id}")
        if not metadata.get("data_fingerprint"):
            raise BundleValidationError(f"缺少資料 fingerprint：{session_id}")

        uuid_dir_name = metadata.get("chroma_uuid_dir_name")
        if (
            not uuid_dir_name
            or Path(uuid_dir_name).name != uuid_dir_name
            or not (chroma_dir / uuid_dir_name).is_dir()
        ):
            raise BundleValidationError(f"Chroma UUID 目錄不存在：{session_id}")

        sessions.append({
            "session_id": session_id,
            "source_file": source_file.name,
            "total_rows": metadata["total_rows"],
            "data_fingerprint": metadata.get("data_fingerprint"),
            "chroma_documents": chroma_counts[session_id],
        })
    return sessions


def build_runtime_metadata(
    data_dir: Path,
    instance_dir: Path,
    sessions: list[dict[str, Any]],
    embedding_provider: str,
    embedding_model: str,
    index_schema_version: int,
    created_at: str,
) -> RuntimeMetadata:
    """根據已驗證的來源建立 runtime metadata。"""
    session_ids = {session["session_id"] for session in sessions}
    filter_metadata = get_sqlite_filter_metadata(
        instance_dir / "legislature.db",
        session_ids,
    )
    runtime_sessions = {}
    for session in sessions:
        session_id = session["session_id"]
        source_file = data_dir / session["source_file"]
        runtime_sessions[session_id] = {
            "display_name": source_file.stem,
            "source_file": source_file.name,
            "source_file_sha256": calculate_file_hash(source_file),
            "total_rows": session["total_rows"],
            "data_fingerprint": session["data_fingerprint"],
            **filter_metadata[session_id],
        }

    metadata = {
        "metadata_schema_version": RUNTIME_METADATA_SCHEMA_VERSION,
        "created_at": created_at,
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "index_schema_version": index_schema_version,
        "sessions": runtime_sessions,
    }
    try:
        return validate_runtime_metadata(metadata)
    except RuntimeMetadataValidationError as exc:
        raise BundleValidationError("無法建立 runtime metadata") from exc


def verify_deployment_bundle(bundle_dir: Path) -> None:
    """驗證 bundle 實際檔案是否符合 manifest。"""
    manifest_path = bundle_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bundle_version = manifest["bundle_version"]
        expected_hashes = {
            path: metadata["sha256"]
            for path, metadata in manifest["files"].items()
        }
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise BundleValidationError("無法讀取 deployment bundle manifest") from exc

    actual_hashes = collect_file_hashes(bundle_dir)
    actual_hashes.pop("manifest.json", None)
    if actual_hashes != expected_hashes:
        raise BundleValidationError("Deployment bundle 檔案與 manifest 不一致")

    if bundle_version == 2:
        try:
            runtime_metadata = load_runtime_metadata(
                bundle_dir / "runtime_metadata.json"
            )
        except RuntimeMetadataValidationError as exc:
            raise BundleValidationError(
                "Deployment bundle metadata 與 manifest 不一致"
            ) from exc
        if runtime_metadata["created_at"] != manifest.get("created_at"):
            raise BundleValidationError(
                "Deployment bundle metadata 與 manifest 建立時間不一致"
            )
    elif bundle_version != 1:
        raise BundleValidationError("不支援的 deployment bundle version")


def verify_runtime_bundle(
    data_dir: Path,
    instance_dir: Path,
    manifest_path: Path,
) -> None:
    """驗證容器內的唯讀部署資料是否符合 bundle manifest。"""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_hashes = {
            path: metadata["sha256"]
            for path, metadata in manifest["files"].items()
        }
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise BundleValidationError("無法讀取 deployment bundle manifest") from exc

    try:
        actual_hashes = {
            f"data/sessions/{path}": digest
            for path, digest in collect_file_hashes(data_dir).items()
        }
        actual_hashes.update({
            f"instance/{path}": digest
            for path, digest in collect_file_hashes(instance_dir).items()
        })
    except OSError as exc:
        raise BundleValidationError("無法讀取 runtime deployment bundle") from exc

    if actual_hashes != expected_hashes:
        raise BundleValidationError("Runtime deployment bundle 與 manifest 不一致")


def verify_runtime_bundle_v2(
    instance_dir: Path,
    metadata_path: Path,
    manifest_path: Path,
) -> RuntimeMetadata:
    """驗證不含 Excel 與 row history 的 v2 runtime bundle。"""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["bundle_version"] != 2:
            raise BundleValidationError("Runtime deployment bundle 不是 v2")
        expected_hashes = {
            path: metadata["sha256"]
            for path, metadata in manifest["files"].items()
        }
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise BundleValidationError("無法讀取 deployment bundle manifest") from exc

    try:
        actual_hashes = {
            "runtime_metadata.json": calculate_file_hash(metadata_path),
        }
        actual_hashes.update({
            f"instance/{path}": digest
            for path, digest in collect_file_hashes(instance_dir).items()
        })
    except OSError as exc:
        raise BundleValidationError("無法讀取 runtime deployment bundle") from exc

    if set(actual_hashes) != set(expected_hashes):
        raise BundleValidationError("Runtime deployment bundle 與 manifest 不一致")
    mutable_chroma_catalog = "instance/chroma_db/chroma.sqlite3"
    immutable_paths = set(expected_hashes) - {mutable_chroma_catalog}
    if any(
        actual_hashes[path] != expected_hashes[path]
        for path in immutable_paths
    ):
        raise BundleValidationError("Runtime deployment bundle 與 manifest 不一致")

    try:
        runtime_metadata = load_runtime_metadata(metadata_path)
    except RuntimeMetadataValidationError as exc:
        raise BundleValidationError("Runtime metadata 格式不正確") from exc
    if runtime_metadata["created_at"] != manifest.get("created_at"):
        raise BundleValidationError(
            "Runtime metadata 與 manifest 建立時間不一致"
        )

    session_ids = set(runtime_metadata["sessions"])
    sqlite_counts = get_sqlite_row_counts(
        instance_dir / "legislature.db",
        session_ids,
    )
    chroma_counts = get_chroma_collection_counts(instance_dir / "chroma_db")
    if set(chroma_counts) != session_ids:
        raise BundleValidationError("Chroma collections 與 metadata 不一致")

    for session_id, session_metadata in runtime_metadata["sessions"].items():
        total_rows = session_metadata["total_rows"]
        if sqlite_counts[session_id] != total_rows:
            raise BundleValidationError(f"SQLite 筆數不一致：{session_id}")
        if chroma_counts[session_id] != total_rows:
            raise BundleValidationError(f"Chroma 筆數不一致：{session_id}")

    return runtime_metadata


def package_deployment_bundle(
    data_dir: Path,
    instance_dir: Path,
    output_dir: Path,
    embedding_provider: str,
    embedding_model: str,
    index_schema_version: int,
) -> Path:
    """建立不覆蓋既有版本的 deployment bundle。"""
    if output_dir.exists():
        raise FileExistsError(f"Bundle 目錄已存在：{output_dir}")
    if any(
        output_dir.resolve().is_relative_to(source_dir.resolve())
        for source_dir in (data_dir, instance_dir)
    ):
        raise BundleValidationError("Bundle 目錄不可放在來源資料目錄內")

    sessions = validate_deployment_sources(
        data_dir,
        instance_dir,
        embedding_provider,
        embedding_model,
        index_schema_version,
    )
    source_hashes_before = {
        "data": collect_file_hashes(data_dir),
        "instance": collect_file_hashes(instance_dir),
    }

    bundle_instance_dir = output_dir / "instance"
    bundle_instance_dir.mkdir(parents=True)

    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    runtime_metadata = build_runtime_metadata(
        data_dir,
        instance_dir,
        sessions,
        embedding_provider,
        embedding_model,
        index_schema_version,
        created_at,
    )
    with (output_dir / "runtime_metadata.json").open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(
            runtime_metadata,
            file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")

    shutil.copy2(instance_dir / "legislature.db", bundle_instance_dir)
    shutil.copytree(instance_dir / "chroma_db", bundle_instance_dir / "chroma_db")

    source_hashes_after = {
        "data": collect_file_hashes(data_dir),
        "instance": collect_file_hashes(instance_dir),
    }
    if source_hashes_after != source_hashes_before:
        raise BundleValidationError("來源資料在打包期間發生變更")

    bundle_hashes = collect_file_hashes(output_dir)
    manifest = {
        "bundle_version": 2,
        "created_at": created_at,
        "files": {
            path: {"sha256": digest}
            for path, digest in bundle_hashes.items()
        },
    }
    with (output_dir / "manifest.json").open("w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
    verify_deployment_bundle(output_dir)
    return output_dir
