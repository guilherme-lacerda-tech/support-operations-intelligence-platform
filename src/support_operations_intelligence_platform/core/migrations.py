from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

LATEST_SCHEMA_VERSION = 1


def run_migrations(engine: Engine) -> None:
    """Apply small portfolio demo migrations without requiring an external tool."""
    BaseSchemaVersion.ensure_table(engine)
    version = BaseSchemaVersion.current(engine)
    if version < 1:
        _upgrade_to_1(engine)
        BaseSchemaVersion.set_current(engine, 1)


class BaseSchemaVersion:
    @staticmethod
    def ensure_table(engine: Engine) -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS schema_versions (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        version INTEGER NOT NULL
                    )
                    """
                )
            )
            current = connection.execute(text("SELECT version FROM schema_versions WHERE id = 1")).scalar()
            if current is None:
                connection.execute(text("INSERT INTO schema_versions (id, version) VALUES (1, 0)"))

    @staticmethod
    def current(engine: Engine) -> int:
        with engine.begin() as connection:
            value = connection.execute(text("SELECT version FROM schema_versions WHERE id = 1")).scalar_one()
        return int(value)

    @staticmethod
    def set_current(engine: Engine, version: int) -> None:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE schema_versions SET version = :version WHERE id = 1"),
                {"version": version},
            )


def _upgrade_to_1(engine: Engine) -> None:
    _add_column_if_missing(engine, "operational_events", "correlation_id", "VARCHAR(80) DEFAULT ''")
    _add_column_if_missing(engine, "actions", "next_attempt_at", "DATETIME")
    _add_column_if_missing(engine, "actions", "lease_id", "VARCHAR(80)")
    _add_column_if_missing(engine, "actions", "leased_at", "DATETIME")


def _add_column_if_missing(engine: Engine, table_name: str, column_name: str, ddl: str) -> None:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in existing:
        return
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
