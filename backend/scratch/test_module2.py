import sys
import io
from PIL import Image
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.routers.persona_image_templates import _assemble_from_llm_instructions

def test_module2():
    # 1. Create a dummy base image and template json
    base = Image.new("RGBA", (1080, 1080), (200, 200, 200, 255))
    template_json = {
        "canvas_width": 1080,
        "canvas_height": 1080,
        "layers": [
            {
                "id": "layer_1",
                "type": "text",
                "role": "headline",
                "z_index": 1,
                "position_x_percent": 10,
                "position_y_percent": 10,
                "width_percent": 80,
                "height_percent": 20,
                "opacity": 50, # template default opacity
            },
            {
                "id": "layer_2",
                "type": "frame",
                "z_index": 2,
                "opacity": 100,
                "color_options": [{"color_hex": "#ff0000"}],
                "thickness_px": 20,
                "inset_px": 10
            }
        ]
    }

    # 2. Mock llm instructions
    llm_instructions = {
        "layers": [
            {
                "layer_id": "layer_1",
                "text": "Hello World",
                "color_hex": "#000000",
                "font_size_percent": 10,
                "opacity": 60 # LLM overrides opacity
            },
            {
                "layer_id": "layer_2",
                "color_hex": "#ff0000",
                "thickness_px": 15,
                "opacity": 80
            }
        ]
    }

    db = SessionLocal()
    try:
        # We need a logo bytes just to pass the arg, can be None
        result_bytes = _assemble_from_llm_instructions(
            template_json=template_json,
            background=base,
            logo_bytes=None,
            llm_instructions=llm_instructions,
            db=db,
            user_id=1
        )
        
        result_img = Image.open(io.BytesIO(result_bytes))
        result_img.save("module2_test_output.png")
        print("Test passed! Image saved to module2_test_output.png")
    except Exception as e:
        print(f"Test failed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    test_module2()
