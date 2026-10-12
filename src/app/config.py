# src/app/config.py
import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv
"""從 .env 檔案設定資料與索引路徑。"""
load_dotenv(override=False)


SUPPORTED_AI_PROVIDERS = {"openai", "vertexai"}
DEFAULT_INSTANCE_DIRS = {
    "openai": Path("../instance"),
    "vertexai": Path("../instance/vertexai-gemini-embedding-001"),
}


def _read_text_env(name: str, default: str) -> str:
    """讀取文字環境變數，空字串時使用預設值。"""
    return os.getenv(name, "").strip() or default


def _read_optional_text_env(name: str) -> str | None:
    """讀取可選文字環境變數，空字串視為未設定。"""
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _read_provider_env(name: str, default: str) -> str:
    """讀取 AI provider，並拒絕不支援的設定值。"""
    provider = _read_text_env(name, default).lower()
    if provider not in SUPPORTED_AI_PROVIDERS:
        supported = "、".join(sorted(SUPPORTED_AI_PROVIDERS))
        raise ValueError(f"{name} 必須是 {supported}")
    return provider


def _read_bool_env(name: str, default: str) -> bool:
    """讀取布林環境變數，並拒絕無法辨識的設定值。"""
    value = os.getenv(name, default).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 必須是 true 或 false")


def _read_positive_float_env(name: str, default: str) -> float:
    """讀取大於 0 的浮點數環境變數。"""
    try:
        value = float(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} 必須是數字") from exc
    if value <= 0:
        raise ValueError(f"{name} 必須大於 0")
    return value


def _read_non_negative_int_env(name: str, default: str) -> int:
    """讀取大於或等於 0 的整數環境變數。"""
    try:
        value = int(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} 必須是整數") from exc
    if value < 0:
        raise ValueError(f"{name} 不可小於 0")
    return value


def _read_optional_path_env(name: str) -> Path | None:
    """讀取可選路徑，空字串視為未設定。"""
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    return Path(value)


def _get_instance_dir(embedding_provider: str) -> Path:
    """依 embedding provider 取得隔離的本機資料目錄。"""
    configured_path = _read_optional_path_env("INSTANCE_DIR")
    if configured_path is not None:
        return configured_path
    return DEFAULT_INSTANCE_DIRS[embedding_provider]


def _read_path_env(name: str, default: Path) -> Path:
    """讀取路徑環境變數，未設定時使用 provider 預設路徑。"""
    return _read_optional_path_env(name) or default


@dataclass(frozen=True)
class Settings:
    CHAT_PROVIDER = _read_provider_env("CHAT_PROVIDER", "openai")
    EMBEDDING_PROVIDER = _read_provider_env("EMBEDDING_PROVIDER", "openai")
    OPENAI_API_KEY = _read_optional_text_env("OPENAI_API_KEY")
    OPENAI_CHAT_MODEL = _read_text_env("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    OPENAI_EMBEDDING_MODEL = _read_text_env(
        "OPENAI_EMBEDDING_MODEL",
        "text-embedding-3-small",
    )
    GOOGLE_CLOUD_PROJECT = _read_optional_text_env("GOOGLE_CLOUD_PROJECT")
    GOOGLE_CLOUD_LOCATION = _read_text_env("GOOGLE_CLOUD_LOCATION", "global")
    VERTEX_CHAT_MODEL = _read_text_env(
        "VERTEX_CHAT_MODEL",
        "gemini-2.5-flash",
    )
    VERTEX_EMBEDDING_MODEL = _read_text_env(
        "VERTEX_EMBEDDING_MODEL",
        "gemini-embedding-001",
    )
    AI_REQUEST_TIMEOUT_SECONDS = _read_positive_float_env(
        "AI_REQUEST_TIMEOUT_SECONDS",
        "60",
    )
    AI_MAX_RETRIES = _read_non_negative_int_env("AI_MAX_RETRIES", "2")
    INSTANCE_DIR = _get_instance_dir(EMBEDDING_PROVIDER)
    ROW_COUNT_HISTORY_PATH = _read_path_env(
        "ROW_COUNT_HISTORY_PATH",
        INSTANCE_DIR / "row_count_tracker.json",
    )
    CHROMA_DIR = _read_path_env(
        "CHROMA_DIR",
        INSTANCE_DIR / "chroma_db",
    )
    DB_PATH = _read_path_env(
        "DB_PATH",
        INSTANCE_DIR / "legislature.db",
    )
    DATA_FOLDER_PATH = _read_optional_path_env("DATA_FOLDER_PATH")
    RUNTIME_METADATA_PATH = _read_optional_path_env("RUNTIME_METADATA_PATH")
    LOG_DIR = Path(os.getenv("LOG_DIR", "../logs"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "14"))
    LOG_FILE_ENABLED = _read_bool_env("LOG_FILE_ENABLED", "true")
    INDEX_REBUILD_POLICY = os.getenv("INDEX_REBUILD_POLICY", "auto")
    DEPLOYMENT_MANIFEST_PATH = _read_optional_path_env(
        "DEPLOYMENT_MANIFEST_PATH"
    )


