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


class JobResult(BaseModel):
    job_name: str
    status: str
    actions_created: int

