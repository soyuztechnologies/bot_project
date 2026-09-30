import os
import urllib.parse
import getpass
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from pymongo import MongoClient

def cleanup_atlas_logs(days=30):
    # Load environment variables from .env in the same directory
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    load_dotenv(dotenv_path=env_path)
    
    # Get the Atlas URI
    atlas_uri = os.getenv("MONGO_URI_ATLAS")
    if not atlas_uri:
        print("Error: MONGO_URI_ATLAS not found in .env file.")
        return
        
    # Extract the password from the URI to use it as an authorization check
    try:
        parsed_uri = urllib.parse.urlparse(atlas_uri)
        expected_password = parsed_uri.password
    except Exception:
        expected_password = None
        
    if not expected_password:
        print("Error: Could not extract password from the MongoDB URI.")
        return
        
    # Prompt the user for the Atlas password for safety
    print("WARNING: You are about to delete old logs from the database.")
    entered_password = getpass.getpass("Please enter the MongoDB Atlas password to confirm: ")
    
    # URL-decode the expected password just in case it contains special characters
    decoded_expected_password = urllib.parse.unquote(expected_password)
    
    if entered_password != expected_password and entered_password != decoded_expected_password:
        print("Error: Incorrect password. Aborting operation.")
        return
        
    print(f"\nPassword verified. Connecting to MongoDB Atlas...")
    try:
        client = MongoClient(atlas_uri)
        # Try to ping to verify connection
        client.admin.command('ping')
        
        # Determine database name (same logic as database.py)
        db_name = os.getenv("MONGO_DB_NAME", "").strip() or None
        if not db_name:
            try:
                db_name = client.get_default_database().name
            except:
                pass
        if not db_name:
            try:
                path = atlas_uri.split("?", 1)[0].rsplit("/", 1)[-1]
                if path and not path.startswith("mongodb"):
                    db_name = path
            except:
                pass
        if not db_name:
            db_name = os.getenv("MONGO_DB_FALLBACK", "seo_bot_db")
            
        print(f"Using database: {db_name}")
        db = client[db_name]
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        print(f"Deleting documents older than {cutoff_date.isoformat()} ({days} days)...")
        
        # 1. Delete from automation_logs
        logs_coll = db["automation_logs"]
        logs_result = logs_coll.delete_many({"timestamp": {"$lt": cutoff_date}})
        print(f"Deleted {logs_result.deleted_count} logs from 'automation_logs'.")
        
        # 2. Delete from automation_runs
        runs_coll = db["automation_runs"]
        runs_result = runs_coll.delete_many({"started_at": {"$lt": cutoff_date}})
        print(f"Deleted {runs_result.deleted_count} runs from 'automation_runs'.")
        
        # 3. Delete from backlinks
        backlinks_coll = db["backlinks"]
        backlinks_result = backlinks_coll.delete_many({"started_at": {"$lt": cutoff_date}})
        print(f"Deleted {backlinks_result.deleted_count} records from 'backlinks'.")
        
        print("\nCleanup completed successfully.")
        
    except Exception as e:
        print(f"Failed to connect or delete logs: {e}")
    finally:
        if 'client' in locals():
            client.close()

if __name__ == "__main__":
    cleanup_atlas_logs(30)
