import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image
from app.routers.persona_image_templates import _assemble_manual_template_preview

def test_shape_render():
    bg = Image.new("RGB", (1080, 1080), (248, 249, 250))
    template_json = {
        "canvas_width": 1080,
        "canvas_height": 1080,
        "layers": [
            {
                "id": "shape_1",
                "type": "shape",
                "shape_type": "pill",
                "z_index": 1,
                "position_x_percent": 10,
                "position_y_percent": 30,
                "width_percent": 80,
                "height_percent": 20,
                "rotation_degrees": 0,
                "fill_color_options": [{"color_hex": "#3b82f6", "label": "Blue"}],
                "stroke_color_options": [{"color_hex": "#1d4ed8", "label": "Dark Blue"}],
                "stroke_width": 6,
                "corner_radius": 0,
                "opacity": 85,
            },
            {
                "id": "shape_2",
                "type": "shape",
                "shape_type": "circle",
                "z_index": 2,
                "position_x_percent": 5,
                "position_y_percent": 5,
                "width_percent": 20,
                "height_percent": 20,
                "rotation_degrees": 0,
                "fill_color_options": [{"color_hex": "#22c55e", "label": "Green"}],
                "stroke_color_options": [],
                "stroke_width": 0,
                "opacity": 100,
            },
            {
                "id": "shape_3",
                "type": "shape",
                "shape_type": "rectangle",
                "z_index": 3,
                "position_x_percent": 10,
                "position_y_percent": 60,
                "width_percent": 80,
                "height_percent": 15,
                "rotation_degrees": 5,
                "fill_color_options": [{"color_hex": "#f59e0b", "label": "Amber"}],
                "stroke_color_options": [{"color_hex": "#b45309", "label": "Dark Amber"}],
                "stroke_width": 4,
                "corner_radius": 20,
                "opacity": 70,
            },
        ]
    }

    png_bytes = _assemble_manual_template_preview(template_json, bg, None, {})
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_shape_output.png")
    with open(out_path, "wb") as f:
        f.write(png_bytes)
    print(f"[OK] Test rendering complete: {out_path}")
    print(f"  Output size: {len(png_bytes)} bytes")

if __name__ == "__main__":
    test_shape_render()
