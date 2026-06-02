import json

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import SQLALCHEMY_DATABASE_URL


connect_args = (
    {"check_same_thread": False}
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite")
    else {}
)
if (
    SQLALCHEMY_DATABASE_URL.startswith("postgresql")
    and (
        "pgbouncer=true" in SQLALCHEMY_DATABASE_URL
        or "pooler.supabase.com" in SQLALCHEMY_DATABASE_URL
    )
):
    connect_args["prepare_threshold"] = None

engine_kwargs = {
    "connect_args": connect_args,
    "pool_pre_ping": True,
}

if (
    "pgbouncer=true" in SQLALCHEMY_DATABASE_URL
    or "pooler.supabase.com" in SQLALCHEMY_DATABASE_URL
):
    engine_kwargs["poolclass"] = NullPool

engine = create_engine(SQLALCHEMY_DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def create_database_tables() -> None:
    try:
        Base.metadata.create_all(bind=engine)
        _ensure_facebook_credential_columns()
        _ensure_facebook_connection_flow()
        _ensure_product_blueprint_columns()
        _migrate_ai_page_settings_to_personas()
    except OperationalError as exc:
        message = str(exc.orig).lower() if getattr(exc, "orig", None) else str(exc).lower()
        if "failed to resolve host" in message and "supabase.co" in message:
            raise RuntimeError(
                "Could not resolve the Supabase direct database host. "
                "Open Supabase Project Settings -> Database -> Connection string "
                "and use the Transaction pooler URL in backend/.env as DATABASE_URL. "
                "The direct db.<project-ref>.supabase.co URL often fails on networks "
                "that cannot reach Supabase's direct database host."
            ) from exc
        raise


def _ensure_oauth_states_table() -> None:
    """Ensure oauth_states table exists for database-backed OAuth state storage."""
    inspector = inspect(engine)
    if not inspector.has_table("oauth_states"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE oauth_states (
                        id VARCHAR PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        state VARCHAR NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text("CREATE INDEX idx_oauth_states_expires_at ON oauth_states(expires_at)")
            )
            connection.execute(
                text("CREATE INDEX idx_oauth_states_user_id ON oauth_states(user_id)")
            )


def _ensure_facebook_credential_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("facebook_connections"):
        return

    existing_columns = {
        column["name"]
        for column in inspector.get_columns("facebook_connections")
    }
    statements = []
    if "app_id" not in existing_columns:
        statements.append("alter table facebook_connections add column app_id varchar")
    if "app_secret" not in existing_columns:
        statements.append("alter table facebook_connections add column app_secret text")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _add_missing_columns(table_name: str, columns: dict[str, str]) -> None:
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    statements = [
        f"alter table {table_name} add column {column_name} {definition}"
        for column_name, definition in columns.items()
        if column_name not in existing_columns
    ]
    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _ensure_facebook_connection_flow() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("facebook_connections"):
        return

    _add_missing_columns(
        "facebook_connections",
        {
            "connection_status": "varchar default 'connected' not null",
            "disconnected_at": "timestamptz",
            "reconnect_count": "integer default 0 not null",
            "last_token_refresh": "timestamptz",
        },
    )

    is_postgres = SQLALCHEMY_DATABASE_URL.startswith("postgresql")
    with engine.begin() as connection:
        if is_postgres:
            connection.execute(
                text("ALTER TABLE facebook_connections ALTER COLUMN page_access_token DROP NOT NULL")
            )
            connection.execute(
                text("ALTER TABLE facebook_connections DROP CONSTRAINT IF EXISTS facebook_connections_user_id_key")
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_facebook_connections_user_page "
                    "ON facebook_connections(user_id, page_id)"
                )
            )
            connection.execute(
                text("ALTER TABLE post_logs DROP CONSTRAINT IF EXISTS post_logs_facebook_connection_id_fkey")
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE post_logs
                    ADD CONSTRAINT post_logs_facebook_connection_id_fkey
                    FOREIGN KEY (facebook_connection_id)
                    REFERENCES facebook_connections(id)
                    ON DELETE SET NULL
                    """
                )
            )
            connection.execute(
                text("ALTER TABLE ai_personas DROP CONSTRAINT IF EXISTS ai_personas_page_connection_id_fkey")
            )
            connection.execute(
                text(
                    """
                    ALTER TABLE ai_personas
                    ADD CONSTRAINT ai_personas_page_connection_id_fkey
                    FOREIGN KEY (page_connection_id)
                    REFERENCES facebook_connections(id)
                    ON DELETE SET NULL
                    """
                )
            )
        elif SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
            # SQLite cannot drop NOT NULL or recreate FK constraints easily at runtime.
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_facebook_connections_user_page "
                    "ON facebook_connections(user_id, page_id)"
                )
            )


def _ensure_product_blueprint_columns() -> None:
    _add_missing_columns(
        "users",
        {
            "email_verified": "boolean default true not null",
            "timezone": "varchar default 'UTC' not null",
            "plan": "varchar default 'free' not null",
            "brand_logo_url": "text",
        },
    )
    _add_missing_columns(
        "facebook_connections",
        {
            "page_picture_url": "text",
            "connection_status": "varchar default 'connected' not null",
            "connected_at": "timestamp",
        },
    )
    _add_missing_columns(
        "ai_personas",
        {
            "learning_mode_enabled": "boolean default true not null",
            "minimum_engagement_threshold": "numeric(10,4) default 0 not null",
            "learned_patterns_summary": "text",
            "always_include_engagement_hook": "boolean default false not null",
            "prompt_config": "json",
            "custom_prompt": "text",
            "creativity_level": "integer default 7 not null",
            "include_image": "boolean default false not null",
            "image_frequency": "varchar default 'every_post' not null",
            "image_prompt_source": "varchar default 'persona_prompt' not null",
            "image_fallback_policy": "varchar default 'text_only' not null",
            "image_max_wait_seconds": "integer default 120 not null",
        },
    )
    _add_missing_columns(
        "post_logs",
        {
            "media_library_id": "uuid",
        },
    )
    _add_missing_columns(
        "tracked_pages",
        {
            "page_name": "varchar",
            "is_active": "boolean default true not null",
            "last_checked_at": "timestamp",
        },
    )


def _migrate_ai_page_settings_to_personas() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("ai_page_settings") or not inspector.has_table("ai_personas"):
        return

    with engine.begin() as connection:
        existing_count = connection.execute(text("select count(*) from ai_personas")).scalar() or 0
        if existing_count:
            return
        rows = connection.execute(text("select * from ai_page_settings")).mappings().all()
        for row in rows:
            connection.execute(
                text(
                    """
                    insert into ai_personas (
                        page_connection_id, user_id, persona_name, niche, tone_tags,
                        custom_instructions, language, hashtags_enabled, hashtag_count,
                        assigned_days, posting_time_slots, priority_level, is_active,
                        performance_score, total_posts_published, total_likes_received,
                        total_comments_received, total_shares_received, total_reach_received,
                        last_auto_post_at, consecutive_failures, created_at, updated_at
                    ) values (
                        :page_connection_id, :user_id, :persona_name, :niche, :tone_tags,
                        :custom_instructions, :language, :hashtags_enabled, :hashtag_count,
                        :assigned_days, :posting_time_slots, :priority_level, :is_active,
                        :performance_score, 0, 0, 0, 0, 0,
                        :last_auto_post_at, :consecutive_failures, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "page_connection_id": row["page_connection_id"],
                    "user_id": row["user_id"],
                    "persona_name": "Default Persona",
                    "niche": row["niche"],
                    "tone_tags": row["tone_tags"],
                    "custom_instructions": row["custom_instructions"],
                    "language": row["language"],
                    "hashtags_enabled": row["hashtags_enabled"],
                    "hashtag_count": row["hashtag_count"],
                    "assigned_days": row.get("active_days") or "",
                    "posting_time_slots": json.dumps([row.get("active_hours_start") or "09:00"]),
                    "priority_level": "Normal",
                    "is_active": row.get("auto_posting_enabled", True),
                    "performance_score": 0.5,
                    "last_auto_post_at": row.get("last_auto_post_at"),
                    "consecutive_failures": row.get("consecutive_failures", 0),
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                },
            )
    _add_missing_columns(
        "post_logs",
        {
            "ai_persona_id": "integer",
            "media_library_id": "uuid",
            "media_urls": "json default '[]' not null",
            "link_url": "text",
            "link_preview_data": "json",
            "scheduled_at": "timestamp",
            "facebook_post_id": "varchar",
            "retry_count": "integer default 0 not null",
            "ai_generated": "boolean default false not null",
            "auto_generated": "boolean default false not null",
            "created_at": "timestamp",
            "updated_at": "timestamp",
            "topic": "text",
        },
    )
    _add_missing_columns(
        "ai_personas",
        {
            "persona_name": "varchar default 'Default Persona' not null",
            "assigned_days": "varchar default '' not null",
            "posting_time_slots": "json default '[]' not null",
            "priority_level": "varchar default 'Normal' not null",
            "is_active": "boolean default true not null",
            "learning_mode_enabled": "boolean default true not null",
            "minimum_engagement_threshold": "numeric(10,4) default 0 not null",
            "learned_patterns_summary": "text",
            "prompt_config": "json",
            "custom_prompt": "text",
            "creativity_level": "integer default 7 not null",
            "performance_score": "numeric(8,4) default 0.5 not null",
            "total_posts_published": "integer default 0 not null",
            "total_likes_received": "integer default 0 not null",
            "total_comments_received": "integer default 0 not null",
            "total_shares_received": "integer default 0 not null",
            "total_reach_received": "integer default 0 not null",
            "last_performance_update_at": "timestamp",
            "last_auto_post_at": "timestamp",
            "consecutive_failures": "integer default 0 not null",
            "include_image": "boolean default false not null",
            "image_frequency": "varchar default 'every_post' not null",
            "image_prompt_source": "varchar default 'persona_prompt' not null",
            "image_fallback_policy": "varchar default 'text_only' not null",
            "image_max_wait_seconds": "integer default 120 not null",
        },
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
