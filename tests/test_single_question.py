import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

import pandas as pd
from google.api_core.exceptions import GoogleAPIError
from openai import APIError as OpenAIAPIError

from adapters.cli_inputs import get_query_conditions_cli
from app.exceptions import AIProviderError, IndexNotReadyError
from nodes.input_transform import user_input_and_transform
from run_workflow import main
from services.normalizers import build_search_normalize_prompt
from workflows.rag_workflow import (
    optimizer_workflow,
    prepare_local_session,
    prepare_runtime_session,
    run_one_question,
)


class SingleQuestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataframe = pd.DataFrame([{
            "委員名字": "王育敏",
            "所屬委員會1": "教育及文化委員會",
            "涵蓋層級1": "全國性",
        }])
        self.user_inputs = {
            "委員名字": "王育敏",
            "涵蓋層級": "all",
            "所屬委員會": "all",
            "問題": "總共發言幾次？",
        }
        self.runtime_metadata = {
            "metadata_schema_version": 2,
            "created_at": "2026-09-26T00:00:00+08:00",
            "embedding_provider": "openai",
            "embedding_model": "embedding-model",
            "index_schema_version": 1,
            "sessions": {
                "S_11_1": {
                    "display_name": "第11屆第1會期",
                    "source_file": "第11屆第1會期.xlsx",
                    "source_file_sha256": "a" * 64,
                    "total_rows": 1,
                    "data_fingerprint": "b" * 64,
                    "max_committee_count": 1,
                    "max_geographical_scope_count": 1,
                    "filter_options": {
                        "member_names": ["王育敏"],
                        "committees": ["教育及文化委員會"],
                        "geographical_scopes": ["全國性"],
                    },
                }
            },
        }

    def _snapshot_files(self, root: Path) -> dict[str, tuple[bytes, int]]:
        return {
            path.relative_to(root).as_posix(): (
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_normalize_prompt_uses_filter_options(self) -> None:
        filter_options = self.runtime_metadata["sessions"]["S_11_1"][
            "filter_options"
        ]

        prompt = build_search_normalize_prompt(
            filter_options,
            self.user_inputs,
        )

        self.assertIn("委員名字：['王育敏']", prompt)
        self.assertIn("涵蓋層級：['全國性']", prompt)
        self.assertIn("所屬委員會：['教育及文化委員會']", prompt)

    @patch(
        "builtins.input",
        side_effect=["王育敏", "全國性", "教育及文化委員會", "問題"],
    )
    def test_cli_query_conditions_uses_filter_options(self, input_value) -> None:
        state = {
            "filter_options": self.runtime_metadata["sessions"]["S_11_1"][
                "filter_options"
            ]
        }

        inputs, committees, geographical_scopes = get_query_conditions_cli(state)

        self.assertEqual(inputs["委員名字"], "王育敏")
        self.assertEqual(committees, ["教育及文化委員會"])
        self.assertEqual(geographical_scopes, ["全國性"])
        self.assertIn("['全國性']", input_value.call_args_list[1].args[0])

    @patch("nodes.input_transform.normalize_filters_with_llm")
    def test_transform_uses_supplied_inputs(self, normalize) -> None:
        normalize.return_value = "委員名字:王育敏、涵蓋層級:all、所屬委員會:all"
        state = {
            "filter_options": {
                "member_names": ["王育敏"],
                "committees": ["教育及文化委員會"],
                "geographical_scopes": ["全國性"],
            },
            "max_committee_count": 1,
            "max_geographical_scope_count": 1,
            "user_inputs": self.user_inputs,
        }

        result = user_input_and_transform(state)

        self.assertEqual(result["input_query"], "總共發言幾次？")
        self.assertEqual(result["search_filter"], {"委員名字": "王育敏"})
        normalize.assert_called_once_with(
            state["filter_options"],
            self.user_inputs,
        )

    @patch("workflows.rag_workflow.optimizer_workflow")
    def test_run_one_question_returns_workflow_answer(self, workflow) -> None:
        workflow.invoke.return_value = {"response": "查詢結果"}
        prepared_state = {
            "choose_session": "S_11_1",
            "max_committee_count": 1,
            "max_geographical_scope_count": 1,
            "filter_options": {
                "member_names": ["王育敏"],
                "committees": ["教育及文化委員會"],
                "geographical_scopes": ["全國性"],
            },
        }

        answer = run_one_question(prepared_state, self.user_inputs)

        self.assertEqual(answer, "查詢結果")
        workflow.invoke.assert_called_once_with({
            **prepared_state,
            "user_inputs": self.user_inputs,
        })
        self.assertNotIn("user_inputs", prepared_state)

    @patch("workflows.rag_workflow.optimizer_workflow")
    def test_run_one_question_converts_provider_errors(self, workflow) -> None:
        provider_errors = (
            OpenAIAPIError("private detail", request=None, body=None),
            GoogleAPIError("private detail"),
        )

        for provider_error in provider_errors:
            with self.subTest(error_type=type(provider_error).__name__):
                workflow.invoke.side_effect = provider_error
                with self.assertRaisesRegex(
                    AIProviderError,
                    "AI provider request failed",
                ) as error:
                    run_one_question({}, self.user_inputs)
                self.assertNotIn("private detail", str(error.exception))

    @patch("workflows.rag_workflow.optimizer_workflow")
    def test_run_one_question_preserves_domain_error(self, workflow) -> None:
        provider_error = AIProviderError("sanitized provider error")
        workflow.invoke.side_effect = provider_error

        with self.assertRaises(AIProviderError) as error:
            run_one_question({}, self.user_inputs)

        self.assertIs(error.exception, provider_error)

    @patch("workflows.rag_workflow.rebuild")
    @patch("workflows.rag_workflow.need_rebuild", return_value="not rebuild")
    @patch("workflows.rag_workflow.get_row_count")
    @patch("workflows.rag_workflow.preprocess_and_merge")
    def test_prepare_local_session_checks_index_once(
        self, preprocess, get_row_count, need_rebuild, rebuild
    ) -> None:
        preprocess.return_value = (self.dataframe, 1, 1, {"total": 1})
        get_row_count.return_value = {
            "counts": {"total": 1},
            "row_count_history": {},
            "data_fingerprint": "fingerprint",
        }

        prepared_state = prepare_local_session("session.xlsx", "S_11_1")

        self.assertEqual(prepared_state["excel_path"], "session.xlsx")
        self.assertEqual(prepared_state["choose_session"], "S_11_1")
        self.assertEqual(prepared_state["filter_options"], {
            "member_names": ["王育敏"],
            "committees": ["教育及文化委員會"],
            "geographical_scopes": ["全國性"],
        })
        preprocess.assert_called_once_with("session.xlsx")
        get_row_count.assert_called_once()
        need_rebuild.assert_called_once_with(prepared_state)
        rebuild.assert_not_called()

    @patch("workflows.rag_workflow.rebuild")
    @patch("workflows.rag_workflow.need_rebuild", return_value="rebuild")
    @patch("workflows.rag_workflow.get_row_count", return_value={"counts": {"total": 1}})
    @patch("workflows.rag_workflow.preprocess_and_merge")
    def test_prepare_local_session_rebuilds_selected_session(
        self, preprocess, get_row_count, need_rebuild, rebuild
    ) -> None:
        preprocess.return_value = (self.dataframe, 1, 1, {"total": 1})

        with patch("workflows.rag_workflow.config.INDEX_REBUILD_POLICY", "auto"):
            prepared_state = prepare_local_session(
                "other-session.xlsx",
                "S_11_2",
            )

        self.assertEqual(prepared_state["choose_session"], "S_11_2")
        get_row_count.assert_called_once()
        need_rebuild.assert_called_once_with(prepared_state)
        rebuild.assert_called_once_with(prepared_state)

    @patch("workflows.rag_workflow.rebuild")
    @patch("workflows.rag_workflow.need_rebuild", return_value="rebuild")
    @patch("workflows.rag_workflow.get_row_count", return_value={"counts": {"total": 1}})
    @patch("workflows.rag_workflow.preprocess_and_merge")
    def test_prepare_local_session_verify_only_does_not_rebuild(
        self, preprocess, get_row_count, need_rebuild, rebuild
    ) -> None:
        preprocess.return_value = (self.dataframe, 1, 1, {"total": 1})

        with patch("workflows.rag_workflow.config.INDEX_REBUILD_POLICY", "verify_only"):
            with self.assertRaises(IndexNotReadyError):
                prepare_local_session("session.xlsx", "S_11_1")

        get_row_count.assert_called_once()
        need_rebuild.assert_called_once()
        rebuild.assert_not_called()

    @patch("workflows.rag_workflow.rebuild")
    @patch("workflows.rag_workflow.preprocess_and_merge")
    def test_prepare_local_session_verify_only_does_not_modify_runtime_files(
        self,
        preprocess,
        rebuild,
    ) -> None:
        preprocess.return_value = (
            self.dataframe,
            1,
            1,
            {"total": 1, "per_sheet": {"Sheet1": 1}},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir)
            data_dir = runtime_dir / "data"
            instance_dir = runtime_dir / "instance"
            chroma_dir = instance_dir / "chroma_db"
            data_dir.mkdir()
            chroma_dir.mkdir(parents=True)

            excel_path = data_dir / "第11屆第1會期.xlsx"
            excel_path.write_bytes(b"excel")
            (instance_dir / "legislature.db").write_bytes(b"sqlite")
            (chroma_dir / "chroma.sqlite3").write_bytes(b"chroma")
            uuid_dir = chroma_dir / "collection-uuid"
            uuid_dir.mkdir()
            (uuid_dir / "index.bin").write_bytes(b"index")

            history_path = instance_dir / "row_count_tracker.json"
            history_path.write_text(
                json.dumps({
                    "S_11_1": {
                        "total_rows": 1,
                        "data_fingerprint": "outdated-fingerprint",
                    }
                }),
                encoding="utf-8",
            )
            files_before = self._snapshot_files(runtime_dir)

            with patch(
                "nodes.maintenance.config.ROW_COUNT_HISTORY_PATH",
                str(history_path),
            ), patch(
                "workflows.rag_workflow.config.INDEX_REBUILD_POLICY",
                "verify_only",
            ):
                with self.assertRaises(IndexNotReadyError):
                    prepare_local_session(str(excel_path), "S_11_1")

            files_after = self._snapshot_files(runtime_dir)

        self.assertEqual(files_after, files_before)
        rebuild.assert_not_called()

    @patch("workflows.rag_workflow.rebuild")
    @patch("workflows.rag_workflow.need_rebuild")
    @patch("workflows.rag_workflow.get_row_count")
    @patch("workflows.rag_workflow.preprocess_and_merge")
    def test_prepare_runtime_session_does_not_use_local_build_steps(
        self,
        preprocess,
        get_row_count,
        need_rebuild,
        rebuild,
    ) -> None:
        with patch.multiple(
            "workflows.rag_workflow",
            EMBEDDING_PROVIDER="openai",
            EMBEDDING_MODEL="embedding-model",
            INDEX_SCHEMA_VERSION=1,
        ):
            prepared_state = prepare_runtime_session(
                self.runtime_metadata,
                "S_11_1",
            )

        self.assertEqual(prepared_state, {
            "choose_session": "S_11_1",
            "max_committee_count": 1,
            "max_geographical_scope_count": 1,
            "filter_options": {
                "member_names": ["王育敏"],
                "committees": ["教育及文化委員會"],
                "geographical_scopes": ["全國性"],
            },
        })
        preprocess.assert_not_called()
        get_row_count.assert_not_called()
        need_rebuild.assert_not_called()
        rebuild.assert_not_called()

    def test_prepare_runtime_session_rejects_incompatible_index(self) -> None:
        cases = {
            "embedding-provider": {"embedding_provider": "vertexai"},
            "embedding-model": {"embedding_model": "different-model"},
            "index-schema": {"index_schema_version": 2},
        }
        for name, changes in cases.items():
            with self.subTest(mismatch=name):
                metadata = copy.deepcopy(self.runtime_metadata)
                metadata.update(changes)
                with patch.multiple(
                    "workflows.rag_workflow",
                    EMBEDDING_PROVIDER="openai",
                    EMBEDDING_MODEL="embedding-model",
                    INDEX_SCHEMA_VERSION=1,
                ):
                    with self.assertRaises(IndexNotReadyError):
                        prepare_runtime_session(metadata, "S_11_1")

    def test_prepare_runtime_session_rejects_unknown_session(self) -> None:
        with patch.multiple(
            "workflows.rag_workflow",
            EMBEDDING_PROVIDER="openai",
            EMBEDDING_MODEL="embedding-model",
            INDEX_SCHEMA_VERSION=1,
        ):
            with self.assertRaisesRegex(ValueError, "找不到指定的會期"):
                prepare_runtime_session(self.runtime_metadata, "S_11_2")

    def test_answer_paths_end_after_one_question(self) -> None:
        edges = {
            (edge.source, edge.target)
            for edge in optimizer_workflow.get_graph().edges
        }

        self.assertIn(("llm_call", "__end__"), edges)
        self.assertIn(("vector_search", "__end__"), edges)

    @patch(
        "run_workflow.select_session_cli",
        return_value=("session.xlsx", "S_11_1"),
    )
    @patch("run_workflow.prepare_local_session")
    @patch("run_workflow.get_query_conditions_cli")
    @patch("run_workflow.run_one_question", side_effect=["第一題答案", "第二題答案"])
    @patch("builtins.print")
    @patch("run_workflow.should_continue_chat", side_effect=["continue", "stop"])
    def test_cli_controls_multiple_questions(
        self, continue_chat, print_answer, ask, get_inputs, prepare, select_session
    ) -> None:
        prepared_state = {
            "choose_session": "S_11_1",
            "filter_options": {
                "member_names": ["王育敏"],
                "committees": ["教育及文化委員會"],
                "geographical_scopes": ["全國性"],
            },
        }
        prepare.return_value = prepared_state
        second_inputs = {**self.user_inputs, "問題": "有什麼看法？"}
        get_inputs.side_effect = [
            (self.user_inputs, [], []),
            (second_inputs, [], []),
        ]

        main()

        prepare.assert_called_once_with("session.xlsx", "S_11_1")
        self.assertEqual(ask.call_args_list, [
            call(prepared_state, self.user_inputs),
            call(prepared_state, second_inputs),
        ])
        self.assertEqual(continue_chat.call_count, 2)
        self.assertEqual(print_answer.call_args_list, [
            call("\n第一題答案"),
            call("\n第二題答案"),
        ])

    @patch("run_workflow.select_session_cli", return_value=("session.xlsx", "S_11_1"))
    @patch("run_workflow.prepare_local_session", return_value={})
    @patch("run_workflow.get_query_conditions_cli")
    @patch("run_workflow.run_one_question")
    @patch("builtins.print")
    @patch("run_workflow.should_continue_chat", return_value="stop")
    def test_cli_reports_sanitized_provider_error(
        self,
        continue_chat,
        print_answer,
        ask,
        get_inputs,
        prepare,
        select_session,
    ) -> None:
        get_inputs.return_value = (self.user_inputs, [], [])
        ask.side_effect = AIProviderError("private detail")

        main()

        print_answer.assert_called_once_with(
            "\nAI 服務暫時無法使用，請稍後再試。"
        )
        continue_chat.assert_called_once()


if __name__ == "__main__":
    unittest.main()
