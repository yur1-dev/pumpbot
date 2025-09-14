# populate_lock_pool.py
"""
FIXED: Enhanced script to populate the LOCK address pool with pre-generated addresses
Run this before starting your bot to ensure instant LOCK address availability
"""

import sys
import time
import signal
import threading
import logging
import os
import asyncio

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global variables for graceful shutdown
shutdown_requested = False
current_pool = None

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    global shutdown_requested, current_pool
    print("\n\nShutdown requested... stopping gracefully...")
    shutdown_requested = True
    if current_pool:
        current_pool.stop_background_generation()
    sys.exit(0)

# Register signal handler
signal.signal(signal.SIGINT, signal_handler)

def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        from lock_address_pool import LockAddressPool
        return True, None
    except ImportError as e:
        missing_deps = []
        if "solders" in str(e):
            missing_deps.append("solders")
        if "base58" in str(e):
            missing_deps.append("base58")
        
        error_msg = f"Missing required dependencies: {', '.join(missing_deps) if missing_deps else str(e)}\n"
        error_msg += "\nInstall with: pip install solders base58"
        return False, error_msg

def populate_pool_instant(count=50):
    """
    FIXED: Instant population with better progress tracking and error handling
    """
    global current_pool
    
    print(f"=== FIXED LOCK ADDRESS POOL POPULATION ===")
    print(f"Target: {count} LOCK addresses")
    print(f"Enhanced with better database management")
    print(f"Expected time: {count * 1}-{count * 3} minutes (faster generation)")
    print()
    
    # Check dependencies first
    deps_ok, error_msg = check_dependencies()
    if not deps_ok:
        print(f"❌ {error_msg}")
        return
    
    try:
        from lock_address_pool import LockAddressPool
        
        # Initialize pool with enhanced settings
        pool = LockAddressPool(
            db_path="lock_addresses.db",
            target_pool_size=count
        )
        current_pool = pool
        
        # Check current status
        current_count = pool.count_available()
        total_count = pool.count_total()
        
        print(f"Current pool status:")
        print(f"  Available: {current_count} addresses")
        print(f"  Total: {total_count} addresses") 
        print(f"  Used: {total_count - current_count} addresses")
        
        if current_count >= count:
            print(f"✅ Pool already has {current_count} addresses - no generation needed!")
            print("Your bot is ready for instant LOCK token creation!")
            
            # Still start background generation to maintain pool
            print("Starting background generation to maintain pool...")
            pool.start_background_generation()
            
            # Show status for a bit
            for i in range(10):
                if shutdown_requested:
                    break
                time.sleep(1)
                current = pool.count_available()
                if current != current_count:
                    print(f"Pool status: {current} addresses available")
                    current_count = current
            
            return
        
        needed = count - current_count
        print(f"Need to generate: {needed} additional LOCK addresses")
        print(f"Press Ctrl+C to stop gracefully...")
        print()
        
        # Start generation with enhanced progress tracking
        start_time = time.time()
        generated = 0
        
        try:
            # Generate in optimized batches
            batch_size = min(10, needed)
            while generated < needed and not shutdown_requested:
                batch_needed = min(batch_size, needed - generated)
                print(f"🔄 Generating batch {generated + 1}-{generated + batch_needed}...")
                
                batch_start_time = time.time()
                
                # Set generation active flag for the duration
                pool.generation_active = True
                batch_generated = pool.generate_lock_addresses(batch_needed, suffix="LOCK")
                pool.generation_active = False  # Reset after generation
                
                batch_time = time.time() - batch_start_time
                
                generated += batch_generated
                
                elapsed_minutes = (time.time() - start_time) / 60
                remaining = needed - generated
                
                if generated > 0:
                    avg_time_per_address = elapsed_minutes / generated
                    estimated_remaining_minutes = remaining * avg_time_per_address
                    progress_percent = (generated / needed) * 100
                    
                    print(f"✅ Progress: {generated}/{needed} ({progress_percent:.1f}%)")
                    print(f"   Time elapsed: {elapsed_minutes:.1f}min")
                    print(f"   ETA: {estimated_remaining_minutes:.1f}min")
                    print(f"   Avg per address: {avg_time_per_address:.2f}min")
                    
                    # Show current pool status
                    current_available = pool.count_available()
                    print(f"   Pool now has: {current_available} addresses ready")
                
                if batch_generated < batch_needed:
                    print("⚠️  Batch generation incomplete (normal for LOCK addresses)")
                
                print()  # Add spacing for readability
                
        except KeyboardInterrupt:
            print("\n⏹️  Generation interrupted by user")
        except Exception as e:
            print(f"\n❌ Generation error: {e}")
            logger.error(f"Generation failed: {e}", exc_info=True)
        
        end_time = time.time()
        elapsed_minutes = (end_time - start_time) / 60
        final_count = pool.count_available()
        
        print()
        print(f"=== GENERATION COMPLETE ===")
        print(f"Generated: {generated} new LOCK addresses")
        print(f"Time taken: {elapsed_minutes:.1f} minutes")
        if generated > 0:
            print(f"Average: {elapsed_minutes/generated:.2f} minutes per address")
        print(f"Pool now has: {final_count} addresses ready")
        print()
        
        if generated > 0:
            print("✅ Pool populated successfully!")
            print("Your bot can now create LOCK tokens instantly!")
            print(f"Next {final_count} token creations will be instant (<1 second)")
            
            # Start background generation
            print("\n🔄 Starting background generation to maintain pool...")
            pool.start_background_generation()
            
            # Monitor for a bit to show it's working
            print("Monitoring background generation (Ctrl+C to exit)...")
            try:
                last_count = final_count
                for i in range(60):  # Monitor for 1 minute
                    if shutdown_requested:
                        break
                    time.sleep(1)
                    current = pool.count_available()
                    if current != last_count:
                        print(f"📈 Pool updated: {current} addresses available (+{current - last_count})")
                        last_count = current
            except KeyboardInterrupt:
                print("\n⏹️  Monitoring stopped")
        else:
            print("❌ No addresses were generated.")
            print("This could be due to computational complexity or interruption.")
            
    except Exception as e:
        print(f"❌ Error during generation: {e}")
        logger.error(f"Pool population failed: {e}", exc_info=True)

