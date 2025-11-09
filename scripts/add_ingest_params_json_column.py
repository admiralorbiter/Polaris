"""
Migration script to add ingest_params_json column to import_runs table.

This column stores parameters needed for retry functionality:
- file_path: Path to the uploaded/staged file
- source_system: Source identifier (e.g., "csv")
- dry_run: Whether the run was executed in dry-run mode
- keep_file: Whether to retain the file after processing (for retry)

Run this script after deploying the code changes that add retry support.
"""

from flask_app import create_app
from flask_app.models.base import db
from sqlalchemy import text


def add_ingest_params_json_column():
    """Add ingest_params_json column to import_runs table if it doesn't exist."""
    app = create_app()
    with app.app_context():
        # Check if column already exists
        inspector = db.inspect(db.engine)
        columns = [col["name"] for col in inspector.get_columns("import_runs")]
        
        if "ingest_params_json" in columns:
            print("Column ingest_params_json already exists. Skipping migration.")
            return
        
        # Add the column
        with db.engine.connect() as conn:
            conn.execute(
                text(
                    """
                    ALTER TABLE import_runs
                    ADD COLUMN ingest_params_json JSON
                    """
                )
            )
            conn.commit()
        
        print("Successfully added ingest_params_json column to import_runs table.")


if __name__ == "__main__":
    add_ingest_params_json_column()

