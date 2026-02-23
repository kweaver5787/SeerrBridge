"""
Schema sync: add missing columns to existing tables so the DB matches the current models.
Only adds columns that the model expects but the table doesn't have; never drops or alters.
Safe for end users after app updates.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from loguru import logger


def _get_existing_column_names(engine: Engine, table_name: str) -> set:
    """Return set of column names that exist in the database for the given table."""
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return set()
    columns = inspector.get_columns(table_name)
    return {c["name"] for c in columns}


def _default_expr_for_column(column) -> str:
    """Return MySQL DEFAULT clause for a column, or empty string if none."""
    if column.server_default is not None:
        try:
            return " DEFAULT " + str(column.server_default.arg)
        except Exception:
            pass
    if column.default is not None:
        arg = getattr(column.default, "arg", None)
        if arg is not None and not callable(arg):
            if isinstance(arg, bool):
                return " DEFAULT 1" if arg else " DEFAULT 0"
            if isinstance(arg, (int, float)):
                return f" DEFAULT {arg}"
            if isinstance(arg, str):
                escaped = arg.replace("'", "''")
                return f" DEFAULT '{escaped}'"
    return ""


def _add_column_ddl(engine: Engine, table_name: str, column) -> str:
    """Build ALTER TABLE ... ADD COLUMN for one column (MySQL)."""
    # Compile type for MySQL
    type_str = column.type.compile(engine.dialect)
    null_str = " NULL" if column.nullable else " NOT NULL"
    default_str = _default_expr_for_column(column)
    # Use backticks for identifiers (MySQL)
    table = table_name
    col = column.name
    return f"ALTER TABLE `{table}` ADD COLUMN `{col}` {type_str}{null_str}{default_str}"


def sync_table_columns(engine: Engine, table_name: str, table_metadata) -> int:
    """
    Add any columns that exist in the SQLAlchemy Table but not in the database.
    Returns the number of columns added.
    """
    existing = _get_existing_column_names(engine, table_name)
    added = 0
    # table_metadata is the Table object (e.g. UnifiedMedia.__table__)
    for column in table_metadata.c:
        if column.name in existing:
            continue
        try:
            ddl = _add_column_ddl(engine, table_name, column)
            with engine.connect() as conn:
                conn.execute(text(ddl))
                conn.commit()
            logger.info(f"Schema sync: added column {table_name}.{column.name}")
            added += 1
        except Exception as e:
            logger.warning(f"Schema sync: could not add column {table_name}.{column.name}: {e}")
    return added


def sync_schema(engine: Engine, extra_metadata=None) -> int:
    """
    Sync all known model tables: add missing columns only.
    Call this after create_tables() so existing DBs get new columns on app update.
    Never drops or alters existing columns. Safe for end users after updates.
    extra_metadata: optional list of SQLAlchemy MetaData objects (e.g. [Base.metadata]) to sync.
    Returns total number of columns added across all tables.
    """
    from seerr.unified_models import Base as UnifiedMediaBase

    total = 0
    metadatas = [UnifiedMediaBase.metadata]
    if extra_metadata is not None:
        metadatas.extend(extra_metadata)
    for metadata in metadatas:
        for table_name, table in metadata.tables.items():
            added = sync_table_columns(engine, table_name, table)
            total += added
    if total:
        logger.info(f"Schema sync: added {total} missing column(s) to match current models")
    return total
