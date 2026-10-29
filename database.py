import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nestora.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Table for storing all past booking attempts & results
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS booking_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            target_date TEXT NOT NULL,
            meals_booked TEXT NOT NULL,
            status TEXT NOT NULL,
            log_text TEXT
        );
    """)

    # Table for app settings & auto-scheduling configuration
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            auto_booking_enabled INTEGER DEFAULT 1,
            booking_time TEXT DEFAULT '20:00',
            book_today INTEGER DEFAULT 1,
            book_tomorrow INTEGER DEFAULT 1
        );
    """)

    # Insert default settings row if not present
    cursor.execute("""
        INSERT OR IGNORE INTO app_settings (id, auto_booking_enabled, booking_time, book_today, book_tomorrow)
        VALUES (1, 1, '20:00', 1, 1);
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized at: {DB_PATH}")

def add_booking_record(target_date: str, meals_booked: str, status: str, log_text: str = ""):
    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        INSERT INTO booking_history (timestamp, target_date, meals_booked, status, log_text)
        VALUES (?, ?, ?, ?, ?);
    """, (now_str, target_date, meals_booked, status, log_text))
    
    conn.commit()
    conn.close()

def get_booking_history(limit: int = 50):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, timestamp, target_date, meals_booked, status, log_text
        FROM booking_history
        ORDER BY id DESC
        LIMIT ?;
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_booking_stats():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM booking_history WHERE status = 'SUCCESS'")
    success_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM booking_history")
    total_count = cursor.fetchone()[0]
    conn.close()
    
    return {
        "total_runs": total_count,
        "successful_runs": success_count,
        "success_rate": round((success_count / total_count * 100), 1) if total_count > 0 else 100.0
    }

def get_settings():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT auto_booking_enabled, booking_time, book_today, book_tomorrow FROM app_settings WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"auto_booking_enabled": 1, "booking_time": "20:00", "book_today": 1, "book_tomorrow": 1}

def update_settings(auto_booking_enabled: int, booking_time: str, book_today: int, book_tomorrow: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE app_settings
        SET auto_booking_enabled = ?, booking_time = ?, book_today = ?, book_tomorrow = ?
        WHERE id = 1;
    """, (auto_booking_enabled, booking_time, book_today, book_tomorrow))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
