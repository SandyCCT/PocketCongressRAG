import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict, cast


RUNTIME_METADATA_SCHEMA_VERSION = 2
SUPPORTED_EMBEDDING_PROVIDERS = {"openai", "vertexai"}
SESSION_ID_PATTERN = re.compile(r"^S_\d+_\d+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class RuntimeMetadataValidationError(ValueError):
    """Runtime metadata 格式不正確。"""


class FilterOptions(TypedDict):
    member_names: list[str]
    committees: list[str]
    geographical_scopes: list[str]


class SessionRuntimeMetadata(TypedDict):
    display_name: str
    source_file: str
    source_file_sha256: str
    total_rows: int
    data_fingerprint: str
    max_committee_count: int
    max_geographical_scope_count: int
    filter_options: FilterOptions


class RuntimeMetadata(TypedDict):
    metadata_schema_version: int
    created_at: str
    embedding_provider: str
    embedding_model: str
    index_schema_version: int
    sessions: dict[str, SessionRuntimeMetadata]


def _require_exact_keys(
    value: dict[str, Any],
    expected_keys: set[str],
    field_name: str,
) -> None:
    actual_keys = set(value)
    if actual_keys != expected_keys:
        raise RuntimeMetadataValidationError(
            f"{field_name} 欄位不完整或包含未支援欄位"
        )


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeMetadataValidationError(f"{field_name} 必須是非空白字串")
    return value


def _require_non_negative_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeMetadataValidationError(f"{field_name} 必須是非負整數")
    return value


def _validate_sha256(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise RuntimeMetadataValidationError(
            f"{field_name} 必須是小寫 SHA-256"
        )


def _validate_sorted_unique_strings(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise RuntimeMetadataValidationError(f"{field_name} 必須是字串清單")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise RuntimeMetadataValidationError(
            f"{field_name} 不可包含空白或非字串值"
        )
    if value != sorted(set(value)):
        raise RuntimeMetadataValidationError(
            f"{field_name} 必須排序且不可重複"
        )


def _validate_filter_options(value: Any, session_id: str) -> None:
    if not isinstance(value, dict):
        raise RuntimeMetadataValidationError(
            f"filter_options 必須是物件：{session_id}"
        )
    _require_exact_keys(
        value,
        {"member_names", "committees", "geographical_scopes"},
        f"filter_options：{session_id}",
    )
    for field_name in ("member_names", "committees", "geographical_scopes"):
        _validate_sorted_unique_strings(
            value[field_name],
            f"filter_options.{field_name}：{session_id}",
        )


def _validate_session_metadata(value: Any, session_id: str) -> None:
    if not isinstance(value, dict):
        raise RuntimeMetadataValidationError(
            f"會期 metadata 必須是物件：{session_id}"
        )
    _require_exact_keys(
        value,
        {
            "display_name",
            "source_file",
            "source_file_sha256",
            "total_rows",
            "data_fingerprint",
            "max_committee_count",
            "max_geographical_scope_count",
            "filter_options",
        },
        f"會期 metadata：{session_id}",
    )
    _require_non_empty_string(value["display_name"], f"display_name：{session_id}")
    source_file = _require_non_empty_string(
        value["source_file"],
        f"source_file：{session_id}",
    )
    if (
        Path(source_file).name != source_file
        or Path(source_file).suffix.lower() != ".xlsx"
    ):
        raise RuntimeMetadataValidationError(
            f"source_file 必須是 Excel 檔名：{session_id}"
        )
    _validate_sha256(
        value["source_file_sha256"],
        f"source_file_sha256：{session_id}",
    )
    _require_non_negative_integer(value["total_rows"], f"total_rows：{session_id}")
    _validate_sha256(value["data_fingerprint"], f"data_fingerprint：{session_id}")
    _require_non_negative_integer(
        value["max_committee_count"],
        f"max_committee_count：{session_id}",
    )
    _require_non_negative_integer(
        value["max_geographical_scope_count"],
        f"max_geographical_scope_count：{session_id}",
    )
    _validate_filter_options(value["filter_options"], session_id)


def validate_runtime_metadata(metadata: Any) -> RuntimeMetadata:
    """驗證 deployment bundle 使用的 runtime metadata contract。"""
    if not isinstance(metadata, dict):
        raise RuntimeMetadataValidationError("runtime metadata 必須是物件")
    _require_exact_keys(
        metadata,
        {
            "metadata_schema_version",
            "created_at",
            "embedding_provider",
            "embedding_model",
            "index_schema_version",
            "sessions",
        },
        "runtime metadata",
    )

    metadata_schema_version = metadata["metadata_schema_version"]
    if (
        isinstance(metadata_schema_version, bool)
        or metadata_schema_version != RUNTIME_METADATA_SCHEMA_VERSION
    ):
        raise RuntimeMetadataValidationError("不支援的 runtime metadata schema version")

    created_at = _require_non_empty_string(metadata["created_at"], "created_at")
    try:
        parsed_created_at = datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise RuntimeMetadataValidationError("created_at 必須是 ISO 8601 時間") from exc
    if parsed_created_at.tzinfo is None:
        raise RuntimeMetadataValidationError("created_at 必須包含時區")

    embedding_provider = _require_non_empty_string(
        metadata["embedding_provider"],
        "embedding_provider",
    )
    if embedding_provider not in SUPPORTED_EMBEDDING_PROVIDERS:
        raise RuntimeMetadataValidationError(
            "不支援的 embedding provider"
        )
    _require_non_empty_string(metadata["embedding_model"], "embedding_model")
    index_schema_version = metadata["index_schema_version"]
    if (
        isinstance(index_schema_version, bool)
        or not isinstance(index_schema_version, int)
        or index_schema_version < 1
    ):
        raise RuntimeMetadataValidationError("index_schema_version 必須是正整數")

    sessions = metadata["sessions"]
    if not isinstance(sessions, dict) or not sessions:
        raise RuntimeMetadataValidationError("sessions 必須是非空白物件")
    for session_id, session_metadata in sessions.items():
        if (
            not isinstance(session_id, str)
            or not SESSION_ID_PATTERN.fullmatch(session_id)
        ):
            raise RuntimeMetadataValidationError(f"不合法的會期 ID：{session_id}")
        _validate_session_metadata(session_metadata, session_id)

    return cast(RuntimeMetadata, metadata)


def load_runtime_metadata(path: Path) -> RuntimeMetadata:
    """讀取並驗證 runtime metadata JSON。"""
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeMetadataValidationError("無法讀取 runtime metadata") from exc
    return validate_runtime_metadata(metadata)
