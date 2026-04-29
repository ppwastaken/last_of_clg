import json
from dataclasses import dataclass

from groq import Groq
import requests

from backend.config import Settings
from backend.models import ArtifactType


SYSTEM_PROMPT = """You generate infrastructure-as-code only.
Return exactly one JSON object with keys:
- artifact_type: "terraform" or "kubernetes"
- config: a single string containing valid Terraform HCL or Kubernetes YAML

Rules:
- Produce only the requested artifact type.
- Do not include Markdown fences, prose, comments about safety, or explanations.
- Prefer minimal, valid, production-readable configuration.
- Kubernetes output must be one or more YAML documents separated by ---.
- Kubernetes workload pod fields such as containers, volumes, and volumeMounts must be under the pod template spec.
- For Kubernetes Redis cluster requests, prefer a StatefulSet and include:
  - a headless Service with clusterIP: None
  - Service spec.ports with Redis port 6379 and a selector matching the StatefulSet pod labels
  - StatefulSet spec.serviceName exactly matching the headless Service metadata.name
  - StatefulSet spec.selector.matchLabels matching spec.template.metadata.labels
  - Redis cluster mode enabled by command, args, or ConfigMap configuration
  - persistent volumeClaimTemplates for Redis data
  - CPU/memory resource requests and limits
  - livenessProbe and readinessProbe on the Redis container
- Terraform output must be a complete main.tf style HCL document.
- Never include real secrets, credentials, tokens, or private keys.
"""


@dataclass
class LLMResult:
    config: str
    model: str


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, prompt: str, artifact_type: ArtifactType, validation_error: str | None = None) -> LLMResult:
        user_prompt = self._build_user_prompt(prompt, artifact_type, validation_error)
        if self.settings.llm_provider.lower() == "ollama":
            return self._generate_ollama(user_prompt)
        return self._generate_groq(user_prompt)

    def revise(
        self,
        existing_config: str,
        edit_prompt: str,
        artifact_type: ArtifactType,
        validation_error: str | None = None,
    ) -> LLMResult:
        user_prompt = self._build_revision_prompt(existing_config, edit_prompt, artifact_type, validation_error)
        if self.settings.llm_provider.lower() == "ollama":
            return self._generate_ollama(user_prompt)
        return self._generate_groq(user_prompt)

    def _build_user_prompt(
        self, prompt: str, artifact_type: ArtifactType, validation_error: str | None
    ) -> str:
        retry_context = ""
        if validation_error:
            retry_context = (
                "\nThe previous output failed validation. Fix the config and return the same JSON shape.\n"
                f"Validation error:\n{validation_error}"
            )
        return f"Requested artifact type: {artifact_type.value}\nUser request:\n{prompt}{retry_context}"

    def _build_revision_prompt(
        self,
        existing_config: str,
        edit_prompt: str,
        artifact_type: ArtifactType,
        validation_error: str | None,
    ) -> str:
        retry_context = ""
        if validation_error:
            retry_context = (
                "\nThe previous revised output failed validation. Fix the config and return the same JSON shape.\n"
                f"Validation error:\n{validation_error}"
            )
        return (
            f"Requested artifact type: {artifact_type.value}\n"
            "Revise the existing infrastructure-as-code according to the developer edit request.\n"
            "Preserve unrelated valid configuration unless the edit request requires changing it.\n"
            f"Developer edit request:\n{edit_prompt}\n\n"
            f"Existing config:\n{existing_config}"
            f"{retry_context}"
        )

    def _generate_groq(self, user_prompt: str) -> LLMResult:
        if not self.settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is required when LLM_PROVIDER=groq")

        client = Groq(api_key=self.settings.groq_api_key)
        response = client.chat.completions.create(
            model=self.settings.groq_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content or "{}"
        return LLMResult(config=_extract_config(content), model=self.settings.groq_model)

    def _generate_ollama(self, user_prompt: str) -> LLMResult:
        response = requests.post(
            f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
            json={
                "model": self.settings.ollama_model,
                "format": "json",
                "stream": False,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "options": {"temperature": 0.1},
            },
            timeout=120,
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        return LLMResult(config=_extract_config(content), model=self.settings.ollama_model)


def _extract_config(raw_json: str) -> str:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM returned invalid JSON: {exc}") from exc

    config = payload.get("config")
    if not isinstance(config, str) or not config.strip():
        raise RuntimeError("LLM JSON response did not include a non-empty config string")
    return config.strip()
