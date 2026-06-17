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
    "pool_recycle": 1800,
    "pool_size": 3,
    "max_overflow": 5,
}

engine = create_engine(SQLALCHEMY_DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def create_database_tables() -> None:
    try:
        Base.metadata.create_all(bind=engine)
        _ensure_facebook_credential_columns()
        _ensure_facebook_connection_flow()
        _ensure_post_logs_publish_tracking()
        _ensure_product_blueprint_columns()
        _ensure_user_settings_table()
        _migrate_ai_page_settings_to_personas()
        _ensure_background_asset_schema()
    except OperationalError as exc:
        message = str(exc.orig).lower() if getattr(exc, "orig", None) else str(exc).lower()
        
        # Check for statement timeout - these are non-critical schema updates, allow startup
        if "statement timeout" in message or "canceling statement" in message:
            print(f"[MIGRATION WARNING] Database statement timeout during startup (non-critical): {message}")
            print("[MIGRATION WARNING] App will start, but some schema migrations may be pending.")
            return
        
        if "failed to resolve host" in message and "supabase.co" in message:
            raise RuntimeError(
                "Could not resolve the Supabase direct database host. "
                "Open Supabase Project Settings -> Database -> Connection string "
                "and use the Transaction pooler URL in backend/.env as DATABASE_URL. "
                "The direct db.<project-ref>.supabase.co URL often fails on networks "
                "that cannot reach Supabase's direct database host."
            ) from exc
        raise


def _ensure_post_logs_publish_tracking() -> None:
    _add_missing_columns(
        "post_logs",
        {
            "facebook_post_url": "text",
            "published_at": "timestamptz",
            "publish_error": "text",
        },
    )


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
    try:
        with engine.begin() as connection:
            if is_postgres:
                # These constraint operations may timeout on large tables in production.
                # We execute them with error handling to allow app startup even if they timeout.
                try:
                    connection.execute(
                        text("ALTER TABLE facebook_connections ALTER COLUMN page_access_token DROP NOT NULL")
                    )
                except Exception as e:
                    print(f"[MIGRATION WARNING] Could not alter facebook_connections column: {e}")
                
                try:
                    connection.execute(
                        text("ALTER TABLE facebook_connections DROP CONSTRAINT IF EXISTS facebook_connections_user_id_key")
                    )
                except Exception as e:
                    print(f"[MIGRATION WARNING] Could not drop facebook_connections constraint: {e}")
                
                try:
                    connection.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS idx_facebook_connections_user_page "
                            "ON facebook_connections(user_id, page_id)"
                        )
                    )
                except Exception as e:
                    print(f"[MIGRATION WARNING] Could not create index on facebook_connections: {e}")
                
                try:
                    connection.execute(
                        text("ALTER TABLE post_logs DROP CONSTRAINT IF EXISTS post_logs_facebook_connection_id_fkey")
                    )
                except Exception as e:
                    print(f"[MIGRATION WARNING] Could not drop post_logs constraint: {e}")
                
                try:
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
                except Exception as e:
                    print(f"[MIGRATION WARNING] Could not add post_logs constraint: {e}")
                
                try:
                    connection.execute(
                        text("ALTER TABLE ai_personas DROP CONSTRAINT IF EXISTS ai_personas_page_connection_id_fkey")
                    )
                except Exception as e:
                    print(f"[MIGRATION WARNING] Could not drop ai_personas constraint: {e}")
                
                try:
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
                except Exception as e:
                    print(f"[MIGRATION WARNING] Could not add ai_personas constraint: {e}")
            elif SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
                # SQLite cannot drop NOT NULL or recreate FK constraints easily at runtime.
                connection.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_facebook_connections_user_page "
                        "ON facebook_connections(user_id, page_id)"
                    )
                )
    except Exception as e:
        # Log migration errors but don't fail startup - these are non-critical schema updates
        print(f"[MIGRATION WARNING] Skipping facebook_connection_flow migrations: {e}")


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
            "template_image_generation_enabled": "boolean default false not null",
            "template_logo_url": "text",
        },
    )
    _add_missing_columns(
        "post_logs",
        {
            "media_library_id": "uuid",
            "image_url": "text",
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
    _add_missing_columns(
        "image_templates",
        {
            "creation_method": "varchar default 'extracted' not null",
            "updated_at": "timestamp",
        },
    )
    _add_missing_columns(
        "image_prompt_settings",
        {
            "reference_image_url": "text",
            "template_layers_json": "json",
            "template_analyzed_at": "timestamp",
            "template_logo_url": "text",
        },
    )
    _add_missing_columns(
        "prompt_templates",
        {
            "template_name": "varchar default 'Custom' not null",
            "question_answers": "json default '{}' not null",
            "assembled_prompt": "text",
            "raw_prompt": "text",
            "creativity_level": "integer default 7 not null",
            "style_examples": "json default '[]' not null",
            "updated_at": "timestamp",
        },
    )
    _add_missing_columns(
        "post_image_generations",
        {
            "llm_instructions": "json default '{}' not null",
        },
    )


def _ensure_user_settings_table() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("user_settings"):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE user_settings (
                        user_id INTEGER PRIMARY KEY,
                        post_generation_provider VARCHAR DEFAULT 'openai' NOT NULL,
                        post_generation_model VARCHAR DEFAULT 'gpt-4o' NOT NULL,
                        image_generation_provider VARCHAR DEFAULT 'gemini' NOT NULL,
                        image_generation_model VARCHAR DEFAULT 'imagen-3.0-generate-001' NOT NULL
                    )
                    """
                )
            )
            # Best-effort FK (SQLite allows it, Postgres requires users table already)
            try:
                connection.execute(
                    text(
                        """
                        ALTER TABLE user_settings
                        ADD CONSTRAINT user_settings_user_id_fkey
                        FOREIGN KEY (user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE
                        """
                    )
                )
            except Exception:
                pass
        return

    _add_missing_columns(
        "user_settings",
        {
            "post_generation_provider": "varchar default 'openai' not null",
            "post_generation_model": "varchar default 'gpt-4o' not null",
            "image_generation_provider": "varchar default 'gemini' not null",
            "image_generation_model": "varchar default 'imagen-3.0-generate-001' not null",
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
            "template_image_generation_enabled": "boolean default false not null",
            "template_logo_url": "text",
        },
    )


def _ensure_background_asset_schema() -> None:
    """Rename legacy asset_type/value_json columns to type/config and migrate data."""
    import json as _json
    inspector = inspect(engine)
    if not inspector.has_table("template_background_assets"):
        return

    existing_columns = {col["name"] for col in inspector.get_columns("template_background_assets")}

    # Step 1: rename columns if still using old names
    if "asset_type" in existing_columns and "type" not in existing_columns:
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE template_background_assets RENAME COLUMN asset_type TO type"))
                conn.execute(text("ALTER TABLE template_background_assets RENAME COLUMN value_json TO config"))
            print("[MIGRATION] Renamed asset_type->type and value_json->config on template_background_assets")
        except Exception as e:
            print(f"[MIGRATION WARNING] Could not rename background asset columns: {e}")
            return

    # Step 2: migrate config JSON values from old format to new format
    try:
        with engine.begin() as conn:
            rows = conn.execute(
                text("SELECT id, type, config FROM template_background_assets")
            ).mappings().all()

            for row in rows:
                bg_type = row["type"] or ""
                config = row["config"]
                if isinstance(config, str):
                    try:
                        config = _json.loads(config)
                    except Exception:
                        config = {}
                config = config or {}

                # Only migrate records that still use old config keys
                if bg_type in ("solid_color", "solid") and "color_hex" in config and "hex" not in config:
                    new_config = {"hex": config.get("color_hex", "#000000")}
                    new_type = "solid"
                elif bg_type in ("gradient", "gradient_linear") and "stops" in config and "from_hex" not in config:
                    stops = config.get("stops", [])
                    new_config = {
                        "from_hex": stops[0] if stops else "#000000",
                        "to_hex": stops[-1] if stops else "#ffffff",
                        "angle_deg": 135,
                    }
                    new_type = "gradient_linear"
                else:
                    continue

                conn.execute(
                    text("UPDATE template_background_assets SET type=:t, config=:c WHERE id=:id"),
                    {"t": new_type, "c": _json.dumps(new_config), "id": row["id"]},
                )
        print("[MIGRATION] Background asset config data migrated successfully")
    except Exception as e:
        print(f"[MIGRATION WARNING] Could not migrate background asset config data: {e}")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
