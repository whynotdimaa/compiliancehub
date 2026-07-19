import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EvalItemIn(BaseModel):
    question: str = Field(min_length=5, max_length=2000)
    ground_truth: str | None = None


class EvalRunRequest(BaseModel):
    dataset_name: str = Field(default="golden", max_length=255)
    items: list[EvalItemIn] | None = None  # None -> bundled golden dataset


class EvalRunQueued(BaseModel):
    run_id: uuid.UUID
    dataset_name: str
    items: int
    status: str = "queued"


class EvalRunSummary(BaseModel):
    run_id: uuid.UUID
    dataset_name: str
    started_at: datetime
    items: int
    avg_faithfulness: float | None
    avg_answer_relevancy: float | None
    avg_context_precision: float | None
    avg_context_recall: float | None


class EvalRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    ground_truth: str | None
    answer: str
    contexts: list[str] | None
    faithfulness: float | None
    answer_relevancy: float | None
    context_precision: float | None
    context_recall: float | None
    low_confidence: bool
    created_at: datetime
