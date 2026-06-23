import sys
import os
from PIL import Image
import io

# Ensure backend path is loaded
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

from app.routers.persona_image_templates import _assemble_manual_template_preview

def run_test():
    bg = Image.new("RGBA", (1080, 1080), (20, 20, 30, 255))
    
    template_json = {
        "canvas_width": 1080,
        "canvas_height": 1080,
        "layers": [
            {
                "id": "headline",
                "type": "text",
                "role": "headline",
                "z_index": 1,
                "position_x_percent": 10,
                "position_y_percent": 20,
                "width_percent": 80,
                "height_percent": 20,
                "font_size_min_percent": 8,
                "font_size_max_percent": 8,
                "font_weight": "bold",
                "text_align_options": ["center"],
                "color_options": [{"color_hex": "#ffffff"}],
            },
            {
                "id": "my_divider",
                "type": "divider",
                "z_index": 2,
                "position_x_percent": 0,
                "position_y_percent": 50,
                "width_percent": 100,
                "height_percent": 10,
                "orientation": "horizontal",
                "color_options": [{"color_hex": "#ff0055"}],
                "thickness_px": 8,
                "opacity": 100,
                "width_pct": 60,
                "y_pct": 45,
                "x_start_pct": 20
            },
            {
                "id": "subheadline",
                "type": "text",
                "role": "subheadline",
                "z_index": 3,
                "position_x_percent": 10,
                "position_y_percent": 60,
                "width_percent": 80,
                "height_percent": 15,
                "font_size_min_percent": 5,
                "font_size_max_percent": 5,
                "font_weight": "regular",
                "text_align_options": ["center"],
                "color_options": [{"color_hex": "#cccccc"}],
            }
        ]
    }
    
    # Empty font assets for default system fonts
    png_bytes = _assemble_manual_template_preview(template_json, bg, None, {})
    
    out_path = os.path.abspath("test_divider_out.png")
    with open(out_path, "wb") as f:
        f.write(png_bytes)
        
    print(f"Saved test image to {out_path}")

if __name__ == "__main__":
    run_test()
