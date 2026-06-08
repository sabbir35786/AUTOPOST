"""Debug script to test the full publish flow and capture the exact error."""
import os
import sys
import asyncio
import traceback

os.environ["DATABASE_URL"] = "postgresql://postgres.hejnjmtbqjlrmjxssrwx:e6i4MVQrBvcADYzu@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"
os.environ["SECRET_KEY"] = "your-super-secret-key-change-mehSfWzFSEMg7UD4LMw19I+k+U5kOiYv9qLUI4q7KGEKRJU7vp9SuDmxMNIaKjM4bj1zkmydiNjojlgCWWHRqquQ=="
os.environ["SUPABASE_URL"] = "https://hejnjmtbqjlrmjxssrwx.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imhlam5qbXRicWpscm1qeHNzcnd4Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3OTQyMzAzMiwiZXhwIjoyMDk0OTk5MDMyfQ.IXuYBJ-FpVelFrl8nHV0g6zZAJD9NJ7yQ8NAtMfw1fE"
os.environ["FRONTEND_URL"] = "http://localhost:3000"
os.environ["BACKEND_URL"] = "http://localhost:8000"
os.environ["FACEBOOK_APP_ID"] = "1297638102047989"
os.environ["FACEBOOK_APP_SECRET"] = "test"
os.environ["FACEBOOK_TOKEN_ENCRYPTION_KEY"] = "test"

sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal
from app import models
from app.services.publish_flow import run_full_publish_flow


async def test():
    db = SessionLocal()
    try:
        persona = db.query(models.AIPersona).filter(models.AIPersona.id == 11).first()
        if not persona:
            print("Persona 11 not found")
            return
        print(f"Testing: {persona.persona_name} (id={persona.id})")
        print(f"  page_connection_id={persona.page_connection_id}")
        print(f"  template_image_generation_enabled={persona.template_image_generation_enabled}")
        print(f"  image_fallback_policy={persona.image_fallback_policy}")
        print(f"  include_image={persona.include_image}")

        result = await run_full_publish_flow(
            persona_id=persona.id,
            db=db,
            is_test=True,
            slot=None,
            force_image=True,
        )
        print(f"\nResult status: {result.get('status')}")
        if result.get("status") == "failed":
            print(f"ERROR: {result.get('error_message')}")
        else:
            print(f"SUCCESS! post_id={result.get('post_id')}")
            content = result.get("content") or ""
            print(f"content: {content[:100]}...")
            print(f"image_url: {result.get('image_url')}")
    except Exception as e:
        traceback.print_exc()
    finally:
        db.close()


asyncio.run(test())
