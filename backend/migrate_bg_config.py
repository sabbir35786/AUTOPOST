import sys
import os
import json

# Add backend directory to path so app.database can be imported
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from sqlalchemy import text
from app.database import engine

def migrate_config():
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE template_background_assets RENAME COLUMN asset_type TO type"))
            conn.execute(text("ALTER TABLE template_background_assets RENAME COLUMN value_json TO config"))
        except Exception as e:
            print(f"Skipping alter table: {e}")
            
        # Fetch all rows
        rows = conn.execute(text("SELECT id, type, config FROM template_background_assets")).mappings().all()
        for row in rows:
            bg_id = row['id']
            bg_type = row['type']
            config = row['config']
            
            if isinstance(config, str):
                try:
                    config = json.loads(config)
                except Exception:
                    config = {}
                    
            if not config:
                continue
                
            new_config = {}
            if bg_type == 'solid':
                new_config['hex'] = config.get('color_hex', '#000000')
            elif bg_type == 'gradient_linear':
                stops = config.get('stops', [])
                if isinstance(stops, list) and len(stops) >= 2:
                    new_config['from_hex'] = stops[0]
                    new_config['to_hex'] = stops[-1]
                else:
                    new_config['from_hex'] = '#000000'
                    new_config['to_hex'] = '#ffffff'
                new_config['angle_deg'] = 135
            else:
                new_config = config
                
            # Update the row
            conn.execute(
                text("UPDATE template_background_assets SET config = :config WHERE id = :id"),
                {"config": json.dumps(new_config), "id": bg_id}
            )

if __name__ == "__main__":
    print("Migrating config data...")
    migrate_config()
    print("Done!")
