import sys
import os
import uuid
import asyncio
from datetime import datetime, timezone
import io
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import models
from app.routers.persona_image_templates import _load_background_asset_image, _assemble_from_llm_instructions

async def run_test():
    db = SessionLocal()
    try:
        user = db.query(models.User).first()
        if not user:
            print("No user found.")
            return

        # 1. Create photo background
        from PIL import Image
        img = Image.new("RGB", (800, 800), color="blue")
        out = io.BytesIO()
        img.save(out, format="JPEG")
        
        # We need to simulate _download_bytes returning our image
        import app.routers.persona_image_templates
        async def mock_download_bytes(url):
            return out.getvalue()
        app.routers.persona_image_templates._download_bytes = mock_download_bytes
        
        test_url = "https://example.com/test.jpg"
        
        bg_asset = models.TemplateBackgroundAsset(
            id=str(uuid.uuid4()),
            user_id=user.id,
            type="image",
            label="Test Photo BG",
            preview_url=test_url,
            config={"url": test_url, "fit": "cover", "tags": "test, photo"},
            created_at=datetime.now(timezone.utc)
        )
        db.add(bg_asset)
        db.flush()
        
        print("Testing background loading...")
        bg_img = await _load_background_asset_image(db, user.id, bg_asset.id, 1080, 1080)
        print(f"Loaded BG image: {bg_img.size}, mode: {bg_img.mode}")
        
        print("Testing compositor...")
        test_font_id = str(uuid.uuid4())
        template_json = {
            "canvas_width": 1080,
            "canvas_height": 1080,
            "aspect_ratio": "1:1",
            "background_options": [
                {
                    "asset_id": bg_asset.id,
                    "label": bg_asset.label,
                    "type": bg_asset.type,
                    "config": bg_asset.config
                }
            ],
            "layers": [
                {
                    "id": "layer_1",
                    "type": "text",
                    "role": "headline",
                    "z_index": 1,
                    "position_x_percent": 10,
                    "position_y_percent": 40,
                    "width_percent": 80,
                    "height_percent": 20,
                    "font_size_min_percent": 5,
                    "font_size_max_percent": 10,
                    "font_options": [
                        {
                            "font_asset_id": test_font_id,
                            "label": "Test Font"
                        }
                    ],
                    "color_options": [{"color_hex": "#ffffff", "label": "White"}],
                    "text_align_options": ["center"]
                }
            ]
        }
        
        llm_instructions = {
            "chosen_background_asset_id": bg_asset.id,
            "layers": [
                {
                    "layer_id": "layer_1",
                    "text": "Hello World",
                    "font_asset_id": test_font_id,
                    "color_hex": "#ffffff",
                    "font_size_percent": 8.0,
                    "text_align": "center"
                }
            ]
        }
        
        final_bytes = _assemble_from_llm_instructions(
            template_json=template_json,
            background=bg_img,
            logo_bytes=None,
            llm_instructions=llm_instructions,
            db=db,
            user_id=user.id
        )
        
        print(f"Compositor generated image bytes of length: {len(final_bytes)}")
        if len(final_bytes) > 0:
            print("SUCCESS! Test passed.")
        else:
            print("FAILED! Compositor returned 0 bytes.")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(run_test())
