from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.apply import apply_config
from backend.config import Settings, get_settings
from backend.database import get_db, init_db
from backend.models import ApprovalStatus, IaCGenerationAttempt, IaCRequest
from backend.schemas import ApprovalAction, EditRequest, GenerateRequest, GenerateResponse, GenerationAttemptOut, IaCRequestOut
from backend.service import generate_validate_and_queue, revise_validate_request

app = FastAPI(title="IaC Copilot Approval Service")


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.post("/generate", response_model=GenerateResponse)
def generate(
    payload: GenerateRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IaCRequest:
    return generate_validate_and_queue(db, settings, payload.prompt, payload.artifact_type)


@app.get("/requests", response_model=list[IaCRequestOut])
def list_requests(
    status: ApprovalStatus | None = None,
    db: Session = Depends(get_db),
) -> list[IaCRequest]:
    query = db.query(IaCRequest)
    if status:
        query = query.filter(IaCRequest.status == status)
    return query.order_by(desc(IaCRequest.created_at)).all()


@app.get("/requests/{request_id}", response_model=IaCRequestOut)
def get_request(request_id: int, db: Session = Depends(get_db)) -> IaCRequest:
    item = db.get(IaCRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Request not found")
    return item


@app.get("/requests/{request_id}/attempts", response_model=list[GenerationAttemptOut])
def list_generation_attempts(request_id: int, db: Session = Depends(get_db)) -> list[IaCGenerationAttempt]:
    if not db.get(IaCRequest, request_id):
        raise HTTPException(status_code=404, detail="Request not found")
    return (
        db.query(IaCGenerationAttempt)
        .filter(IaCGenerationAttempt.request_id == request_id)
        .order_by(IaCGenerationAttempt.attempt_number)
        .all()
    )


@app.post("/requests/{request_id}/approve", response_model=IaCRequestOut)
def approve_request(
    request_id: int,
    payload: ApprovalAction,
    db: Session = Depends(get_db),
) -> IaCRequest:
    item = db.get(IaCRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Request not found")
    if item.status != ApprovalStatus.pending:
        raise HTTPException(status_code=409, detail=f"Only pending requests can be approved; current={item.status}")
    item.status = ApprovalStatus.approved
    item.reviewer_note = payload.note
    db.commit()
    db.refresh(item)
    return item


@app.post("/requests/{request_id}/reject", response_model=IaCRequestOut)
def reject_request(
    request_id: int,
    payload: ApprovalAction,
    db: Session = Depends(get_db),
) -> IaCRequest:
    item = db.get(IaCRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Request not found")
    if item.status not in {ApprovalStatus.pending, ApprovalStatus.validation_failed}:
        raise HTTPException(status_code=409, detail=f"Cannot reject request with status={item.status}")
    item.status = ApprovalStatus.rejected
    item.reviewer_note = payload.note
    db.commit()
    db.refresh(item)
    return item


@app.post("/requests/{request_id}/edit", response_model=IaCRequestOut)
def edit_request(
    request_id: int,
    payload: EditRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IaCRequest:
    item = db.get(IaCRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Request not found")
    if item.status == ApprovalStatus.applied:
        raise HTTPException(status_code=409, detail="Applied requests cannot be edited; create a new request")
    return revise_validate_request(db, settings, item, payload.prompt)


@app.post("/requests/{request_id}/apply", response_model=IaCRequestOut)
def apply_request(
    request_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> IaCRequest:
    item = db.get(IaCRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="Request not found")
    if item.status != ApprovalStatus.approved:
        raise HTTPException(status_code=409, detail="Request must be approved before apply")

    ok, output = apply_config(settings, item.artifact_type, item.generated_config)
    item.status = ApprovalStatus.applied if ok else ApprovalStatus.apply_failed
    item.apply_output = output
    db.commit()
    db.refresh(item)
    return item
