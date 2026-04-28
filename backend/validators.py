import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from backend.config import Settings
from backend.models import ArtifactType


@dataclass
class ValidationResult:
    ok: bool
    output: str


class IaCValidator:
    def __init__(self, settings: Settings):
        self.settings = settings

    def validate(self, artifact_type: ArtifactType, config: str) -> ValidationResult:
        if artifact_type == ArtifactType.terraform:
            return self._validate_terraform(config)
        return self._validate_kubernetes(config)

    def _validate_terraform(self, config: str) -> ValidationResult:
        if not shutil.which("terraform"):
            return ValidationResult(False, "terraform executable was not found on PATH")

        with tempfile.TemporaryDirectory(prefix="iac-terraform-") as tmp:
            workdir = Path(tmp)
            (workdir / "main.tf").write_text(config, encoding="utf-8")
            init = self._run(["terraform", "init", "-backend=false", "-input=false"], workdir)
            if init.returncode != 0:
                return ValidationResult(False, _combined_output(init))
            validate = self._run(["terraform", "validate", "-no-color"], workdir)
            return ValidationResult(validate.returncode == 0, _combined_output(validate))

    def _validate_kubernetes(self, config: str) -> ValidationResult:
        dry_run = self.settings.kubectl_dry_run.lower()
        if dry_run not in {"client", "server"}:
            return ValidationResult(False, "KUBECTL_DRY_RUN must be either 'client' or 'server'")

        if dry_run == "client":
            return _validate_kubernetes_yaml(config)

        if not shutil.which("kubectl"):
            return ValidationResult(False, "kubectl executable was not found on PATH")

        with tempfile.TemporaryDirectory(prefix="iac-k8s-") as tmp:
            manifest = Path(tmp) / "manifest.yaml"
            manifest.write_text(config, encoding="utf-8")
            result = self._run(
                [
                    "kubectl",
                    "apply",
                    "--dry-run=server",
                    "-n",
                    self.settings.kubectl_namespace,
                    "-f",
                    str(manifest),
                ],
                Path(tmp),
            )
            return ValidationResult(result.returncode == 0, _combined_output(result))

    def _run(self, command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=self.settings.validation_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(
                command,
                124,
                stdout=exc.stdout or "",
                stderr=f"Command timed out after {self.settings.validation_timeout_seconds}s",
            )


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part).strip()


def _validate_kubernetes_yaml(config: str) -> ValidationResult:
    try:
        raw_docs = list(yaml.safe_load_all(config))
    except yaml.YAMLError as exc:
        return ValidationResult(False, f"Invalid Kubernetes YAML: {exc}")

    docs = [doc for doc in raw_docs if doc is not None]
    if not docs:
        return ValidationResult(False, "Kubernetes manifest did not contain any resources")

    errors: list[str] = []
    for index, doc in enumerate(docs, start=1):
        if not isinstance(doc, dict):
            errors.append(f"Document {index}: resource must be a YAML mapping")
            continue

        kind = doc.get("kind")
        name = _get(doc, "metadata", "name")
        if not isinstance(doc.get("apiVersion"), str):
            errors.append(f"Document {index}: apiVersion is required")
        if not isinstance(kind, str):
            errors.append(f"Document {index}: kind is required")
        if not isinstance(name, str):
            errors.append(f"Document {index}: metadata.name is required")

        if kind == "Deployment":
            errors.extend(_validate_deployment(doc, index))
        elif kind == "StatefulSet":
            errors.extend(_validate_stateful_set(doc, index))
        elif kind == "Service":
            errors.extend(_validate_service(doc, index))
        elif kind == "PersistentVolumeClaim":
            errors.extend(_validate_pvc(doc, index))

    errors.extend(_validate_redis_cluster_requirements(docs))

    if errors:
        return ValidationResult(False, "\n".join(errors))
    return ValidationResult(True, "Kubernetes YAML validation passed")


def _validate_deployment(doc: dict, index: int) -> list[str]:
    errors: list[str] = []
    if "volumes" in _as_dict(doc.get("spec")):
        errors.append(
            f"Document {index}: Deployment volumes must be under spec.template.spec.volumes, not spec.volumes"
        )

    selector_labels = _get(doc, "spec", "selector", "matchLabels")
    template_labels = _get(doc, "spec", "template", "metadata", "labels")
    containers = _get(doc, "spec", "template", "spec", "containers")
    if not isinstance(selector_labels, dict) or not selector_labels:
        errors.append(f"Document {index}: Deployment spec.selector.matchLabels is required")
    if not isinstance(template_labels, dict) or not template_labels:
        errors.append(f"Document {index}: Deployment spec.template.metadata.labels is required")
    if isinstance(selector_labels, dict) and isinstance(template_labels, dict):
        for key, value in selector_labels.items():
            if template_labels.get(key) != value:
                errors.append(f"Document {index}: Deployment selector labels must match template labels")
                break
    if not isinstance(containers, list) or not containers:
        errors.append(f"Document {index}: Deployment spec.template.spec.containers must be a non-empty list")
    return errors


