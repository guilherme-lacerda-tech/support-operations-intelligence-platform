from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


ExecutorMode = Literal["success", "transient_failure", "permanent_failure"]


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
    asset_id: str | None = Field(default=None, min_length=3, max_length=80)
    asset_external_id: str | None = Field(default=None, min_length=3, max_length=80)
    source: str = Field(min_length=3, max_length=120)
    category: str = Field(min_length=2, max_length=80)
    severity: int = Field(ge=1, le=100)
    message: str = Field(min_length=5)
    occurred_at: datetime | None = None
    executor_mode: ExecutorMode = "success"

    @model_validator(mode="after")
    def normalize_asset_fields(self) -> "EventCreate":
        if not self.asset_id and not self.asset_external_id:
            raise ValueError("asset_id or asset_external_id is required")
        if self.asset_id and not self.asset_external_id:
            self.asset_external_id = self.asset_id
        if self.asset_external_id and not self.asset_id:
            self.asset_id = self.asset_external_id
        return self


class EventRead(BaseModel):
    id: int
    source: str
    category: str
    severity: int
    message: str
    occurred_at: datetime
    executor_mode: str
    created_at: datetime

    model_config = {"from_attributes": True}


class IncidentRead(BaseModel):
    id: int
    asset_id: int
    rule_id: int | None
    event_id: int
    category: str
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


class AuditRead(BaseModel):
    id: int
    event_type: str
    entity_type: str
    entity_id: int
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MaintenanceResult(BaseModel):
    processed: int
    succeeded: int
    failed: int


class MetricsRead(BaseModel):
    events: int
    incidents: int
    actions: int
    audit_logs: int
    suppressions: int
    queued_actions: int
    succeeded_actions: int
    failed_actions: int
    retries: int


class ResetResult(BaseModel):
    deleted: dict[str, int]

