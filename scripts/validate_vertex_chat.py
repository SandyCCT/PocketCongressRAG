import argparse
import json
import os
import shutil
import subprocess
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


TEST_CASES = [
    {
        "name": "總筆數統計",
        "expected_route": "SQL",
        "question": "這個會期總共有幾筆發言？",
    },
    {
        "name": "委員發言次數",
        "expected_route": "SQL",
        "question": "黃國昌委員總共發言幾次？",
    },
    {
        "name": "指定日期查詢",
        "expected_route": "SQL",
        "question": "2024-03-07 有哪些委員發言？",
    },
    {
        "name": "特教助理員議題",
        "expected_route": "Vector",
        "question": "哪些委員要求改善特教助理員的名額、薪資或待遇？",
    },
    {
        "name": "學習歷程代寫議題",
        "expected_route": "Vector",
        "question": "哪些委員關切學習歷程檔案代寫亂象？",
    },
    {
        "name": "營養午餐食安議題",
        "expected_route": "Vector",
        "question": "哪些委員關注蘇丹紅與學生營養午餐安全？",
    },
]

FAILED_ANSWERS = {
    "向量檢索失敗，請稍後再試。",
}


class ValidationError(RuntimeError):
    """Gemini Chat 手動驗收失敗。"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "對 private Cloud Run Vertex revision 執行手動驗收；"
            "實際執行會產生少量 API 使用量。"
        )
    )
    parser.add_argument(
        "--base-url",
        help="Cloud Run revision 或 service 的 HTTPS URL。",
    )
    parser.add_argument(
        "--session-id",
        default="S_11_1",
        help="用於問答測試的會期 ID，預設為 S_11_1。",
    )
    parser.add_argument(
        "--route",
        choices=("SQL", "Vector"),
        help="只執行指定 route 的測試案例。",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="每個 HTTP request 的 timeout 秒數，預設為 300。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出測試案例，不取得 token、不發送 HTTP request。",
    )
    return parser.parse_args()


def _validate_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValidationError("--base-url 必須是有效的 HTTPS URL")
    if (
        parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ValidationError("--base-url 不可包含 path、query 或 fragment")
    return value.rstrip("/")


def _load_identity_token() -> str:
    environment_token = os.getenv("CLOUD_RUN_ID_TOKEN", "").strip()
    if environment_token:
        return environment_token

    if shutil.which("gcloud") is None:
        raise ValidationError(
            "找不到 gcloud；請先安裝並登入，或設定 CLOUD_RUN_ID_TOKEN"
        )

    result = subprocess.run(
        ["gcloud", "auth", "print-identity-token"],
        capture_output=True,
        check=False,
        text=True,
    )
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        raise ValidationError(
            "無法取得 identity token；請先確認 gcloud active account"
        )
    return token


def _request_json(
    base_url: str,
    path: str,
    token: str,
    timeout: float,
    payload: dict[str, Any] | None = None,
) -> Any:
    body = None
    method = "GET"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        method = "POST"

    request = Request(
        f"{base_url}{path}",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise ValidationError(
            f"{method} {path} 回傳 HTTP {exc.code}：{error_body}"
        ) from None
    except URLError as exc:
        raise ValidationError(
            f"{method} {path} 連線失敗：{exc.reason}"
        ) from None

    try:
        return json.loads(response_body)
    except json.JSONDecodeError:
        raise ValidationError(
            f"{method} {path} 未回傳有效 JSON"
        ) from None


def _select_test_cases(route: str | None) -> list[dict[str, str]]:
    if route is None:
        return TEST_CASES
    return [
        test_case
        for test_case in TEST_CASES
        if test_case["expected_route"] == route
    ]


def _print_test_cases(test_cases: list[dict[str, str]]) -> None:
    for index, test_case in enumerate(test_cases, start=1):
        print(
            f'{index}. [{test_case["expected_route"]}] '
            f'{test_case["name"]}：{test_case["question"]}'
        )


def main() -> None:
    args = parse_args()
    test_cases = _select_test_cases(args.route)
    if args.dry_run:
        print("Dry run：不會取得 token，也不會送出 API request。")
        _print_test_cases(test_cases)
        return

    if not args.base_url:
        raise ValidationError("實際執行時必須提供 --base-url")

    base_url = _validate_base_url(args.base_url)
    token = _load_identity_token()

    live = _request_json(base_url, "/health/live", token, args.timeout)
    ready = _request_json(base_url, "/health/ready", token, args.timeout)
    sessions = _request_json(
        base_url,
        "/api/v1/sessions",
        token,
        args.timeout,
    )
    if live != {"status": "ok"}:
        raise ValidationError("Liveness response 不符合預期")
    if ready != {"status": "ready"}:
        raise ValidationError("Readiness response 不符合預期")
    if not isinstance(sessions, list):
        raise ValidationError("Sessions response 必須是陣列")

    available_session_ids = {
        session.get("id")
        for session in sessions
        if isinstance(session, dict)
    }
    if args.session_id not in available_session_ids:
        raise ValidationError(
            f"找不到測試會期：{args.session_id}"
        )

    print("基礎 endpoints 驗證通過，開始付費問答測試。")
    for index, test_case in enumerate(test_cases, start=1):
        response = _request_json(
            base_url,
            "/api/v1/questions",
            token,
            args.timeout,
            {
                "session_id": args.session_id,
                "question": test_case["question"],
            },
        )
        answer = response.get("answer") if isinstance(response, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise ValidationError(
                f'{test_case["name"]} 未回傳非空白答案'
            )
        if answer.strip() in FAILED_ANSWERS:
            raise ValidationError(
                f'{test_case["name"]} 回傳應用程式錯誤：{answer.strip()}'
            )

        print(
            f'\n{index}. 預期 route={test_case["expected_route"]} '
            f'測試={test_case["name"]}'
        )
        print(answer.strip())

    print(
        "\nHTTP 與回答格式驗證通過。請繼續從 Cloud Run logs 核對 "
        "route、structured output 與 sql_query tool call。"
    )


if __name__ == "__main__":
    try:
        main()
    except ValidationError as exc:
        raise SystemExit(f"驗收失敗：{exc}") from None
