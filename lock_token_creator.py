# lock_address_pool.py
"""
LOCK Address Pool - Pre-generate and store LOCK addresses for instant creation
Complete implementation with error handling and background generation
"""

import sqlite3
import logging
import threading
import time
import base58
import os
from typing import Optional, Dict, Any, List
from solders.keypair import Keypair as SoldersKeypair
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)

class LockAddressPool:
    def __init__(self, db_path: str = "lock_addresses.db", target_pool_size: int = 100):
        self.db_path = db_path
        self.target_pool_size = target_pool_size
        self.generation_active = False
        self.generation_thread = None
        self.lock = threading.Lock()
        
        # Initialize database with proper error handling
        self._init_database()
        
        logger.info(f"LockAddressPool initialized with target size: {target_pool_size}")
        
    def _init_database(self):
        """Initialize the database with correct schema and error handling"""
        try:
            # Ensure directory exists
            db_dir = os.path.dirname(self.db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create table with complete schema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS lock_addresses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    public_key TEXT UNIQUE NOT NULL,
                    private_key TEXT NOT NULL,
                    suffix TEXT NOT NULL DEFAULT 'LOCK',
                    created_at TEXT NOT NULL,
                    used BOOLEAN DEFAULT FALSE,
                    used_at TEXT NULL,
                    generation_attempts INTEGER DEFAULT 0,
                    generation_time_seconds REAL DEFAULT 0.0
                )
            ''')
            
            # Create indexes for performance
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_unused_suffix 
                ON lock_addresses (used, suffix)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_created_at 
                ON lock_addresses (created_at)
            ''')
            
            # Add metadata table for stats
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pool_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT
                )
            ''')
            
            conn.commit()
            
            # Verify schema by checking if we can select from the table
            cursor.execute("SELECT public_key FROM lock_addresses LIMIT 1")
            
            conn.close()
            
            logger.info(f"Database initialized successfully: {self.db_path}")
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            
            # Try to fix common issues
            if "no such column" in str(e).lower():
                logger.info("Attempting to fix database schema...")
                self._fix_database_schema()
            else:
                raise
    
    def _fix_database_schema(self):
        """Fix database schema issues"""
        try:
            # Backup old database
            if os.path.exists(self.db_path):
                backup_path = f"{self.db_path}.backup_{int(time.time())}"
                os.rename(self.db_path, backup_path)
                logger.info(f"Old database backed up to: {backup_path}")
            
            # Recreate with correct schema
            self._init_database()
            
        except Exception as e:
            logger.error(f"Schema fix failed: {e}")
            raise
    
    def count_available(self, suffix: str = "LOCK") -> int:
        """Count available unused addresses"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT COUNT(*) FROM lock_addresses WHERE used = FALSE AND suffix = ?",
                    (suffix,)
                )
                
                count = cursor.fetchone()[0]
                return count
                
        except Exception as e:
            logger.error(f"Count available failed: {e}")
            return 0
    
    def count_total(self, suffix: str = "LOCK") -> int:
        """Count total addresses (used + unused)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT COUNT(*) FROM lock_addresses WHERE suffix = ?",
                    (suffix,)
                )
                
                count = cursor.fetchone()[0]
                return count
                
        except Exception as e:
            logger.error(f"Count total failed: {e}")
            return 0
    
    def get_next_address(self, suffix: str = "LOCK") -> Dict[str, Any]:
        """Get next available address from pool"""
        with self.lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # Get oldest unused address
                cursor.execute('''
                    SELECT id, public_key, private_key, created_at
                    FROM lock_addresses 
                    WHERE used = FALSE AND suffix = ? 
                    ORDER BY created_at ASC 
                    LIMIT 1
                ''', (suffix,))
                
                row = cursor.fetchone()
                
                if not row:
                    conn.close()
                    raise Exception(f"No {suffix} addresses available in pool. Pool size: {self.count_available(suffix)}")
                
                address_id, public_key, private_key, created_at = row
                
                # Mark as used
                cursor.execute('''
                    UPDATE lock_addresses 
                    SET used = TRUE, used_at = ? 
                    WHERE id = ?
                ''', (datetime.now().isoformat(), address_id))
                
                conn.commit()
                conn.close()
                
                # Recreate keypair from stored private key
                private_key_bytes = base58.b58decode(private_key)
                keypair = SoldersKeypair.from_bytes(private_key_bytes)
                
                # Verify the keypair matches
                if str(keypair.pubkey()) != public_key:
                    raise Exception(f"Keypair mismatch for address {public_key}")
                
                logger.info(f"Retrieved {suffix} address from pool: {public_key}")
                
                return {
                    'keypair': keypair,
                    'public_key': public_key,
                    'private_key': private_key,
                    'address_id': address_id,
                    'created_at': created_at
                }
                
            except Exception as e:
                logger.error(f"Get next address failed: {e}")
                raise
    
    def generate_lock_addresses(self, count: int, suffix: str = "LOCK") -> int:
        """Generate and store multiple LOCK addresses"""
        generated = 0
        start_time = time.time()
        total_attempts = 0
        
        logger.info(f"Generating {count} {suffix} addresses...")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            while generated < count and self.generation_active:
                batch_start = time.time()
                batch_attempts = 0
                
                # Generate in batches for better performance
                batch_size = min(10, count - generated)
                batch_generated = 0
                
                while batch_generated < batch_size:
                    # Generate keypair
                    keypair = SoldersKeypair()
                    public_key = str(keypair.pubkey())
                    batch_attempts += 1
                    total_attempts += 1
                    
                    # Check if ends with target suffix
                    if public_key.endswith(suffix):
                        private_key = base58.b58encode(bytes(keypair)).decode()
                        generation_time = time.time() - batch_start
                        
                        try:
                            # Store in database
                            cursor.execute('''
                                INSERT INTO lock_addresses 
                                (public_key, private_key, suffix, created_at, generation_attempts, generation_time_seconds) 
                                VALUES (?, ?, ?, ?, ?, ?)
                            ''', (
                                public_key, 
                                private_key, 
                                suffix, 
                                datetime.now().isoformat(),
                                batch_attempts,
                                generation_time
                            ))
                            
                            batch_generated += 1
                            generated += 1
                            
                        except sqlite3.IntegrityError:
                            # Duplicate address (extremely rare), skip
                            logger.warning(f"Duplicate address generated: {public_key}")
                            continue
                
                # Commit batch
                conn.commit()
                
                # Progress logging
                if generated % 5 == 0 or generated == count:
                    elapsed = time.time() - start_time
                    rate = total_attempts / elapsed if elapsed > 0 else 0
                    avg_attempts_per_address = total_attempts / generated if generated > 0 else 0
                    
                    logger.info(f"Generated {generated}/{count} {suffix} addresses "
                              f"({rate:,.0f} attempts/sec, avg {avg_attempts_per_address:,.0f} attempts per address)")
                
                # Allow thread interruption
                if not self.generation_active:
                    break
            
            conn.close()
            
            elapsed = time.time() - start_time
            logger.info(f"Generation complete: {generated} {suffix} addresses in {elapsed:.1f}s ({total_attempts:,} total attempts)")
            
            # Update metadata
            self._update_metadata("last_generation", {
                "timestamp": datetime.now().isoformat(),
                "generated": generated,
                "total_attempts": total_attempts,
                "duration_seconds": elapsed,
                "suffix": suffix
            })
            
            return generated
            
        except Exception as e:
            logger.error(f"Generation failed after {generated} addresses: {e}")
            return generated
    
    def start_background_generation(self, suffix: str = "LOCK"):
        """Start background thread to maintain pool"""
        if self.generation_active:
            logger.info("Background generation already active")
            return
        
        self.generation_active = True
        self.generation_thread = threading.Thread(
            target=self._background_generator, 
            args=(suffix,), 
            daemon=True,
            name=f"LockPool-{suffix}"
        )
        self.generation_thread.start()
        
        logger.info(f"Background generation started for {suffix} addresses")
    
    def stop_background_generation(self):
        """Stop background generation gracefully"""
        if not self.generation_active:
            return
            
        logger.info("Stopping background generation...")
        self.generation_active = False
        
        if self.generation_thread and self.generation_thread.is_alive():
            self.generation_thread.join(timeout=10)
            if self.generation_thread.is_alive():
                logger.warning("Background generation thread did not stop cleanly")
            else:
                logger.info("Background generation stopped successfully")
    
    def _background_generator(self, suffix: str):
        """Background thread to maintain pool size"""
        logger.info(f"Background generator started for {suffix}")
        
        while self.generation_active:
            try:
                available = self.count_available(suffix)
                min_threshold = max(10, self.target_pool_size // 4)  # 25% or minimum 10
                
                if available < min_threshold:
                    needed = self.target_pool_size - available
                    logger.info(f"Pool low ({available}/{self.target_pool_size}), generating {needed} {suffix} addresses...")
                    
                    generated = self.generate_lock_addresses(needed, suffix)
                    
                    if generated > 0:
                        logger.info(f"Background generation added {generated} {suffix} addresses")
                    else:
                        logger.warning("Background generation failed to add addresses")
                
                # Check every 5 minutes
                for _ in range(300):  # 5 minutes in 1-second intervals
                    if not self.generation_active:
                        break
                    time.sleep(1)
                
            except Exception as e:
                logger.error(f"Background generation error: {e}")
                # Wait 2 minutes before retry on error
                for _ in range(120):
                    if not self.generation_active:
                        break
                    time.sleep(1)
        
        logger.info(f"Background generator stopped for {suffix}")
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """Get comprehensive pool statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Basic counts
                cursor.execute("SELECT COUNT(*) FROM lock_addresses")
                total = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM lock_addresses WHERE used = FALSE")
                available = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM lock_addresses WHERE used = TRUE")
                used = cursor.fetchone()[0]
                
                # By suffix breakdown
                cursor.execute("""
                    SELECT suffix, 
                           COUNT(*) as total, 
                           SUM(CASE WHEN used = FALSE THEN 1 ELSE 0 END) as available,
                           AVG(generation_attempts) as avg_attempts,
                           AVG(generation_time_seconds) as avg_time
                    FROM lock_addresses 
                    GROUP BY suffix
                """)
                
                by_suffix = {}
                for row in cursor.fetchall():
                    suffix, suffix_total, suffix_available, avg_attempts, avg_time = row
                    by_suffix[suffix] = {
                        'total': suffix_total,
                        'available': suffix_available,
                        'used': suffix_total - suffix_available,
                        'avg_generation_attempts': round(avg_attempts or 0, 1),
                        'avg_generation_time_seconds': round(avg_time or 0, 2)
                    }
                
                # Recent activity (last 24 hours)
                yesterday = (datetime.now() - timedelta(days=1)).isoformat()
                cursor.execute("""
                    SELECT COUNT(*) FROM lock_addresses 
                    WHERE created_at > ? OR used_at > ?
                """, (yesterday, yesterday))
                recent_activity = cursor.fetchone()[0]
                
                # Pool health
                health_status = "healthy"
                if available == 0:
                    health_status = "empty"
                elif available < self.target_pool_size // 4:
                    health_status = "low"
                elif available < self.target_pool_size // 2:
                    health_status = "medium"
                
                return {
                    'total': total,
                    'available': available,
                    'used': used,
                    'by_suffix': by_suffix,
                    'generation_active': self.generation_active,
                    'target_size': self.target_pool_size,
                    'health_status': health_status,
                    'recent_activity_24h': recent_activity,
                    'database_path': self.db_path,
                    'last_updated': datetime.now().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Get stats failed: {e}")
            return {
                'error': str(e),
                'available': 0,
                'generation_active': self.generation_active
            }
    
    def _update_metadata(self, key: str, value: Any):
        """Update metadata in database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT OR REPLACE INTO pool_metadata (key, value, updated_at)
                    VALUES (?, ?, ?)
                ''', (key, json.dumps(value), datetime.now().isoformat()))
                
        except Exception as e:
            logger.error(f"Metadata update failed: {e}")
    
    def cleanup_old_used_addresses(self, days_old: int = 7):
        """Clean up old used addresses to keep database size manageable"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days_old)).isoformat()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    DELETE FROM lock_addresses 
                    WHERE used = TRUE AND used_at < ?
                """, (cutoff_date,))
                
                deleted = cursor.rowcount
                logger.info(f"Cleaned up {deleted} old used addresses (older than {days_old} days)")
                
                return deleted
                
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            return 0
    
    def export_addresses(self, suffix: str = "LOCK", used_only: bool = False) -> List[Dict]:
        """Export addresses for backup or analysis"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                query = "SELECT public_key, private_key, suffix, created_at, used, used_at FROM lock_addresses WHERE suffix = ?"
                params = [suffix]
                
                if used_only:
                    query += " AND used = TRUE"
                
                cursor.execute(query, params)
                
                addresses = []
                for row in cursor.fetchall():
                    public_key, private_key, suffix, created_at, used, used_at = row
                    addresses.append({
                        'public_key': public_key,
                        'private_key': private_key,
                        'suffix': suffix,
                        'created_at': created_at,
                        'used': bool(used),
                        'used_at': used_at
                    })
                
                logger.info(f"Exported {len(addresses)} {suffix} addresses")
                return addresses
                
        except Exception as e:
            logger.error(f"Export failed: {e}")
            return []
    
    def __del__(self):
        """Cleanup when object is destroyed"""
        self.stop_background_generation()

def test_pool():
    """Test the address pool functionality"""
    print("Testing LOCK Address Pool...")
    
    # Use test database
    test_db = "test_lock_pool.db"
    if os.path.exists(test_db):
        os.remove(test_db)
    
    pool = LockAddressPool(test_db, target_pool_size=5)
    
    try:
        # Test generation
        print("Generating 3 LOCK addresses...")
        generated = pool.generate_lock_addresses(3)
        print(f"Generated: {generated}")
        
        # Test stats
        stats = pool.get_pool_stats()
        print(f"Pool stats: {stats}")
        
        # Test getting address
        print("Getting address from pool...")
        address_data = pool.get_next_address()
        print(f"Got address: {address_data['public_key']}")
        print(f"Ends with LOCK: {address_data['public_key'].endswith('LOCK')}")
        
        # Test stats after use
        stats = pool.get_pool_stats()
        print(f"Stats after use: Available={stats['available']}, Used={stats['used']}")
        
        # Test background generation
        print("Testing background generation...")
        pool.start_background_generation()
        time.sleep(2)  # Let it check pool status
        pool.stop_background_generation()
        
        print("Test completed successfully!")
        
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        if os.path.exists(test_db):
            os.remove(test_db)
            print("Test database cleaned up")

if __name__ == "__main__":
    # Enable logging for testing
    logging.basicConfig(level=logging.INFO)
    test_pool()