import shutil
import subprocess
import tempfile
from pathlib import Path

from backend.config import Settings
from backend.models import ArtifactType


def apply_config(settings: Settings, artifact_type: ArtifactType, config: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix=f"iac-apply-{artifact_type.value}-") as tmp:
        workdir = Path(tmp)
        if artifact_type == ArtifactType.terraform:
            if not shutil.which("terraform"):
                return False, "terraform executable was not found on PATH"
            (workdir / "main.tf").write_text(config, encoding="utf-8")
            init = _run(["terraform", "init", "-input=false"], workdir, settings.validation_timeout_seconds)
            if init.returncode != 0:
                return False, _combined(init)
            result = _run(["terraform", "apply", "-auto-approve", "-no-color"], workdir, 600)
            return result.returncode == 0, _combined(result)

        if not shutil.which("kubectl"):
            return False, "kubectl executable was not found on PATH"
        manifest = workdir / "manifest.yaml"
        manifest.write_text(config, encoding="utf-8")
        result = _run(
            ["kubectl", "apply", "-n", settings.kubectl_namespace, "-f", str(manifest)],
            workdir,
            settings.validation_timeout_seconds,
        )
        return result.returncode == 0, _combined(result)


def _run(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(command, 124, stdout=exc.stdout or "", stderr="Command timed out")


def _combined(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part).strip()
