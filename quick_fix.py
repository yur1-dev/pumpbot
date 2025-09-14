#!/usr/bin/env python3
"""
Quick fix - create a fresh LOCK address database with new name
"""

import os
import sys

def main():
    print("=== CREATING FRESH LOCK ADDRESS DATABASE ===")
    
    # Remove any existing lock_addresses files
    files_to_remove = [
        "lock_addresses.db",
        "lock_addresses.db-journal", 
        "lock_addresses.db-wal",
        "lock_addresses.db-shm"
    ]
    
    removed = []
    locked = []
    
    for filename in files_to_remove:
        if os.path.exists(filename):
            try:
                os.remove(filename)
                removed.append(filename)
                print(f"✅ Removed: {filename}")
            except Exception as e:
                locked.append(filename)
                print(f"🔒 Locked: {filename} - {e}")
    
    if locked:
        print(f"\n⚠️  {len(locked)} files are locked by another process")
        print("Creating database with new name to avoid conflicts...")
        
        # Use a fresh database name
        new_db_name = "lock_addresses_fresh.db"
    else:
        new_db_name = "lock_addresses.db"
        print("All old files removed successfully")
    
    # Test creating the database
    try:
        from lock_address_pool import LockAddressPool
        
        print(f"\n🏗️  Creating fresh database: {new_db_name}")
        pool = LockAddressPool(db_path=new_db_name, target_pool_size=10)
        
        # Test basic functionality
        stats = pool.get_pool_stats()
        print(f"✅ Database created successfully!")
        print(f"📊 Stats: Available={stats['available']}, Total={stats['total']}")
        
        # Update the populate script to use the new database name
        if new_db_name != "lock_addresses.db":
            print(f"\n📝 To use this database, run commands with the new name:")
            print(f"   python -c \"")
            print(f"from lock_address_pool import LockAddressPool")
            print(f"pool = LockAddressPool('{new_db_name}', 100)")
            print(f"print('Pool status:', pool.get_pool_stats())")
            print(f"generated = pool.generate_lock_addresses(5)")
            print(f"print(f'Generated {{generated}} LOCK addresses')")
            print(f"print('Updated stats:', pool.get_pool_stats())")
            print(f"\"")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to create database: {e}")
        return False

if __name__ == "__main__":
    success = main()
    if success:
        print("\n🎉 SUCCESS: Fresh LOCK address database ready!")
        print("\nNext steps:")
        print("1. Generate some LOCK addresses")
        print("2. Test the pool functionality")
        print("3. Use in your bot")
    else:
        print("\n❌ FAILED: Could not create database")
        print("Check that lock_address_pool.py is properly updated")