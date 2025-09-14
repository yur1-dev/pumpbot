#!/usr/bin/env python3
"""
Fix LOCK address database schema and search for LOCK addresses
"""
import sqlite3
import os
from datetime import datetime

def fix_database_schema(db_path="lock_addresses.db"):
    """Fix the database schema by adding missing columns"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get current table info
        cursor.execute("PRAGMA table_info(lock_addresses)")
        columns = [column[1] for column in cursor.fetchall()]
        print(f"Current columns: {columns}")
        
        # Add missing columns if they don't exist
        if 'used' not in columns:
            print("Adding 'used' column...")
            cursor.execute("ALTER TABLE lock_addresses ADD COLUMN used BOOLEAN DEFAULT 0")
            
        if 'generation_time' not in columns:
            print("Adding 'generation_time' column...")
            cursor.execute("ALTER TABLE lock_addresses ADD COLUMN generation_time REAL DEFAULT 0")
            
        if 'attempts' not in columns:
            print("Adding 'attempts' column...")
            cursor.execute("ALTER TABLE lock_addresses ADD COLUMN attempts INTEGER DEFAULT 0")
            
        conn.commit()
        print("✅ Database schema fixed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error fixing schema: {e}")
        return False
    finally:
        conn.close()

def check_lock_addresses(db_path="lock_addresses.db"):
    """Check for addresses ending with LOCK"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all addresses ending with LOCK
        cursor.execute("""
            SELECT public_key, private_key, created_at, 
                   CASE WHEN used IS NULL THEN 0 ELSE used END as used_status
            FROM lock_addresses 
            WHERE public_key LIKE '%LOCK'
            ORDER BY created_at DESC
        """)
        
        lock_addresses = cursor.fetchall()
        
        print("🔒 ADDRESSES ENDING WITH 'LOCK':")
        print("=" * 80)
        
        if not lock_addresses:
            print("❌ No addresses ending with 'LOCK' found in database")
            return []
            
        available_count = 0
        used_count = 0
        
        for i, (public_key, private_key, created_at, used_status) in enumerate(lock_addresses, 1):
            status = "🔴 USED" if used_status else "🟢 AVAILABLE"
            if used_status:
                used_count += 1
            else:
                available_count += 1
                
            print(f"\n{i:2d}. {public_key}")
            print(f"    Status: {status}")
            print(f"    Created: {created_at}")
            print(f"    Private Key: {private_key[:20]}...{private_key[-10:]}")
        
        print("\n" + "=" * 80)
        print(f"📊 SUMMARY:")
        print(f"   Total LOCK addresses: {len(lock_addresses)}")
        print(f"   Available: {available_count}")
        print(f"   Used: {used_count}")
        
        return lock_addresses
        
    except Exception as e:
        print(f"❌ Error checking addresses: {e}")
        return []
    finally:
        conn.close()

def search_specific_lock_address(search_term, db_path="lock_addresses.db"):
    """Search for specific LOCK address containing search term"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT public_key, private_key, created_at,
                   CASE WHEN used IS NULL THEN 0 ELSE used END as used_status
            FROM lock_addresses 
            WHERE public_key LIKE ? AND public_key LIKE '%LOCK'
            ORDER BY created_at DESC
        """, (f'%{search_term}%',))
        
        results = cursor.fetchall()
        
        if results:
            print(f"🔍 Found {len(results)} LOCK addresses containing '{search_term}':")
            for public_key, private_key, created_at, used_status in results:
                status = "🔴 USED" if used_status else "🟢 AVAILABLE"
                print(f"\n🔒 {public_key}")
                print(f"   Status: {status}")
                print(f"   Created: {created_at}")
                print(f"   Private Key: {private_key}")
        else:
            print(f"❌ No LOCK addresses found containing '{search_term}'")
        
        return results
        
    except Exception as e:
        print(f"❌ Error searching: {e}")
        return []
    finally:
        conn.close()

