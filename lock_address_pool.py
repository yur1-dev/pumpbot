# lock_address_pool.py - FAST VERSION (All Case Variations)
"""
OPTIMIZED LOCK Address Pool - Accepts ALL case variations for 16x faster generation!
Generates: LOCK, LOCk, LOck, LoCK, LoCk, Lock, lOCK, lOCk, lOck, loCK, loCk, lock, etc.
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
        self.stop_generation = False
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
            
            # Connect with WAL mode for better performance
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=10000")
            
            # Create table if it doesn't exist
            conn.execute("""
                CREATE TABLE IF NOT EXISTS addresses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    public_key TEXT UNIQUE NOT NULL,
                    private_key_bytes BLOB NOT NULL,
                    suffix TEXT NOT NULL,
                    actual_suffix TEXT NOT NULL,
                    is_available INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    used_at TIMESTAMP NULL,
                    generation_attempts INTEGER DEFAULT 1,
                    generation_time_seconds REAL DEFAULT 0
                )
            """)
            
            # Create indexes for better performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_available ON addresses(is_available)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_suffix ON addresses(suffix)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_actual_suffix ON addresses(actual_suffix)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON addresses(created_at)")
            
            conn.commit()
            conn.close()
            
            logger.info(f"Database initialized successfully: {self.db_path}")
            
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
    
    def _generate_single_lock_address(self, suffix: str = "LOCK") -> Optional[Dict[str, Any]]:
        """
        OPTIMIZED: Generate address ending with ANY case variation of 'lock' - 16x faster!
        Accepts: LOCK, LOCk, LOck, LoCK, LoCk, Lock, lOCK, lOCk, lOck, loCK, loCk, lock, etc.
        """
        attempts = 0
        start_time = time.time()
        
        try:
            while attempts < 10000000:  # Reasonable limit
                attempts += 1
                
                # Generate new keypair
                keypair = SoldersKeypair()
                public_key = str(keypair.pubkey())
                
                # OPTIMIZED: Accept ANY case variation of "lock" - 16x faster!
                if public_key.upper().endswith("LOCK"):
                    generation_time = time.time() - start_time
                    actual_suffix = public_key[-4:]  # Store the actual case variation found
                    
                    logger.info(f"SUCCESS: Generated address ending with '{actual_suffix}' (case variation of LOCK)")
                    
                    return {
                        'keypair': keypair,
                        'public_key': public_key,
                        'private_key_bytes': bytes(keypair),
                        'suffix': suffix,
                        'actual_suffix': actual_suffix,  # Store actual case found
                        'attempts': attempts,
                        'generation_time': generation_time
                    }
                
                # Progress logging for long generation (should be much faster now!)
                if attempts % 100000 == 0:
                    elapsed_minutes = (time.time() - start_time) / 60
                    logger.info(f"FAST lock generation progress: {attempts:,} attempts, {elapsed_minutes:.1f}min elapsed")
                    
                    # Check if we should stop
                    if self.stop_generation:
                        logger.info("Lock generation stopped by request")
                        return None
            
            logger.warning(f"Lock address generation failed after {attempts:,} attempts")
            return None
            
        except Exception as e:
            logger.error(f"Error during lock address generation: {e}")
            return None
    
    def generate_lock_addresses(self, count: int, suffix: str = "LOCK") -> int:
        """Generate multiple lock addresses (any case) and store in database"""
        generated_count = 0
        
        logger.info(f"Starting FAST generation of {count} addresses with ANY case variation of '{suffix}'")
        logger.info(f"Will accept: LOCK, LOCk, LOck, LoCK, LoCk, Lock, lOCK, lOCk, lOck, loCK, loCk, lock, etc.")
        
        try:
            for i in range(count):
                if self.stop_generation:
                    logger.info("Generation stopped by request")
                    break
                
                logger.info(f"Generating lock address {i + 1}/{count} (any case variation)...")
                
                address_data = self._generate_single_lock_address(suffix)
                
                if address_data:
                    # Store in database
                    success = self._store_address(address_data)
                    if success:
                        generated_count += 1
                        logger.info(f"Generated and stored lock address: {address_data['public_key']}")
                        logger.info(f"Actual suffix: '{address_data['actual_suffix']}'")
                        logger.info(f"Took {address_data['attempts']:,} attempts, {address_data['generation_time']:.2f} seconds")
                    else:
                        logger.error("Failed to store generated address")
                else:
                    logger.error(f"Failed to generate address {i + 1}")
            
            logger.info(f"FAST generation complete: {generated_count}/{count} lock addresses generated")
            return generated_count
            
        except Exception as e:
            logger.error(f"Error during batch generation: {e}")
            return generated_count
    
    def _store_address(self, address_data: Dict[str, Any]) -> bool:
        """Store generated address in database with actual case variation"""
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30)
                conn.execute("""
                    INSERT INTO addresses 
                    (public_key, private_key_bytes, suffix, actual_suffix, generation_attempts, generation_time_seconds)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    address_data['public_key'],
                    address_data['private_key_bytes'],
                    address_data['suffix'],
                    address_data['actual_suffix'],
                    address_data['attempts'],
                    address_data['generation_time']
                ))
                conn.commit()
                conn.close()
                return True
                
        except sqlite3.IntegrityError:
            logger.warning(f"Address already exists in database: {address_data['public_key']}")
            return False
        except Exception as e:
            logger.error(f"Database storage error: {e}")
            return False
    
    def get_next_address(self, suffix: str = "LOCK") -> Optional[Dict[str, Any]]:
        """Get next available address from pool (any case variation)"""
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_path, timeout=30)
                cursor = conn.cursor()
                
                # Get oldest available address with any case variation of the suffix
                cursor.execute("""
                    SELECT id, public_key, private_key_bytes, actual_suffix, created_at, generation_attempts, generation_time_seconds
                    FROM addresses 
                    WHERE is_available = 1 AND UPPER(actual_suffix) = UPPER(?)
                    ORDER BY created_at ASC
                    LIMIT 1
                """, (suffix,))
                
                row = cursor.fetchone()
                
                if row:
                    addr_id, public_key, private_key_bytes, actual_suffix, created_at, attempts, gen_time = row
                    
                    # Validate it's a lock variation
                    if not public_key.upper().endswith("LOCK"):
                        logger.error(f"CRITICAL: Pool contains invalid address: {public_key}")
                        # Mark as used to remove from pool
                        cursor.execute("""
                            UPDATE addresses 
                            SET is_available = 0, used_at = CURRENT_TIMESTAMP 
                            WHERE id = ?
                        """, (addr_id,))
                        conn.commit()
                        conn.close()
                        
                        # Try to get next address
                        return self.get_next_address(suffix)
                    
                    # Mark as used
                    cursor.execute("""
                        UPDATE addresses 
                        SET is_available = 0, used_at = CURRENT_TIMESTAMP 
                        WHERE id = ?
                    """, (addr_id,))
                    
                    conn.commit()
                    conn.close()
                    
                    # Recreate keypair from stored bytes
                    keypair = SoldersKeypair.from_bytes(private_key_bytes)
                    
                    logger.info(f"Successfully retrieved lock address: {public_key} (ends with '{actual_suffix}')")
                    
                    return {
                        'keypair': keypair,
                        'public_key': public_key,
                        'actual_suffix': actual_suffix,
                        'created_at': created_at,
                        'generation_attempts': attempts,
                        'generation_time_seconds': gen_time
                    }
                else:
                    conn.close()
                    logger.warning(f"No available addresses with lock variation in pool")
                    return None
                    
        except Exception as e:
            logger.error(f"Error retrieving address from pool: {e}")
            return None
    
    def count_available(self, suffix: str = None) -> int:
        """Count available addresses in pool"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()
            
            if suffix:
                cursor.execute("SELECT COUNT(*) FROM addresses WHERE is_available = 1 AND UPPER(actual_suffix) = UPPER(?)", (suffix,))
            else:
                cursor.execute("SELECT COUNT(*) FROM addresses WHERE is_available = 1")
                
            count = cursor.fetchone()[0]
            conn.close()
            return count
            
        except Exception as e:
            logger.error(f"Error counting available addresses: {e}")
            return 0
    
    def count_total(self, suffix: str = None) -> int:
        """Count total addresses in pool"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()
            
            if suffix:
                cursor.execute("SELECT COUNT(*) FROM addresses WHERE UPPER(actual_suffix) = UPPER(?)", (suffix,))
            else:
                cursor.execute("SELECT COUNT(*) FROM addresses")
                
            count = cursor.fetchone()[0]
            conn.close()
            return count
            
        except Exception as e:
            logger.error(f"Error counting total addresses: {e}")
            return 0
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """Get comprehensive pool statistics"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()
            
            stats = {}
            
            # Basic counts
            cursor.execute("SELECT COUNT(*) FROM addresses")
            stats['total'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM addresses WHERE is_available = 1")
            stats['available'] = cursor.fetchone()[0]
            
            stats['used'] = stats['total'] - stats['available']
            stats['target_size'] = self.target_pool_size
            stats['generation_active'] = self.generation_active
            
            # Case variation breakdown
            cursor.execute("""
                SELECT actual_suffix, 
                       COUNT(*) as count,
                       SUM(CASE WHEN is_available = 1 THEN 1 ELSE 0 END) as available
                FROM addresses 
                WHERE UPPER(actual_suffix) = 'LOCK'
                GROUP BY actual_suffix
                ORDER BY count DESC
            """)
            
            case_variations = {}
            for actual_suffix, count, available in cursor.fetchall():
                case_variations[actual_suffix] = {
                    'total': count,
                    'available': available,
                    'used': count - available
                }
            
            stats['case_variations'] = case_variations
            
            # Health status
            if stats['available'] == 0:
                stats['health_status'] = 'critical'
            elif stats['available'] < self.target_pool_size * 0.25:
                stats['health_status'] = 'low'
            elif stats['available'] >= self.target_pool_size:
                stats['health_status'] = 'excellent'
            else:
                stats['health_status'] = 'good'
            
            # Generation performance
            cursor.execute("""
                SELECT AVG(generation_attempts) as avg_attempts,
                       AVG(generation_time_seconds) as avg_time,
                       MIN(generation_attempts) as min_attempts,
                       MAX(generation_attempts) as max_attempts
                FROM addresses 
                WHERE UPPER(actual_suffix) = 'LOCK'
            """)
            
            perf_row = cursor.fetchone()
            if perf_row and perf_row[0]:
                stats['performance'] = {
                    'avg_attempts': round(perf_row[0], 0),
                    'avg_time_seconds': round(perf_row[1] or 0, 2),
                    'min_attempts': perf_row[2] or 0,
                    'max_attempts': perf_row[3] or 0
                }
            
            conn.close()
            return stats
            
        except Exception as e:
            logger.error(f"Error getting pool stats: {e}")
            return {
                'total': 0,
                'available': 0,
                'used': 0,
                'target_size': self.target_pool_size,
                'generation_active': False,
                'health_status': 'error'
            }
    
    def start_background_generation(self, suffix: str = "LOCK"):
        """Start background thread to maintain pool"""
        if self.generation_active:
            logger.info("Background generation already active")
            return
        
        self.generation_active = True
        self.stop_generation = False
        
        def generation_worker():
            logger.info(f"FAST background generation started for ANY case of '{suffix}'")
            
            while self.generation_active and not self.stop_generation:
                try:
                    available_count = self.count_available(suffix)
                    
                    if available_count < self.target_pool_size:
                        needed = self.target_pool_size - available_count
                        logger.info(f"Generating {needed} FAST lock addresses to reach target")
                        
                        # Generate in larger batches since it's faster now
                        batch_size = min(10, needed)  # Increased from 5 to 10
                        generated = self.generate_lock_addresses(batch_size, suffix)
                        
                        if generated > 0:
                            logger.info(f"FAST background generation: added {generated} lock addresses")
                    else:
                        logger.debug("Pool target reached, background generation sleeping")
                    
                    # Sleep between checks
                    for _ in range(30):  # 30 second sleep, but check stop flag frequently
                        if self.stop_generation:
                            break
                        time.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Background generation error: {e}")
                    time.sleep(10)  # Wait before retry
            
            logger.info("Background generation stopped")
            self.generation_active = False
        
        self.generation_thread = threading.Thread(target=generation_worker, daemon=True)
        self.generation_thread.start()
        
        logger.info("FAST background generation thread started")
    
    def stop_background_generation(self):
        """Stop background generation"""
        if not self.generation_active:
            return
        
        logger.info("Stopping background generation...")
        self.stop_generation = True
        self.generation_active = False
        
        if self.generation_thread and self.generation_thread.is_alive():
            self.generation_thread.join(timeout=5)
        
        logger.info("Background generation stopped")
    
    def get_case_variation_stats(self) -> Dict[str, int]:
        """Get statistics on which case variations have been generated"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT actual_suffix, COUNT(*) as count
                FROM addresses 
                WHERE UPPER(actual_suffix) = 'LOCK'
                GROUP BY actual_suffix
                ORDER BY count DESC
            """)
            
            variations = {}
            for actual_suffix, count in cursor.fetchall():
                variations[actual_suffix] = count
            
            conn.close()
            return variations
            
        except Exception as e:
            logger.error(f"Error getting case variation stats: {e}")
            return {}


def test_pool_functionality():
    """Test the FAST pool functionality with case variations"""
    print("Testing FAST Lock Address Pool (All Case Variations)...")
    
    # Initialize pool
    pool = LockAddressPool(db_path="test_fast_lock_addresses.db", target_pool_size=2)
    
    # Generate a couple addresses for testing
    print("Generating 2 test lock addresses (any case variation - FAST!)...")
    start_time = time.time()
    generated = pool.generate_lock_addresses(2, "LOCK")
    generation_time = time.time() - start_time
    
    print(f"Generated {generated} addresses in {generation_time:.2f} seconds")
    print(f"Average: {generation_time/max(generated,1):.2f} seconds per address (16x faster!)")
    
    # Check stats
    stats = pool.get_pool_stats()
    print(f"Pool stats: {stats}")
    
    # Show case variations found
    variations = pool.get_case_variation_stats()
    if variations:
        print("Case variations generated:")
        for case_variant, count in variations.items():
            print(f"  '{case_variant}': {count} addresses")
    
    # Get an address
    address = pool.get_next_address("LOCK")
    if address:
        public_key = address['public_key']
        actual_case = address.get('actual_suffix', public_key[-4:])
        print(f"Retrieved address: {public_key}")
        print(f"Actual case ending: '{actual_case}'")
        print(f"Accepts any lock variation: {public_key.upper().endswith('LOCK')}")
    else:
        print("No addresses available")
    
    # Cleanup test database
    if os.path.exists("test_fast_lock_addresses.db"):
        os.remove("test_fast_lock_addresses.db")
    
    print("FAST test completed!")


if __name__ == "__main__":
    # Run test when executed directly
    test_pool_functionality()