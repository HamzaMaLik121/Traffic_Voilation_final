"""
Database Module — Worker Service
Manages violation records in SQLite database
"""

import sqlite3
from datetime import datetime
from pathlib import Path
import sys
import json

sys.path.append(str(Path(__file__).parent.parent.parent))
from config.config import DATABASE_PATH, DATABASE_DIR


class ViolationDatabase:
    """Database manager for traffic violations"""
    
    def __init__(self, db_path=None):
        """
        Initialize database connection
        
        Args:
            db_path: Path to database file
        """
        if db_path is None:
            db_path = DATABASE_PATH
        
        # Ensure database directory exists
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)
        
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        
        self._connect()
        self._create_tables()
    
    def _connect(self):
        """Connect to database"""
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.cursor = self.conn.cursor()
        print(f"✓ Connected to database: {self.db_path}")
    
    def _create_tables(self):
        """Create database tables if they don't exist"""
        
        # Violations table
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
        
        # Statistics table
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
        print("✓ Database tables ready")
    
    def add_violation(self, violation_data):
        """
        Add a violation record
        
        Args:
            violation_data: Dictionary containing violation information
            
        Returns:
            violation_id: ID of inserted record
        """
        query = '''
            INSERT INTO violations (
                violation_type, timestamp, location, vehicle_type,
                license_plate, confidence, speed, speed_limit,
                evidence_image_path, video_frame_number, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        
        values = (
            violation_data.get('violation_type'),
            violation_data.get('timestamp', datetime.now()),
            violation_data.get('location'),
            violation_data.get('vehicle_type'),
            violation_data.get('license_plate'),
            violation_data.get('confidence'),
            violation_data.get('speed'),
            violation_data.get('speed_limit'),
            violation_data.get('evidence_image_path'),
            violation_data.get('video_frame_number'),
            json.dumps(violation_data.get('metadata', {}))
        )
        
        self.cursor.execute(query, values)
        self.conn.commit()
        
        violation_id = self.cursor.lastrowid
        
        # Update statistics
        self._update_statistics(
            violation_data.get('violation_type'),
            violation_data.get('timestamp', datetime.now())
        )
        
        return violation_id
    
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
            # Parse metadata JSON
            if violation.get('metadata'):
                violation['metadata'] = json.loads(violation['metadata'])
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
            return violation
        
        return None
    
    def _update_statistics(self, violation_type, timestamp):
        """Update daily statistics"""
        date = timestamp.date() if isinstance(timestamp, datetime) else timestamp
        
        self.cursor.execute('''
            INSERT INTO statistics (date, violation_type, count)
            VALUES (?, ?, 1)
            ON CONFLICT(date, violation_type)
            DO UPDATE SET count = count + 1
        ''', (date, violation_type))
        
        self.conn.commit()
    
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
    
    def delete_violation(self, violation_id):
        """Delete a violation record"""
        self.cursor.execute("DELETE FROM violations WHERE id = ?", (violation_id,))
        self.conn.commit()
        return self.cursor.rowcount > 0
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            print("✓ Database connection closed")