def get_database_info(db_path="lock_addresses.db"):
    """Get general database information"""
    try:
        if not os.path.exists(db_path):
            print(f"❌ Database file '{db_path}' does not exist")
            return
            
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get total count
        cursor.execute("SELECT COUNT(*) FROM lock_addresses")
        total = cursor.fetchone()[0]
        
        # Get LOCK addresses count
        cursor.execute("SELECT COUNT(*) FROM lock_addresses WHERE public_key LIKE '%LOCK'")
        lock_total = cursor.fetchone()[0]
        
        # Get available LOCK addresses
        cursor.execute("""
            SELECT COUNT(*) FROM lock_addresses 
            WHERE public_key LIKE '%LOCK' 
            AND (used IS NULL OR used = 0)
        """)
        lock_available = cursor.fetchone()[0]
        
        print("📋 DATABASE INFO:")
        print("=" * 40)
        print(f"📊 Total addresses: {total}")
        print(f"🔒 Total LOCK addresses: {lock_total}")
        print(f"🟢 Available LOCK addresses: {lock_available}")
        print(f"🔴 Used LOCK addresses: {lock_total - lock_available}")
        print(f"📁 Database file: {db_path}")
        print(f"💾 Database size: {os.path.getsize(db_path) / 1024:.1f} KB")
        
    except Exception as e:
        print(f"❌ Error getting database info: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    import sys
    
    print("🔧 LOCK ADDRESS DATABASE FIXER & CHECKER")
    print("=" * 50)
    
    db_path = "lock_addresses.db"
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "fix":
            print("\n🔧 Fixing database schema...")
            fix_database_schema(db_path)
            
        elif command == "info":
            print("\n📋 Database information...")
            get_database_info(db_path)
            
        elif command == "search" and len(sys.argv) > 2:
            search_term = sys.argv[2]
            print(f"\n🔍 Searching for addresses containing '{search_term}'...")
            search_specific_lock_address(search_term, db_path)
            
        elif command == "lock":
            print("\n🔒 LOCK addresses only...")
            check_lock_addresses(db_path, "LOCK")
            
        elif command == "lck":
            print("\n🔐 LCK addresses only...")
            check_lock_addresses(db_path, "LCK")
            
        elif command == "all":
            print("\n🔒 All LOCK/LCK addresses...")
            check_lock_addresses(db_path)
            
        elif command == "suffix" and len(sys.argv) > 2:
            suffix = sys.argv[2].upper()
            print(f"\n🔍 Addresses ending with '{suffix}'...")
            check_lock_addresses(db_path, suffix)
            
        else:
            print("❌ Invalid command")
            print("\nAvailable commands:")
            print("  fix     - Fix database schema")
            print("  info    - Show database info") 
            print("  lock    - Show LOCK addresses only")
            print("  lck     - Show LCK addresses only")
            print("  all     - Show all LOCK/LCK addresses")
            print("  search <term>  - Search for addresses containing term")
            print("  suffix <suffix> - Show addresses ending with specific suffix")
    else:
        # Default: fix schema then show all addresses
        print("\n🔧 Step 1: Fixing database schema...")
        if fix_database_schema(db_path):
            print("\n📋 Step 2: Database info...")
            get_database_info(db_path)
            print("\n🔒 Step 3: Checking LOCK/LCK addresses...")
            check_lock_addresses(db_path)
        
    print("\n" + "=" * 50)
    print("Usage examples:")
    print("  python fix_lock_database.py          # Fix schema and show all")
    print("  python fix_lock_database.py fix      # Fix schema only")
    print("  python fix_lock_database.py info     # Database info only")
    print("  python fix_lock_database.py lock     # Show LOCK addresses only")
    print("  python fix_lock_database.py lck      # Show LCK addresses only")
    print("  python fix_lock_database.py all      # Show all LOCK/LCK addresses")
    print("  python fix_lock_database.py search LCK  # Search for 'LCK'")
    print("  python fix_lock_database.py suffix PUMP # Show addresses ending with 'PUMP'")