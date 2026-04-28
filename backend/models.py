from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ArtifactType(str, Enum):
    terraform = "terraform"
    kubernetes = "kubernetes"


class ApprovalStatus(str, Enum):
    validation_failed = "validation_failed"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    applied = "applied"
    apply_failed = "apply_failed"


class IaCRequest(Base):
    __tablename__ = "iac_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_type: Mapped[ArtifactType] = mapped_column(SAEnum(ArtifactType), nullable=False)
    generated_config: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus), default=ApprovalStatus.pending, nullable=False
    )
    validation_output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    llm_model: Mapped[str] = mapped_column(String(128), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    apply_output: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class IaCGenerationAttempt(Base):
    __tablename__ = "iac_generation_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    request_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_config: Mapped[str] = mapped_column(Text, nullable=False)
    validation_output: Mapped[str] = mapped_column(Text, default="", nullable=False)
    validation_ok: Mapped[bool] = mapped_column(default=False, nullable=False)
    llm_model: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
