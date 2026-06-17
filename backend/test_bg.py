import asyncio
import io
from PIL import Image

# Mock dependencies
class MockAsset:
    def __init__(self, id, type, config):
        self.id = id
        self.type = type
        self.config = config
        self.preview_url = None

class MockDB:
    def query(self, *args, **kwargs):
        return self
    def filter(self, *args, **kwargs):
        return self
    def first(self):
        return self.asset
    def set_asset(self, asset):
        self.asset = asset

async def main():
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    from app.routers.persona_image_templates import _load_background_asset_image
    
    db = MockDB()
    w, h = 400, 400
    
    print("Testing solid...")
    db.set_asset(MockAsset("1", "solid", {"hex": "#E63946"}))
    img = await _load_background_asset_image(db, 1, "1", w, h)
    assert img.size == (w, h)
    
    print("Testing gradient_linear...")
    db.set_asset(MockAsset("2", "gradient_linear", {"from_hex": "#E63946", "to_hex": "#1D3557", "angle_deg": 45}))
    img = await _load_background_asset_image(db, 1, "2", w, h)
    assert img.size == (w, h)
    
    print("Testing gradient_radial...")
    db.set_asset(MockAsset("3", "gradient_radial", {"center_hex": "#F1FAEE", "edge_hex": "#457B9D"}))
    img = await _load_background_asset_image(db, 1, "3", w, h)
    assert img.size == (w, h)
    
    print("All background types generated successfully without errors.")

if __name__ == "__main__":
    asyncio.run(main())
