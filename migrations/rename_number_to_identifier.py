"""
Migration script to rename 'number' column to 'identifier' in all tables.
"""
from sqlalchemy import text
from database.database import engine

def apply_migration():
    with engine.connect() as conn:
        # Rename columns in number_records table
        conn.execute(text("""
            CREATE TABLE number_records_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identifier TEXT NOT NULL,
                notes TEXT,
                group_id TEXT,
                message_id INTEGER,
                user_id INTEGER,
                is_duplicate BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (identifier)
            )
        """))
        
        # Copy data from old table to new table
        conn.execute(text("""
            INSERT INTO number_records_new 
            (id, identifier, notes, group_id, message_id, user_id, is_duplicate, created_at, updated_at)
            SELECT id, number, notes, group_id, message_id, user_id, is_duplicate, created_at, updated_at
            FROM number_records
        """))
        
        # Drop old table and rename new one
        conn.execute(text("DROP TABLE number_records"))
        conn.execute(text("ALTER TABLE number_records_new RENAME TO number_records"))
        
        # Recreate indexes
        conn.execute(text("CREATE INDEX ix_number_records_identifier ON number_records (identifier)"))
        
        # Commit changes
        conn.commit()
        
        print("Migration completed successfully!")

if __name__ == "__main__":
    apply_migration()
