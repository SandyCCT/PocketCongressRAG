# run_workflow.py
from workflows.rag_workflow import prepare_local_session, run_one_question
from adapters.cli_inputs import select_session_cli, get_query_conditions_cli
from app.exceptions import AIProviderError
from nodes.chat_control import should_continue_chat
import app.config as config
from app.logging_config import configure_logging


def main():
    configure_logging()
    # 從 cli 互動取得 Excel 路徑與會期
    excel_path, choose_session = select_session_cli(config.DATA_FOLDER_PATH)

    # 前處理資料並檢查索引，只在選定會期後執行一次
    prepared_state = prepare_local_session(excel_path, choose_session)
    # 由 CLI 控制是否繼續提問，workflow 每次只回答一題
    while True:
        user_inputs, _, _ = get_query_conditions_cli(prepared_state)
        try:
            answer = run_one_question(prepared_state, user_inputs)
        except AIProviderError:
            answer = "AI 服務暫時無法使用，請稍後再試。"
        print(f"\n{answer}")
        if should_continue_chat() == "stop":
            break


if __name__ == "__main__":
    main()
