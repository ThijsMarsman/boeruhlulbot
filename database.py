"""
Database module for Solana Trading Bot
Supports SQLite (local) and PostgreSQL (Railway)
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any
from contextlib import contextmanager

# Try to import both database drivers
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

import sqlite3

logger = logging.getLogger(__name__)


class Database:
    """Database handler supporting SQLite and PostgreSQL"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.is_postgres = database_url.startswith("postgres")
        
        if self.is_postgres and not HAS_POSTGRES:
            raise ImportError("psycopg2 is required for PostgreSQL support")
    
    def _get_connection(self):
        """Get database connection"""
        if self.is_postgres:
            return psycopg2.connect(self.database_url)
        else:
            # SQLite
            db_path = self.database_url.replace("sqlite:///", "")
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            return conn
    
    @contextmanager
    def get_cursor(self):
        """Context manager for database cursor"""
        conn = self._get_connection()
        try:
            if self.is_postgres:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
            else:
                cursor = conn.cursor()
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()
    
    def init_db(self):
        """Initialize database tables"""
        if self.is_postgres:
            self._init_postgres()
        else:
            self._init_sqlite()
        logger.info("Database initialized successfully")
    
    def _init_sqlite(self):
        """Initialize SQLite tables"""
        with self.get_cursor() as cursor:
            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    wallet_address TEXT NOT NULL,
                    private_key TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    slippage REAL DEFAULT 15.0,
                    auto_buy_amount REAL DEFAULT 0.1,
                    mev_protection INTEGER DEFAULT 1,
                    priority_fee TEXT DEFAULT 'medium',
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
                )
            """)
            
            # Trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER NOT NULL,
                    token_address TEXT NOT NULL,
                    trade_type TEXT NOT NULL,
                    amount_in REAL NOT NULL,
                    amount_out REAL NOT NULL,
                    signature TEXT,
                    status TEXT DEFAULT 'completed',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
                )
            """)
            
            # Positions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER NOT NULL,
                    token_address TEXT NOT NULL,
                    symbol TEXT,
                    name TEXT,
                    amount REAL NOT NULL,
                    entry_price REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id),
                    UNIQUE(telegram_id, token_address)
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_telegram_id ON trades(telegram_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_telegram_id ON positions(telegram_id)")
    
    def _init_postgres(self):
        """Initialize PostgreSQL tables"""
        with self.get_cursor() as cursor:
            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    username TEXT,
                    wallet_address TEXT NOT NULL,
                    private_key TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    slippage REAL DEFAULT 15.0,
                    auto_buy_amount REAL DEFAULT 0.1,
                    mev_protection BOOLEAN DEFAULT TRUE,
                    priority_fee TEXT DEFAULT 'medium',
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
                )
            """)
            
            # Trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT NOT NULL,
                    token_address TEXT NOT NULL,
                    trade_type TEXT NOT NULL,
                    amount_in REAL NOT NULL,
                    amount_out REAL NOT NULL,
                    signature TEXT,
                    status TEXT DEFAULT 'completed',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
                )
            """)
            
            # Positions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id SERIAL PRIMARY KEY,
                    telegram_id BIGINT NOT NULL,
                    token_address TEXT NOT NULL,
                    symbol TEXT,
                    name TEXT,
                    amount REAL NOT NULL,
                    entry_price REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id),
                    UNIQUE(telegram_id, token_address)
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_telegram_id ON trades(telegram_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_telegram_id ON positions(telegram_id)")
    
    def _row_to_dict(self, row) -> Optional[Dict]:
        """Convert database row to dictionary"""
        if row is None:
            return None
        if self.is_postgres:
            return dict(row)
        else:
            return dict(zip(row.keys(), row))
    
    # User methods
    def create_user(self, telegram_id: int, username: str, wallet_address: str, private_key: str) -> bool:
        """Create a new user"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (telegram_id, username, wallet_address, private_key)
                    VALUES (%s, %s, %s, %s)
                    """ if self.is_postgres else """
                    INSERT INTO users (telegram_id, username, wallet_address, private_key)
                    VALUES (?, ?, ?, ?)
                    """,
                    (telegram_id, username, wallet_address, private_key)
                )
                
                # Create default settings
                cursor.execute(
                    """
                    INSERT INTO settings (telegram_id) VALUES (%s)
                    """ if self.is_postgres else """
                    INSERT INTO settings (telegram_id) VALUES (?)
                    """,
                    (telegram_id,)
                )
            return True
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return False
    
    def get_user(self, telegram_id: int) -> Optional[Dict]:
        """Get user by telegram ID"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM users WHERE telegram_id = %s
                    """ if self.is_postgres else """
                    SELECT * FROM users WHERE telegram_id = ?
                    """,
                    (telegram_id,)
                )
                row = cursor.fetchone()
                return self._row_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting user: {e}")
            return None
    
    # Settings methods
    def get_settings(self, telegram_id: int) -> Dict:
        """Get user settings"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM settings WHERE telegram_id = %s
                    """ if self.is_postgres else """
                    SELECT * FROM settings WHERE telegram_id = ?
                    """,
                    (telegram_id,)
                )
                row = cursor.fetchone()
                if row:
                    return self._row_to_dict(row)
                return {"slippage": 15.0, "auto_buy_amount": 0.1, "mev_protection": True, "priority_fee": "medium"}
        except Exception as e:
            logger.error(f"Error getting settings: {e}")
            return {"slippage": 15.0, "auto_buy_amount": 0.1, "mev_protection": True, "priority_fee": "medium"}
    
    def update_settings(self, telegram_id: int, settings: Dict) -> bool:
        """Update user settings"""
        try:
            with self.get_cursor() as cursor:
                for key, value in settings.items():
                    if key in ["slippage", "auto_buy_amount", "mev_protection", "priority_fee"]:
                        cursor.execute(
                            f"""
                            UPDATE settings SET {key} = %s WHERE telegram_id = %s
                            """ if self.is_postgres else f"""
                            UPDATE settings SET {key} = ? WHERE telegram_id = ?
                            """,
                            (value, telegram_id)
                        )
            return True
        except Exception as e:
            logger.error(f"Error updating settings: {e}")
            return False
    
    # Trade methods
    def log_trade(
        self,
        telegram_id: int,
        token_address: str,
        trade_type: str,
        amount_in: float,
        amount_out: float,
        signature: str
    ) -> bool:
        """Log a trade"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO trades (telegram_id, token_address, trade_type, amount_in, amount_out, signature)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """ if self.is_postgres else """
                    INSERT INTO trades (telegram_id, token_address, trade_type, amount_in, amount_out, signature)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (telegram_id, token_address, trade_type, amount_in, amount_out, signature)
                )
            return True
        except Exception as e:
            logger.error(f"Error logging trade: {e}")
            return False
    
    def get_trades(self, telegram_id: int, limit: int = 10) -> List[Dict]:
        """Get recent trades for a user"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM trades WHERE telegram_id = %s
                    ORDER BY created_at DESC LIMIT %s
                    """ if self.is_postgres else """
                    SELECT * FROM trades WHERE telegram_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (telegram_id, limit)
                )
                rows = cursor.fetchall()
                return [self._row_to_dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting trades: {e}")
            return []
    
    # Position methods
    def update_position(
        self,
        telegram_id: int,
        token_address: str,
        symbol: str,
        name: str,
        amount: float,
        entry_price: float
    ) -> bool:
        """Update or create a position"""
        try:
            with self.get_cursor() as cursor:
                if self.is_postgres:
                    cursor.execute(
                        """
                        INSERT INTO positions (telegram_id, token_address, symbol, name, amount, entry_price)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (telegram_id, token_address)
                        DO UPDATE SET amount = positions.amount + EXCLUDED.amount, updated_at = CURRENT_TIMESTAMP
                        """,
                        (telegram_id, token_address, symbol, name, amount, entry_price)
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO positions (telegram_id, token_address, symbol, name, amount, entry_price)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT (telegram_id, token_address)
                        DO UPDATE SET amount = amount + excluded.amount, updated_at = CURRENT_TIMESTAMP
                        """,
                        (telegram_id, token_address, symbol, name, amount, entry_price)
                    )
            return True
        except Exception as e:
            logger.error(f"Error updating position: {e}")
            return False
    
    def get_positions(self, telegram_id: int) -> List[Dict]:
        """Get all positions for a user"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM positions WHERE telegram_id = %s AND amount > 0
                    ORDER BY updated_at DESC
                    """ if self.is_postgres else """
                    SELECT * FROM positions WHERE telegram_id = ? AND amount > 0
                    ORDER BY updated_at DESC
                    """,
                    (telegram_id,)
                )
                rows = cursor.fetchall()
                return [self._row_to_dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []
    
    def delete_position(self, telegram_id: int, token_address: str) -> bool:
        """Delete a position"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM positions WHERE telegram_id = %s AND token_address = %s
                    """ if self.is_postgres else """
                    DELETE FROM positions WHERE telegram_id = ? AND token_address = ?
                    """,
                    (telegram_id, token_address)
                )
            return True
        except Exception as e:
            logger.error(f"Error deleting position: {e}")
            return False
