from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class IncidentState(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class ActionState(StrEnum):
    QUEUED = "queued"
    RETRY = "retry"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class CheckState(StrEnum):
    PENDING = "pending"
    STARTED = "started"
    WAITING_CONFIRMATION = "waiting_confirmation"
    CONFIRMED = "confirmed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    group: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="unknown")

    events: Mapped[list["OperationalEvent"]] = relationship(back_populates="asset")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="asset")


class AutomationRule(Base):
    __tablename__ = "automation_rules"
    __table_args__ = (UniqueConstraint("name", "category", name="uq_rule_name_category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80), index=True)
    minimum_severity: Mapped[int] = mapped_column(Integer, default=70)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=15)
    action_type: Mapped[str] = mapped_column(String(80), default="create_ticket")
    enabled: Mapped[bool] = mapped_column(default=True)


class OperationalEvent(Base):
    __tablename__ = "operational_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    source: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    asset: Mapped[Asset] = relationship(back_populates="events")


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    rule_id: Mapped[int] = mapped_column(ForeignKey("automation_rules.id"))
    event_id: Mapped[int] = mapped_column(ForeignKey("operational_events.id"))
    state: Mapped[str] = mapped_column(String(40), default=IncidentState.OPEN.value)
    summary: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    asset: Mapped[Asset] = relationship(back_populates="incidents")
    rule: Mapped[AutomationRule] = relationship()
    event: Mapped[OperationalEvent] = relationship()
    actions: Mapped[list["Action"]] = relationship(back_populates="incident")


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"))
    action_type: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(40), default=ActionState.QUEUED.value)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(Text, default="")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    incident: Mapped[Incident] = relationship(back_populates="actions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("operational_events.id"), nullable=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    action_id: Mapped[int | None] = mapped_column(ForeignKey("actions.id"), nullable=True)
    skipped_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    event: Mapped[OperationalEvent | None] = relationship()
    incident: Mapped[Incident | None] = relationship()
    action: Mapped[Action | None] = relationship()


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CheckRun(Base):
    __tablename__ = "check_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    asset_external_id: Mapped[str] = mapped_column(String(80), index=True)
    state: Mapped[str] = mapped_column(String(40), default=CheckState.PENDING.value)
    detail: Mapped[str] = mapped_column(Text, default="")
    confirmation_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
