import unittest
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAG_CLI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "rag-cli.yml"


class RagCliWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow_text = RAG_CLI_WORKFLOW.read_text(encoding="utf-8")
        cls.workflow = yaml.load(cls.workflow_text, Loader=yaml.BaseLoader)

    def test_requires_manual_paid_run_confirmation(self) -> None:
        confirmation = self.workflow["on"]["workflow_dispatch"]["inputs"][
            "confirm_paid_openai_run"
        ]

        self.assertEqual(confirmation["type"], "boolean")
        self.assertEqual(confirmation["required"], "true")
        self.assertEqual(confirmation["default"], "false")
        self.assertEqual(
            self.workflow["jobs"]["run-demo"]["if"],
            "${{ inputs.confirm_paid_openai_run }}",
        )

    def test_demo_rebuilds_only_when_manually_run(self) -> None:
        job = self.workflow["jobs"]["run-demo"]

        self.assertEqual(job["env"]["CHAT_PROVIDER"], "openai")
        self.assertEqual(job["env"]["EMBEDDING_PROVIDER"], "openai")
        self.assertEqual(job["env"]["INDEX_REBUILD_POLICY"], "auto")
        self.assertEqual(job["env"]["LOG_FILE_ENABLED"], "false")
        self.assertNotIn("cp .env.example .env", self.workflow_text)

    def test_real_key_is_scoped_to_cli_step(self) -> None:
        steps = self.workflow["jobs"]["run-demo"]["steps"]
        offline_step = next(
            step for step in steps if step["name"] == "Run offline checks"
        )
        cli_step = next(
            step for step in steps if step["name"] == "Run CLI with prefilled input"
        )

        self.assertEqual(offline_step["env"]["OPENAI_API_KEY"], "test-key")
        self.assertEqual(
            cli_step["env"]["OPENAI_API_KEY"],
            "${{ secrets.OPENAI_API_KEY }}",
        )
        self.assertNotIn("OPENAI_API_KEY", self.workflow["jobs"]["run-demo"]["env"])


if __name__ == "__main__":
    unittest.main()
