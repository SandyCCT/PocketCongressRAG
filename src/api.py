"""提供會期清單與單次問答 API。"""
from functools import lru_cache
from pathlib import Path
import re
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.config import (
    CHROMA_DIR,
    DATA_FOLDER_PATH,
    DB_PATH,
    DEPLOYMENT_MANIFEST_PATH,
    ROW_COUNT_HISTORY_PATH,
    RUNTIME_METADATA_PATH,
)
from app.exceptions import AIProviderError, IndexNotReadyError
from app.logging_config import configure_logging
from services.deployment_bundle import (
    BundleValidationError,
    verify_runtime_bundle,
    verify_runtime_bundle_v2,
)
from services.deployment_metadata import (
    RuntimeMetadata,
    load_runtime_metadata,
)
from workflows.rag_workflow import (
    prepare_local_session,
    prepare_runtime_session,
    run_one_question,
)


logger = configure_logging()

app = FastAPI(title="PocketCongressRAG")
WEB_DIR = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


class Session(BaseModel):
    id: str
    name: str


class QuestionRequest(BaseModel):
    session_id: str
    question: str = Field(min_length=1)
    member_name: str = "all"
    geographical_scope: str = "all"
    committee: str = "all"

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("問題不能為空白")
        return value.strip()


class QuestionResponse(BaseModel):
    answer: str


class HealthResponse(BaseModel):
    status: str


def get_session_files() -> dict[str, Path]:
    """只從設定的資料夾取得符合命名規則的會期 Excel。"""
    if DATA_FOLDER_PATH is None:
        raise OSError("未設定本機會期資料路徑")
    files = sorted(
        (path for path in Path(DATA_FOLDER_PATH).iterdir()
         if path.is_file() and path.suffix.lower() == ".xlsx"
         and not path.name.startswith("~$")),
        key=lambda path: path.name,
    )
    sessions = {}
    for path in files:
        match = re.match(r"第(\d+)屆第(\d+)會期", path.stem)
        if match:
            session_id = f"S_{match.group(1)}_{match.group(2)}"
            sessions.setdefault(session_id, path)
    return sessions


def _session_sort_key(session_id: str) -> tuple[int, ...]:
    """將會期 ID 轉成數字排序鍵。"""
    return tuple(map(int, session_id.split("_")[1:]))


@lru_cache(maxsize=2)
def _load_runtime_metadata(
    metadata_path: str,
    modified_time_ns: int,
    file_size: int,
) -> RuntimeMetadata:
    """依 metadata 檔案狀態快取解析結果。"""
    logger.info(
        "讀取 runtime metadata：modified_time_ns=%s file_size=%s",
        modified_time_ns,
        file_size,
    )
    return load_runtime_metadata(Path(metadata_path))


def get_session_catalog() -> dict[str, str]:
    """依執行模式取得會期 ID 與顯示名稱。"""
    if RUNTIME_METADATA_PATH is None:
        return {
            session_id: path.stem
            for session_id, path in get_session_files().items()
        }

    metadata_path = Path(RUNTIME_METADATA_PATH)
    file_stat = metadata_path.stat()
    metadata = _load_runtime_metadata(
        str(metadata_path),
        file_stat.st_mtime_ns,
        file_stat.st_size,
    )
    return {
        session_id: session_metadata["display_name"]
        for session_id, session_metadata in metadata["sessions"].items()
    }


