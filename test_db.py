from db import get_db

try:
    db = get_db()
    print("Connection successful!")
    db.close()
except Exception as e:
    print("Connection failed:", e)