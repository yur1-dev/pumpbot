import logging
import os
import random
import base58
import json
import requests
import asyncio
import time
import threading
import subprocess
import base64
from datetime import datetime, timedelta, timezone
from mnemonic import Mnemonic
from dotenv import load_dotenv

# --- Solana & Solders Imports ---
from solders.keypair import Keypair as SoldersKeypair
from solders.message import Message as SoldersMessage
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey as SoldersPubkey
from solders.system_program import transfer, TransferParams
from solders.instruction import Instruction
from solders.hash import Hash as SoldersHash

# solana-py for on-chain interactions - MINIMAL IMPORTS (only what works)
from solana.rpc.api import Client
from solana.rpc.types import TxOpts

# --- Telegram Bot Imports ---
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown
from telegram.error import BadRequest

# --- LOCK Address Pool Import ---
from lock_address_pool import LockAddressPool

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----- CONFIGURATION CONSTANTS -----
SUBSCRIPTION_WALLET = {
    "address": "84YWzdTEva6zmH43xPTX8oEUbxS47s6yRAkFp2D5esXk",
    "balance": 0,
}
SUBSCRIPTION_PRICING = {
    "weekly": 0,  # Set to 0 for testing
    "monthly": 3,
    "lifetime": 8,
}

# VANITY ADDRESS CONFIGURATION - STRICT LOCK SUFFIX ONLY
CONTRACT_SUFFIX = "LOCK"   # Contract addresses MUST end with "LOCK" - no fallbacks
VANITY_GENERATION_TIMEOUT = 1800   # 30 minutes for LOCK generation (strict mode)
FALLBACK_SUFFIX = None     # NO FALLBACK - LOCK addresses only

# RAYDIUM LAUNCHLAB CONFIGURATION - FIXED CHEAP PRICING
RAYDIUM_LAUNCHLAB_PROGRAM = "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"
LETSBONK_METADATA_SERVICE = "https://gateway.pinata.cloud/ipfs/"
LAUNCHLAB_MIN_COST = 0.005  # FIXED: 10x cheaper (was 0.05 SOL)

# GLOBAL FLAGS
NODEJS_AVAILABLE = False
NODEJS_SETUP_MESSAGE = ""
LOCK_ADDRESS_POOL = None  # Global address pool instance

# CALLBACKS – Simplified for own platform only
CALLBACKS = {
    "start": "start",
    "launch": "launch",
    "subscription": "subscription",
    "subscription_back": "subscription:back",
    "wallets": "wallets",
    "settings": "settings",
    "show_private_key": "wallets:show_private_key",
    "import_wallet": "wallets:import_wallet",
    "cancel_import_wallet": "wallets:cancel_import_wallet",
    "back_to_wallets": "back_to_wallets",
    "wallet_details": "wallets:details",
    "deposit_sol": "wallets:deposit_sol",
    "withdraw_sol": "wallets:withdraw_sol",
    "cancel_withdraw_sol": "wallets:cancel_withdraw_sol",
    "withdraw_25": "wallets:withdraw_25",
    "withdraw_50": "wallets:withdraw_50", 
    "withdraw_100": "wallets:withdraw_100",
    "refresh_balance": "wallets:refresh_balance",
    "bundle": "wallets:bundle",
    "bundle_distribute_sol": "wallets:bundle_distribute_sol",
    "bump_volume": "bump_volume",
    "create_bundle_for_volume": "create_bundle_for_volume",
    "start_volume_trading": "start_volume_trading",
    "socials": "socials",
    "dynamic_back": "dynamic_back",
    "launch_confirm_yes": "launch_confirm_yes",
    "launch_confirm_no": "launch_confirm_no",
    "launched_coins": "launched_coins",
    "launch_proceed_buy_amount": "launch:proceed_buy_amount",
    "launch_change_buy_amount": "launch:change_buy_amount",
    "subscription_weekly": "subscription:weekly",
    "subscription_monthly": "subscription:monthly",
    "subscription_lifetime": "subscription:lifetime",
    "subscription_pending": "subscription:pending",
    "subscription_confirm": "subscription:confirm",
    "setup_nodejs": "setup_nodejs",
}

user_wallets = {}         # { user_id: { public, private, mnemonic, balance, bundle, ... } }
user_subscriptions = {}   # { user_id: { active, plan, amount, expires_at, tx_signature } }
user_coins = {}           # { user_id: [ coin_data, ... ] }
vanity_generation_status = {}  # { user_id: { generating: bool, attempts: int, found: keypair or None } }

# ----- SIMPLIFIED LAUNCH FLOW -----
LAUNCH_STEPS_SIMPLIFIED = [
    ("name", "*LOCK Token Name*\nEnter your token name (e.g., 'Chain Lock'):\n\n🔒 All contracts end with 'LOCK' suffix"), 
    ("ticker", "*Token Symbol*\nEnter your token symbol (e.g., 'CHAIN'):\n\n📊 Standard: 1B supply, 9 decimals"),
    ("description", "*Token Description (Optional)*\nDescribe your LOCK token project:\n\n✍️ Keep it short and engaging"), 
    ("image", "*Logo Image*\nSend your LOCK token logo:\n\n• Square image (512x512px recommended)\n• Max 5MB\n• PNG/JPG/GIF"), 
    ("website", "*Website (Optional)*\nAdd your project website:"), 
    ("twitter", "*Twitter/X (Optional)*\nAdd your Twitter/X profile:"), 
    ("buy_amount", f"*Initial Purchase (Optional)*\nEnter SOL amount for initial buy:\n\n💰 FIXED: Only {LAUNCHLAB_MIN_COST} SOL base cost\n• Creates bonding curve liquidity\n• Range: 0.001 - 10 SOL")
]

# SIMPLIFIED DEFAULTS - NO MORE COMPLEXITY
SIMPLIFIED_DEFAULTS = {
    "total_supply": 1_000_000_000,  # Always 1 billion
    "decimals": 9,                  # Always 9 decimals
    "banner": None,                 # No banner needed
    "telegram": None,               # Removed telegram option
}

# ----- SUBSCRIPTION HELPER FUNCTIONS -----
def is_subscription_active(user_id: int) -> bool:
    """Check if user has active subscription (including expiry check)"""
    subscription = user_subscriptions.get(user_id, {})
    
    if not subscription.get("active"):
        return False
    
    # Check if subscription has expired
    expires_at = subscription.get("expires_at")
    if expires_at:
        # Parse the expires_at datetime
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            except:
                return False
        
        # Check if expired
        if datetime.now(timezone.utc) > expires_at:
            # Mark as expired
            subscription["active"] = False
            return False
    
    return True

def get_subscription_status(user_id: int) -> dict:
    """Get detailed subscription status"""
    subscription = user_subscriptions.get(user_id, {})
    
    if not subscription:
        return {"active": False, "plan": None, "expires_at": None, "time_left": None}
    
    expires_at = subscription.get("expires_at")
    time_left = None
    
    if expires_at:
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            except:
                expires_at = None
        
        if expires_at:
            now = datetime.now(timezone.utc)
            if now < expires_at:
                time_left = expires_at - now
            else:
                # Expired
                subscription["active"] = False
    
    return {
        "active": subscription.get("active", False) and (not expires_at or time_left),
        "plan": subscription.get("plan"),
        "expires_at": expires_at,
        "time_left": time_left
    }

# ----- ENHANCED VANITY ADDRESS GENERATION FOR LOCK SUFFIX (FALLBACK ONLY) -----
async def generate_vanity_keypair_with_progress(suffix: str, progress_callback=None, max_attempts: int = 50000000) -> tuple[SoldersKeypair, int]:
    """
    FALLBACK: Generate keypair ending with EXACT case-sensitive suffix "LOCK"
    This is now only used when the address pool is empty
    """
    attempts = 0
    start_time = time.time()
    last_progress_time = start_time
    
    # FIXED: Keep exact case - NO lowercase conversion
    target_suffix = suffix  # "LOCK" stays "LOCK"
    
    logger.info(f"FALLBACK: Starting vanity generation for suffix '{target_suffix}'...")
    logger.info(f"Target: addresses ending with EXACT '{target_suffix}' (case sensitive)")
    logger.info(f"Timeout: {VANITY_GENERATION_TIMEOUT} seconds (~{VANITY_GENERATION_TIMEOUT/60:.1f} minutes)")
    logger.info(f"Max attempts: {max_attempts:,}")
    
    for attempt in range(max_attempts):
        # Generate random keypair
        keypair = SoldersKeypair()
        public_key_str = str(keypair.pubkey())
        
        attempts += 1
        
        # FIXED: Check for EXACT case match - NO .lower()
        if public_key_str.endswith(target_suffix):
            elapsed = time.time() - start_time
            logger.info(f"SUCCESS: Found address ending with EXACT '{target_suffix}' after {attempts:,} attempts in {elapsed:.1f}s")
            logger.info(f"Address: {public_key_str}")
            logger.info(f"Verification: Address ends with '{public_key_str[-len(target_suffix):]}' (target: '{target_suffix}')")
            
            # Double-check exact case verification
            actual_suffix = public_key_str[-len(target_suffix):]
            if actual_suffix != target_suffix:
                logger.error(f"CRITICAL: Case mismatch! Got '{actual_suffix}' expected '{target_suffix}'")
                continue
                
            return keypair, attempts
        
        # Progress callback every 100k attempts or every 30 seconds
        current_time = time.time()
        if (attempts % 100000 == 0 or current_time - last_progress_time >= 30) and progress_callback:
            elapsed = current_time - start_time
            rate = attempts / elapsed if elapsed > 0 else 0
            
            # Calculate ETA for exact uppercase "LOCK" (much harder)
            eta_text = "Calculating..."
            if rate > 0 and target_suffix == "LOCK":
                # Exact uppercase LOCK is much harder - estimated 11.3M attempts
                expected_total = 11316496  # 58^4 for exact case
                remaining = expected_total - attempts
                if remaining > 0:
                    eta_seconds = remaining / rate
                    eta_minutes = eta_seconds / 60
                    if eta_minutes > 1:
                        eta_text = f"ETA: {eta_minutes:.1f}min"
                    else:
                        eta_text = f"ETA: {eta_seconds:.0f}s"
                else:
                    eta_text = "Almost there..."
            
            # Call async progress callback
            try:
                await progress_callback(attempts, elapsed, rate, eta_text)
                last_progress_time = current_time
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")
        
        # Log progress every 500k attempts
        if attempts % 500000 == 0:
            elapsed = time.time() - start_time
            rate = attempts / elapsed if elapsed > 0 else 0
            logger.info(f"FALLBACK LOCK vanity generation: {attempts:,} attempts in {elapsed:.1f}s ({rate:,.0f}/sec)")
            
        # Timeout check
        if time.time() - start_time > VANITY_GENERATION_TIMEOUT:
            logger.warning(f"FALLBACK LOCK vanity generation timeout after {attempts:,} attempts")
            break
        
        # Allow other async operations to run every 25k attempts
        if attempts % 25000 == 0:
            await asyncio.sleep(0.001)
    
    logger.warning(f"FALLBACK LOCK vanity generation failed after {attempts:,} attempts")
    return None, attempts

def estimate_vanity_generation_time(suffix: str) -> dict:
    """
    Estimate time needed to generate vanity address
    """
    # Base58 alphabet has 58 characters
    # Probability = 1 / (58^suffix_length)
    # Expected attempts = 58^suffix_length
    
    suffix_length = len(suffix)
    base58_chars = 58
    expected_attempts = base58_chars ** suffix_length
    
    # Estimate generation rate (keypairs/second) - conservative estimate
    estimated_rate = 75000  # 75k keypairs per second (optimistic)
    
    expected_seconds = expected_attempts / estimated_rate
    
    if expected_seconds < 60:
        time_str = f"{expected_seconds:.1f} seconds"
    elif expected_seconds < 3600:
        time_str = f"{expected_seconds/60:.1f} minutes"  
    elif expected_seconds < 86400:
        time_str = f"{expected_seconds/3600:.1f} hours"
    else:
        time_str = f"{expected_seconds/86400:.1f} days"
    
    return {
        "expected_attempts": expected_attempts,
        "expected_seconds": expected_seconds,
        "time_estimate": time_str,
        "difficulty": "Easy" if expected_seconds < 5 else "Medium" if expected_seconds < 60 else "Hard" if expected_seconds < 3600 else "Very Hard"
    }

# ----- ENHANCED BALANCE FUNCTIONS -----
def get_wallet_balance(public_key: str) -> float:
    """
    WORKING: Get wallet balance using direct RPC calls with account existence check
    """
    rpc_endpoints = [
        "https://api.mainnet-beta.solana.com",
        "https://rpc.ankr.com/solana",
        "https://solana-api.projectserum.com"
    ]
    
    for rpc_url in rpc_endpoints:
        try:
            logger.info(f"Testing RPC: {rpc_url} for address: {public_key}")
            
            # First check if account exists using getAccountInfo
            account_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [public_key, {"commitment": "confirmed"}]
            }
            
            account_response = requests.post(rpc_url, json=account_payload, headers={"Content-Type": "application/json"})
            
            if account_response.status_code == 200:
                account_data = account_response.json()
                if "result" in account_data and account_data["result"]["value"] is None:
                    logger.info(f"Account {public_key} does not exist on-chain yet")
                    return 0.0
            
            # Method 1: Direct HTTP RPC call for balance
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [public_key, {"commitment": "confirmed"}]
            }
            
            response = requests.post(rpc_url, json=payload, headers={"Content-Type": "application/json"})
            
            logger.info(f"HTTP RPC response status: {response.status_code}")
            logger.info(f"HTTP RPC response: {response.text}")
            
            if response.status_code == 200:
                data = response.json()
                if "result" in data and "value" in data["result"]:
                    lamports = data["result"]["value"]
                    balance_sol = lamports / 1_000_000_000
                    logger.info(f"SUCCESS: {public_key} has {balance_sol} SOL ({lamports} lamports)")
                    return balance_sol
                else:
                    logger.warning(f"No result.value in response: {data}")
            
            # Method 2: Try with Client
            try:
                client = Client(rpc_url)
                
                # Use the internal method to avoid PublicKey issues
                params = [public_key, {"commitment": "confirmed"}]
                result = client._provider.make_request("getBalance", params)
                
                logger.info(f"Client method result: {result}")
                
                if isinstance(result, dict) and "result" in result and "value" in result["result"]:
                    lamports = result["result"]["value"] 
                    balance_sol = lamports / 1_000_000_000
                    logger.info(f"SUCCESS via client: {balance_sol} SOL")
                    return balance_sol
                    
            except Exception as client_error:
                logger.error(f"Client method failed: {client_error}")
                
        except Exception as e:
            logger.error(f"RPC {rpc_url} completely failed: {e}")
            continue
    
    logger.error(f"ALL methods failed for {public_key}")
    return 0.0

def get_wallet_balance_enhanced(public_key: str) -> dict:
    """
    Enhanced balance function that also returns account status
    """
    rpc_endpoints = [
        "https://api.mainnet-beta.solana.com",
        "https://rpc.ankr.com/solana", 
        "https://solana-api.projectserum.com"
    ]
    
    for rpc_url in rpc_endpoints:
        try:
            logger.info(f"Testing enhanced RPC: {rpc_url} for address: {public_key}")
            
            # Check account info first
            account_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [public_key, {"commitment": "confirmed", "encoding": "base64"}]
            }
            
            account_response = requests.post(rpc_url, json=account_payload, headers={"Content-Type": "application/json"})
            
            if account_response.status_code == 200:
                account_data = account_response.json()
                
                if "result" in account_data:
                    account_info = account_data["result"]["value"]
                    
                    if account_info is None:
                        logger.info(f"Account {public_key} does not exist on-chain yet")
                        return {"balance": 0.0, "exists": False, "initialized": False}
                    else:
                        lamports = account_info.get("lamports", 0)
                        balance_sol = lamports / 1_000_000_000
                        owner = account_info.get("owner", "")
                        is_system_account = owner == "11111111111111111111111111111112"
                        
                        logger.info(f"ENHANCED SUCCESS: {public_key} has {balance_sol} SOL ({lamports} lamports), Owner: {owner}")
                        
                        return {
                            "balance": balance_sol,
                            "exists": True,
                            "initialized": is_system_account,
                            "lamports": lamports,
                            "owner": owner,
                            "can_send": lamports >= 890880  # Has enough for rent exemption
                        }
            
        except Exception as e:
            logger.error(f"Enhanced RPC {rpc_url} failed: {e}")
            continue
    
    logger.error(f"ALL enhanced methods failed for {public_key}")
    return {"balance": 0.0, "exists": False, "initialized": False}

