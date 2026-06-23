import sys
import os
import uuid
import asyncio
from datetime import datetime, timezone
import io

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import models
from app.routers.persona_image_templates import _run_post_image_generation

async def run_test():
    db = SessionLocal()
    try:
        # 1. Ensure user exists
        user = db.query(models.User).first()
        if not user:
            print("No user found.")
            return

        print(f"User ID: {user.id}")

        # 2. Upload a photo background (mock)
        # Create a red 500x500 image
        from PIL import Image
        img = Image.new("RGB", (500, 500), color="red")
        out = io.BytesIO()
        img.save(out, format="JPEG")
        img_bytes = out.getvalue()
        
        # Uploading to supabase directly is complex in a script because we need auth.
        # Instead, let's create the record manually using a fake URL, but _load_background_asset_image downloads it.
        # So we need a real URL, or we can use a data URL?
        # Let's use a dummy public URL for an image.
        test_url = "https://picsum.photos/800/600"
        
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
        
        # 3. Create a persona
        conn = db.query(models.FacebookConnection).filter(models.FacebookConnection.user_id == user.id).first()
        persona = db.query(models.AIPersona).filter(models.AIPersona.user_id == user.id).first()
        if not persona:
            persona = models.AIPersona(
                user_id=user.id,
                page_connection_id=conn.id if conn else 1,
                persona_name="Test Persona",
                niche="Testing",
                tone_tags="Casual"
            )
            db.add(persona)
            db.flush()

        # 4. Create a template using it
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
                            "font_asset_id": "test_font",
                            "label": "Test Font"
                        }
                    ],
                    "color_options": [{"color_hex": "#ffffff", "label": "White"}],
                    "text_align_options": ["center"]
                }
            ]
        }
        template = models.ImageTemplate(
            id=str(uuid.uuid4()),
            user_id=user.id,
            name="Test Template",
            reference_image_url="test",
            creation_method="manual",
            template_json=template_json
        )
        db.add(template)
        
        # 5. Assign template
        assignment = db.query(models.PersonaImageTemplateAssignment).filter(models.PersonaImageTemplateAssignment.persona_id == persona.id).first()
        if not assignment:
            assignment = models.PersonaImageTemplateAssignment(persona_id=persona.id, image_template_id=template.id)
            db.add(assignment)
        else:
            assignment.image_template_id = template.id

        # 6. Create post log
        post = models.PostLog(
            user_id=user.id,
            facebook_connection_id=conn.id if conn else 1,
            ai_persona_id=persona.id,
            content="This is a test post for the image generator.",
            status="draft"
        )
        db.add(post)
        db.commit()

        print(f"Triggering generation for Post ID: {post.id}")
        # 7. Trigger post generation
        gen = await _run_post_image_generation(db, post.id, user.id, template_id=template.id)
        print(f"Generation status: {gen.status}")
        if gen.error_message:
            print(f"Error: {gen.error_message}")
        print(f"Background Image URL: {gen.background_image_url}")
        print(f"Final Image URL: {gen.final_image_url}")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(run_test())
