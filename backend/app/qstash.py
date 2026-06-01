from typing import Any

try:
    from qstash import QStash
except ModuleNotFoundError:
    QStash = None

from app.config import BACKEND_URL, CRON_SECRET, QSTASH_TOKEN


_client: Any | None = None


def get_qstash_client() -> Any | None:
    global _client
    if QStash is None:
        return None
    if _client is None and QSTASH_TOKEN:
        _client = QStash(token=QSTASH_TOKEN)
    return _client


async def schedule_scheduler_endpoint() -> bool:
    """Schedule the /api/internal/run-scheduler endpoint to run every minute via QStash."""
    client = get_qstash_client()
    if client is None:
        return False

    callback_url = f"{BACKEND_URL.rstrip('/')}/api/internal/run-scheduler"

    try:
        client.schedules.create(
            destination=callback_url,
            cron="* * * * *",
            headers={"X-Cron-Secret": CRON_SECRET},
        )
        print(f"QStash scheduler created successfully for {callback_url}")
        return True
    except Exception as exc:
        print(f"Failed to create QStash scheduler: {exc}")
        return False


def _print_qstash_config_status() -> None:
    print("QStash configuration:")
    status_icon = "OK" if QSTASH_TOKEN else "MISSING"
    print(f"  [{status_icon}] QSTASH_TOKEN {'loaded' if QSTASH_TOKEN else 'is missing'}")
    if QStash is None:
        print("  [MISSING] qstash package is not installed")