# ----- FIXED WALLET FUNDING VALIDATION WITH CHEAPER PRICING -----
def check_wallet_funding_requirements_fixed(coin_data, user_wallet):
    """
    FIXED: Check wallet funding with cheaper 0.005 SOL requirement (10x cheaper!)
    """
    try:
        # Get current balance
        current_balance = get_wallet_balance(user_wallet["public"])
        
        # FIXED: Much cheaper creation cost
        base_creation_cost = LAUNCHLAB_MIN_COST  # 0.005 SOL instead of 0.05 (10x cheaper!)
        initial_buy_amount = 0
        
        # Handle initial buy amount
        buy_amount_raw = coin_data.get('buy_amount')
        if buy_amount_raw is not None and buy_amount_raw != 0:
            try:
                initial_buy_amount = float(buy_amount_raw)
                if initial_buy_amount < 0:
                    initial_buy_amount = 0
            except (ValueError, TypeError):
                initial_buy_amount = 0
        
        total_required = base_creation_cost + initial_buy_amount
        
        # Check if sufficient
        if current_balance < total_required:
            return {
                "sufficient": False,
                "current_balance": current_balance,
                "required": total_required,
                "base_cost": base_creation_cost,
                "initial_buy": initial_buy_amount,
                "shortfall": total_required - current_balance,
                "cost_fixed": True,
                "savings": "10x cheaper than before!",
                "old_cost": 0.05,
                "new_cost": base_creation_cost
            }
        
        return {
            "sufficient": True,
            "current_balance": current_balance,
            "required": total_required,
            "base_cost": base_creation_cost,
            "initial_buy": initial_buy_amount,
            "remaining_after": current_balance - total_required,
            "cost_fixed": True,
            "savings": "10x cheaper than before!",
            "old_cost": 0.05,
            "new_cost": base_creation_cost
        }
        
    except Exception as e:
        logger.error(f"Error checking wallet funding: {e}")
        return {
            "sufficient": False,
            "error": str(e),
            "current_balance": 0,
            "required": LAUNCHLAB_MIN_COST,
            "cost_fixed": True
        }
    # ----- ULTIMATE FIXED TRANSFER FUNCTION -----
def transfer_sol_ultimate(from_wallet: dict, to_address: str, amount_sol: float) -> dict:
    """
    ULTIMATE FIX: Transfer SOL with account initialization handling + multiple methods
    """
    try:
        # First check account status
        account_info = get_wallet_balance_enhanced(from_wallet["public"])
        logger.info(f"Account status check: {account_info}")
        
        if not account_info["exists"]:
            return {
                "status": "error",
                "message": "Your wallet account doesn't exist on-chain yet. Please receive some SOL first to initialize your account."
            }
        
        # Solana rent exemption requirements
        RENT_EXEMPT_MINIMUM = 0.000890880  # ~890,880 lamports
        current_balance = account_info["balance"]
        
        if current_balance < amount_sol:
            return {
                "status": "error", 
                "message": f"Insufficient balance. Current: {current_balance:.6f} SOL, Required: {amount_sol:.6f} SOL"
            }
        
        # Check if account has enough for rent exemption after transfer
        remaining_after_transfer = current_balance - amount_sol
        if remaining_after_transfer < RENT_EXEMPT_MINIMUM and remaining_after_transfer > 0:
            # Adjust transfer amount to leave rent-exempt minimum
            adjusted_amount = current_balance - RENT_EXEMPT_MINIMUM - 0.000005  # Leave buffer for fees
            if adjusted_amount <= 0:
                return {
                    "status": "error",
                    "message": f"Cannot withdraw {amount_sol:.6f} SOL. Minimum {RENT_EXEMPT_MINIMUM:.6f} SOL must remain for rent exemption."
                }
            
            logger.info(f"Adjusting withdrawal from {amount_sol} to {adjusted_amount} SOL to maintain rent exemption")
            amount_sol = adjusted_amount
        
        # If account doesn't have enough lamports for reliable sending, try activation first
        if account_info["lamports"] < 5000000:  # Less than 0.005 SOL
            logger.info("Account has low balance, attempting to activate first...")
            activation_result = activate_account_for_sending(from_wallet)
            if activation_result["status"] != "success":
                return {
                    "status": "error",
                    "message": f"Account activation failed: {activation_result['message']}. Please deposit more SOL (at least 0.005 SOL) and try again."
                }
        
        # Try multiple transfer methods
        methods = [
            ("VersionedTransaction", transfer_sol_versioned),
            ("LegacyTransaction", transfer_sol_legacy),
            ("DirectRPC", transfer_sol_direct_rpc)
        ]
        
        for method_name, method_func in methods:
            try:
                logger.info(f"Attempting transfer using {method_name}...")
                result = method_func(from_wallet, to_address, amount_sol)
                
                if result["status"] == "success":
                    logger.info(f"Transfer successful using {method_name}")
                    return result
                else:
                    logger.warning(f"{method_name} failed: {result.get('message')}")
                    
            except Exception as e:
                logger.error(f"{method_name} exception: {e}")
                continue
        
        return {"status": "error", "message": "All transfer methods failed. Your account may need more SOL or time to fully activate."}
        
    except Exception as e:
        logger.error(f"Ultimate transfer error: {e}", exc_info=True)
        return {"status": "error", "message": f"Transfer system error: {str(e)}"}

def activate_account_for_sending(wallet: dict) -> dict:
    """
    Activate account by creating a tiny self-transfer to initialize it for sending
    """
    try:
        logger.info("Attempting account activation via self-transfer...")
        
        # Very small self-transfer to activate account
        result = transfer_sol_versioned(wallet, wallet["public"], 0.000001)  # 1000 lamports
        
        if result["status"] == "success":
            logger.info("Account activation successful")
            time.sleep(1)  # Wait for confirmation
            return {"status": "success", "message": "Account activated"}
        else:
            return {"status": "error", "message": f"Activation failed: {result['message']}"}
            
    except Exception as e:
        logger.error(f"Account activation error: {e}")
        return {"status": "error", "message": f"Activation error: {str(e)}"}

def transfer_sol_versioned(from_wallet: dict, to_address: str, amount_sol: float) -> dict:
    """
    Transfer using VersionedTransaction (modern Solana method)
    """
    rpc_url = "https://api.mainnet-beta.solana.com"
    lamports = int(amount_sol * 1_000_000_000)
    
    try:
        # Create keypair from wallet
        secret_key = base58.b58decode(from_wallet["private"])
        keypair = SoldersKeypair.from_bytes(secret_key)
        
        # Validate destination address
        to_pubkey = SoldersPubkey.from_string(to_address)
        
        # Create transfer instruction
        transfer_instruction = transfer(
            TransferParams(
                from_pubkey=keypair.pubkey(),
                to_pubkey=to_pubkey,
                lamports=lamports
            )
        )
        
        # Get recent blockhash
        blockhash_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLatestBlockhash",
            "params": [{"commitment": "finalized"}]
        }
        
        blockhash_response = requests.post(
            rpc_url, 
            json=blockhash_payload, 
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        blockhash_response.raise_for_status()
        blockhash_data = blockhash_response.json()
        
        if "result" not in blockhash_data or "value" not in blockhash_data["result"]:
            raise Exception("Could not get blockhash")
            
        recent_blockhash_str = blockhash_data["result"]["value"]["blockhash"]
        recent_blockhash = SoldersHash.from_string(recent_blockhash_str)
        
        # Create message
        message = SoldersMessage.new_with_blockhash(
            instructions=[transfer_instruction],
            payer=keypair.pubkey(),
            blockhash=recent_blockhash
        )
        
        # Create VersionedTransaction
        transaction = VersionedTransaction(message, [keypair])
        
        # Serialize transaction
        serialized_txn = base58.b58encode(bytes(transaction)).decode()
        
        # Send transaction
        send_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction", 
            "params": [
                serialized_txn,
                {
                    "skipPreflight": True,  # CRITICAL: Skip preflight for problematic accounts
                    "commitment": "confirmed",
                    "maxRetries": 5
                }
            ]
        }
        
        send_response = requests.post(
            rpc_url, 
            json=send_payload, 
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        
        send_response.raise_for_status()
        result = send_response.json()
        
        if "result" in result:
            signature = result["result"]
            return {"status": "success", "signature": signature}
        elif "error" in result:
            error_msg = result["error"].get("message", "Unknown error")
            return {"status": "error", "message": error_msg}
        else:
            return {"status": "error", "message": "Unexpected response"}
            
    except Exception as e:
        return {"status": "error", "message": f"VersionedTransaction failed: {str(e)}"}

def transfer_sol_legacy(from_wallet: dict, to_address: str, amount_sol: float) -> dict:
    """
    Transfer using legacy Transaction (fallback method)
    """
    try:
        from solders.transaction import Transaction as LegacyTransaction
        
        rpc_url = "https://api.mainnet-beta.solana.com"
        lamports = int(amount_sol * 1_000_000_000)
        
        # Create keypair
        secret_key = base58.b58decode(from_wallet["private"])
        keypair = SoldersKeypair.from_bytes(secret_key)
        
        # Create destination pubkey
        to_pubkey = SoldersPubkey.from_string(to_address)
        
        # Create transfer instruction
        transfer_instruction = transfer(
            TransferParams(
                from_pubkey=keypair.pubkey(),
                to_pubkey=to_pubkey,
                lamports=lamports
            )
        )
        
        # Get recent blockhash
        blockhash_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLatestBlockhash",
            "params": [{"commitment": "finalized"}]
        }
        
        blockhash_response = requests.post(rpc_url, json=blockhash_payload, headers={"Content-Type": "application/json"})
        blockhash_response.raise_for_status()
        blockhash_data = blockhash_response.json()
        
        recent_blockhash_str = blockhash_data["result"]["value"]["blockhash"]
        recent_blockhash = SoldersHash.from_string(recent_blockhash_str)
        
        # Create legacy transaction
        transaction = LegacyTransaction(
            instructions=[transfer_instruction],
            payer=keypair.pubkey(),
            blockhash=recent_blockhash
        )
        
        # Sign transaction
        transaction.sign([keypair])
        
        # Serialize and send
        serialized_txn = base58.b58encode(bytes(transaction)).decode()
        
        send_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                serialized_txn, 
                {
                    "skipPreflight": True,  # Skip preflight
                    "commitment": "confirmed"
                }
            ]
        }
        
        send_response = requests.post(rpc_url, json=send_payload, headers={"Content-Type": "application/json"})
        send_response.raise_for_status()
        result = send_response.json()
        
        if "result" in result:
            signature = result["result"]
            return {"status": "success", "signature": signature}
        elif "error" in result:
            error_msg = result["error"].get("message", "Unknown error")
            return {"status": "error", "message": error_msg}
        else:
            return {"status": "error", "message": "Unexpected response"}
            
    except Exception as e:
        return {"status": "error", "message": f"Legacy transaction failed: {str(e)}"}

def transfer_sol_direct_rpc(from_wallet: dict, to_address: str, amount_sol: float) -> dict:
    """
    Direct RPC transfer using raw transaction construction
    """
    try:
        # Use Helius RPC which handles new accounts better
        rpc_endpoints = [
            "https://rpc.helius.xyz/?api-key=demo",
            "https://api.mainnet-beta.solana.com",
            "https://rpc.ankr.com/solana"
        ]
        
        lamports = int(amount_sol * 1_000_000_000)
        
        for rpc_url in rpc_endpoints:
            try:
                logger.info(f"Trying direct RPC method with {rpc_url}")
                
                # Create keypair
                secret_key = base58.b58decode(from_wallet["private"])
                keypair = SoldersKeypair.from_bytes(secret_key)
                to_pubkey = SoldersPubkey.from_string(to_address)
                
                # Create instruction
                transfer_instruction = transfer(
                    TransferParams(
                        from_pubkey=keypair.pubkey(),
                        to_pubkey=to_pubkey,
                        lamports=lamports
                    )
                )
                
                # Get blockhash from this specific RPC
                blockhash_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getLatestBlockhash",
                    "params": [{"commitment": "processed"}]  # Use "processed" for faster response
                }
                
                blockhash_response = requests.post(rpc_url, json=blockhash_payload, headers={"Content-Type": "application/json"})
                blockhash_response.raise_for_status()
                blockhash_data = blockhash_response.json()
                
                recent_blockhash_str = blockhash_data["result"]["value"]["blockhash"]
                recent_blockhash = SoldersHash.from_string(recent_blockhash_str)
                
                # Create message and transaction
                message = SoldersMessage.new_with_blockhash(
                    instructions=[transfer_instruction],
                    payer=keypair.pubkey(),
                    blockhash=recent_blockhash
                )
                
                transaction = VersionedTransaction(message, [keypair])
                serialized_txn = base58.b58encode(bytes(transaction)).decode()
                
                # Send with aggressive settings for new accounts
                send_payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [
                        serialized_txn,
                        {
                            "skipPreflight": True,  # CRITICAL for new accounts
                            "commitment": "processed",
                            "maxRetries": 0  # No retries for direct method
                        }
                    ]
                }
                
                send_response = requests.post(rpc_url, json=send_payload, headers={"Content-Type": "application/json"}, timeout=30)
                
                if send_response.status_code == 200:
                    result = send_response.json()
                    
                    if "result" in result:
                        signature = result["result"]
                        logger.info(f"Direct RPC transfer successful: {signature}")
                        return {"status": "success", "signature": signature}
                    elif "error" in result:
                        error_msg = result["error"].get("message", "")
                        logger.warning(f"RPC {rpc_url} error: {error_msg}")
                        continue
                
            except Exception as e:
                logger.warning(f"Direct RPC {rpc_url} failed: {e}")
                continue
        
        return {"status": "error", "message": "All direct RPC methods failed"}
        
    except Exception as e:
        return {"status": "error", "message": f"Direct RPC method error: {str(e)}"}

# Validation helper function
def validate_solana_address(address: str) -> bool:
    """
    Validate Solana address format
    """
    try:
        # Try to create a Pubkey object  
        SoldersPubkey.from_string(address)
        
        # Additional format checks
        if len(address) < 32 or len(address) > 44:
            return False
            
        # Check if it's valid base58
        try:
            decoded = base58.b58decode(address)
            if len(decoded) != 32:  # Solana pubkeys are 32 bytes
                return False
        except Exception:
            return False
            
        return True
    except Exception:
        return False

# ----- NAVIGATION HELPERS -----
def push_nav_state(context, state_data):
    if "nav_stack" not in context.user_data:
        context.user_data["nav_stack"] = []
    context.user_data["nav_stack"].append(state_data)

def pop_nav_state(context):
    if context.user_data.get("nav_stack"):
        return context.user_data["nav_stack"].pop()
    return None

# ----- WALLET GENERATION -----
def generate_solana_wallet():
    """Generate wallet compatible with Phantom and other standard Solana wallets"""
    try:
        mnemo = Mnemonic("english")
        mnemonic_words = mnemo.generate(strength=128)  # 12 words standard
        
        # Use standard Solana derivation that Phantom uses
        seed = mnemo.to_seed(mnemonic_words, passphrase="")
        
        # Use first 32 bytes for keypair generation (standard approach)
        keypair = SoldersKeypair.from_seed(seed[:32])
        public_key_str = str(keypair.pubkey())
        private_key = base58.b58encode(bytes(keypair)).decode()
        
        logger.info(f"Generated wallet - Public: {public_key_str}")
        logger.info(f"Mnemonic: {mnemonic_words}")
        
        # Test the wallet immediately
        try:
            test_balance = get_wallet_balance(public_key_str)
            logger.info(f"Test balance for new wallet: {test_balance} SOL")
        except Exception as e:
            logger.warning(f"Could not test balance for new wallet: {e}")
        
        return mnemonic_words, public_key_str, private_key
        
    except Exception as e:
        logger.error(f"Error generating wallet: {e}", exc_info=True)
        raise

# ----- LETSBONK/RAYDIUM LAUNCHLAB TOKEN CREATION -----
def upload_letsbonk_metadata(coin_data):
    """Upload metadata optimized for LetsBonk/Raydium LaunchLab"""
    try:
        # Handle logo image upload
        image_path = coin_data.get('image')
        if not image_path or not os.path.exists(image_path):
            raise Exception("Logo image file not found")
        
        # Read the logo image file
        with open(image_path, 'rb') as f:
            file_content = f.read()
        
        # Upload to IPFS via Pinata (common service for Raydium)
        files = {
            'file': (os.path.basename(image_path), file_content, 'image/png')
        }
        
        logger.info("Uploading logo to IPFS for LetsBonk...")
        
        # Use Pinata API for IPFS upload
        pinata_url = "https://api.pinata.cloud/pinning/pinFileToIPFS"
        pinata_key = os.getenv("PINATA_API_KEY", "demo")
        pinata_secret = os.getenv("PINATA_SECRET_KEY", "demo")
        
        headers = {
            'pinata_api_key': pinata_key,
            'pinata_secret_api_key': pinata_secret
        }
        
        try:
            img_response = requests.post(pinata_url, files=files, headers=headers, timeout=30)
            if img_response.status_code == 200:
                ipfs_hash = img_response.json()['IpfsHash']
                img_uri = f"https://gateway.pinata.cloud/ipfs/{ipfs_hash}"
            else:
                # Fallback to free IPFS service
                img_uri = upload_to_free_ipfs(image_path)
        except:
            # Fallback to free IPFS service
            img_uri = upload_to_free_ipfs(image_path)
        
        logger.info(f"Logo uploaded to IPFS: {img_uri}")
        
        # Enhanced metadata payload for LetsBonk/Raydium LaunchLab
        metadata_payload = {
            'name': coin_data.get('name'),
            'symbol': coin_data.get('ticker'),
            'description': coin_data.get('description', ''),
            'image': img_uri,
            'website': coin_data.get('website', ''),
            'twitter': coin_data.get('twitter', ''),
            # LetsBonk specific fields
            'totalSupply': coin_data.get('total_supply', 1_000_000_000),
            'decimals': coin_data.get('decimals', 9),
            'platform': 'LetsBonk',
            'launchpad': 'Raydium LaunchLab',
            'contractSuffix': CONTRACT_SUFFIX,
            'createdAt': datetime.now().isoformat(),
            'creator': f"LetsBonk-{CONTRACT_SUFFIX}",
            'costFixed': True,
            'cheaperPricing': True,
            'tradingReady': True
        }
        
        logger.info(f"Uploading LetsBonk metadata: {metadata_payload}")
        
        # Upload metadata to IPFS
        metadata_json = json.dumps(metadata_payload)
        metadata_files = {
            'file': ('metadata.json', metadata_json, 'application/json')
        }
        
        try:
            metadata_response = requests.post(pinata_url, files=metadata_files, headers=headers, timeout=30)
            if metadata_response.status_code == 200:
                metadata_hash = metadata_response.json()['IpfsHash']
                metadata_uri = f"https://gateway.pinata.cloud/ipfs/{metadata_hash}"
            else:
                # Create a simple metadata URI
                metadata_uri = create_simple_metadata_uri(metadata_payload)
        except:
            metadata_uri = create_simple_metadata_uri(metadata_payload)
        
        logger.info(f"LetsBonk metadata uploaded: {metadata_uri}")
        
        # Return comprehensive token metadata
        return {
            'name': coin_data.get('name'),
            'symbol': coin_data.get('ticker'),
            'uri': metadata_uri,
            'decimals': coin_data.get('decimals', 9),
            'totalSupply': coin_data.get('total_supply', 1_000_000_000)
        }
        
    except Exception as e:
        logger.error(f"Error uploading LetsBonk metadata: {e}")
        raise

