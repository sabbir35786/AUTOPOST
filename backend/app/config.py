import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def _load_env_file() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://autopost-woad.vercel.app").rstrip("/")


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)

    parsed_url = urlparse(database_url)
    if (
        parsed_url.scheme.startswith("postgresql")
        and parsed_url.hostname
        and "supabase" in parsed_url.hostname
    ):
        query_params = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
        query_params.setdefault("sslmode", "require")
        database_url = urlunparse(
            parsed_url._replace(query=urlencode(query_params)),
        )

    return database_url


SQLALCHEMY_DATABASE_URL = _normalize_database_url(os.getenv(
    "DATABASE_URL",
    os.getenv("SQLITE_DATABASE_URL", "sqlite:///./auto_poster.db"),
))
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID", "")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "")
FACEBOOK_OAUTH_SCOPES = os.getenv(
    "FACEBOOK_OAUTH_SCOPES",
    "pages_manage_posts,pages_read_engagement,pages_show_list",
)
FACEBOOK_REDIRECT_URI = os.getenv(
    "FACEBOOK_REDIRECT_URI",
    "https://autopost-qwgw.onrender.com/auth/facebook/callback",
)
FACEBOOK_TOKEN_ENCRYPTION_KEY = os.getenv("FACEBOOK_TOKEN_ENCRYPTION_KEY", "")
FACEBOOK_GRAPH_API_BASE_URL = os.getenv(
    "FACEBOOK_GRAPH_API_BASE_URL",
    "https://graph.facebook.com/v19.0",
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
MISTRAL_API_BASE_URL = os.getenv("MISTRAL_API_BASE_URL", "https://api.mistral.ai/v1")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
ANTHROPIC_API_BASE_URL = os.getenv("ANTHROPIC_API_BASE_URL", "https://api.anthropic.com/v1")
