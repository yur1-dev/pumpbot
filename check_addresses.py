# check_used_addresses.py
import sqlite3

def check_used_addresses():
    conn = sqlite3.connect("lock_addresses.db")
    cursor = conn.cursor()
    
    # Get addresses that were actually used for token creation
    cursor.execute("""
        SELECT public_key, suffix, used_at, generation_attempts 
        FROM addresses 
        WHERE used_at IS NOT NULL 
        ORDER BY used_at DESC 
        LIMIT 10
    """)
    
    used_addresses = cursor.fetchall()
    
    print(f"Addresses actually used for token creation ({len(used_addresses)}):")
    print("=" * 60)
    
    if not used_addresses:
        print("No addresses have been used for token creation yet.")
        print("This means tokens were either:")
        print("1. Generated in real-time (not from pool)")
        print("2. Creation failed before using pool address")
        return
    
    for addr, suffix, used_at, attempts in used_addresses:
        print(f"Address: {addr}")
        print(f"Ends with: {addr[-4:]}")
        print(f"Used at: {used_at}")
        print(f"Generation attempts: {attempts:,}")
        print(f"Solscan: https://solscan.io/token/{addr}")
        print("-" * 50)
    
    conn.close()

check_used_addresses()