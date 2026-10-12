import unittest
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ComposeConfigTests(unittest.TestCase):
    def _load_config(self, name: str) -> dict:
        return yaml.safe_load(
            (PROJECT_ROOT / name).read_text(encoding="utf-8")
        )

    def test_base_config_allows_provider_selected_instance_directory(self) -> None:
        config = self._load_config("compose.yaml")
        app_config = config["services"]["app"]
        environment = app_config["environment"]

        self.assertEqual(app_config["build"]["context"], ".")
        self.assertEqual(app_config["build"]["target"], "local")
        self.assertEqual(
            app_config["ports"],
            ["127.0.0.1:${POCKETCONGRESS_PORT:-18000}:8000"],
        )

        self.assertEqual(environment["INSTANCE_DIR"], "${INSTANCE_DIR:-}")
        self.assertEqual(
            environment["ROW_COUNT_HISTORY_PATH"],
            "${ROW_COUNT_HISTORY_PATH:-}",
        )
        self.assertEqual(environment["CHROMA_DIR"], "${CHROMA_DIR:-}")
        self.assertEqual(environment["DB_PATH"], "${DB_PATH:-}")
        self.assertEqual(
            environment["INDEX_REBUILD_POLICY"],
            "${INDEX_REBUILD_POLICY:-verify_only}",
        )

    def test_vertex_override_mounts_adc_read_only(self) -> None:
        config = self._load_config("compose.vertexai.yaml")
        app_config = config["services"]["app"]

        self.assertEqual(
            app_config["environment"]["GOOGLE_APPLICATION_CREDENTIALS"],
            "/var/run/secrets/google/application_default_credentials.json",
        )
        self.assertEqual(
            app_config["volumes"],
            [
                "${GOOGLE_ADC_PATH:?請設定 GOOGLE_ADC_PATH}:"
                "/var/run/secrets/google/"
                "application_default_credentials.json:ro"
            ],
        )


if __name__ == "__main__":
    unittest.main()
