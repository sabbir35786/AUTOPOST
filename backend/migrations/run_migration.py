import os
import sys
import glob

# Add backend directory to path so app.database can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text
from app.database import engine

# Migration files to run in order (priority order)
MIGRATIONS = [
    '01.sql',
    '02 add_image_generation_tables.sql',
    '03 add_manual_template_builder_step1.sql',
    '04 add_manual_template_builder_step2.sql',
    '05 add_manual_template_builder_step5.sql',
    '06 add_media_library_id_to_post_logs.sql',
    '07 add_sessions_table.sql',
    '08 add_template_image_generation.sql',
    '09 add_user_settings_models.sql',
    '10 fix_facebook_connections_flow.sql',
    '11 fix_image_templates_schema.sql',
    '12 rebuild_image_templates_system.sql',
    '13 drop_layers_json_column.sql',
    '14 add_updated_at_to_image_templates.sql',
]

def run_migrations():
    migration_dir = os.path.dirname(__file__)
    
    for migration_file in MIGRATIONS:
        migration_path = os.path.join(migration_dir, migration_file)
        
        if not os.path.exists(migration_path):
            print(f"⏭️  Skipping {migration_file} (not found)")
            continue
            
        print(f"⏳ Running {migration_file}...")
        
        try:
            with open(migration_path, 'r') as f:
                sql_script = f.read()
            
            with engine.begin() as conn:
                for statement in sql_script.split(';'):
                    if statement.strip():
                        conn.execute(text(statement))
            print(f"✅ {migration_file} completed successfully")
        except Exception as e:
            print(f"❌ Error running {migration_file}: {e}")
            # Continue with other migrations instead of failing completely
            continue

if __name__ == "__main__":
    print("🚀 Starting database migrations...")
    run_migrations()
    print("🎉 All migrations completed!")