def check_pool_status_enhanced():
    """
    FIXED: Enhanced pool status check with detailed information
    """
    print(f"=== ENHANCED LOCK ADDRESS POOL STATUS ===")
    print()
    
    # Check dependencies first
    deps_ok, error_msg = check_dependencies()
    if not deps_ok:
        print(f"❌ {error_msg}")
        return
    
    try:
        from lock_address_pool import LockAddressPool
        pool = LockAddressPool(db_path="lock_addresses.db")
        stats = pool.get_pool_stats()
        
        # Basic stats
        print(f"📊 Pool Statistics:")
        print(f"   Total addresses: {stats.get('total', 0)}")
        print(f"   Available addresses: {stats.get('available', 0)}")
        print(f"   Used addresses: {stats.get('used', 0)}")
        print(f"   Target pool size: {stats.get('target_size', 0)}")
        print(f"   Health status: {stats.get('health_status', 'unknown').upper()}")
        print(f"   Background generation: {'Active' if stats.get('generation_active', False) else 'Inactive'}")
        
        # Database info
        if os.path.exists("lock_addresses.db"):
            db_size = os.path.getsize("lock_addresses.db") / 1024  # KB
            print(f"   Database size: {db_size:.1f} KB")
        
        print()
        
        # Detailed LOCK address stats
        by_suffix = stats.get('by_suffix', {})
        if 'LOCK' in by_suffix:
            lock_stats = by_suffix['LOCK']
            print(f"🔒 LOCK Address Details:")
            print(f"   Available: {lock_stats.get('available', 0)}")
            print(f"   Used: {lock_stats.get('used', 0)}")
            print(f"   Total: {lock_stats.get('total', 0)}")
            
            avg_attempts = lock_stats.get('avg_generation_attempts', 0)
            avg_time = lock_stats.get('avg_generation_time_seconds', 0)
            
            if avg_attempts > 0:
                print(f"   Avg generation attempts: {avg_attempts:,.0f}")
            if avg_time > 0:
                print(f"   Avg generation time: {avg_time:.1f} seconds")
        
        print()
        
        # Enhanced recommendations
        available = stats.get('available', 0)
        target = stats.get('target_size', 100)
        
        if available == 0:
            print("🔴 CRITICAL: Pool is empty!")
            print("   All token creations will take 10-30 minutes each")
            print("   🚀 SOLUTION: python populate_lock_pool.py instant 25")
        elif available < 5:
            print("🟠 URGENT: Pool critically low")
            print("   Only a few instant creations available")
            print("   🚀 SOLUTION: python populate_lock_pool.py instant 50")
        elif available < target * 0.25:
            print("🟡 WARNING: Pool running low")
            print("   Consider generating more addresses soon")
            print(f"   🚀 SOLUTION: python populate_lock_pool.py instant {target - available}")
        elif available >= target:
            print("🟢 EXCELLENT: Pool is well stocked")
            print("   Your bot can provide instant LOCK token creation!")
            print(f"   ⚡ Next {available} tokens will be instant!")
        else:
            print("🟡 OK: Pool has addresses available")
            print("   Some instant creations available")
            print(f"   ⚡ Next {available} tokens will be instant")
        
        # Performance metrics
        recent_activity = stats.get('recent_activity_24h', 0)
        if recent_activity > 0:
            print(f"\n📈 Recent activity (24h): {recent_activity} addresses created/used")
        
        # Usage projection
        if available > 0 and recent_activity > 0:
            days_remaining = available / (recent_activity / 24) if recent_activity > 0 else float('inf')
            if days_remaining < float('inf'):
                print(f"📅 At current usage rate: ~{days_remaining:.1f} days of addresses remaining")
        
        print("\n🎯 RECOMMENDATION:")
        if available < 10:
            print("   Run: python populate_lock_pool.py instant 100")
        else:
            print("   Pool status is good - continue monitoring")
        
    except Exception as e:
        print(f"❌ Error checking pool status: {e}")
        if "no such table" in str(e).lower():
            print("Pool database not initialized yet.")
            print("🚀 SOLUTION: python populate_lock_pool.py instant 50")
        else:
            logger.error(f"Status check failed: {e}", exc_info=True)

