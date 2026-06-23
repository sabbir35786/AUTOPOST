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
    '20_expand_background_assets.sql',
]

def split_sql_statements(sql_script: str) -> list:
    statements = []
    current_statement = []
    
    in_single_quote = False
    in_double_quote = False
    in_dollar_quote = False
    dollar_quote_tag = ""
    in_line_comment = False
    in_block_comment = False
    
    i = 0
    n = len(sql_script)
    while i < n:
        char = sql_script[i]
        
        # Check comments
        if in_line_comment:
            if char == '\n':
                in_line_comment = False
            current_statement.append(char)
            i += 1
            continue
            
        if in_block_comment:
            if char == '*' and i + 1 < n and sql_script[i+1] == '/':
                in_block_comment = False
                current_statement.append('*/')
                i += 2
            else:
                current_statement.append(char)
                i += 1
            continue
            
        if in_single_quote:
            if char == "'":
                if i + 1 < n and sql_script[i+1] == "'":
                    current_statement.append("''")
                    i += 2
                else:
                    in_single_quote = False
                    current_statement.append(char)
                    i += 1
            else:
                current_statement.append(char)
                i += 1
            continue
            
        if in_double_quote:
            if char == '"':
                in_double_quote = False
            current_statement.append(char)
            i += 1
            continue
            
        if in_dollar_quote:
            tag_len = len(dollar_quote_tag)
            if sql_script[i:i+tag_len] == dollar_quote_tag:
                in_dollar_quote = False
                current_statement.extend(sql_script[i:i+tag_len])
                i += tag_len
            else:
                current_statement.append(char)
                i += 1
            continue
            
        # Start of comments or quotes
        if char == '-' and i + 1 < n and sql_script[i+1] == '-':
            in_line_comment = True
            current_statement.append('--')
            i += 2
            continue
            
        if char == '/' and i + 1 < n and sql_script[i+1] == '*':
            in_block_comment = True
            current_statement.append('/*')
            i += 2
            continue
            
        if char == "'":
            in_single_quote = True
            current_statement.append(char)
            i += 1
            continue
            
        if char == '"':
            in_double_quote = True
            current_statement.append(char)
            i += 1
            continue
            
        if char == '$':
            next_dollar = sql_script.find('$', i + 1)
            if next_dollar != -1 and next_dollar - i < 50:
                tag = sql_script[i:next_dollar+1]
                content = tag[1:-1]
                if not content or content.isidentifier():
                    in_dollar_quote = True
                    dollar_quote_tag = tag
                    current_statement.extend(tag)
                    i = next_dollar + 1
                    continue
                    
        if char == ';':
            statements.append("".join(current_statement))
            current_statement = []
            i += 1
            continue
            
        current_statement.append(char)
        i += 1
        
    if current_statement:
        statements.append("".join(current_statement))
        
    return [s.strip() for s in statements if s.strip()]

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
            
            statements = split_sql_statements(sql_script)
            with engine.begin() as conn:
                for statement in statements:
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
