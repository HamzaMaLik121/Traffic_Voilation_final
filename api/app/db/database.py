"""
Database Module -- API Service (read-write with read-only fallback)
Provides database access for the API.
- If the DB file already exists (worker created it), connects in read-only mode.
- If the DB file doesn't exist yet, creates it with the required tables
  (the worker hasn't written anything yet, so there's nothing to read).

NOTE: Table schema is duplicated from worker/app/db/database.py.
Keep both in sync when making schema changes.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
import sys
import json

sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import DATABASE_PATH, DATABASE_DIR


class ViolationDatabase:
    """Database manager for traffic violations (read-only if DB exists)"""
    
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = DATABASE_PATH
        
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        
        self._lazy_connect()
    
    def _lazy_connect(self):
        """
        Connect to database with graceful fallback:
        - If the DB file exists, connect in read-only mode
        - If the DB file doesn't exist yet, create + connect in read-write mode
          (the worker hasn't written anything yet, so there's nothing to read)
        """
        db_file = Path(self.db_path)
        
        if db_file.exists():
            # Read-only mode for existing DB (worker has written records)
            uri = f"file:{self.db_path}?mode=ro"
            self.conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            self.cursor = self.conn.cursor()
            print(f"✓ Connected to database (read-only): {self.db_path}")
        else:
            # DB doesn't exist yet — create it in read-write mode
            # Tables will be empty, but queries won't crash
            print(f"ℹ Database not found at {self.db_path} — creating empty database")
            self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self.cursor = self.conn.cursor()
            self._create_tables()
            print(f"✓ Created and connected to database: {self.db_path}")
    
    def _create_tables(self):
        """Create database tables so queries don't fail on empty DB"""
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                violation_type TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                location TEXT,
                vehicle_type TEXT,
                license_plate TEXT,
                confidence REAL,
                speed REAL,
                speed_limit REAL,
                evidence_image_path TEXT,
                video_frame_number INTEGER,
                metadata TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                violation_type TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                UNIQUE(date, violation_type)
            )
        ''')
        self.conn.commit()
        print(f"✓ Created database tables")
    
    def get_violations(self, filters=None, limit=100):
        """
        Retrieve violations with optional filters
        
        Args:
            filters: Dictionary of filter criteria
            limit: Maximum number of records to return
            
        Returns:
            violations: List of violation records
        """
        query = "SELECT * FROM violations"
        conditions = []
        values = []
        
        if filters:
            if 'violation_type' in filters:
                conditions.append("violation_type = ?")
                values.append(filters['violation_type'])
            
            if 'license_plate' in filters:
                conditions.append("license_plate = ?")
                values.append(filters['license_plate'])
            
            if 'start_date' in filters:
                conditions.append("timestamp >= ?")
                values.append(filters['start_date'])
            
            if 'end_date' in filters:
                conditions.append("timestamp <= ?")
                values.append(filters['end_date'])
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += f" ORDER BY timestamp DESC LIMIT {limit}"
        
        self.cursor.execute(query, values)
        
        columns = [desc[0] for desc in self.cursor.description]
        violations = []
        
        for row in self.cursor.fetchall():
            violation = dict(zip(columns, row))
            if violation.get('metadata'):
                violation['metadata'] = json.loads(violation['metadata'])
            # Convert datetime objects to strings for JSON serialization
            for key, val in violation.items():
                if isinstance(val, datetime):
                    violation[key] = val.isoformat()
            violations.append(violation)
        
        return violations
    
    def get_violation_by_id(self, violation_id):
        """Get a specific violation by ID"""
        self.cursor.execute("SELECT * FROM violations WHERE id = ?", (violation_id,))
        
        row = self.cursor.fetchone()
        if row:
            columns = [desc[0] for desc in self.cursor.description]
            violation = dict(zip(columns, row))
            if violation.get('metadata'):
                violation['metadata'] = json.loads(violation['metadata'])
            # Convert datetime objects to strings for JSON serialization
            for key, val in violation.items():
                if isinstance(val, datetime):
                    violation[key] = val.isoformat()
            return violation
        
        return None
    
    def get_statistics(self, start_date=None, end_date=None):
        """
        Get violation statistics
        
        Args:
            start_date: Start date for statistics
            end_date: End date for statistics
            
        Returns:
            statistics: Dictionary of statistics
        """
        query = "SELECT violation_type, SUM(count) as total FROM statistics"
        conditions = []
        values = []
        
        if start_date:
            conditions.append("date >= ?")
            values.append(start_date)
        
        if end_date:
            conditions.append("date <= ?")
            values.append(end_date)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " GROUP BY violation_type"
        
        self.cursor.execute(query, values)
        
        statistics = {}
        for row in self.cursor.fetchall():
            statistics[row[0]] = row[1]
        
        return statistics
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
