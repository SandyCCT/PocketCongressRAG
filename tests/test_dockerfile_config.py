import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DockerfileConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(
            encoding="utf-8"
        )

    def test_local_and_cloud_targets_share_runtime_base(self) -> None:
        self.assertIn(
            "FROM python:3.12-slim-bookworm AS runtime-base",
            self.dockerfile,
        )
        self.assertIn("FROM runtime-base AS cloud", self.dockerfile)
        self.assertIn("FROM runtime-base AS local", self.dockerfile)

    def test_only_cloud_target_copies_deployment_bundle(self) -> None:
        cloud_section, local_section = self.dockerfile.split(
            "FROM runtime-base AS local",
            maxsplit=1,
        )
        cloud_section = cloud_section.split(
            "FROM runtime-base AS cloud",
            maxsplit=1,
        )[1]

        self.assertIn("DEPLOYMENT_BUNDLE_PATH", cloud_section)
        self.assertIn("runtime_metadata.json", cloud_section)
        self.assertIn("manifest.json", cloud_section)
        self.assertNotIn("DEPLOYMENT_BUNDLE_PATH", local_section)
        self.assertNotIn("runtime_metadata.json", local_section)
        self.assertNotIn("manifest.json", local_section)

    def test_cloud_target_is_read_only_runtime(self) -> None:
        cloud_section = self.dockerfile.split(
            "FROM runtime-base AS cloud",
            maxsplit=1,
        )[1].split("FROM runtime-base AS local", maxsplit=1)[0]

        self.assertIn("INDEX_REBUILD_POLICY=verify_only", cloud_section)
        self.assertIn("LOG_FILE_ENABLED=false", cloud_section)

    def test_cloud_target_copies_bundle_to_runtime_paths(self) -> None:
        cloud_section = self.dockerfile.split(
            "FROM runtime-base AS cloud",
            maxsplit=1,
        )[1].split("FROM runtime-base AS local", maxsplit=1)[0]

        expected_copy_commands = [
            "COPY --chown=appuser:appuser "
            "${DEPLOYMENT_BUNDLE_PATH}/instance/ /app/instance/",
            "COPY --chown=appuser:appuser "
            "${DEPLOYMENT_BUNDLE_PATH}/runtime_metadata.json "
            "/app/deployment/runtime_metadata.json",
            "COPY --chown=appuser:appuser "
            "${DEPLOYMENT_BUNDLE_PATH}/manifest.json "
            "/app/deployment/manifest.json",
        ]

        for command in expected_copy_commands:
            with self.subTest(command=command):
                self.assertIn(command, cloud_section)


if __name__ == "__main__":
    unittest.main()
