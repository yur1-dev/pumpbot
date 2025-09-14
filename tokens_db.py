# tokens_db.py
import sqlite3
from datetime import datetime

class TokenStorage:
    def __init__(self, db_path="user_tokens.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_tokens (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                ticker TEXT NOT NULL,
                mint_address TEXT NOT NULL,
                tx_signature TEXT,
                was_instant BOOLEAN DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                initial_buy_sol REAL DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_tokens ON user_tokens(user_id)")
        conn.commit()
        conn.close()
    
    def save_token(self, user_id, token_data):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO user_tokens (user_id, name, ticker, mint_address, tx_signature, was_instant, initial_buy_sol)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            token_data['name'],
            token_data['ticker'], 
            token_data['mint'],
            token_data['signature'],
            token_data.get('was_instant', False),
            token_data.get('initial_buy', 0)
        ))
        conn.commit()
        conn.close()
    
    def get_user_tokens(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, ticker, mint_address, tx_signature, was_instant, created_at, initial_buy_sol
            FROM user_tokens 
            WHERE user_id = ? 
            ORDER BY created_at DESC
        """, (user_id,))
        
        tokens = []
        for row in cursor.fetchall():
            tokens.append({
                'name': row[0],
                'ticker': row[1], 
                'mint': row[2],
                'tx_link': f"https://solscan.io/tx/{row[3]}",
                'was_instant': row[4],
                'created_at': row[5],
                'initial_buy': row[6]
            })
        
        conn.close()
        return tokens