def _validate_stateful_set(doc: dict, index: int) -> list[str]:
    errors: list[str] = []
    selector_labels = _get(doc, "spec", "selector", "matchLabels")
    template_labels = _get(doc, "spec", "template", "metadata", "labels")
    containers = _get(doc, "spec", "template", "spec", "containers")
    if not isinstance(_get(doc, "spec", "serviceName"), str):
        errors.append(f"Document {index}: StatefulSet spec.serviceName is required for stable network identity")
    if not isinstance(selector_labels, dict) or not selector_labels:
        errors.append(f"Document {index}: StatefulSet spec.selector.matchLabels is required")
    if not isinstance(template_labels, dict) or not template_labels:
        errors.append(f"Document {index}: StatefulSet spec.template.metadata.labels is required")
    if isinstance(selector_labels, dict) and isinstance(template_labels, dict):
        for key, value in selector_labels.items():
            if template_labels.get(key) != value:
                errors.append(f"Document {index}: StatefulSet selector labels must match template labels")
                break
    if not isinstance(containers, list) or not containers:
        errors.append(f"Document {index}: StatefulSet spec.template.spec.containers must be a non-empty list")
    return errors


def _validate_service(doc: dict, index: int) -> list[str]:
    errors: list[str] = []
    selector = _get(doc, "spec", "selector")
    ports = _get(doc, "spec", "ports")
    if not isinstance(selector, dict) or not selector:
        errors.append(f"Document {index}: Service spec.selector is required")
    if not isinstance(ports, list) or not ports:
        errors.append(f"Document {index}: Service spec.ports must be a non-empty list")
    return errors


def _validate_pvc(doc: dict, index: int) -> list[str]:
    errors: list[str] = []
    access_modes = _get(doc, "spec", "accessModes")
    storage = _get(doc, "spec", "resources", "requests", "storage")
    if not isinstance(access_modes, list) or not access_modes:
        errors.append(f"Document {index}: PersistentVolumeClaim spec.accessModes is required")
    if not isinstance(storage, str):
        errors.append(f"Document {index}: PersistentVolumeClaim storage request is required")
    return errors


def _validate_redis_cluster_requirements(docs: list[object]) -> list[str]:
    errors: list[str] = []
    redis_stateful_sets = [
        (index, doc)
        for index, doc in enumerate(docs, start=1)
        if isinstance(doc, dict) and doc.get("kind") == "StatefulSet" and _is_redis_workload(doc)
    ]
    if not redis_stateful_sets:
        return errors

    services = {
        _get(doc, "metadata", "name"): doc
        for doc in docs
        if isinstance(doc, dict) and doc.get("kind") == "Service" and isinstance(_get(doc, "metadata", "name"), str)
    }
    config_text = "\n".join(
        str(_get(doc, "data", key))
        for doc in docs
        if isinstance(doc, dict) and doc.get("kind") == "ConfigMap" and isinstance(doc.get("data"), dict)
        for key in doc["data"]
    ).lower()

    for index, doc in redis_stateful_sets:
        service_name = _get(doc, "spec", "serviceName")
        containers = _get(doc, "spec", "template", "spec", "containers")
        redis_container = _find_redis_container(containers)
        volume_claim_templates = _get(doc, "spec", "volumeClaimTemplates")

        if not isinstance(volume_claim_templates, list) or not volume_claim_templates:
            errors.append(f"Document {index}: Redis StatefulSet must include spec.volumeClaimTemplates for persistent data")

        if not isinstance(service_name, str) or service_name not in services:
            errors.append(f"Document {index}: Redis StatefulSet must reference a matching headless Service in spec.serviceName")
        else:
            cluster_ip = _get(services[service_name], "spec", "clusterIP")
            if cluster_ip != "None":
                errors.append(f"Document {index}: Redis Service '{service_name}' must be headless with spec.clusterIP: None")

        if not isinstance(redis_container, dict):
            errors.append(f"Document {index}: Redis StatefulSet must include a Redis container")
            continue

        if not _has_cluster_mode(redis_container, config_text):
            errors.append(
                f"Document {index}: Redis container must enable cluster mode using --cluster-enabled yes or config"
            )
        if not isinstance(_get(redis_container, "resources", "requests"), dict):
            errors.append(f"Document {index}: Redis container must define resources.requests")
        if not isinstance(_get(redis_container, "resources", "limits"), dict):
            errors.append(f"Document {index}: Redis container must define resources.limits")
        if not isinstance(redis_container.get("livenessProbe"), dict):
            errors.append(f"Document {index}: Redis container must define livenessProbe")
        if not isinstance(redis_container.get("readinessProbe"), dict):
            errors.append(f"Document {index}: Redis container must define readinessProbe")

    return errors


def _is_redis_workload(doc: dict) -> bool:
    name = str(_get(doc, "metadata", "name") or "").lower()
    containers = _get(doc, "spec", "template", "spec", "containers")
    return "redis" in name or _find_redis_container(containers) is not None


def _find_redis_container(containers: object) -> object:
    if not isinstance(containers, list):
        return None
    for container in containers:
        if not isinstance(container, dict):
            continue
        name = str(container.get("name") or "").lower()
        image = str(container.get("image") or "").lower()
        if "redis" in name or "redis" in image:
            return container
    return None


def _has_cluster_mode(container: dict, config_text: str) -> bool:
    command_text = " ".join([*_as_list(container.get("command")), *_as_list(container.get("args"))]).lower()
    return "cluster-enabled yes" in command_text or "--cluster-enabled yes" in command_text or "cluster-enabled yes" in config_text


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []


def _get(data: object, *keys: str) -> object:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}
