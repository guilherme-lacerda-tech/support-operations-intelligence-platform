from sqlalchemy import select
from sqlalchemy.orm import Session

from support_operations_intelligence_platform.models import AutomationRule, OperationalEvent


class RuleEngine:
    def __init__(self, session: Session):
        self.session = session

    def match(self, event: OperationalEvent) -> AutomationRule | None:
        statement = (
            select(AutomationRule)
            .where(AutomationRule.enabled.is_(True))
            .where(AutomationRule.category == event.category)
            .where(AutomationRule.minimum_severity <= event.severity)
            .order_by(AutomationRule.minimum_severity.desc())
        )
        return self.session.scalars(statement).first()

