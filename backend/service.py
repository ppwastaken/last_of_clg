from sqlalchemy.orm import Session

from backend.config import Settings
from backend.llm import LLMClient
from backend.models import ApprovalStatus, ArtifactType, IaCGenerationAttempt, IaCRequest
from backend.validators import IaCValidator


def generate_validate_and_queue(
    db: Session,
    settings: Settings,
    prompt: str,
    artifact_type: ArtifactType,
) -> IaCRequest:
    llm = LLMClient(settings)
    validator = IaCValidator(settings)
    validation_error: str | None = None
    last_config = ""
    last_model = ""
    last_output = ""
    audit_attempts: list[dict[str, object]] = []

    for attempt in range(1, settings.max_repair_attempts + 1):
        result = llm.generate(prompt, artifact_type, validation_error)
        last_config = result.config
        last_model = result.model
        validation = validator.validate(artifact_type, result.config)
        last_output = validation.output
        audit_attempts.append(
            {
                "attempt_number": attempt,
                "generated_config": result.config,
                "validation_output": validation.output,
                "validation_ok": validation.ok,
                "llm_model": result.model,
            }
        )
        if validation.ok:
            return _save_request(
                db,
                prompt,
                artifact_type,
                result.config,
                ApprovalStatus.pending,
                validation.output or "Validation passed",
                result.model,
                attempt,
                audit_attempts,
            )
        validation_error = validation.output or "Validation failed without output"

    return _save_request(
        db,
        prompt,
        artifact_type,
        last_config,
        ApprovalStatus.validation_failed,
        last_output or "Validation failed",
        last_model or settings.llm_provider,
        settings.max_repair_attempts,
        audit_attempts,
    )


def _save_request(
    db: Session,
    prompt: str,
    artifact_type: ArtifactType,
    config: str,
    status: ApprovalStatus,
    validation_output: str,
    model: str,
    attempts: int,
    audit_attempts: list[dict[str, object]],
) -> IaCRequest:
    item = IaCRequest(
        prompt=prompt,
        artifact_type=artifact_type,
        generated_config=config,
        status=status,
        validation_output=validation_output,
        llm_model=model,
        attempts=attempts,
    )
    db.add(item)
    db.flush()
    for attempt in audit_attempts:
        db.add(IaCGenerationAttempt(request_id=item.id, **attempt))
    db.commit()
    db.refresh(item)
    return item