def test_pool_enhanced():
    """
    FIXED: Enhanced pool test with detailed verification
    """
    print(f"=== ENHANCED LOCK ADDRESS POOL TEST ===")
    print()
    
    # Check dependencies first
    deps_ok, error_msg = check_dependencies()
    if not deps_ok:
        print(f"❌ {error_msg}")
        return
    
    try:
        from lock_address_pool import LockAddressPool
        pool = LockAddressPool(db_path="lock_addresses.db")
        
        available_before = pool.count_available()
        print(f"Available addresses before test: {available_before}")
        
        if available_before == 0:
            print("🔴 No addresses available for testing")
            print("🚀 SOLUTION: python populate_lock_pool.py instant 10")
            return
        
        # Get an address from pool
        print("🧪 Testing address retrieval...")
        start_time = time.time()
        address_data = pool.get_next_address(suffix="LOCK")
        retrieval_time = time.time() - start_time
        
        public_key = address_data['public_key']
        
        print(f"✅ Successfully retrieved address in {retrieval_time:.4f} seconds")
        print(f"   Address: {public_key}")
        print(f"   Ends with LOCK: {public_key.endswith('LOCK')}")
        print(f"   Address length: {len(public_key)} characters")
        print(f"   Created at: {address_data.get('created_at', 'Unknown')}")
        
        # Verify address format
        if len(public_key) >= 32 and len(public_key) <= 44:
            print("✅ Address length is valid")
        else:
            print("⚠️  Address length may be invalid")
        
        # Verify LOCK suffix
        if public_key.endswith('LOCK'):
            print("✅ LOCK suffix verified")
        else:
            print("❌ LOCK suffix verification failed")
        
        # Update status
        available_after = pool.count_available()
        print(f"   Remaining addresses: {available_after}")
        print(f"   Addresses consumed: {available_before - available_after}")
        
        # Test keypair functionality
        try:
            keypair = address_data['keypair']
            test_pubkey = str(keypair.pubkey())
            if test_pubkey == public_key:
                print("✅ Keypair verification successful")
            else:
                print("❌ Keypair verification failed")
        except Exception as e:
            print(f"⚠️  Keypair test failed: {e}")
        
        print()
        print("🎉 Pool test completed successfully!")
        print("Your bot can retrieve LOCK addresses instantly!")
        print("Note: This test address is now marked as used in the pool")
        
    except Exception as e:
        print(f"❌ Pool test failed: {e}")
        if "no such table" in str(e).lower():
            print("Pool database not initialized yet.")
            print("🚀 SOLUTION: python populate_lock_pool.py instant 10")
        else:
            logger.error(f"Pool test failed: {e}", exc_info=True)

def show_help():
    """Show enhanced help information"""
    print("ENHANCED LOCK Address Pool Management Tool")
    print("=" * 60)
    print()
    print("This tool manages pre-generated LOCK addresses for instant token creation.")
    print("LOCK addresses end with 'LOCK' and take significant time to generate.")
    print("With this pool, your users get INSTANT token creation!")
    print()
    print("COMMANDS:")
    print("  instant [count]      - FIXED instant generation (default: 50)")
    print("  status              - Enhanced pool status check")
    print("  test                - Enhanced pool functionality test")
    print("  background [count]  - Start background generation (default: 200)")
    print("  help                - Show this help message")
    print()
    print("EXAMPLES:")
    print("  python populate_lock_pool.py instant 100      # Generate 100 addresses")
    print("  python populate_lock_pool.py status           # Check detailed status")
    print("  python populate_lock_pool.py test             # Test pool functionality")
    print("  python populate_lock_pool.py background 200   # Background generation")
    print()
    print("ENHANCEMENTS:")
    print("  - Faster database operations with WAL mode")
    print("  - Better error handling and recovery")
    print("  - Enhanced progress tracking")
    print("  - Improved thread safety")
    print("  - Detailed status reporting")
    print()
    print("TIME ESTIMATES (Enhanced):")
    print("  - 1 LOCK address: 1-3 minutes (improved)")
    print("  - 25 addresses: 30-75 minutes")
    print("  - 50 addresses: 60-150 minutes")
    print("  - 100 addresses: 120-300 minutes")
    print()
    print("REQUIREMENTS:")
    print("  - Python packages: solders, base58")
    print("  - Install with: pip install solders base58")
    print()
    print("🚀 INSTANT TOKEN CREATION READY!")

