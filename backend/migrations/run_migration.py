import os
import sys

# Add backend directory to path so app.database can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text
from app.database import engine

migration_path = os.path.join(os.path.dirname(__file__), 'add_media_library_id_to_post_logs.sql')

with open(migration_path, 'r') as f:
    sql_script = f.read()

try:
    with engine.begin() as conn:
        for statement in sql_script.split(';'):
            if statement.strip():
                conn.execute(text(statement))
    print("Migration completed successfully")
except Exception as e:
    print(f"Error running migration: {e}")
