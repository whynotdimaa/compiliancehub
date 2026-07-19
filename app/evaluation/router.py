import json
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.auth.deps import CurrentUser, TenantSession, require_role
from app.evaluation.models import EvaluationRecord
from app.evaluation.schemas import (
    EvalRecordOut,
    EvalRunQueued,
    EvalRunRequest,
    EvalRunSummary,
)
from app.evaluation.tasks import run_evaluation
from app.tenants.models import User, UserRole

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

GOLDEN_DATASET = Path(__file__).parent / "golden_dataset.json"

Evaluator = Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.AUDITOR))]


@router.post("/runs", response_model=EvalRunQueued, status_code=status.HTTP_202_ACCEPTED)
async def start_run(data: EvalRunRequest, user: Evaluator, session: TenantSession) -> EvalRunQueued:
    """Queue an evaluation run; omit items to use the bundled golden dataset."""
    if data.items is not None:
        items = [item.model_dump() for item in data.items]
    else:
        items = json.loads(GOLDEN_DATASET.read_text(encoding="utf-8"))
    if not items:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Dataset is empty")

    run_id = uuid.uuid4()
    run_evaluation.delay(str(run_id), str(user.tenant_id), data.dataset_name, items)
    return EvalRunQueued(run_id=run_id, dataset_name=data.dataset_name, items=len(items))


@router.get("/runs", response_model=list[EvalRunSummary])
async def list_runs(user: CurrentUser, session: TenantSession) -> list[EvalRunSummary]:
    """Per-run averages — SQL AVG ignores NULL metrics by design."""
    rows = await session.execute(
        select(
            EvaluationRecord.run_id,
            EvaluationRecord.dataset_name,
            func.min(EvaluationRecord.created_at).label("started_at"),
            func.count().label("items"),
            func.avg(EvaluationRecord.faithfulness).label("avg_faithfulness"),
            func.avg(EvaluationRecord.answer_relevancy).label("avg_answer_relevancy"),
            func.avg(EvaluationRecord.context_precision).label("avg_context_precision"),
            func.avg(EvaluationRecord.context_recall).label("avg_context_recall"),
        )
        .group_by(EvaluationRecord.run_id, EvaluationRecord.dataset_name)
        .order_by(func.min(EvaluationRecord.created_at).desc())
    )
    return [EvalRunSummary(**row._mapping) for row in rows]


@router.get("/runs/{run_id}", response_model=list[EvalRecordOut])
async def run_details(
    run_id: uuid.UUID, user: CurrentUser, session: TenantSession
) -> list[EvalRecordOut]:
    records = list(
        await session.scalars(
            select(EvaluationRecord)
            .where(EvaluationRecord.run_id == run_id)
            .order_by(EvaluationRecord.created_at)
        )
    )
    if not records:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {run_id} not found")
    return [EvalRecordOut.model_validate(r) for r in records]