@lru_cache(maxsize=1)
def _validate_readiness() -> None:
    """以唯讀方式確認執行所需的資料與索引皆可使用。"""
    if RUNTIME_METADATA_PATH is not None:
        if DEPLOYMENT_MANIFEST_PATH is None:
            raise BundleValidationError("未設定 deployment manifest")
        runtime_metadata = verify_runtime_bundle_v2(
            instance_dir=Path(DB_PATH).parent,
            metadata_path=Path(RUNTIME_METADATA_PATH),
            manifest_path=Path(DEPLOYMENT_MANIFEST_PATH),
        )
        for session_id in runtime_metadata["sessions"]:
            prepare_runtime_session(runtime_metadata, session_id)
        return

    if not get_session_files():
        raise BundleValidationError("找不到可使用的會期資料")

    if ROW_COUNT_HISTORY_PATH is None:
        raise BundleValidationError("未設定 row history 路徑")
    required_paths = [
        Path(DB_PATH),
        Path(ROW_COUNT_HISTORY_PATH),
        Path(CHROMA_DIR) / "chroma.sqlite3",
    ]
    if any(not path.is_file() for path in required_paths):
        raise BundleValidationError("執行所需的索引檔案不完整")

    if DEPLOYMENT_MANIFEST_PATH:
        verify_runtime_bundle(
            data_dir=Path(DATA_FOLDER_PATH),
            instance_dir=Path(DB_PATH).parent,
            manifest_path=Path(DEPLOYMENT_MANIFEST_PATH),
        )


@lru_cache(maxsize=8)
def _get_local_prepared_session(
    session_id: str,
    excel_path: str,
    modified_time_ns: int,
    file_size: int,
) -> dict:
    """依會期與 Excel 檔案狀態快取前處理結果。"""
    logger.info(
        "準備會期資料快取：session=%s modified_time_ns=%s file_size=%s",
        session_id,
        modified_time_ns,
        file_size,
    )
    return prepare_local_session(excel_path, session_id)


@lru_cache(maxsize=8)
def _get_runtime_prepared_session(
    session_id: str,
    metadata_path: str,
    modified_time_ns: int,
    file_size: int,
) -> dict:
    """依會期與 metadata 檔案狀態快取唯讀問答狀態。"""
    runtime_metadata = _load_runtime_metadata(
        metadata_path,
        modified_time_ns,
        file_size,
    )
    return prepare_runtime_session(runtime_metadata, session_id)


@app.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/health/ready", response_model=HealthResponse)
def health_ready() -> HealthResponse:
    try:
        _validate_readiness()
    except (BundleValidationError, OSError, ValueError) as exc:
        logger.warning(
            "Readiness 檢查失敗：error_type=%s",
            type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="服務尚未就緒") from None
    return HealthResponse(status="ready")


@app.get("/api/v1/sessions", response_model=List[Session])
def list_sessions() -> List[Session]:
    try:
        session_catalog = get_session_catalog()
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="目前無法讀取會期資料") from None

    session_ids = sorted(
        session_catalog,
        key=_session_sort_key,
    )
    return [Session(id=session_id, name=session_catalog[session_id])
            for session_id in session_ids]


@app.post("/api/v1/questions", response_model=QuestionResponse)
def ask_question(request: QuestionRequest) -> QuestionResponse:
    try:
        if RUNTIME_METADATA_PATH is None:
            session_files = get_session_files()
            session_exists = request.session_id in session_files
        else:
            session_files = {}
            session_exists = request.session_id in get_session_catalog()
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="目前無法讀取會期資料") from None

    if not session_exists:
        raise HTTPException(status_code=404, detail="找不到指定的會期")

    user_inputs = {
        "委員名字": request.member_name,
        "涵蓋層級": request.geographical_scope,
        "所屬委員會": request.committee,
        "問題": request.question,
    }
    try:
        if RUNTIME_METADATA_PATH is None:
            excel_path = session_files[request.session_id]
            file_stat = excel_path.stat()
            prepared_state = _get_local_prepared_session(
                request.session_id,
                str(excel_path),
                file_stat.st_mtime_ns,
                file_stat.st_size,
            )
        else:
            metadata_path = Path(RUNTIME_METADATA_PATH)
            file_stat = metadata_path.stat()
            prepared_state = _get_runtime_prepared_session(
                request.session_id,
                str(metadata_path),
                file_stat.st_mtime_ns,
                file_stat.st_size,
            )
        answer = run_one_question(prepared_state, user_inputs)
    except IndexNotReadyError:
        raise HTTPException(status_code=503, detail="目前資料索引尚未就緒") from None
    except AIProviderError as exc:
        logger.warning(
            "AI provider 無法完成問答：error_type=%s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="AI 服務暫時無法使用，請稍後再試",
        ) from None
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="目前無法完成問答，請稍後再試") from None

    return QuestionResponse(answer=answer)
