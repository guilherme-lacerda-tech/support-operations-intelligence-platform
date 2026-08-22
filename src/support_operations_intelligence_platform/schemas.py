from datetime import datetime

from pydantic import BaseModel, Field


class AssetCreate(BaseModel):
    external_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=3, max_length=120)
    group: str = Field(min_length=2, max_length=80)


class AssetRead(AssetCreate):
    id: int
    status: str

    model_config = {"from_attributes": True}


class RuleCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    category: str = Field(min_length=2, max_length=80)
    minimum_severity: int = Field(ge=1, le=100)
    cooldown_minutes: int = Field(ge=0, le=1440)
    action_type: str = Field(default="create_ticket", min_length=3, max_length=80)
    enabled: bool = True


class RuleRead(RuleCreate):
    id: int

    model_config = {"from_attributes": True}


class EventCreate(BaseModel):
    asset_external_id: str = Field(min_length=3, max_length=80)
    source: str = Field(min_length=3, max_length=120)
    category: str = Field(min_length=2, max_length=80)
    severity: int = Field(ge=1, le=100)
    message: str = Field(min_length=5)
    executor_mode: str = Field(default="success", min_length=3, max_length=40)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)
    correlation_id: str | None = Field(default=None, min_length=3, max_length=80)


class EventRead(BaseModel):
    id: int
    source: str
    category: str
    severity: int
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class IncidentRead(BaseModel):
    id: int
    asset_id: int
    rule_id: int
    event_id: int
    state: str
    summary: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ActionRead(BaseModel):
    id: int
    incident_id: int
    action_type: str
    state: str
    attempts: int
    detail: str

    model_config = {"from_attributes": True}


class ProcessResult(BaseModel):
    event: EventRead
    incident: IncidentRead | None
    action: ActionRead | None
    skipped_reason: str | None = None
    idempotency_key: str | None = None
    idempotent_replay: bool = False


class JobResult(BaseModel):
    job_name: str
    status: str
    actions_created: int


class CheckCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    asset_external_id: str = Field(min_length=3, max_length=80)
    detail: str = Field(default="", max_length=500)


class CheckTransition(BaseModel):
    target_state: str = Field(min_length=3, max_length=40)
    detail: str = Field(default="", max_length=500)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86_400)


class CheckRead(BaseModel):
    id: int
    name: str
    asset_external_id: str
    state: str
    detail: str
    confirmation_due_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
