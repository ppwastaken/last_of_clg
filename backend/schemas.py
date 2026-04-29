from datetime import datetime

from pydantic import BaseModel, Field

from backend.models import ApprovalStatus, ArtifactType


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=3)
    artifact_type: ArtifactType


class EditRequest(BaseModel):
    prompt: str = Field(min_length=3)


class GenerateResponse(BaseModel):
    id: int
    status: ApprovalStatus
    artifact_type: ArtifactType
    generated_config: str
    validation_output: str
    attempts: int

    model_config = {"from_attributes": True}


class ApprovalAction(BaseModel):
    note: str | None = None


class IaCRequestOut(BaseModel):
    id: int
    prompt: str
    artifact_type: ArtifactType
    generated_config: str
    status: ApprovalStatus
    validation_output: str
    llm_model: str
    attempts: int
    reviewer_note: str | None
    apply_output: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GenerationAttemptOut(BaseModel):
    id: int
    request_id: int
    attempt_number: int
    generated_config: str
    validation_output: str
    validation_ok: bool
    llm_model: str
    created_at: datetime

    model_config = {"from_attributes": True}
