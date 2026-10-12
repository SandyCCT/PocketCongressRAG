import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CloudBuildConfigTests(unittest.TestCase):
    def _load_config(self, name: str) -> dict:
        return yaml.safe_load(
            (PROJECT_ROOT / name).read_text(encoding="utf-8")
        )

    @staticmethod
    def _step_args(config: dict, step_id: str) -> list[str]:
        step = next(step for step in config["steps"] if step["id"] == step_id)
        return step["args"]

    @staticmethod
    def _write_manifest(bundle_dir: Path) -> None:
        metadata_path = bundle_dir / "runtime_metadata.json"
        metadata_hash = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
        (bundle_dir / "manifest.json").write_text(
            json.dumps({
                "bundle_version": 2,
                "files": {
                    "runtime_metadata.json": {"sha256": metadata_hash},
                },
            }),
            encoding="utf-8",
        )

    def test_formal_deployment_uses_vertex_without_openai_secret(self) -> None:
        config = self._load_config("cloudbuild.yaml")
        deploy_args = self._step_args(config, "deploy-cloud-run")

        self.assertEqual(
            config["substitutions"]["_DEPLOYMENT_BUNDLE_PATH"],
            "deployment_bundles/2026-09-28-v6",
        )
        self.assertIn("--remove-secrets=OPENAI_API_KEY", deploy_args)
        self.assertFalse(
            any(argument.startswith("--update-secrets=") for argument in deploy_args)
        )
        self.assertIn(
            "--update-env-vars=CHAT_PROVIDER=vertexai,"
            "EMBEDDING_PROVIDER=vertexai,"
            "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,"
            "GOOGLE_CLOUD_LOCATION=global,"
            "VERTEX_CHAT_MODEL=gemini-2.5-flash,"
            "VERTEX_EMBEDDING_MODEL=gemini-embedding-001",
            deploy_args,
        )
        self.assertNotIn("_OPENAI_SECRET", config["substitutions"])
        self.assertNotIn("_OPENAI_SECRET_VERSION", config["substitutions"])
        self.assertEqual(
            config["substitutions"]["_VALIDATION_TAG"],
            "candidate",
        )
        self.assertIn("--no-traffic", deploy_args)
        self.assertIn("--tag=${_VALIDATION_TAG}", deploy_args)

    def test_cloud_build_uses_cloud_docker_target(self) -> None:
        config = self._load_config("cloudbuild.yaml")
        build_args = self._step_args(config, "build-image")

        target_index = build_args.index("--target")
        self.assertEqual(build_args[target_index + 1], "cloud")

    def test_vertex_bundle_metadata_gate(self) -> None:
        config = self._load_config("cloudbuild.yaml")
        script = config["steps"][0]["args"][1]

        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_dir = Path(temp_dir)
            metadata_path = bundle_dir / "runtime_metadata.json"
            compatible = {
                "metadata_schema_version": 2,
                "embedding_provider": "vertexai",
                "embedding_model": "gemini-embedding-001",
            }
            metadata_path.write_text(
                json.dumps(compatible),
                encoding="utf-8",
            )
            self._write_manifest(bundle_dir)
            executable = script.replace(
                "${_DEPLOYMENT_BUNDLE_PATH}",
                str(bundle_dir),
            )

            exec(executable, {})

            incompatible = {
                **compatible,
                "embedding_provider": "openai",
            }
            metadata_path.write_text(
                json.dumps(incompatible),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SystemExit, "metadata 不相容"):
                exec(executable, {})

    def test_vertex_bundle_manifest_gate(self) -> None:
        config = self._load_config("cloudbuild.yaml")
        script = config["steps"][0]["args"][1]

        with tempfile.TemporaryDirectory() as temp_dir:
            bundle_dir = Path(temp_dir)
            metadata_path = bundle_dir / "runtime_metadata.json"
            metadata_path.write_text(
                json.dumps({
                    "metadata_schema_version": 2,
                    "embedding_provider": "vertexai",
                    "embedding_model": "gemini-embedding-001",
                }),
                encoding="utf-8",
            )
            self._write_manifest(bundle_dir)
            executable = script.replace(
                "${_DEPLOYMENT_BUNDLE_PATH}",
                str(bundle_dir),
            )

            exec(executable, {})

            (bundle_dir / "unexpected.bin").write_bytes(b"changed")
            with self.assertRaisesRegex(SystemExit, "manifest 不一致"):
                exec(executable, {})

    def test_formal_deployment_does_not_promote_revision(self) -> None:
        config = self._load_config("cloudbuild.yaml")
        step_ids = {step["id"] for step in config["steps"]}
        all_args = [
            argument
            for step in config["steps"]
            for argument in step.get("args", [])
        ]

        self.assertNotIn("promote-cloud-run-revision", step_ids)
        self.assertNotIn("--to-latest", all_args)


if __name__ == "__main__":
    unittest.main()