def _validate_provider_settings(provider_settings: Settings) -> None:
    """確認已選用 provider 的必要設定存在。"""
    selected_providers = {
        provider_settings.CHAT_PROVIDER,
        provider_settings.EMBEDDING_PROVIDER,
    }
    if (
        "openai" in selected_providers
        and provider_settings.OPENAI_API_KEY is None
    ):
        raise ValueError("使用 openai provider 時必須設定 OPENAI_API_KEY")
    if (
        "vertexai" in selected_providers
        and provider_settings.GOOGLE_CLOUD_PROJECT is None
    ):
        raise ValueError("使用 vertexai provider 時必須設定 GOOGLE_CLOUD_PROJECT")


settings = Settings()

if settings.INDEX_REBUILD_POLICY not in {"auto", "verify_only"}:
    raise ValueError("INDEX_REBUILD_POLICY 必須是 auto 或 verify_only")

_validate_provider_settings(settings)

CHAT_PROVIDER = settings.CHAT_PROVIDER
EMBEDDING_PROVIDER = settings.EMBEDDING_PROVIDER
OPENAI_API_KEY = settings.OPENAI_API_KEY
OPENAI_CHAT_MODEL = settings.OPENAI_CHAT_MODEL
OPENAI_EMBEDDING_MODEL = settings.OPENAI_EMBEDDING_MODEL
GOOGLE_CLOUD_PROJECT = settings.GOOGLE_CLOUD_PROJECT
GOOGLE_CLOUD_LOCATION = settings.GOOGLE_CLOUD_LOCATION
VERTEX_CHAT_MODEL = settings.VERTEX_CHAT_MODEL
VERTEX_EMBEDDING_MODEL = settings.VERTEX_EMBEDDING_MODEL
AI_REQUEST_TIMEOUT_SECONDS = settings.AI_REQUEST_TIMEOUT_SECONDS
AI_MAX_RETRIES = settings.AI_MAX_RETRIES
ROW_COUNT_HISTORY_PATH = (
    str(settings.ROW_COUNT_HISTORY_PATH)
    if settings.ROW_COUNT_HISTORY_PATH is not None
    else None
)
CHROMA_DIR = str(settings.CHROMA_DIR)
DB_PATH = str(settings.DB_PATH)
DATA_FOLDER_PATH = (
    str(settings.DATA_FOLDER_PATH)
    if settings.DATA_FOLDER_PATH is not None
    else None
)
RUNTIME_METADATA_PATH = (
    str(settings.RUNTIME_METADATA_PATH)
    if settings.RUNTIME_METADATA_PATH is not None
    else None
)
LOG_DIR = str(settings.LOG_DIR)
LOG_LEVEL = settings.LOG_LEVEL
LOG_RETENTION_DAYS = settings.LOG_RETENTION_DAYS
LOG_FILE_ENABLED = settings.LOG_FILE_ENABLED
INDEX_REBUILD_POLICY = settings.INDEX_REBUILD_POLICY
DEPLOYMENT_MANIFEST_PATH = (
    str(settings.DEPLOYMENT_MANIFEST_PATH)
    if settings.DEPLOYMENT_MANIFEST_PATH is not None
    else None
)