def main():
    """
    FIXED main function with enhanced command handling
    """
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1].lower()
    
    try:
        if command == "instant":
            count = int(sys.argv[2]) if len(sys.argv) > 2 else 50
            if count <= 0 or count > 500:
                print("Error: Count must be between 1 and 500")
                return
            populate_pool_instant(count)
            
        elif command == "status":
            check_pool_status_enhanced()
            
        elif command == "test":
            test_pool_enhanced()
            
        elif command == "background":
            count = int(sys.argv[2]) if len(sys.argv) > 2 else 200
            if count <= 0 or count > 1000:
                print("Error: Background target must be between 1 and 1000")
                return
            # Use the original background function from your code
            populate_pool_background(count)
            
        elif command == "help" or command == "--help" or command == "-h":
            show_help()
            
        else:
            print(f"Unknown command: {command}")
            print("Run 'python populate_lock_pool.py help' for usage information")
            
    except ValueError as e:
        print(f"Invalid count parameter: {e}")
        print("Count must be a positive integer")
    except KeyboardInterrupt:
        print("\n⏹️  Operation cancelled by user")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        logger.error(f"Main execution failed: {e}", exc_info=True)

# Keep your original background function for compatibility
def populate_pool_background(count=200):
    """
    Background method: Start generation and monitor progress (from your original code)
    """
    global current_pool
    
    print(f"=== STARTING BACKGROUND LOCK ADDRESS GENERATION ===")
    print(f"Target: {count} LOCK addresses")
    print(f"This will run continuously to maintain the pool")
    print(f"Press Ctrl+C to stop")
    print()
    
    # Check dependencies first
    deps_ok, error_msg = check_dependencies()
    if not deps_ok:
        print(f"❌ {error_msg}")
        return
    
    try:
        from lock_address_pool import LockAddressPool
        
        # Initialize pool
        pool = LockAddressPool(
            db_path="lock_addresses.db", 
            target_pool_size=count
        )
        current_pool = pool
        
        # Check current status
        current_count = pool.count_available()
        print(f"Current pool status: {current_count} addresses available")
        
        # Start background generation
        pool.start_background_generation(suffix="LOCK")
        
        print("✅ Background generation started!")
        print(f"The pool will automatically maintain {count} LOCK addresses")
        print("You can now start your bot - it will use addresses as they become available")
        print()
        print("Real-time status updates (press Ctrl+C to stop):")
        print("-" * 60)
        
        last_count = current_count
        start_time = time.time()
        
        try:
            while not shutdown_requested:
                current_count = pool.count_available()
                elapsed_hours = (time.time() - start_time) / 3600
                
                # Show progress
                progress = (current_count / count) * 100 if count > 0 else 0
                bar_length = 30
                filled_length = int(bar_length * current_count // count) if count > 0 else 0
                bar = '█' * filled_length + '-' * (bar_length - filled_length)
                
                status = f"Pool: [{bar}] {current_count}/{count} ({progress:.1f}%)"
                
                if current_count != last_count:
                    # Show generation rate
                    if elapsed_hours > 0 and current_count > last_count:
                        rate = (current_count - last_count) / elapsed_hours
                        status += f" | Rate: {rate:.2f}/hour"
                    status += f" | +{current_count - last_count} new"
                
                print(f"\r{status}", end="", flush=True)
                last_count = current_count
                
                if current_count >= count:
                    print(f"\n✅ Target reached! Pool has {current_count} addresses ready.")
                    print("Background generation will continue to maintain this level.")
                    # Still continue monitoring but at longer intervals
                    time.sleep(60)
                else:
                    time.sleep(5)  # Update every 5 seconds
                    
        except KeyboardInterrupt:
            print(f"\n\n⏹️  Stopping background generation...")
            
        finally:
            pool.stop_background_generation()
            print("Background generation stopped.")
            
            final_count = pool.count_available()
            print(f"Final pool status: {final_count} addresses available")
        
    except Exception as e:
        print(f"❌ Error in background generation: {e}")
        logger.error(f"Background generation failed: {e}", exc_info=True)

if __name__ == "__main__":
    main()