def upload_to_free_ipfs(file_path):
    """Upload to free IPFS service as fallback"""
    try:
        with open(file_path, 'rb') as f:
            files = {'file': f}
            response = requests.post('https://ipfs.infura.io:5001/api/v0/add', files=files, timeout=30)
            if response.status_code == 200:
                hash_value = response.json()['Hash']
                return f"https://ipfs.infura.io/ipfs/{hash_value}"
    except:
        pass
    
    # Ultimate fallback - return a placeholder
    return f"https://via.placeholder.com/512x512/000000/FFFFFF/?text=LOCK"

def create_simple_metadata_uri(metadata):
    """Create a simple metadata URI as fallback"""
    # This is a simplified approach - in production you'd want proper IPFS hosting
    encoded_metadata = base58.b58encode(json.dumps(metadata).encode()).decode()
    return f"data:application/json;base58,{encoded_metadata}"

# ----- ENHANCED TOKEN CREATION WITH INSTANT LOCK ADDRESSES -----
async def create_lock_token_with_raydium_fixed_instant(coin_data, user_wallet, progress_message_func):
    """
    INSTANT: Create LOCK token using pre-generated address pool
    """
    global LOCK_ADDRESS_POOL
    
    try:
        # First check wallet funding (same as before)
        await progress_message_func(
            "Checking Wallet Requirements...\n\n"
            f"FIXED: Only {LAUNCHLAB_MIN_COST} SOL required (10x cheaper!)\n"
            "Verifying SOL balance for LaunchLab token creation..."
        )
        
        funding_check = check_wallet_funding_requirements_fixed(coin_data, user_wallet)
        
        if not funding_check["sufficient"]:
            # Same error handling as before
            shortfall = funding_check.get("shortfall", LAUNCHLAB_MIN_COST)
            current = funding_check.get("current_balance", 0)
            required = funding_check.get("required", LAUNCHLAB_MIN_COST)
            
            error_message = (
                f"Insufficient SOL Balance for LaunchLab\n\n"
                f"Current: {current:.6f} SOL\n"
                f"Required: {required:.6f} SOL\n"
                f"Shortfall: {shortfall:.6f} SOL\n\n"
                f"FIXED: Only {LAUNCHLAB_MIN_COST} SOL needed (was 0.05!)\n"
                f"10x cheaper token creation!\n\n"
                f"Please add {shortfall:.6f} SOL to your wallet and try again."
            )
            
            return {
                'status': 'error',
                'message': error_message,
                'funding_required': required,
                'current_balance': current,
                'cost_fixed': True,
                'savings': "10x cheaper than before"
            }
        
        # Show wallet ready status
        remaining_balance = funding_check["remaining_after"]
        await progress_message_func(
            f"Wallet Ready - FIXED Pricing!\n\n"
            f"Balance: {funding_check['current_balance']:.6f} SOL\n"
            f"Creation Cost: {funding_check['base_cost']:.6f} SOL (FIXED!)\n"
            f"Initial Buy: {funding_check['initial_buy']:.6f} SOL\n"
            f"Remaining: {remaining_balance:.6f} SOL\n\n"
            f"Getting LOCK address..."
        )
        
        # INSTANT ADDRESS RETRIEVAL
        vanity_keypair = None
        attempts = 0
        pool_status = "No Pool"
        was_instant = False
        
        if LOCK_ADDRESS_POOL:
            try:
                await progress_message_func(
                    f"Retrieving LOCK Address...\n\n"
                    f"⚡ INSTANT retrieval from address pool!\n"
                    f"No waiting required!\n\n"
                    f"Getting next available LOCK address..."
                )
                
                # Get address from pool - INSTANT!
                lock_data = LOCK_ADDRESS_POOL.get_next_address()
                vanity_keypair = lock_data['keypair']
                attempts = 0  # No attempts needed!
                was_instant = True
                
                pool_remaining = LOCK_ADDRESS_POOL.count_available()
                pool_status = f"{pool_remaining} remaining"
                
                vanity_address = str(vanity_keypair.pubkey())
                
                await progress_message_func(
                    f"✅ LOCK Address Retrieved Instantly!\n\n"
                    f"Address: ...{vanity_address[-12:]}\n"
                    f"Pool Status: {pool_remaining} LOCK addresses remaining\n"
                    f"Time Saved: 10-30 minutes!\n\n"
                    f"Proceeding to token creation..."
                )
                
                logger.info(f"INSTANT: Got LOCK address from pool: {vanity_address}")
                logger.info(f"Pool status: {pool_remaining} addresses remaining")
                
            except Exception as pool_error:
                logger.error(f"Pool retrieval failed: {pool_error}")
                # Fall back to real-time generation
                await progress_message_func(
                    f"Pool Empty - Generating Live...\n\n"
                    f"Address pool is empty\n"
                    f"Falling back to real-time generation\n"
                    f"This will take 10-30 minutes...\n\n"
                    f"Please wait while we find your LOCK address..."
                )
                
                # Use existing generation function as fallback
                async def progress_callback(attempts_made, elapsed, rate, eta_text=""):
                    progress_text = (
                        f"Generating LOCK Address...\n\n"
                        f"Pool was empty - generating live\n"
                        f"Target: ...LOCK\n"
                        f"Attempts: {attempts_made:,}\n"
                        f"Time: {elapsed:.1f}s ({elapsed/60:.1f}min)\n"
                        f"Rate: {rate:,.0f}/sec\n"
                        f"{eta_text}\n\n"
                        f"Next time will be instant!"
                    )
                    await progress_message_func(progress_text)
                
                vanity_keypair, attempts = await generate_vanity_keypair_with_progress(
                    CONTRACT_SUFFIX, 
                    progress_callback, 
                    max_attempts=20000000
                )
                pool_status = "Generated Live"
        else:
            # No pool available, use real-time generation
            await progress_message_func(
                f"Generating LOCK Address...\n\n"
                f"Pool not available - using real-time generation\n"
                f"This may take 10-30 minutes...\n\n"
                f"Consider setting up the address pool for instant results!"
            )
            
            async def progress_callback(attempts_made, elapsed, rate, eta_text=""):
                progress_text = (
                    f"Generating LOCK Address...\n\n"
                    f"Target: ...LOCK\n"
                    f"Attempts: {attempts_made:,}\n"
                    f"Time: {elapsed:.1f}s ({elapsed/60:.1f}min)\n"
                    f"Rate: {rate:,.0f}/sec\n"
                    f"{eta_text}\n\n"
                    f"Set up address pool for instant results!"
                )
                await progress_message_func(progress_text)
            
            vanity_keypair, attempts = await generate_vanity_keypair_with_progress(
                CONTRACT_SUFFIX, 
                progress_callback, 
                max_attempts=20000000
            )
            pool_status = "Generated Live"
        
        # Check if we got an address
        if not vanity_keypair:
            logger.error(f"LOCK address generation failed after {attempts:,} attempts")
            await progress_message_func(
                f"❌ LOCK Generation Failed\n\n"
                f"Could not generate a LOCK address\n"
                f"Pool Status: {pool_status}\n\n"
                f"Try again - next time may be instant!"
            )
            return {
                'status': 'error',
                'message': 'LOCK address generation failed. Try again.',
                'attempts': attempts,
                'pool_status': pool_status
            }
        
        vanity_address = str(vanity_keypair.pubkey())
        logger.info(f"Final LOCK address: {vanity_address}")
        
        # Upload metadata (same as before)
        await progress_message_func(
            f"Uploading Enhanced Metadata...\n\n"
            f"Address: ...{vanity_address[-12:]}\n"
            f"Pool Status: {pool_status}\n"
            f"Processing token data for trading platforms...\n\n"
            f"Preparing for Raydium LaunchLab..."
        )
        
        token_metadata = upload_letsbonk_metadata(coin_data)
        
        # Continue with rest of token creation logic...
        has_initial_buy = funding_check["initial_buy"] > 0
        
        if has_initial_buy:
            await progress_message_func(
                f"Launching on LaunchLab!\n\n"
                f"Contract: ...{vanity_address[-8:]}\n"
                f"Pool Status: {pool_status}\n"
                f"Initial Buy: {funding_check['initial_buy']} SOL\n"
                f"Total Cost: {funding_check['required']} SOL\n"
                f"{'⚡ INSTANT ADDRESS' if was_instant else 'Generated Address'}\n\n"
                f"Creating bonding curve..."
            )
        else:
            await progress_message_func(
                f"Launching on LaunchLab!\n\n"
                f"Contract: ...{vanity_address[-8:]}\n"
                f"Pool Status: {pool_status}\n"
                f"Mode: Pure Creation\n"
                f"Cost: {funding_check['base_cost']} SOL\n"
                f"{'⚡ INSTANT ADDRESS' if was_instant else 'Generated Address'}\n\n"
                f"Creating token..."
            )
        
        # Create token using existing function
        result = await create_token_on_raydium_launchlab_fixed(
            vanity_keypair,
            token_metadata,
            coin_data,
            user_wallet,
            has_initial_buy,
            funding_check["initial_buy"]
        )
        
        if result['status'] == 'success':
            result.update({
                'attempts': attempts,
                'vanity_suffix': "LOCK",
                'is_full_lock': True,
                'was_instant': was_instant,
                'pool_status': pool_status,
                'platform': 'Raydium LaunchLab',
                'initial_liquidity_sol': funding_check["initial_buy"],
                'trading_enabled': True,
                'pure_creation': not has_initial_buy,
                'funding_used': funding_check["required"],
                'wallet_balance_after': funding_check["current_balance"] - funding_check["required"],
                'funding_target': result.get('funding_target', 85),
                'cost_fixed': True,
                'savings': "10x cheaper than before",
                'creation_cost_old': 0.05,
                'creation_cost_new': funding_check["base_cost"]
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error creating LOCK token: {e}", exc_info=True)
        return {'status': 'error', 'message': f"Token creation failed: {str(e)}"}

# ----- FIXED TOKEN CREATION FUNCTION WITH YOUR NODE.JS SCRIPT -----
async def create_token_on_raydium_launchlab_fixed(keypair, metadata, coin_data, user_wallet, has_initial_buy, buy_amount):
    """
    FIXED: Enhanced token creation using your create_real_launchlab_token.js script with cheaper pricing
    """
    try:
        mint_address = str(keypair.pubkey())
        logger.info(f"Creating LOCK token using your script: {mint_address}")
        
        # Check if Node.js environment is available
        if not NODEJS_AVAILABLE:
            return {
                'status': 'error',
                'message': f'Node.js Setup Required\n\n{NODEJS_SETUP_MESSAGE}\n\nPlease set up the required files and restart the bot.',
                'requires_nodejs_setup': True
            }
        
        # Check if your script exists
        script_path = "create_real_launchlab_token.js"  # Your actual script
        if not os.path.exists(script_path):
            return {
                'status': 'error',
                'message': f'Your script not found: {script_path}\n\nPlease ensure create_real_launchlab_token.js is present.',
                'requires_script': True
            }
        
        # CRITICAL: Verify the address ends with LOCK suffix (STRICT MODE)
        if not mint_address.upper().endswith("LOCK"):
            logger.error(f"CRITICAL ERROR: Generated address {mint_address} does not end with LOCK!")
            return {
                'status': 'error',
                'message': f'Address validation failed - address must end with LOCK. Got: {mint_address}'
            }
        
        logger.info(f"VERIFIED: Token address format acceptable: {mint_address}")
        
        # Validate wallet balance - FIXED: Cheaper requirements
        current_balance = get_wallet_balance(user_wallet["public"])
        required_balance = LAUNCHLAB_MIN_COST + (buy_amount if has_initial_buy else 0)  # FIXED: 0.005 + optional buy
        
        if current_balance < required_balance:
            return {
                'status': 'error',
                'message': f'Insufficient balance. FIXED requirement: {required_balance:.6f} SOL (10x cheaper!). Current: {current_balance:.6f} SOL'
            }
        
        # Get user keypair
        user_secret = base58.b58decode(user_wallet["private"])
        user_keypair = SoldersKeypair.from_bytes(user_secret)
        
        # Prepare data for YOUR Node.js script with FIXED parameters
        enhanced_node_params = {
            'mintKeypair': base64.b64encode(bytes(keypair)).decode(),
            'creatorKeypair': base64.b64encode(bytes(user_keypair)).decode(),
            'name': metadata['name'][:32],
            'symbol': metadata['symbol'][:10],
            'decimals': metadata['decimals'],
            'totalSupply': metadata['totalSupply'],
            'uri': metadata['uri'],
            'initialBuyAmount': buy_amount if has_initial_buy else 0,
            'creatorBalance': current_balance,
            'expectedLockSuffix': True,
            
            # FIXED: Enhanced parameters for your script
            'costFixed': True,
            'minCostSOL': LAUNCHLAB_MIN_COST,  # Tell your script about cheaper cost
            'costOptimized': True,
            'tradingReady': True,
            'dexScreenerReady': True,
            'cheaperPricing': True,
            'savings': "10x cheaper than before",
            
            # LaunchLab specific parameters
            'fundingTarget': 85,  # 85 SOL target
            'migrateType': 'cpmm',  # Use CPMM for better liquidity
            'platform': 'Enhanced LOCK System'
        }
        
        # Write parameters to temp file for YOUR script
        params_file = 'lock_token_params.json'
        with open(params_file, 'w') as f:
            json.dump(enhanced_node_params, f, indent=2)
        
        logger.info(f"Executing your create_real_launchlab_token.js with FIXED pricing...")
        
        try:
            # FIXED: Handle Unicode properly for Windows and run YOUR script
            result = subprocess.run([
                'node', script_path, params_file
            ], 
            capture_output=True, 
            text=True, 
            timeout=300,  # 5 minute timeout for LaunchLab
            cwd=os.getcwd(),
            encoding='utf-8',  # FIXED: Force UTF-8 encoding
            errors='ignore'    # FIXED: Ignore decode errors
            )
            
            logger.info(f"Your script process return code: {result.returncode}")
            
            # FIXED: Handle stdout/stderr safely
            stdout_safe = result.stdout.encode('utf-8', errors='ignore').decode('utf-8') if result.stdout else ""
            stderr_safe = result.stderr.encode('utf-8', errors='ignore').decode('utf-8') if result.stderr else ""
            
            logger.info(f"Your script stdout: {stdout_safe}")
            if stderr_safe:
                logger.info(f"Your script stderr: {stderr_safe}")
            
            if result.returncode == 0:
                # Parse the JSON response from YOUR script
                output_lines = stdout_safe.strip().split('\n')
                json_output = None
                
                # Find the JSON response (should be the last valid JSON line)
                for line in reversed(output_lines):
                    try:
                        json_output = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
                
                if json_output and json_output.get('status') == 'success':
                    logger.info(f"SUCCESS: LOCK Token creation successful with your script!")
                    
                    # FINAL VERIFICATION: Check that address ends with exact "LOCK"
                    returned_mint = json_output.get('mintAddress', '')
                    address_ok = returned_mint.endswith('LOCK') or returned_mint.endswith('LOCK')
                    
                    if not address_ok:
                        logger.error(f"CRITICAL: Your script returned address {returned_mint} doesn't end with LOCK!")
                        return {
                            'status': 'error',
                            'message': f'Token created but address verification failed: {returned_mint}'
                        }
                    
                    logger.info(f"FINAL SUCCESS: Token created with LOCK address: {returned_mint}")
                    logger.info(f"Pool ID: {json_output.get('poolId', 'N/A')}")
                    
                    # Wait for confirmation
                    await asyncio.sleep(1)
                    
                    return {
                        'status': 'success',
                        'signature': json_output.get('signature'),
                        'mint': returned_mint,
                        'pool_id': json_output.get('poolId'),
                        'pool_address': json_output.get('poolAddress', json_output.get('poolId')),
                        'bonding_curve_address': json_output.get('bondingCurveAddress', json_output.get('poolId')),
                        'initial_buy_signature': json_output.get('initialBuySignature'),
                        'verified_on_chain': True,
                        'verified_lock_suffix': address_ok,
                        'funding_target': json_output.get('fundingTarget', 85),
                        'total_supply': json_output.get('totalSupply'),
                        'script_used': script_path,
                        'is_tradeable': json_output.get('isTradeable', True),
                        'is_dexscreener_ready': json_output.get('dexScreenerReady', True),
                        'has_launchlab': json_output.get('hasLaunchLab', True),
                        'raydium_url': json_output.get('raydiumUrl'),
                        'solscan_url': json_output.get('solscanUrl'),
                        'cost_fixed': True,
                        'creation_cost': LAUNCHLAB_MIN_COST,
                        'cost_savings': '10x cheaper'
                    }
                else:
                    # Handle error response from YOUR script
                    error_msg = "Token creation failed"
                    if json_output:
                        error_msg = json_output.get('message', error_msg)
                        technical_error = json_output.get('technical_error')
                        if technical_error:
                            logger.error(f"Technical error from your script: {technical_error}")
                    
                    logger.warning(f"Your script failed: {error_msg}")
                    return {
                        'status': 'error',
                        'message': f'Script error: {error_msg}'
                    }
            else:
                error_msg = stderr_safe or stdout_safe or f"Your script failed with return code {result.returncode}"
                logger.error(f"Your script failed with return code {result.returncode}: {error_msg}")
                
                # Check for specific errors
                if 'config not found' in error_msg.lower():
                    logger.error("Raydium LaunchLab configuration missing!")
                    return {
                        'status': 'error',
                        'message': 'Raydium LaunchLab configuration missing. Using simplified token creation.'
                    }
                
                return {
                    'status': 'error',
                    'message': f'Script failed: {error_msg}'
                }
                    
        except subprocess.TimeoutExpired:
            logger.error(f"Your script timeout (5 minutes)")
            return {'status': 'error', 'message': 'Script timeout (5 minutes)'}
        except Exception as e:
            logger.error(f"Subprocess error with your script: {e}")
            return {'status': 'error', 'message': f'Script execution error: {str(e)}'}
        
    except Exception as e:
        logger.error(f"Error in LaunchLab token creation: {e}")
        return {'status': 'error', 'message': get_user_friendly_error_message(str(e))}
    finally:
        # Clean up temp file
        try:
            if os.path.exists('lock_token_params.json'):
                os.remove('lock_token_params.json')
        except:
            pass

# HELPER FUNCTIONS FOR TOKEN CREATION
async def verify_token_on_chain(mint_address, max_attempts=10):
    """
    Verify that the token exists and is searchable on-chain
    """
    rpc_endpoints = [
        "https://api.mainnet-beta.solana.com",
        "https://rpc.ankr.com/solana", 
        "https://solana-api.projectserum.com"
    ]
    
    for attempt in range(max_attempts):
        for rpc_url in rpc_endpoints:
            try:
                # Check if mint account exists
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getAccountInfo",
                    "params": [
                        mint_address,
                        {"commitment": "confirmed", "encoding": "base64"}
                    ]
                }
                
                response = requests.post(rpc_url, json=payload, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    if "result" in data and data["result"]["value"] is not None:
                        logger.info(f"Token {mint_address} verified on {rpc_url}")
                        return True
                        
            except Exception as e:
                logger.warning(f"Verification attempt failed on {rpc_url}: {e}")
                continue
        
        # Wait before next attempt
        if attempt < max_attempts - 1:
            await asyncio.sleep(0.5)
    
    return False

def setup_nodejs_environment():
    """
    FIXED: Enhanced Node.js environment setup with correct function references
    Returns: True if ready, False if missing components (but allows bot to start)
    """
    global NODEJS_AVAILABLE, NODEJS_SETUP_MESSAGE
    
    try:
        # Check if Node.js is available
        node_result = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=10)
        if node_result.returncode != 0:
            NODEJS_SETUP_MESSAGE = "Node.js not installed or not in PATH. Please install Node.js 18+ to create tokens."
            return False
        
        node_version = node_result.stdout.strip()
        logger.info(f"Node.js version: {node_version}")
        
        # Check Node.js version (need 18+)
        try:
            version_number = int(node_version.replace('v', '').split('.')[0])
            if version_number < 18:
                logger.warning(f"Node.js version {node_version} may be too old. Recommended: v18+")
                NODEJS_SETUP_MESSAGE = f"Node.js version {node_version} is too old. Please install Node.js 18+."
                return False
        except:
            pass
        
        # Check if package.json exists
        if not os.path.exists('package.json'):
            logger.warning("package.json not found. Token creation will be limited.")
            NODEJS_SETUP_MESSAGE = (
                "Missing package.json with Raydium LaunchLab dependencies.\n"
                "Create package.json with required dependencies:\n"
                "- @raydium-io/raydium-sdk-v2\n"
                "- @solana/web3.js\n"
                "- @solana/spl-token\n"
                "- bn.js\n"
                "- decimal.js"
            )
            return False
        
        # Check package.json for required dependencies
        try:
            with open('package.json', 'r') as f:
                package_data = json.load(f)
                
            dependencies = package_data.get('dependencies', {})
            required_deps = [
                '@raydium-io/raydium-sdk-v2',
                '@solana/web3.js', 
                '@solana/spl-token',
                'bn.js',
                'decimal.js'
            ]
            
            missing_deps = [dep for dep in required_deps if dep not in dependencies]
            
            if missing_deps:
                logger.warning(f"Missing required dependencies: {missing_deps}")
                NODEJS_SETUP_MESSAGE = f"Missing required dependencies in package.json: {', '.join(missing_deps)}"
                return False
                
        except Exception as e:
            logger.warning(f"Error reading package.json: {e}")
            NODEJS_SETUP_MESSAGE = f"Error reading package.json: {str(e)}"
            return False
        
        # Check if node_modules exists
        if not os.path.exists('node_modules'):
            logger.warning("node_modules not found. Run 'npm install' to install dependencies.")
            NODEJS_SETUP_MESSAGE = "Dependencies not installed. Please run 'npm install' to install required packages."
            return False
        
        # Check if your creation script exists
        script_path = "create_real_launchlab_token.js"
        
        if not os.path.exists(script_path):
            logger.warning(f"Your LaunchLab creation script not found: {script_path}")
            NODEJS_SETUP_MESSAGE = (
                f"Missing your token creation script: {script_path}\n\n"
                f"Please ensure create_real_launchlab_token.js is present.\n"
                f"This script handles the Raydium LaunchLab token creation."
            )
            return False
            
        logger.info(f"Your script found: {script_path}")
        
        # Test the main script quickly
        try:
            test_result = subprocess.run([
                'node', '-e', 'const { Connection } = require("@solana/web3.js"); console.log("SDK OK");'
            ], capture_output=True, text=True, timeout=10)
            
            if test_result.returncode != 0:
                NODEJS_SETUP_MESSAGE = f"Solana SDK test failed: {test_result.stderr}"
                return False
        except Exception as e:
            NODEJS_SETUP_MESSAGE = f"Node.js test failed: {str(e)}"
            return False
        
        # All checks passed
        logger.info("Node.js environment ready for LOCK token creation!")
        return True
        
    except Exception as e:
        logger.warning(f"Node.js environment check failed: {e}")
        NODEJS_SETUP_MESSAGE = f"Node.js environment check failed: {str(e)}. Token creation features will be limited."
        return False

def get_user_friendly_error_message(error_msg):
    """
    Enhanced error message conversion with specific Solana error handling
    """
    error_lower = error_msg.lower()
    
    if "attempt to debit an account but found no record of a prior credit" in error_lower:
        return f"Your wallet needs more SOL. Please add at least {LAUNCHLAB_MIN_COST} SOL to your wallet and try again."
    elif "insufficient balance" in error_lower or "insufficient funds" in error_lower:
        return f"Insufficient SOL balance. FIXED: Only {LAUNCHLAB_MIN_COST} SOL required (10x cheaper!). Please add more SOL."
    elif "account not found" in error_lower:
        return "Wallet account not found. Please fund your wallet with SOL first."
    elif "timeout" in error_lower:
        return "Network timeout. Please try again in a few minutes."
    elif "simulation failed" in error_lower:
        return "Transaction simulation failed. Your wallet might need more SOL or the network is congested."
    elif "blockhash" in error_lower:
        return "Network error. Please try again in a moment."
    elif "node.js" in error_lower or "system" in error_lower:
        return "System error. Please contact support if this persists."
    elif "network" in error_lower:
        return "Network error. Please check your connection and try again."
    elif "dependencies missing" in error_lower:
        return "Node.js setup incomplete. Please run 'npm install' and restart the bot."
    else:
        return f"Token creation failed: {error_msg}"

# ----- SIMPLIFIED KEYBOARD FUNCTIONS -----
def get_simplified_launch_keyboard(context, confirm=False):
    """Simplified keyboard with skip buttons"""
    keyboard = []
    
    if confirm:
        keyboard.append([
            InlineKeyboardButton("🚀 Launch LOCK Token", callback_data=CALLBACKS["launch_confirm_yes"]),
        ])
        keyboard.append([
            InlineKeyboardButton("✏️ Edit", callback_data=CALLBACKS["launch_change_buy_amount"])
        ])
    else:
        # Show skip button for optional steps
        current_step = context.user_data.get("launch_step_index", 0)
        if current_step < len(LAUNCH_STEPS_SIMPLIFIED):
            step_key, _ = LAUNCH_STEPS_SIMPLIFIED[current_step]
            if step_key in ["description", "website", "twitter", "buy_amount"]:
                keyboard.append([
                    InlineKeyboardButton("⏭️ Skip", callback_data=f"skip_{step_key}")
                ])
    
    keyboard.append([
        InlineKeyboardButton("🏠 Main Menu", callback_data=CALLBACKS["start"])
    ])
    return InlineKeyboardMarkup(keyboard)

async def prompt_simplified_launch_step(update_obj, context):
    """Simplified step prompting"""
    index = context.user_data.get("launch_step_index", 0)
    
    if not context.user_data.get("user_id") and hasattr(update_obj, "effective_user"):
        context.user_data["user_id"] = update_obj.effective_user.id
    
    # Clean up previous message
    if "last_prompt_msg_id" in context.user_data:
        try:
            if hasattr(update_obj, "message") and update_obj.message:
                await update_obj.message.bot.delete_message(
                    update_obj.message.chat_id, 
                    context.user_data["last_prompt_msg_id"]
                )
        except Exception:
            pass
    
    if index < len(LAUNCH_STEPS_SIMPLIFIED):
        step_key, prompt_text = LAUNCH_STEPS_SIMPLIFIED[index]
        keyboard = get_simplified_launch_keyboard(context, confirm=False)
        
        if hasattr(update_obj, "callback_query") and update_obj.callback_query:
            sent_msg = await update_obj.callback_query.message.reply_text(
                prompt_text, 
                reply_markup=keyboard, 
                parse_mode="Markdown"
            )
        elif hasattr(update_obj, "message") and update_obj.message:
            sent_msg = await update_obj.message.reply_text(
                prompt_text, 
                reply_markup=keyboard, 
                parse_mode="Markdown"
            )
        context.user_data["last_prompt_msg_id"] = sent_msg.message_id
        
    else:
        # Show simplified review screen
        await show_simplified_review(update_obj, context)

async def show_simplified_review(update_obj, context):
    """Simplified review screen with automatic defaults"""
    coin_data = context.user_data.get("coin_data", {})
    
    # Apply automatic defaults
    coin_data.update(SIMPLIFIED_DEFAULTS)
    context.user_data["coin_data"] = coin_data
    
    # Get pool status for instant creation info
    pool_info = "Real-time generation (10-30 min)"
    if LOCK_ADDRESS_POOL:
        available = LOCK_ADDRESS_POOL.count_available()
        if available > 0:
            pool_info = f"⚡ INSTANT ({available} addresses ready)"
        else:
            pool_info = "Pool empty - will generate live"
    
    # Handle buy amount
    buy_amount_raw = coin_data.get('buy_amount')
    has_initial_buy = False
    buy_amount_display = "None"
    
    if buy_amount_raw is not None and buy_amount_raw != 0:
        try:
            buy_amount = float(buy_amount_raw)
            if buy_amount > 0:
                has_initial_buy = True
                buy_amount_display = f"{buy_amount} SOL"
        except (ValueError, TypeError):
            pass
    
    # Simplified summary
    summary = (
        f"*🔒 LOCK Token Review - SIMPLIFIED*\n\n"
        f"*Token Details:*\n"
        f"• Name: {coin_data.get('name', 'Not set')}\n"
        f"• Symbol: {coin_data.get('ticker', 'Not set')}\n"
        f"• Supply: 1,000,000,000 (1B) 📊\n"
        f"• Decimals: 9 ⚙️\n"
        f"• Initial Buy: {buy_amount_display}\n\n"
        f"*Features:*\n"
        f"• Logo: {'✅' if coin_data.get('image') else '❌'}\n"
        f"• Description: {'✅' if coin_data.get('description') else '➖'}\n"
        f"• Website: {'✅' if coin_data.get('website') else '➖'}\n"
        f"• Twitter: {'✅' if coin_data.get('twitter') else '➖'}\n\n"
        f"*Contract & Pricing:*\n"
        f"• Address will end with: *LOCK*\n"
        f"• {pool_info}\n"
        f"• Platform: Raydium LaunchLab\n"
        f"• Cost: {LAUNCHLAB_MIN_COST} SOL (FIXED - 10x cheaper!)\n\n"
        f"Ready to launch your LOCK token?"
    )
    
    keyboard = get_simplified_launch_keyboard(context, confirm=True)
    
    if hasattr(update_obj, "callback_query") and update_obj.callback_query:
        sent_msg = await update_obj.callback_query.message.reply_text(
            summary, 
            reply_markup=keyboard, 
            parse_mode="Markdown"
        )
    elif hasattr(update_obj, "message") and update_obj.message:
        sent_msg = await update_obj.message.reply_text(
            summary, 
            reply_markup=keyboard, 
            parse_mode="Markdown"
        )
    context.user_data["last_prompt_msg_id"] = sent_msg.message_id

def start_simplified_launch_flow(context):
    """Start the simplified LOCK launch flow"""
    context.user_data["launch_step_index"] = 0
    context.user_data["coin_data"] = {}

# ----- ENHANCED LAUNCH CONFIRMATION WITH POOL STATUS -----
async def process_launch_confirmation_fixed(query, context):
    """
    ENHANCED: Launch confirmation with instant address pool
    """
    coin_data = context.user_data.get("coin_data", {})
    user_id = query.from_user.id

    # Check wallet exists
    wallet = user_wallets.get(user_id)
    if not wallet:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("No wallet found. Please create a wallet first.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return

    # Check if Node.js is available
    if not NODEJS_AVAILABLE:
        keyboard = [
            [InlineKeyboardButton("Setup Instructions", callback_data=CALLBACKS["setup_nodejs"])],
            [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
        ]
        await query.message.edit_text(
            f"Node.js Setup Required\n\n"
            f"To create LOCK tokens with FIXED pricing ({LAUNCHLAB_MIN_COST} SOL):\n\n"
            f"{NODEJS_SETUP_MESSAGE}\n\n"
            f"Please complete the setup and restart the bot.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Use INSTANT token creation with address pool
    async def update_progress(message_text):
        try:
            await query.message.edit_text(message_text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Progress update failed: {e}")

    result = await create_lock_token_with_raydium_fixed_instant(coin_data, wallet, update_progress)
    
    if result.get('status') != 'success':
        error_message = result.get('message', 'Unknown error occurred')
        
        # Check if it's a Node.js setup issue
        if result.get('requires_nodejs_setup'):
            keyboard = [
                [InlineKeyboardButton("Setup Instructions", callback_data=CALLBACKS["setup_nodejs"])],
                [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
            ]
        # Enhanced error handling with FIXED pricing info
        elif 'insufficient' in error_message.lower() or 'balance' in error_message.lower():
            required = result.get('funding_required', LAUNCHLAB_MIN_COST)
            current = result.get('current_balance', 0)
            
            keyboard = [
                [InlineKeyboardButton("Check Balance", callback_data=CALLBACKS["refresh_balance"])],
                [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
            ]
            
            funding_message = (
                f"LOCK Token Creation Failed\n\n"
                f"Reason: {error_message}\n\n"
                f"FIXED PRICING - 10x Cheaper!\n"
                f"• Old cost: 0.05 SOL\n"
                f"• New cost: {LAUNCHLAB_MIN_COST} SOL\n"
                f"• You save: 0.045 SOL per token!\n\n"
                f"Requirements:\n"
                f"• FIXED: {LAUNCHLAB_MIN_COST} SOL for token creation\n"
                f"• Additional SOL if you want initial liquidity\n"
                f"• Small amount for transaction fees\n\n"
                f"Please add SOL to your wallet:\n"
                f"`{wallet['public']}`"
            )
            error_message = funding_message
        else:
            keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        
        await query.message.edit_text(error_message,
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return

    # SUCCESS: Enhanced success handling with instant address info
    tx_signature = result.get('signature')
    vanity_address = result.get('mint')
    attempts = result.get('attempts', 0)
    was_instant = result.get('was_instant', False)
    pool_status = result.get('pool_status', 'Unknown')
    is_pure_creation = result.get('pure_creation', True)
    funding_used = result.get('funding_used', LAUNCHLAB_MIN_COST)
    balance_after = result.get('wallet_balance_after', 0)
    cost_savings = result.get('savings', '10x cheaper')
    creation_cost_old = result.get('creation_cost_old', 0.05)
    creation_cost_new = result.get('creation_cost_new', LAUNCHLAB_MIN_COST)
    
    # Build enhanced success message with instant address info
    tx_link = f"https://solscan.io/tx/{tx_signature}"
    chart_url = f"https://raydium.io/launchpad/token/?mint={vanity_address}"

    # Address generation info
    if was_instant:
        address_info = (
            f"⚡ INSTANT ADDRESS RETRIEVAL!\n"
            f"• Time saved: 10-30 minutes\n"
            f"• Pool status: {pool_status}\n"
            f"• Zero wait time!"
        )
    else:
        address_info = (
            f"Generated Address: {attempts:,} attempts\n"
            f"• Pool status: {pool_status}\n"
            f"• Next time will be instant!"
        )

    if is_pure_creation:
        mode_description = (
            f"Launch Mode: Pure Creation\n"
            f"• Token created without initial liquidity\n"
            f"• Ready for bonding curve trading\n"
            f"• FIXED Cost: {funding_used:.6f} SOL"
        )
    else:
        initial_buy = result.get('initial_liquidity_sol', 0)
        mode_description = (
            f"Launch Mode: With Bonding Curve Liquidity\n"
            f"• Initial Liquidity: {initial_buy} SOL\n"
            f"• Total Cost: {funding_used:.6f} SOL\n"
            f"• Immediate trading available"
        )

    message = (
        f"LOCK Token Launched - INSTANT EDITION!\n\n"
        f"{coin_data.get('name')} ({coin_data.get('ticker')})\n"
        f"Contract: `{vanity_address}`\n\n"
        + address_info + "\n\n"
        f"💰 COST SAVINGS: {cost_savings}\n"
        f"• Old cost: {creation_cost_old:.6f} SOL\n"
        f"• New cost: {creation_cost_new:.6f} SOL\n"
        f"• You saved: {creation_cost_old - creation_cost_new:.6f} SOL!\n\n"
        f"Token Details:\n"
        f"• Supply: {coin_data.get('total_supply', 1_000_000_000):,}\n"
        f"• Wallet Balance: {balance_after:.6f} SOL remaining\n\n"
        + mode_description + "\n\n"
        f"LaunchLab Features:\n"
        f"• Raydium LaunchLab bonding curve\n"
        f"• Auto-graduation at 85 SOL\n"
        f"• DexScreener ready\n"
        f"• Professional token infrastructure\n\n"
        f"Your LOCK token is live and tradeable!\n\n"
        f"Contract: `{vanity_address}`"
    )
    
    keyboard = [
        [InlineKeyboardButton("View on Raydium", url=chart_url)],
        [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/{vanity_address}")],
        [InlineKeyboardButton("View Transaction", url=tx_link)],
        [InlineKeyboardButton("Launch Another LOCK", callback_data=CALLBACKS["launch"])],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
    ]

    # Save to user coins with enhanced tracking
    if user_id not in user_coins:
        user_coins[user_id] = []
    user_coins[user_id].append({
        "name": coin_data.get("name", "Unnamed LOCK Token"),
        "ticker": coin_data.get("ticker", ""),
        "tx_link": tx_link,
        "chart_url": chart_url,
        "mint": vanity_address,
        "is_vanity": True,
        "vanity_suffix": "LOCK",
        "is_full_lock": True,
        "was_instant": was_instant,
        "pool_status": pool_status,
        "generation_attempts": attempts,
        "has_liquidity": not is_pure_creation,
        "initial_buy_amount": result.get('initial_liquidity_sol', 0),
        "platform": "Raydium LaunchLab",
        "funding_used": funding_used,
        "cost_fixed": True,
        "cost_savings": cost_savings,
        "creation_cost": creation_cost_new,
        "creation_cost_old": creation_cost_old,
        "trading_ready": True,
        "dexscreener_ready": result.get('is_dexscreener_ready', True),
        "created_at": datetime.now().isoformat()
    })
    
    # Clear launch data
    context.user_data.pop("launch_step_index", None)
    context.user_data.pop("coin_data", None)
    
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- LAUNCHED TOKENS DISPLAY WITH INSTANT ADDRESS INFO -----
async def show_launched_coins(update: Update, context):
    """Show user's launched LOCK tokens with instant address status"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_coins_list = user_coins.get(user_id, [])
    
    if not user_coins_list:
        pool_info = ""
        if LOCK_ADDRESS_POOL:
            available = LOCK_ADDRESS_POOL.count_available()
            if available > 0:
                pool_info = f"\n\n⚡ {available} LOCK addresses ready for instant creation!"
            else:
                pool_info = "\n\nPool empty - addresses will be generated live"
        
        message = f"You haven't launched any LOCK tokens yet.\n\nStart creating your LOCK collection today!\n\nFIXED PRICING: Only {LAUNCHLAB_MIN_COST} SOL per token (10x cheaper!)\nAll your tokens will have contract addresses ending with '{CONTRACT_SUFFIX}' - Premium branding guaranteed!{pool_info}"
        keyboard = [
            [InlineKeyboardButton("Launch First LOCK Token", callback_data=CALLBACKS["launch"])],
            [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
        ]
    else:
        message = f"Your LOCK Token Portfolio ({len(user_coins_list)} tokens):\n\n"
        
        # Calculate total savings and instant count
        total_savings = 0
        total_spent = 0
        instant_count = 0
        for coin in user_coins_list:
            if coin.get("cost_fixed"):
                old_cost = coin.get("creation_cost_old", 0.05)
                new_cost = coin.get("creation_cost", LAUNCHLAB_MIN_COST)
                total_savings += (old_cost - new_cost)
            total_spent += coin.get("funding_used", LAUNCHLAB_MIN_COST)
            if coin.get("was_instant"):
                instant_count += 1
        
        message += f"💰 *TOTAL SAVINGS: {total_savings:.6f} SOL*\n"
        message += f"📊 Total Spent: {total_spent:.6f} SOL\n"
        message += f"🔒 All with LOCK suffix\n"
        message += f"⚡ Instant creations: {instant_count}/{len(user_coins_list)}\n\n"
        
        for i, coin in enumerate(user_coins_list[-10:], 1):  # Show last 10 tokens
            created_date = coin.get("created_at", "")
            has_liquidity = coin.get("has_liquidity", False)
            cost_fixed = coin.get("cost_fixed", False)
            creation_cost = coin.get("creation_cost", LAUNCHLAB_MIN_COST)
            trading_ready = coin.get("trading_ready", True)
            was_instant = coin.get("was_instant", False)
            
            if created_date:
                try:
                    date_obj = datetime.fromisoformat(created_date.replace('Z', '+00:00'))
                    date_str = date_obj.strftime("%m/%d %H:%M")
                except:
                    date_str = "Unknown"
            else:
                date_str = "Unknown"
            
            # Show last 8 chars to highlight the LOCK suffix
            contract_display = f"...{coin['mint'][-8:]}" if len(coin['mint']) > 8 else coin['mint']
            
            message += f"{i}. *{coin['ticker']}* - {coin['name']}\n"
            message += f"   Contract: `{contract_display}`\n"
            message += f"   Status: 🔒 FULL LOCK {'⚡' if was_instant else '🔄'}\n"
            message += f"   Created: {date_str}\n"
            message += f"   Mode: {'With Liquidity' if has_liquidity else 'Pure Creation'}\n"
            if cost_fixed:
                message += f"   Cost: {creation_cost:.6f} SOL (FIXED - 10x cheaper!)\n"
            else:
                message += f"   Cost: {coin.get('funding_used', 0):.6f} SOL\n"
            message += f"   Trading: {'✅' if trading_ready else '○'}\n"
            message += f"\n"
        
        if len(user_coins_list) > 10:
            message += f"... and {len(user_coins_list) - 10} more LOCK tokens\n\n"
        
        # Pool status info
        pool_info = ""
        if LOCK_ADDRESS_POOL:
            available = LOCK_ADDRESS_POOL.count_available()
            if available > 0:
                pool_info = f"⚡ Next creation will be INSTANT ({available} addresses ready)!"
            else:
                pool_info = "Next creation will generate live (10-30 min)"
        
        message += f"All tokens created with enhanced LOCK system!\nFixed pricing: {LAUNCHLAB_MIN_COST} SOL per token (10x cheaper!)\n{pool_info}"
        
        keyboard = [
            [InlineKeyboardButton("Launch Another LOCK", callback_data=CALLBACKS["launch"])],
            [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
        ]
    
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- NODEJS SETUP INSTRUCTIONS -----
async def show_nodejs_setup_instructions(update: Update, context):
    """Show Node.js setup instructions with FIXED pricing info"""
    query = update.callback_query
    await query.answer()
    
    setup_instructions = (
        f"Node.js Setup Instructions\n\n"
        f"To create LOCK tokens ending with '{CONTRACT_SUFFIX}' for only {LAUNCHLAB_MIN_COST} SOL:\n\n"
        f"*1. Install Node.js 18+*\n"
        f"Download from: nodejs.org\n\n"
        f"*2. Create package.json*\n"
        f"Required dependencies:\n"
        f"• @raydium-io/raydium-sdk-v2\n"
        f"• @solana/web3.js\n"
        f"• @solana/spl-token\n"
        f"• bn.js\n"
        f"• decimal.js\n\n"
        f"*3. Install Dependencies*\n"
        f"Run: `npm install`\n\n"
        f"*4. Your Script*\n"
        f"Ensure create_real_launchlab_token.js is present\n\n"
        f"*Current Status:*\n"
        f"{NODEJS_SETUP_MESSAGE}\n\n"
        f"*FIXED PRICING BENEFITS:*\n"
        f"• Only {LAUNCHLAB_MIN_COST} SOL per token (was 0.05!)\n"
        f"• 10x cheaper token creation\n"
        f"• Save 0.045 SOL per token\n\n"
        f"Once setup is complete, restart the bot to enable LOCK token creation."
    )
    
    keyboard = [
        [InlineKeyboardButton("Check Status Again", callback_data=CALLBACKS["settings"])],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
    ]
    
    await query.message.edit_text(setup_instructions, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- SUBSCRIPTION FEATURES -----
def process_subscription_payment(user_id, plan):
    subscription_cost = SUBSCRIPTION_PRICING.get(plan, 0)
    wallet = user_wallets.get(user_id)
    if not wallet:
        return {"status": "error", "message": "No wallet found"}
    
    current_balance = get_wallet_balance(wallet["public"])
    if current_balance < subscription_cost:
        return {"status": "error", "message": f"Insufficient balance"}
    
    # For testing - just activate subscription
    fake_signature = base58.b58encode(os.urandom(32)).decode()[:44]
    
    now = datetime.now(timezone.utc)
    if plan == "weekly":
        expires_at = now + timedelta(days=7)
    elif plan == "monthly":
        expires_at = now + timedelta(days=30)
    else:
        expires_at = None
    
    user_subscriptions[user_id] = {
        "active": True,
        "plan": plan,
        "amount": subscription_cost,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "tx_signature": fake_signature
    }
    return {"status": "success", "message": "Subscription activated"}

async def show_subscription_details(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    sub_status = get_subscription_status(user_id)
    
    if sub_status["active"]:
        time_left_str = ""
        if sub_status["time_left"]:
            days = sub_status["time_left"].days
            hours, remainder = divmod(sub_status["time_left"].seconds, 3600)
            if days > 0:
                time_left_str = f"\nTime left: {days} days, {hours} hours"
            else:
                time_left_str = f"\nTime left: {hours} hours"
        
        nodejs_status = "Ready" if NODEJS_AVAILABLE else "Setup Required"
        
        # Pool status
        pool_info = ""
        if LOCK_ADDRESS_POOL:
            available = LOCK_ADDRESS_POOL.count_available()
            if available > 0:
                pool_info = f"\n\n{available} LOCK addresses ready for instant creation!"
        
        message = (
            f"*Subscription Active!*\n"
            f"Plan: {sub_status['plan'].capitalize()}{time_left_str}\n\n"
            f"Node.js Status: {nodejs_status}{pool_info}\n\n"
            f"You can now create LOCK tokens ending with '{CONTRACT_SUFFIX}' on Raydium LaunchLab!\n\n"
            f"FIXED PRICING: Only {LAUNCHLAB_MIN_COST} SOL per token (10x cheaper!)"
        )
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
    else:
        nodejs_status = "Ready" if NODEJS_AVAILABLE else "Setup Required"
        
        # Pool status
        pool_info = ""
        if LOCK_ADDRESS_POOL:
            available = LOCK_ADDRESS_POOL.count_available()
            if available > 0:
                pool_info = f"\n\n{available} LOCK addresses ready for instant creation!"
        
        message = (
            f"Subscribe to create LOCK tokens:\n\n"
            f"Unlock the ability to create tokens with contract addresses ending in '{CONTRACT_SUFFIX}' on Raydium LaunchLab.\n\n"
            f"FIXED PRICING: Only {LAUNCHLAB_MIN_COST} SOL per token (10x cheaper!)\n\n"
            f"Node.js Status: {nodejs_status}{pool_info}"
        )
        keyboard = [
            [InlineKeyboardButton("Weekly - FREE", callback_data="subscription:weekly")],
            [InlineKeyboardButton("Monthly - 3 SOL", callback_data="subscription:monthly")],
            [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
        ]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def process_subscription_plan(update: Update, context):
    query = update.callback_query
    await query.answer()
    plan = query.data.split(":")[1]
    user_id = query.from_user.id
    
    result = process_subscription_payment(user_id, plan)
    
    if result["status"] == "success":
        nodejs_status = "Ready" if NODEJS_AVAILABLE else "Setup Required"
        
        # Pool status
        pool_info = ""
        if LOCK_ADDRESS_POOL:
            available = LOCK_ADDRESS_POOL.count_available()
            if available > 0:
                pool_info = f"\n\n{available} LOCK addresses ready for instant creation!"
        
        message = (
            f"{plan.capitalize()} subscription activated!\n\n"
            f"Node.js Status: {nodejs_status}{pool_info}\n\n"
            f"You can now create LOCK tokens ending with '{CONTRACT_SUFFIX}' on Raydium LaunchLab!\n\n"
            f"FIXED PRICING: Only {LAUNCHLAB_MIN_COST} SOL per token (10x cheaper!)"
        )
    else:
        message = f"Subscription failed: {result['message']}"
    
    keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- BUNDLE MANAGEMENT -----
async def show_bundle(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    wallet = user_wallets.get(user_id)
    if not wallet:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("No wallet found.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return
    if "bundle" not in wallet:
        bundle_list = []
        for _ in range(7):
            mnemonic, public_key, private_key = generate_solana_wallet()
            bundle_list.append({"public": public_key, "private": private_key, "mnemonic": mnemonic, "balance": 0})
        wallet["bundle"] = bundle_list
    
    message = f"Bundle Wallets for LOCK Token Management\n\n"
    for idx, b_wallet in enumerate(wallet["bundle"], start=1):
        message += f"{idx}. `{b_wallet['public']}`\n"
    
    keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- MESSAGE HANDLERS -----
async def import_private_key(update: Update, context):
    user_id = update.message.from_user.id
    user_private_key = update.message.text.strip()
    try:
        await update.message.delete()
        private_key_bytes = base58.b58decode(user_private_key)
        if len(private_key_bytes) != 64:
            raise ValueError("Invalid private key length")
        keypair = SoldersKeypair.from_bytes(private_key_bytes)
        public_key = str(keypair.pubkey())
        user_wallets[user_id] = {"public": public_key, "private": user_private_key, "mnemonic": None, "balance": 0}
        balance = get_wallet_balance(public_key)
        user_wallets[user_id]["balance"] = balance
        
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await update.message.reply_text(
            f"Wallet imported:\n`{public_key}`\nBalance: {balance:.6f} SOL", 
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await update.message.reply_text(
            f"Import failed: {str(e)}", 
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def handle_skip_button(update: Update, context):
    """Handle skip button presses"""
    query = update.callback_query
    await query.answer()
    
    # Extract step from callback data (e.g., "skip_description")
    step_to_skip = query.data.replace("skip_", "")
    
    # Set the skipped field to None
    context.user_data.setdefault("coin_data", {})[step_to_skip] = None
    
    # Move to next step
    current_index = context.user_data.get("launch_step_index", 0)
    context.user_data["launch_step_index"] = current_index + 1
    
    await prompt_simplified_launch_step(query, context)

async def handle_simplified_text_input(update: Update, context):
    """Handle text input for simplified launch flow"""
    user_input = update.message.text.strip()
    
    # Handle withdraw address input
    if "awaiting_withdraw_dest" in context.user_data:
        success = await handle_withdraw_address_input(update, context)
        if success:
            return
        context.user_data.pop("awaiting_withdraw_dest", None)
        return
    
    # Handle wallet import
    if context.user_data.get("awaiting_import"):
        await import_private_key(update, context)
        context.user_data.pop("awaiting_import", None)
        return
    
    # Handle launch flow
    if "launch_step_index" in context.user_data:
        index = context.user_data.get("launch_step_index", 0)
        
        if index >= len(LAUNCH_STEPS_SIMPLIFIED):
            return
            
        step_key, _ = LAUNCH_STEPS_SIMPLIFIED[index]
        
        # Skip image steps for text
        if step_key == "image":
            await update.message.reply_text("Please send an image file, not text.")
            return
        
        # Handle buy amount validation
        if step_key == "buy_amount":
            if user_input.lower() in ["0", "none", ""]:
                context.user_data.setdefault("coin_data", {})[step_key] = None
            else:
                try:
                    buy_amount = float(user_input)
                    if buy_amount < 0:
                        await update.message.reply_text("Buy amount cannot be negative. Enter 0 for no initial purchase.")
                        return
                    elif buy_amount > 10:  # Simplified limit
                        await update.message.reply_text("Maximum initial purchase is 10 SOL.")
                        return
                    
                    # Check balance with FIXED pricing
                    user_id = update.message.from_user.id
                    wallet = user_wallets.get(user_id)
                    if wallet:
                        current_balance = get_wallet_balance(wallet["public"])
                        required_total = LAUNCHLAB_MIN_COST + buy_amount
                        if current_balance < required_total:
                            await update.message.reply_text(
                                f"Insufficient balance.\n"
                                f"Required: {required_total:.6f} SOL\n"
                                f"Current: {current_balance:.6f} SOL"
                            )
                            return
                    
                    context.user_data.setdefault("coin_data", {})[step_key] = buy_amount
                except ValueError:
                    await update.message.reply_text("Please enter a valid number or 0 for no initial purchase.")
                    return
        
        # Handle optional fields - no more typing "skip"
        elif step_key in ["description", "website", "twitter"]:
            if user_input.lower() in ["", "none"]:
                context.user_data.setdefault("coin_data", {})[step_key] = None
            else:
                context.user_data.setdefault("coin_data", {})[step_key] = user_input
        
        # Handle required fields
        else:
            if step_key == "name" and len(user_input) > 50:
                await update.message.reply_text("Token name too long. Keep it under 50 characters.")
                return
            elif step_key == "ticker" and len(user_input) > 10:
                await update.message.reply_text("Token symbol too long. Keep it under 10 characters.")
                return
            elif step_key == "description" and len(user_input) > 200:  # Simplified limit
                await update.message.reply_text("Description too long. Keep it under 200 characters.")
                return
                
            context.user_data.setdefault("coin_data", {})[step_key] = user_input
        
        # Move to next step
        context.user_data["launch_step_index"] = index + 1
        await prompt_simplified_launch_step(update, context)
        return
    
    # Default response
    await update.message.reply_text("Use the buttons to create LOCK tokens!")

async def handle_withdraw_address_input(update: Update, context):
    """Enhanced withdrawal address handler with validation"""
    user_input = update.message.text.strip()
    destination = user_input
    
    # Validate Solana address format
    if not validate_solana_address(destination):
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await update.message.reply_text(
            "Invalid Solana address format.\n"
            "Please provide a valid Solana address.\n\n"
            "Example: 2TgDLY7xajqMSLS78jY7P1JjDo8jr15chcaz4hhLtXBA",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return False
    
    withdraw_data = context.user_data["awaiting_withdraw_dest"]
    
    # Check if trying to send to same address
    if destination == withdraw_data["from_wallet"]["public"]:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await update.message.reply_text(
            "Cannot send SOL to the same wallet address.\nPlease provide a different destination address.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return False
    
    # Get current balance and calculate withdrawal amounts
    current_balance = get_wallet_balance(withdraw_data["from_wallet"]["public"])
    transaction_fee = 0.000005  # 5000 lamports
    
    if current_balance <= transaction_fee:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await update.message.reply_text(
            f"Insufficient balance for withdrawal.\n"
            f"Current balance: {current_balance:.6f} SOL\n"
            f"Minimum required: {transaction_fee:.6f} SOL (for transaction fees)",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return False
    
    # Calculate withdrawal amounts for each percentage
    max_withdrawable = current_balance - transaction_fee
    amount_25 = round(max_withdrawable * 0.25, 6)
    amount_50 = round(max_withdrawable * 0.50, 6) 
    amount_100 = round(max_withdrawable * 1.0, 6)
    
    # Store destination and amounts in context
    context.user_data["withdraw_destination"] = destination
    context.user_data["withdraw_amounts"] = {
        "25": amount_25,
        "50": amount_50,
        "100": amount_100
    }
    context.user_data["withdraw_wallet"] = withdraw_data["from_wallet"]
    
    # Clear the awaiting flag
    context.user_data.pop("awaiting_withdraw_dest", None)
    
    message = (
        f"Withdrawal Preview\n\n"
        f"From: `{withdraw_data['from_wallet']['public']}`\n"
        f"To: `{destination}`\n\n"
        f"Available: {current_balance:.6f} SOL\n"
        f"Fee: ~{transaction_fee:.6f} SOL\n\n"
        f"Choose withdrawal amount:\n"
        f"• 25% = {amount_25:.6f} SOL\n"
        f"• 50% = {amount_50:.6f} SOL\n" 
        f"• 100% = {amount_100:.6f} SOL"
    )
    
    keyboard = [
        [InlineKeyboardButton(f"25% ({amount_25:.6f} SOL)", callback_data=CALLBACKS["withdraw_25"])],
        [InlineKeyboardButton(f"50% ({amount_50:.6f} SOL)", callback_data=CALLBACKS["withdraw_50"])],
        [InlineKeyboardButton(f"100% ({amount_100:.6f} SOL)", callback_data=CALLBACKS["withdraw_100"])],
        [InlineKeyboardButton("Cancel", callback_data=CALLBACKS["cancel_withdraw_sol"])]
    ]
    
    await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return True

# Handle withdrawal percentages
async def handle_percentage_withdrawal(update: Update, context, percentage: str):
    """Handle withdrawal with proper account status checking"""
    query = update.callback_query
    await query.answer()
    
    destination = context.user_data.get("withdraw_destination")
    amounts = context.user_data.get("withdraw_amounts", {})
    wallet = context.user_data.get("withdraw_wallet")
    
    if not destination or not amounts or not wallet:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text(
            "Withdrawal session expired. Please try again.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    withdrawal_amount = amounts.get(percentage, 0)
    
    if withdrawal_amount <= 0:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text(
            "Invalid withdrawal amount. Please try again.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Show processing message
    await query.message.edit_text(
        f"Processing {percentage}% withdrawal...\n\n"
        f"Amount: {withdrawal_amount:.6f} SOL\n"
        f"To: {destination[:6]}...{destination[-6:]}\n\n"
        f"Checking account status...",
        parse_mode="Markdown"
    )
    
    try:
        # Check account status first
        account_info = get_wallet_balance_enhanced(wallet["public"])
        
        # Handle AccountNotFound issue
        if not account_info.get("can_send", False) and account_info["balance"] > 0:
            await query.message.edit_text(
                f"Account Activation Required\n\n"
                f"Your wallet has SOL but needs activation for sending transactions.\n\n"
                f"Solution: Please deposit at least 0.005 SOL total to fully activate your account, then try again.\n\n"
                f"Current balance: {account_info['balance']:.6f} SOL\n"
                f"Recommended: Add 0.003 SOL more",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Try Anyway", callback_data=f"force_{query.data}")],
                    [InlineKeyboardButton("Cancel", callback_data=CALLBACKS["cancel_withdraw_sol"])]
                ]),
                parse_mode="Markdown"
            )
            return
        
        # Update processing message
        await query.message.edit_text(
            f"Processing {percentage}% withdrawal...\n\n"
            f"Amount: {withdrawal_amount:.6f} SOL\n"
            f"To: {destination[:6]}...{destination[-6:]}\n\n"
            f"Executing transfer...",
            parse_mode="Markdown"
        )
        
        # Execute withdrawal
        result = transfer_sol_ultimate(wallet, destination, withdrawal_amount)
        
        # Clean up context data
        context.user_data.pop("withdraw_wallet", None)
        
        if result["status"] == "success":
            tx_signature = result["signature"]
            tx_link = f"https://solscan.io/tx/{tx_signature}"
            
            # Get updated balance
            new_balance = get_wallet_balance(wallet["public"])
            
            message = (
                f"Withdrawal Complete!\n\n"
                f"Amount: {withdrawal_amount:.6f} SOL ({percentage}%)\n"
                f"To: `{destination}`\n"
                f"New Balance: {new_balance:.6f} SOL\n\n"
                f"Transaction: {tx_link}\n\n"
                f"TX ID: `{tx_signature}`"
            )
            
            keyboard = [
                [InlineKeyboardButton("View on Solscan", url=tx_link)],
                [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
                 InlineKeyboardButton("Withdraw More", callback_data=CALLBACKS["withdraw_sol"])]
            ]
            
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            error_msg = result.get('message', 'Unknown error')
            
            # Provide specific solutions
            if "AccountNotFound" in error_msg or "no record of a prior credit" in error_msg:
                solution = "\n\nSOLUTION: Your account needs more SOL\n1. Deposit 0.05+ SOL total\n2. Wait 2-3 minutes\n3. Try again"
            elif "rent exemption" in error_msg:
                solution = "\n\nSOLUTION: Leave minimum SOL in wallet\n1. Try smaller withdrawal amount\n2. Keep 0.001 SOL minimum"
            else:
                solution = "\n\nTry again in a few minutes or contact support"
            
            message = (
                f"Withdrawal Failed\n\n"
                f"Error: {error_msg}{solution}\n\n"
                f"Your SOL is safe in your wallet."
            )
            keyboard = [
                [InlineKeyboardButton("Try Again", callback_data=CALLBACKS["withdraw_sol"])],
                [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
            ]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            
    except Exception as e:
        logger.error(f"Critical withdrawal error: {e}", exc_info=True)
        
        # Clean up context data
        context.user_data.pop("awaiting_withdraw_dest", None)
        context.user_data.pop("withdraw_destination", None)
        context.user_data.pop("withdraw_amounts", None)
        context.user_data.pop("withdraw_wallet", None)
        
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text(
            f"Critical error. Your funds are safe.\nPlease try again later.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def handle_media_message(update: Update, context):
    if "launch_step_index" in context.user_data:
        index = context.user_data.get("launch_step_index", 0)
        step_key, _ = LAUNCH_STEPS_SIMPLIFIED[index]
        
        if step_key == "image":  # Only handle image for logo
            file = None
            file_size_mb = 0
            
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
                file = await context.bot.get_file(file_id)
                file_size_mb = file.file_size / (1024 * 1024)  # Convert to MB
                filename = f"logo.png"
                
                # Check file size limits
                if file_size_mb > 5:  # Simplified 5MB limit
                    await update.message.reply_text("Logo too large. Maximum size: 5MB")
                    return
                    
            elif update.message.video:
                file_id = update.message.video.file_id
                file = await context.bot.get_file(file_id)
                file_size_mb = file.file_size / (1024 * 1024)
                filename = f"logo.mp4"
                
                if file_size_mb > 10:  # 10MB limit for videos
                    await update.message.reply_text("Video too large. Maximum size: 10MB")
                    return
            
            if file:
                os.makedirs("./downloads", exist_ok=True)
                file_path = f"./downloads/{filename}"
                await file.download_to_drive(file_path)
                
                context.user_data.setdefault("coin_data", {})[step_key] = file_path
                context.user_data["coin_data"][f"{step_key}_filename"] = filename
                context.user_data["launch_step_index"] = index + 1
                
                keyboard = get_simplified_launch_keyboard(context, confirm=False)
                await update.message.reply_text(
                    f"Logo uploaded successfully!\n\nProceeding...",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                await asyncio.sleep(1)
                
                await prompt_simplified_launch_step(update, context)
                return
            else:
                await update.message.reply_text(f"Please send a valid image for your LOCK token logo.")
                return
                
    await handle_simplified_text_input(update, context)

# ----- MAIN MENU WITH POOL STATUS -----
def generate_inline_keyboard():
    pool_status = ""
    if LOCK_ADDRESS_POOL:
        available = LOCK_ADDRESS_POOL.count_available()
        if available > 50:
            pool_status = " ⚡"  # Lightning for instant
        elif available > 10:
            pool_status = " 🟡" 
        else:
            pool_status = " 🔴"
    
    return [
        [InlineKeyboardButton(f"Launch LOCK Token{pool_status}", callback_data=CALLBACKS["launch"])],
        [
            InlineKeyboardButton("Subscription", callback_data=CALLBACKS["subscription"]),
            InlineKeyboardButton("Wallets", callback_data=CALLBACKS["wallets"]),
            InlineKeyboardButton("Settings", callback_data=CALLBACKS["settings"]),
        ],
        [
            InlineKeyboardButton("My LOCK Tokens", callback_data=CALLBACKS["launched_coins"]),
            InlineKeyboardButton("Socials", callback_data=CALLBACKS["socials"]),
        ],
        [InlineKeyboardButton("Refresh", callback_data=CALLBACKS["refresh_balance"])]
    ]

async def start(update: Update, context):
    user_id = update.effective_user.id
    try:
        if user_id not in user_wallets:
            mnemonic, public_key, private_key = generate_solana_wallet()
            user_wallets[user_id] = {"public": public_key, "private": private_key, "mnemonic": mnemonic, "balance": 0}
        wallet_address = user_wallets[user_id]["public"]
        
        balance = get_wallet_balance(wallet_address)
        user_wallets[user_id]["balance"] = balance
        
        # Show wallet funding status for FIXED LaunchLab requirements
        funding_status = "Ready" if balance >= LAUNCHLAB_MIN_COST else "Needs Funding"
        nodejs_status = "Ready" if NODEJS_AVAILABLE else "Setup Required"
        
        # Pool status
        pool_status = "Not Available"
        pool_info = ""
        if LOCK_ADDRESS_POOL:
            available = LOCK_ADDRESS_POOL.count_available()
            if available > 50:
                pool_status = "⚡ Excellent"
                pool_info = f"⚡ {available} LOCK addresses ready for INSTANT creation!"
            elif available > 10:
                pool_status = "🟡 Good"
                pool_info = f"⚡ {available} LOCK addresses available"
            else:
                pool_status = "🔴 Low"
                pool_info = f"⚠️ Only {available} LOCK addresses remaining"
        else:
            pool_info = "Real-time generation only (10-30 min wait)"
        
        welcome_message = (
            f"Welcome to LOCK Token Launcher - SIMPLIFIED EDITION!\n\n"
            f"Create professional tokens with vanity contract addresses ending in '{CONTRACT_SUFFIX}' using Raydium LaunchLab.\n\n"
            f"💰 FIXED PRICING - 10x CHEAPER!\n"
            f"• Old cost: 0.05 SOL per token\n"
            f"• New cost: {LAUNCHLAB_MIN_COST} SOL per token\n"
            f"• You save: 0.045 SOL per token!\n\n"
            f"⚡ INSTANT ADDRESSES:\n"
            f"{pool_info}\n\n"
            f"🚀 SIMPLIFIED CREATION:\n"
            f"• Only 7 steps (was 11!)\n"
            f"• Skip buttons for optional fields\n"
            f"• Auto-defaults: 1B supply, 9 decimals\n"
            f"• Single logo upload only\n\n"
            f"Current Balance: {balance:.6f} SOL\n"
            f"Status: {funding_status}\n"
            f"Node.js: {nodejs_status}\n"
            f"Pool: {pool_status}\n\n"
            "Send SOL to your wallet to get started:\n"
            f"`{wallet_address}`\n\n"
            f"Minimum required: {LAUNCHLAB_MIN_COST} SOL for LaunchLab creation\n"
            "Your funds are safe, but never share your private key."
        )
        reply_markup = InlineKeyboardMarkup(generate_inline_keyboard())
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in start command: {e}", exc_info=True)
        await update.message.reply_text("An error occurred. Please try again.")

async def go_to_main_menu(query, context):
    context.user_data["nav_stack"] = []
    user_id = query.from_user.id
    wallet = user_wallets.get(user_id)
    if wallet:
        wallet_address = wallet["public"]
        balance = get_wallet_balance(wallet_address)
        wallet["balance"] = balance
        funding_status = "Ready" if balance >= LAUNCHLAB_MIN_COST else "Needs Funding"
    else:
        wallet_address = "No wallet"
        balance = 0.0
        funding_status = "No wallet"
    
    nodejs_status = "Ready" if NODEJS_AVAILABLE else "Setup Required"
    
    # Pool status
    pool_status = "Not Available"
    pool_info = ""
    if LOCK_ADDRESS_POOL:
        available = LOCK_ADDRESS_POOL.count_available()
        if available > 50:
            pool_status = "⚡ Excellent"
            pool_info = f"⚡ {available} LOCK addresses ready for INSTANT creation!"
        elif available > 10:
            pool_status = "🟡 Good"
            pool_info = f"⚡ {available} LOCK addresses available"
        else:
            pool_status = "🔴 Low"
            pool_info = f"⚠️ Only {available} LOCK addresses remaining"
    else:
        pool_info = "Real-time generation only (10-30 min wait)"
        
    welcome_message = (
        f"Welcome to LOCK Token Launcher - SIMPLIFIED EDITION!\n\n"
        f"Create professional tokens with vanity contract addresses ending in '{CONTRACT_SUFFIX}' using Raydium LaunchLab.\n\n"
        f"💰 FIXED PRICING - 10x CHEAPER!\n"
        f"• Old cost: 0.05 SOL per token\n"
        f"• New cost: {LAUNCHLAB_MIN_COST} SOL per token\n"
        f"• You save: 0.045 SOL per token!\n\n"
        f"⚡ INSTANT ADDRESSES:\n"
        f"{pool_info}\n\n"
        f"🚀 SIMPLIFIED CREATION:\n"
        f"• Only 7 steps (was 11!)\n"
        f"• Skip buttons for optional fields\n"
        f"• Auto-defaults: 1B supply, 9 decimals\n"
        f"• Single logo upload only\n\n"
        f"Current Balance: {balance:.6f} SOL\n"
        f"Status: {funding_status}\n"
        f"Node.js: {nodejs_status}\n"
        f"Pool: {pool_status}\n\n"
        "Send SOL to your wallet to get started:\n"
        f"`{wallet_address}`\n\n"
        f"Minimum required: {LAUNCHLAB_MIN_COST} SOL for LaunchLab creation\n"
        "Your funds are safe, but never share your private key."
    )
    reply_markup = InlineKeyboardMarkup(generate_inline_keyboard())
    try:
        await query.message.edit_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("go_to_main_menu: Message not modified; ignoring error.")
        else:
            raise e

# ----- REFRESH HANDLER WITH POOL STATUS -----
async def refresh_balance(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    wallet = user_wallets.get(user_id)
    
    if not wallet:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("No wallet found. Please create a wallet first.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return

    # Get balance
    wallet_address = wallet["public"]
    current_balance = get_wallet_balance(wallet_address)
    wallet["balance"] = current_balance
    
    logger.info(f"Balance refreshed for {wallet_address}: {current_balance} SOL")
    
    # Show funding requirements for FIXED LaunchLab pricing
    funding_status = "Ready for LOCK creation" if current_balance >= LAUNCHLAB_MIN_COST else "Need more SOL"
    funding_color = "✅" if current_balance >= LAUNCHLAB_MIN_COST else "⚠"
    nodejs_status = "✅ Ready" if NODEJS_AVAILABLE else "⚠ Setup Required"
    
    # Pool status
    pool_info = ""
    if LOCK_ADDRESS_POOL:
        available = LOCK_ADDRESS_POOL.count_available()
        if available > 0:
            pool_info = f"\n⚡ Pool Status: {available} LOCK addresses ready for INSTANT creation!"
        else:
            pool_info = "\n🔴 Pool Status: Empty - will generate live (10-30 min)"
    else:
        pool_info = "\n🔄 Pool Status: Not available - will generate live"
    
    message = (
        f"LOCK Wallet Balance - SIMPLIFIED EDITION:\n\nAddress:\n`{wallet_address}`\n\n"
        f"Balance: {current_balance:.6f} SOL\n"
        f"Status: {funding_color} {funding_status}\n"
        f"Node.js: {nodejs_status}{pool_info}\n\n"
        f"Ready to create LOCK tokens ending with '{CONTRACT_SUFFIX}'!\n\n"
        f"SIMPLIFIED LaunchLab Requirements:\n"
        f"• Pure creation: {LAUNCHLAB_MIN_COST}+ SOL (10x cheaper!)\n"
        f"• With liquidity: {LAUNCHLAB_MIN_COST}+ SOL + buy amount\n"
        f"• Old cost was: 0.05 SOL\n"
        f"• You save: 0.045 SOL per token!\n\n"
        f"🚀 SIMPLIFIED PROCESS:\n"
        f"• Only 7 steps instead of 11\n"
        f"• Skip buttons for optional fields\n"
        f"• Auto-defaults save time\n\n"
        f"Node.js Status: {'Ready' if NODEJS_AVAILABLE else 'Setup Required'}\n\n"
        f"(Tap address to copy)"
    )
    
    keyboard = [
        [InlineKeyboardButton("Deposit SOL", callback_data=CALLBACKS["deposit_sol"]),
         InlineKeyboardButton("Withdraw SOL", callback_data=CALLBACKS["withdraw_sol"])],
        [InlineKeyboardButton("Refresh Balance", callback_data=CALLBACKS["refresh_balance"])],
        [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/{wallet_address}")],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]
    ]
    
    try:
        await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Refresh: Message not modified; no update necessary.")
        else:
            logger.error(f"Error editing message: {e}", exc_info=True)

# ----- WALLET MANAGEMENT HANDLERS -----
async def handle_wallets_menu(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    wallet = user_wallets.get(user_id)
    if not wallet:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("No wallet found. Please restart by typing /start.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return
    wallet_address = wallet["public"]
    balance = get_wallet_balance(wallet_address)
    bundle_total = sum(b.get("balance", 0) for b in wallet.get("bundle", []))
    total_holdings = balance + bundle_total
    
    # Count LOCK tokens and total funding used with FIXED pricing
    tokens_count = len(user_coins.get(user_id, []))
    total_funding_used = sum(coin.get("funding_used", LAUNCHLAB_MIN_COST) for coin in user_coins.get(user_id, []))
    total_savings = sum((coin.get("creation_cost_old", 0.05) - coin.get("creation_cost", LAUNCHLAB_MIN_COST)) 
                       for coin in user_coins.get(user_id, []) if coin.get("cost_fixed"))
    instant_tokens = sum(1 for coin in user_coins.get(user_id, []) if coin.get("was_instant"))
    
    funding_status = "✅ Ready" if balance >= LAUNCHLAB_MIN_COST else "⚠ Needs SOL"
    nodejs_status = "✅ Ready" if NODEJS_AVAILABLE else "⚠ Setup Required"
    
    keyboard = [
        [InlineKeyboardButton("Wallet Details", callback_data=CALLBACKS["wallet_details"])],
        [InlineKeyboardButton("Show Private Key", callback_data=CALLBACKS["show_private_key"])],
        [InlineKeyboardButton("Import Wallet", callback_data=CALLBACKS["import_wallet"])],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]
    ]
    push_nav_state(context, {"message_text": query.message.text,
                             "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                             "parse_mode": "Markdown"})
    
    msg = (f"LOCK Wallet Management - SIMPLIFIED EDITION\n\nWallet Address:\n`{wallet_address}`\n\n"
           f"Main Balance: {balance:.6f} SOL\nTotal Holdings: {total_holdings:.6f} SOL\n"
           f"Status: {funding_status}\n"
           f"Node.js: {nodejs_status}\n\n"
           f"LOCK Tokens Created: {tokens_count}\n"
           f"⚡ Instant Creations: {instant_tokens}\n"
           f"Total Spent on Tokens: {total_funding_used:.6f} SOL\n"
           f"💰 Total Savings: {total_savings:.6f} SOL (SIMPLIFIED pricing!)")
    await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_wallet_details(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    wallet = user_wallets.get(user_id)
    if not wallet:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("No wallet found. Please create a wallet first.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return
    
    balance = get_wallet_balance(wallet["public"])
    bundle_total = sum(b.get("balance", 0) for b in wallet.get("bundle", []))
    total_holdings = balance + bundle_total
    
    funding_status = "✅ Ready for LOCK creation" if balance >= LAUNCHLAB_MIN_COST else "⚠ Need more SOL"
    nodejs_status = "✅ Ready" if NODEJS_AVAILABLE else "⚠ Setup Required"
    
    # Pool status
    pool_info = ""
    if LOCK_ADDRESS_POOL:
        available = LOCK_ADDRESS_POOL.count_available()
        if available > 0:
            pool_info = f"\n⚡ Pool: {available} LOCK addresses ready"
        else:
            pool_info = "\n🔴 Pool: Empty"
    
    message = (
        f"LOCK Wallet Details - SIMPLIFIED EDITION:\n\nAddress:\n`{wallet['public']}`\n\n"
        f"Main Balance: {balance:.6f} SOL\nTotal Holdings: {total_holdings:.6f} SOL\n"
        f"Status: {funding_status}\n"
        f"Node.js: {nodejs_status}{pool_info}\n\n"
        "Tap address to copy.\nDeposit SOL and tap Refresh to update balance.\n\n"
        f"SIMPLIFIED LaunchLab Creation Requirements:\n"
        f"• Pure creation: {LAUNCHLAB_MIN_COST}+ SOL (10x cheaper!)\n"
        f"• With liquidity: {LAUNCHLAB_MIN_COST}+ SOL + buy amount\n"
        f"• Old cost was: 0.05 SOL per token\n"
        f"• You save: 0.045 SOL per token!\n\n"
        f"🚀 SIMPLIFIED PROCESS:\n"
        f"• Only 7 steps instead of 11\n"
        f"• Skip buttons for optional fields\n"
        f"• Auto-defaults: 1B supply, 9 decimals\n\n"
        f"Ready to create LOCK tokens ending with '{CONTRACT_SUFFIX}'!"
    )
    keyboard = [
        [InlineKeyboardButton("Deposit SOL", callback_data=CALLBACKS["deposit_sol"]),
         InlineKeyboardButton("Withdraw SOL", callback_data=CALLBACKS["withdraw_sol"])],
        [InlineKeyboardButton("Bundle", callback_data=CALLBACKS["bundle"])],
        [InlineKeyboardButton("Refresh Balance", callback_data=CALLBACKS["refresh_balance"])],
        [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/{wallet['public']}")],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]
    ]
    push_nav_state(context, {"message_text": query.message.text,
                             "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                             "parse_mode": "Markdown"})
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- MAIN CALLBACK HANDLER FOR SIMPLIFIED LOCK TOKENS -----
async def button_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    logger.info(f"Button callback triggered: {query.data}")
    
    try:
        if query.data == CALLBACKS["start"]:
            await go_to_main_menu(query, context)
        elif query.data == CALLBACKS["wallets"]:
            await handle_wallets_menu(update, context)
        elif query.data == CALLBACKS["wallet_details"]:
            await show_wallet_details(update, context)
        elif query.data == CALLBACKS["withdraw_sol"]:
            user_id = query.from_user.id
            wallet = user_wallets.get(user_id)
            if not wallet:
                keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
                await query.message.edit_text("No wallet found.",
                                              reply_markup=InlineKeyboardMarkup(keyboard),
                                              parse_mode="Markdown")
                return
            
            current_balance = get_wallet_balance(wallet["public"])
            transaction_fee = 0.000005
            
            if current_balance <= transaction_fee:
                keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
                await query.message.edit_text(
                    f"Insufficient balance for withdrawal.\nCurrent: {current_balance:.6f} SOL\nMinimum: {transaction_fee:.6f} SOL",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="Markdown"
                )
                return
            
            keyboard = [[InlineKeyboardButton("Cancel", callback_data=CALLBACKS["cancel_withdraw_sol"])]]
            message = (
                f"Withdraw SOL\n\n"
                f"Balance: {current_balance:.6f} SOL\n\n"
                "Reply with the destination Solana address.\n\n"
                "After entering address, choose 25%, 50%, or 100% withdrawal."
            )
            
            context.user_data["awaiting_withdraw_dest"] = {"from_wallet": wallet}
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        
        elif query.data == CALLBACKS["cancel_withdraw_sol"]:
            context.user_data.pop("awaiting_withdraw_dest", None)
            context.user_data.pop("withdraw_destination", None)
            context.user_data.pop("withdraw_amounts", None)
            context.user_data.pop("withdraw_wallet", None)
            await go_to_main_menu(query, context)
        
        elif query.data == CALLBACKS["withdraw_25"]:
            await handle_percentage_withdrawal(update, context, "25")
        elif query.data == CALLBACKS["withdraw_50"]:
            await handle_percentage_withdrawal(update, context, "50") 
        elif query.data == CALLBACKS["withdraw_100"]:
            await handle_percentage_withdrawal(update, context, "100")
        
        elif query.data.startswith("force_wallets:withdraw_"):
            # Handle forced withdrawal for accounts that need activation
            percentage = query.data.split("_")[-1]
            await handle_percentage_withdrawal(update, context, percentage)
        
        elif query.data == CALLBACKS["refresh_balance"]:
            await refresh_balance(update, context)
        elif query.data == CALLBACKS["bundle"]:
            await show_bundle(update, context)
        elif query.data == CALLBACKS["subscription"]:
            await show_subscription_details(update, context)
        elif query.data.startswith("subscription:"):
            await process_subscription_plan(update, context)
        elif query.data == CALLBACKS["show_private_key"]:
            user_id = query.from_user.id
            if user_id not in user_wallets:
                await query.message.edit_text("No wallet found.")
                return
            private_key = user_wallets[user_id]["private"]
            keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
            await query.message.edit_text(
                f"Private Key:\n`{private_key}`\n\nKeep it safe!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        elif query.data == CALLBACKS["import_wallet"]:
            context.user_data["awaiting_import"] = True
            keyboard = [[InlineKeyboardButton("Cancel", callback_data=CALLBACKS["cancel_import_wallet"])]]
            message = "Import Wallet\n\nReply with your private key.\n\n*Your message will be auto-deleted for security.*"
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif query.data == CALLBACKS["cancel_import_wallet"]:
            context.user_data.pop("awaiting_import", None)
            await go_to_main_menu(query, context)
        elif query.data.startswith("skip_"):
            await handle_skip_button(update, context)
        elif query.data == CALLBACKS["launch"]:
            user_id = query.from_user.id
            
            # Check if subscription is active (with expiry check)
            if not is_subscription_active(user_id):
                nodejs_status = "Ready" if NODEJS_AVAILABLE else "Setup Required"
                
                # Pool status
                pool_info = ""
                if LOCK_ADDRESS_POOL:
                    available = LOCK_ADDRESS_POOL.count_available()
                    if available > 0:
                        pool_info = f"\n\n{available} LOCK addresses ready for instant creation!"
                
                message = (
                    f"Subscribe to create LOCK tokens!\n\n"
                    f"You need an active subscription to create LOCK tokens ending with '{CONTRACT_SUFFIX}' on Raydium LaunchLab.\n\n"
                    f"SIMPLIFIED PRICING: Only {LAUNCHLAB_MIN_COST} SOL per token (10x cheaper!)\n\n"
                    f"🚀 SIMPLIFIED PROCESS:\n"
                    f"• Only 7 steps instead of 11\n"
                    f"• Skip buttons for optional fields\n"
                    f"• Auto-defaults save time\n\n"
                    f"Node.js Status: {nodejs_status}{pool_info}"
                )
                keyboard = [
                    [InlineKeyboardButton("Subscribe Now", callback_data=CALLBACKS["subscription"])],
                    [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
                ]
                await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            else:
                # Check Node.js availability before wallet funding
                if not NODEJS_AVAILABLE:
                    keyboard = [
                        [InlineKeyboardButton("Setup Instructions", callback_data=CALLBACKS["setup_nodejs"])],
                        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
                    ]
                    await query.message.edit_text(
                        f"Node.js Setup Required\n\n"
                        f"To create LOCK tokens with SIMPLIFIED pricing ({LAUNCHLAB_MIN_COST} SOL):\n\n"
                        f"{NODEJS_SETUP_MESSAGE}\n\n"
                        f"Please complete the setup and restart the bot.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                    return
                
                # Check wallet funding after Node.js check with FIXED pricing
                wallet = user_wallets.get(user_id)
                if wallet:
                    current_balance = get_wallet_balance(wallet["public"])
                    if current_balance < LAUNCHLAB_MIN_COST:  # FIXED: Only need 0.005 SOL
                        keyboard = [
                            [InlineKeyboardButton("Check Balance", callback_data=CALLBACKS["refresh_balance"])],
                            [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
                        ]
                        await query.message.edit_text(
                            f"Insufficient SOL for LOCK Token Creation\n\n"
                            f"Current Balance: {current_balance:.6f} SOL\n"
                            f"Required: {LAUNCHLAB_MIN_COST} SOL (SIMPLIFIED - 10x cheaper!)\n"
                            f"Old requirement was: 0.05 SOL\n"
                            f"You save: 0.045 SOL!\n\n"
                            f"🚀 SIMPLIFIED PROCESS:\n"
                            f"• Only 7 steps instead of 11\n"
                            f"• Skip buttons for optional fields\n"
                            f"• Auto-defaults save time\n\n"
                            f"Please add SOL to your wallet:\n"
                            f"`{wallet['public']}`",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode="Markdown"
                        )
                        return
                
                # Start SIMPLIFIED launch flow
                start_simplified_launch_flow(context)
                await prompt_simplified_launch_step(query, context)
        elif query.data == CALLBACKS["launch_confirm_yes"]:
            await process_launch_confirmation_fixed(query, context)
        elif query.data == CALLBACKS["launch_confirm_no"]:
            context.user_data.pop("launch_step_index", None)
            context.user_data.pop("coin_data", None)
            await go_to_main_menu(query, context)
        elif query.data == CALLBACKS["launched_coins"]:
            await show_launched_coins(update, context)
        elif query.data == CALLBACKS["setup_nodejs"]:
            await show_nodejs_setup_instructions(update, context)
        elif query.data == CALLBACKS["settings"]:
            user_coins_count = len(user_coins.get(query.from_user.id, []))
            estimates = estimate_vanity_generation_time(CONTRACT_SUFFIX)
            nodejs_status = "Ready" if NODEJS_AVAILABLE else "Setup Required"
            
            # Calculate savings for this user
            user_coins_list = user_coins.get(query.from_user.id, [])
            total_savings = sum((coin.get("creation_cost_old", 0.05) - coin.get("creation_cost", LAUNCHLAB_MIN_COST)) 
                               for coin in user_coins_list if coin.get("cost_fixed"))
            instant_count = sum(1 for coin in user_coins_list if coin.get("was_instant"))
            
            # Pool status
            pool_info = ""
            if LOCK_ADDRESS_POOL:
                available = LOCK_ADDRESS_POOL.count_available()
                pool_info = f"\nPool Status: {available} LOCK addresses ready"
            
            message = (f"LOCK Token Launcher Settings - SIMPLIFIED EDITION\n\n"
                       f"Contract Suffix: {CONTRACT_SUFFIX} (STRICT MODE)\n"
                       f"No Fallbacks: Premium branding only\n"
                       f"Platform: Raydium LaunchLab\n"
                       f"Funding Target: 85 SOL\n"
                       f"Generation Difficulty: {estimates['difficulty']}\n"
                       f"Est. Time per Token: {estimates['time_estimate']}\n"
                       f"Your LOCK Tokens Created: {user_coins_count}\n"
                       f"Instant Creations: {instant_count}/{user_coins_count}\n"
                       f"Node.js Status: {nodejs_status}{pool_info}\n\n"
                       f"SIMPLIFIED PRICING BENEFITS:\n"
                       f"• Old cost: 0.05 SOL per token\n"
                       f"• New cost: {LAUNCHLAB_MIN_COST} SOL per token\n"
                       f"• You save: 0.045 SOL per token\n"
                       f"• Your total savings: {total_savings:.6f} SOL\n\n"
                       f"🚀 SIMPLIFIED FEATURES:\n"
                       f"• Only 7 steps instead of 11\n"
                       f"• Skip buttons for optional fields\n"
                       f"• Auto-defaults: 1B supply, 9 decimals\n"
                       f"• Single logo upload only\n"
                       f"• Streamlined like Raydium's JustSendit mode\n\n"
                       f"LaunchLab Features:\n"
                       f"• LOCK vanity addresses (instant when available)\n"
                       f"• Raydium LaunchLab bonding curves\n"
                       f"• Optional initial liquidity\n"
                       f"• Auto-graduation at 85 SOL\n"
                       f"• Pure creation mode available\n"
                       f"• DexScreener ready\n\n"
                       f"Requirements:\n"
                       f"• SIMPLIFIED: {LAUNCHLAB_MIN_COST} SOL for creation (10x cheaper!)\n"
                       f"• Additional SOL for initial liquidity\n"
                       f"• Valid subscription\n"
                       f"• Node.js 18+ with required dependencies")
            keyboard = [
                [InlineKeyboardButton("Setup Instructions", callback_data=CALLBACKS["setup_nodejs"])],
                [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
            ]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif query.data == CALLBACKS["socials"]:
            # Pool status
            pool_info = ""
            if LOCK_ADDRESS_POOL:
                available = LOCK_ADDRESS_POOL.count_available()
                if available > 0:
                    pool_info = f"\n• Pool: {available} addresses ready for instant creation"
            
            message = (
                f"LOCK Token Community - SIMPLIFIED EDITION\n\n"
                f"Join the community of LOCK token creators!\n\n"
                f"Share your vanity contracts ending with '{CONTRACT_SUFFIX}' and connect with other builders.\n\n"
                f"• Platform: Raydium LaunchLab\n"
                f"• All tokens LOCK compatible\n"
                f"• Bonding curve graduation at 85 SOL\n"
                f"• Professional token infrastructure\n"
                f"• SIMPLIFIED pricing: {LAUNCHLAB_MIN_COST} SOL per token (10x cheaper!)\n"
                f"• Streamlined 7-step process{pool_info}\n\n"
                f"🚀 SIMPLIFIED BENEFITS:\n"
                f"• 7 steps instead of 11\n"
                f"• Skip buttons for optional fields\n"
                f"• Auto-defaults save time\n"
                f"• Like Raydium's JustSendit mode\n\n"
                f"Community links coming soon..."
            )
            keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif query.data == CALLBACKS["deposit_sol"]:
            user_id = query.from_user.id
            wallet = user_wallets.get(user_id)
            if not wallet:
                keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
                await query.message.edit_text("No wallet found.",
                                              reply_markup=InlineKeyboardMarkup(keyboard),
                                              parse_mode="Markdown")
                return
            
            wallet_address = wallet["public"]
            current_balance = get_wallet_balance(wallet_address)
            
            message = (
                f"Deposit SOL to Your Wallet\n\n"
                f"Send SOL to this address:\n"
                f"`{wallet_address}`\n\n"
                f"Current Balance: {current_balance:.6f} SOL\n\n"
                f"SIMPLIFIED LaunchLab Requirements:\n"
                f"• Minimum: {LAUNCHLAB_MIN_COST} SOL per token (10x cheaper!)\n"
                f"• Old cost was: 0.05 SOL per token\n"
                f"• You save: 0.045 SOL per token!\n\n"
                f"Tap the address above to copy it.\n"
                f"After depositing, tap 'Refresh Balance' to update."
            )
            
            keyboard = [
                [InlineKeyboardButton("Refresh Balance", callback_data=CALLBACKS["refresh_balance"])],
                [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/{wallet_address}")],
                [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
            ]
            
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await query.message.edit_text("LOCK feature coming soon!")
            
    except Exception as e:
        logger.error(f"Error in button callback for {query.data}: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("An error occurred. Please try again.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")

# ----- NETWORK CONNECTIVITY CHECK -----
def check_network_connectivity():
    """Check if we can reach basic internet services"""
    test_urls = [
        "https://www.google.com",
        "https://1.1.1.1",  # Cloudflare DNS
        "https://8.8.8.8"   # Google DNS
    ]
    
    for url in test_urls:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                logger.info(f"Network connectivity OK - reached {url}")
                return True
        except Exception as e:
            logger.warning(f"Failed to reach {url}: {e}")
            continue
    
    logger.error("Network connectivity check failed - cannot reach any test URLs")
    return False

def check_telegram_connectivity():
    """Check if we can reach Telegram's API servers"""
    telegram_test_urls = [
        "https://api.telegram.org",
        "https://core.telegram.org"
    ]
    
    for url in telegram_test_urls:
        try:
            response = requests.get(url, timeout=10)
            logger.info(f"Telegram connectivity OK - reached {url} (status: {response.status_code})")
            return True
        except Exception as e:
            logger.warning(f"Failed to reach {url}: {e}")
            continue
    
    logger.error("Cannot reach Telegram API servers")
    return False

# ----- ENHANCED MAIN FUNCTION WITH ADDRESS POOL INITIALIZATION -----
def main():
    """
    Enhanced main function with LOCK address pool initialization and SIMPLIFIED edition
    """
    global NODEJS_AVAILABLE, NODEJS_SETUP_MESSAGE, LOCK_ADDRESS_POOL
    
    print("=" * 80)
    print("🔒 LOCK TOKEN LAUNCHER - SIMPLIFIED EDITION")
    print("=" * 80)
    print(f"💰 REVOLUTIONARY PRICING: Only {LAUNCHLAB_MIN_COST} SOL per token!")
    print(f"⚡ INSTANT LOCK addresses from pre-generated pool!")
    print(f"🚀 SIMPLIFIED PROCESS: Only 7 steps instead of 11!")
    print(f"🎯 Target suffix: '{CONTRACT_SUFFIX}' - Premium branding")
    print(f"🏗️ Platform: Raydium LaunchLab integration")
    print(f"📱 Like Raydium's JustSendit mode - streamlined and fast!")
    print("=" * 80)
    
    logger.info(f"LOCK Token Launcher Bot starting with SIMPLIFIED process and instant address pool...")
    logger.info(f"MAJOR UPDATE: Creation cost {LAUNCHLAB_MIN_COST} SOL (10x cheaper!)")
    logger.info(f"MAJOR UPDATE: Simplified to 7 steps (was 11 steps)")
    logger.info(f"Target suffix: '{CONTRACT_SUFFIX}'")
    logger.info(f"Instant address mode: Enabled")
    
    # Initialize LOCK address pool
    print("🏗️ Initializing LOCK address pool...")
    try:
        LOCK_ADDRESS_POOL = LockAddressPool(
            db_path="lock_addresses.db",
            target_pool_size=100  # Start with 100, increase as needed
        )
        
        # Check current pool status
        available_count = LOCK_ADDRESS_POOL.count_available()
        print(f"📊 Current pool status: {available_count} LOCK addresses available")
        
        if available_count < 10:
            print("🔄 Pool running low, generating initial addresses...")
            print("This may take a few minutes but only needs to happen once...")
            LOCK_ADDRESS_POOL.generate_lock_addresses(50)  # Generate 50 to start
            
        # Start background generation
        LOCK_ADDRESS_POOL.start_background_generation()
        print("✅ LOCK address pool initialized and background generation started!")
        
    except Exception as e:
        print(f"⚠️ LOCK address pool initialization failed: {e}")
        print("Falling back to real-time generation...")
        LOCK_ADDRESS_POOL = None
    
    # Setup Node.js environment (now optional)
    print("🟢 Checking Node.js environment for LOCK token creation...")
    NODEJS_AVAILABLE = setup_nodejs_environment()
    
    if NODEJS_AVAILABLE:
        print("✅ Node.js environment ready for LOCK token creation!")
        print(f"✅ Script found: create_real_launchlab_token.js")
        logger.info("Node.js environment ready for token creation!")
    else:
        print("⚠️ Node.js environment not ready. Bot will start with limited functionality.")
        print(f"ℹ️ Issue: {NODEJS_SETUP_MESSAGE}")
        logger.warning("Node.js environment not ready. Bot will start with limited functionality.")
        logger.warning(f"Setup message: {NODEJS_SETUP_MESSAGE}")
    
    # Check environment variables
    print("🔧 Checking configuration...")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("❌ TELEGRAM_BOT_TOKEN environment variable not set!")
        print("Please set your bot token in .env file:")
        print("TELEGRAM_BOT_TOKEN=your_bot_token_here")
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set!")
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set.")
    
    # Validate bot token format
    if not bot_token.count(':') == 1 or len(bot_token.split(':')[0]) < 8:
        print("❌ Invalid bot token format!")
        print("Bot token should be in format: 123456789:ABCdefGHIjklmnopQRSTuvwxyz")
        logger.error("Invalid bot token format!")
        raise ValueError("Invalid TELEGRAM_BOT_TOKEN format.")
    
    print("✅ Bot token format valid")
    logger.info("Bot token format appears valid")
    
    # Validate other environment variables
    pinata_key = os.getenv("PINATA_API_KEY")
    if not pinata_key or pinata_key == "demo":
        print("⚠️ PINATA_API_KEY not set - using fallback IPFS services")
        logger.warning("PINATA_API_KEY not set - using fallback IPFS services")
    else:
        print("✅ PINATA API configured")
    
    # Network connectivity diagnostics
    print("🌐 Running network diagnostics...")
    logger.info("Running network diagnostics...")
    
    if not check_network_connectivity():
        print("❌ Network connectivity issues detected!")
        print("Please check your internet connection and try again")
        print("If using VPN/Proxy, try disabling it temporarily")
        logger.error("Network connectivity issues detected!")
        return
    
    print("✅ Network connectivity OK")
    
    if not check_telegram_connectivity():
        print("⚠️ Cannot reach Telegram API servers!")
        print("This could be due to:")
        print("• Regional blocking/firewall")
        print("• Proxy/VPN issues") 
        print("• Temporary Telegram API outage")
        print("• Corporate firewall blocking Telegram")
        print("\n🔄 Trying to start bot anyway...")
        logger.error("Cannot reach Telegram API servers!")
    else:
        print("✅ Telegram connectivity OK")
    
    # Create application with enhanced error handling
    try:
        print("🤖 Creating Telegram application...")
        logger.info("Creating Telegram application...")
        
        # Build application with custom request configuration
        application = (Application.builder()
                      .token(bot_token)
                      .connect_timeout(30.0)  # 30 second connection timeout
                      .read_timeout(30.0)     # 30 second read timeout
                      .build())
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_simplified_text_input))
        application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media_message))
        
        print("✅ Handlers registered successfully")
        logger.info("Handlers registered successfully")
        
    except Exception as e:
        print(f"❌ Failed to create Telegram application: {e}")
        print("This usually indicates a network or token issue")
        logger.error(f"Failed to create Telegram application: {e}")
        return
    
    # Try to start with retries
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"🚀 Attempting to start bot (attempt {attempt + 1}/{max_retries})...")
            logger.info(f"Attempting to start bot (attempt {attempt + 1}/{max_retries})...")
            
            print("=" * 80)
            print("🎉 LOCK TOKEN LAUNCHER BOT STARTED - SIMPLIFIED EDITION!")
            print("=" * 80)
            print("SIMPLIFIED FEATURES ACTIVE:")
            print(f"💰 REVOLUTIONARY PRICING: {LAUNCHLAB_MIN_COST} SOL per token (10x cheaper!)")
            print(f"⚡ INSTANT LOCK addresses from address pool")
            print(f"🚀 SIMPLIFIED PROCESS: Only 7 steps instead of 11!")
            print(f"⏭️ Skip buttons for optional fields")
            print(f"🎯 Auto-defaults: 1B supply, 9 decimals")
            print(f"🖼️ Single logo upload only")
            print(f"📱 Like Raydium's JustSendit mode")
            print(f"🔒 LOCK vanity address generation (suffix: '{CONTRACT_SUFFIX}')")
            print(f"🏗️ Raydium LaunchLab integration")
            print(f"⚡ Your create_real_launchlab_token.js script integration")
            print(f"💎 Premium branding with LOCK addresses")
            print(f"🎯 Strict LOCK mode: No fallbacks")
            print(f"📊 DexScreener ready tokens")
            if NODEJS_AVAILABLE:
                print(f"✅ Full token creation capabilities")
            else:
                print(f"⚠️ Limited functionality (Node.js setup required)")
            if LOCK_ADDRESS_POOL:
                available = LOCK_ADDRESS_POOL.count_available()
                print(f"⚡ Address pool: {available} LOCK addresses ready")
            print(f"🛡️ Enhanced wallet management and SOL transfers")
            print(f"📈 Comprehensive error handling")
            print(f"🎫 Subscription system")
            print("=" * 80)
            print(f"💡 COST SAVINGS: Save 0.045 SOL per token!")
            print(f"💡 OLD COST: 0.05 SOL → NEW COST: {LAUNCHLAB_MIN_COST} SOL")
            print(f"💡 TIME SAVINGS: Instant addresses + 7 steps instead of 11!")
            print(f"💡 SIMPLIFIED LIKE: Raydium's JustSendit mode!")
            print("=" * 80)
            
            logger.info(f"LOCK Token Launcher Bot started successfully - SIMPLIFIED EDITION!")
            logger.info(f"Features enabled:")
            logger.info(f"• SIMPLIFIED process: 7 steps instead of 11")
            logger.info(f"• INSTANT addressing with pool system")
            logger.info(f"• REVOLUTIONARY pricing: {LAUNCHLAB_MIN_COST} SOL per token (10x cheaper)")
            logger.info(f"• Skip buttons for optional fields")
            logger.info(f"• Auto-defaults: 1B supply, 9 decimals")
            logger.info(f"• Vanity address generation (suffix: '{CONTRACT_SUFFIX}')")
            logger.info(f"• Strict LOCK mode: Premium branding only")
            if NODEJS_AVAILABLE:
                logger.info(f"• Raydium LaunchLab integration with your script")
                logger.info(f"• Full token creation capabilities")
            else:
                logger.info(f"• Limited functionality (Node.js setup required for token creation)")
            if LOCK_ADDRESS_POOL:
                available = LOCK_ADDRESS_POOL.count_available()
                logger.info(f"• Address pool: {available} LOCK addresses ready")
            logger.info(f"• Wallet management and SOL transfers")
            logger.info(f"• Enhanced error handling")
            logger.info(f"• Subscription system")
            logger.info(f"• Streamlined like Raydium's JustSendit mode")
            
            # Start polling with error handling
            print("🔄 Starting bot polling...")
            logger.info("Starting bot polling...")
            application.run_polling(
                drop_pending_updates=True,  # Ignore old messages
                close_loop=False            # Don't close the event loop
            )
            
            # If we reach here, polling ended normally
            print("Bot polling ended")
            logger.info("Bot polling ended")
            break
            
        except Exception as e:
            print(f"❌ Bot startup attempt {attempt + 1} failed: {e}")
            logger.error(f"Bot startup attempt {attempt + 1} failed: {e}")
            
            # Analyze the error type
            error_msg = str(e).lower()
            if "timeout" in error_msg or "connecttimeout" in error_msg:
                print("Connection timeout - network or firewall issue")
                logger.error("Connection timeout - network or firewall issue")
                if attempt < max_retries - 1:
                    print(f"Retrying in 10 seconds...")
                    logger.info(f"Retrying in 10 seconds...")
                    import time
                    time.sleep(10)
            elif "unauthorized" in error_msg:
                print("❌ Bot token is invalid or expired!")
                print("Please check your TELEGRAM_BOT_TOKEN in .env file")
                logger.error("Bot token is invalid or expired!")
                break
            elif "forbidden" in error_msg:
                print("❌ Bot doesn't have permission - check bot settings with @BotFather")
                logger.error("Bot doesn't have permission - check bot settings with @BotFather")
                break
            else:
                print(f"Unknown error: {e}")
                logger.error(f"Unknown error: {e}")
                if attempt < max_retries - 1:
                    print(f"Retrying in 5 seconds...")
                    logger.info(f"Retrying in 5 seconds...")
                    import time
                    time.sleep(5)
    
    print("❌ All startup attempts failed")
    print("\nPossible solutions:")
    print("1. Check your internet connection")
    print("2. Verify TELEGRAM_BOT_TOKEN in .env file") 
    print("3. Disable VPN/Proxy temporarily")
    print("4. Check if Telegram is blocked in your region")
    print("5. Try again later (Telegram API might be down)")
    logger.error("All startup attempts failed")

if __name__ == "__main__":
    main()