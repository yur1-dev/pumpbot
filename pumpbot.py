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

# VANITY ADDRESS CONFIGURATION - LOCK SUFFIX
CONTRACT_SUFFIX = "lock"   # Contract addresses will end with "lock"
VANITY_GENERATION_TIMEOUT = 180   # 3 minutes timeout for lock generation  
FALLBACK_SUFFIX = ""    # Empty fallback = random address

# RAYDIUM LAUNCHLAB CONFIGURATION
RAYDIUM_LAUNCHLAB_PROGRAM = "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"
LETSBONK_METADATA_SERVICE = "https://gateway.pinata.cloud/ipfs/"

# GLOBAL FLAG FOR NODE.JS AVAILABILITY
NODEJS_AVAILABLE = False
NODEJS_SETUP_MESSAGE = ""

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

# ----- ENHANCED VANITY ADDRESS GENERATION FOR LOCK SUFFIX -----
async def generate_vanity_keypair_with_progress(suffix: str, progress_callback=None, max_attempts: int = 10000000) -> tuple[SoldersKeypair, int]:
    """
    Generate a keypair whose public key ends with the specified suffix with async progress updates
    ENHANCED: Better verification for LOCK suffix
    Returns: (keypair, attempts_made) or (None, attempts_made) if not found
    """
    attempts = 0
    start_time = time.time()
    last_progress_time = start_time
    
    # Ensure suffix is lowercase for comparison
    target_suffix = suffix.lower()
    
    logger.info(f"Starting LOCK vanity generation for suffix '{target_suffix}'...")
    logger.info(f"Target: addresses ending with '{target_suffix}' (case insensitive)")
    
    for attempt in range(max_attempts):
        # Generate random keypair
        keypair = SoldersKeypair()
        public_key_str = str(keypair.pubkey())
        
        attempts += 1
        
        # Check if address ends with desired suffix (case insensitive)
        if public_key_str.lower().endswith(target_suffix):
            elapsed = time.time() - start_time
            logger.info(f"SUCCESS: Found LOCK address ending with '{target_suffix}' after {attempts:,} attempts in {elapsed:.1f}s")
            logger.info(f"Address: {public_key_str}")
            logger.info(f"Verification: Address ends with '{public_key_str[-len(target_suffix):]}' (target: '{target_suffix}')")
            
            # Double-check verification
            if not public_key_str.lower().endswith(target_suffix):
                logger.error(f"CRITICAL: Verification failed after generation!")
                continue
                
            return keypair, attempts
        
        # Progress callback every 50k attempts or every 10 seconds
        current_time = time.time()
        if (attempts % 50000 == 0 or current_time - last_progress_time >= 10) and progress_callback:
            elapsed = current_time - start_time
            rate = attempts / elapsed if elapsed > 0 else 0
            
            # Call async progress callback
            try:
                await progress_callback(attempts, elapsed, rate)
                last_progress_time = current_time
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")
        
        # Log progress every 100k attempts
        if attempts % 100000 == 0:
            elapsed = time.time() - start_time
            rate = attempts / elapsed if elapsed > 0 else 0
            logger.info(f"LOCK vanity generation: {attempts:,} attempts in {elapsed:.1f}s ({rate:,.0f}/sec)")
            
        # Timeout check
        if time.time() - start_time > VANITY_GENERATION_TIMEOUT:
            logger.warning(f"LOCK vanity generation timeout after {attempts:,} attempts")
            break
        
        # Allow other async operations to run
        if attempts % 10000 == 0:
            await asyncio.sleep(0.001)
    
    logger.warning(f"LOCK vanity generation failed after {attempts:,} attempts - no address found ending with '{target_suffix}'")
    return None, attempts

def generate_vanity_keypair(suffix: str, max_attempts: int = 10000000) -> tuple[SoldersKeypair, int]:
    """
    Synchronous wrapper for vanity generation (fallback)
    """
    attempts = 0
    start_time = time.time()
    
    target_suffix = suffix.lower()
    logger.info(f"Starting synchronous LOCK vanity generation for suffix '{target_suffix}'...")
    
    for attempt in range(max_attempts):
        keypair = SoldersKeypair()
        public_key_str = str(keypair.pubkey())
        attempts += 1
        
        if public_key_str.lower().endswith(target_suffix):
            elapsed = time.time() - start_time
            logger.info(f"Found LOCK address ending with '{target_suffix}' after {attempts:,} attempts in {elapsed:.1f}s")
            return keypair, attempts
            
        if attempts % 100000 == 0:
            elapsed = time.time() - start_time
            rate = attempts / elapsed if elapsed > 0 else 0
            logger.info(f"Sync LOCK vanity generation: {attempts:,} attempts in {elapsed:.1f}s ({rate:.0f}/sec)")
            
        if time.time() - start_time > VANITY_GENERATION_TIMEOUT:
            break
    
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

# ----- WALLET FUNDING VALIDATION -----
def check_wallet_funding_requirements(coin_data, user_wallet):
    """
    Check if user wallet has sufficient SOL for LAUNCHLAB token creation
    """
    try:
        # Get current balance
        current_balance = get_wallet_balance(user_wallet["public"])
        
        # Calculate required SOL - HIGHER FOR LAUNCHLAB
        base_creation_cost = 0.1  # Higher cost for LaunchLab (vs 0.02 for basic tokens)
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
                "shortfall": total_required - current_balance
            }
        
        return {
            "sufficient": True,
            "current_balance": current_balance,
            "required": total_required,
            "base_cost": base_creation_cost,
            "initial_buy": initial_buy_amount,
            "remaining_after": current_balance - total_required
        }
        
    except Exception as e:
        logger.error(f"Error checking wallet funding: {e}")
        return {
            "sufficient": False,
            "error": str(e),
            "current_balance": 0,
            "required": 0.1  # LaunchLab minimum
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
            time.sleep(2)  # Wait for confirmation
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
        
        # Handle banner upload if provided
        banner_uri = None
        banner_path = coin_data.get('banner')
        if banner_path and os.path.exists(banner_path):
            try:
                banner_uri = upload_to_free_ipfs(banner_path)
                logger.info(f"Banner uploaded: {banner_uri}")
            except Exception as e:
                logger.warning(f"Banner upload failed: {e}")
        
        # Use placeholder if no banner
        if not banner_uri:
            banner_uri = f"https://via.placeholder.com/512x512/000000/FFFFFF/?text=LOCK"
            logger.info(f"Banner uploaded: {banner_uri}")
        
        # Enhanced metadata payload for LetsBonk/Raydium LaunchLab
        metadata_payload = {
            'name': coin_data.get('name'),
            'symbol': coin_data.get('ticker'),
            'description': coin_data.get('description', ''),
            'image': img_uri,
            'website': coin_data.get('website', ''),
            'telegram': coin_data.get('telegram', ''),
            'twitter': coin_data.get('twitter', ''),
            # LetsBonk specific fields
            'totalSupply': coin_data.get('total_supply', 1_000_000_000),
            'decimals': coin_data.get('decimals', 9),
            'platform': 'LetsBonk',
            'launchpad': 'Raydium LaunchLab',
            'contractSuffix': CONTRACT_SUFFIX,
            'createdAt': datetime.now().isoformat(),
            'creator': f"LetsBonk-{CONTRACT_SUFFIX}",
            'banner': banner_uri
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

# ----- ENHANCED TOKEN CREATION WITH WALLET FUNDING CHECKS -----
async def create_lock_token_with_raydium(coin_data, user_wallet, progress_message_func):
    """
    Enhanced LOCK token creation with wallet funding checks and LaunchLab integration
    """
    try:
        # First check wallet funding with LaunchLab requirements
        await progress_message_func(
            "Checking Wallet Requirements...\n\n"
            "Verifying SOL balance for LaunchLab token creation...\n"
            "Please wait..."
        )
        
        funding_check = check_wallet_funding_requirements(coin_data, user_wallet)
        
        if not funding_check["sufficient"]:
            shortfall = funding_check.get("shortfall", 0.1)
            current = funding_check.get("current_balance", 0)
            required = funding_check.get("required", 0.1)
            
            error_message = (
                f"Insufficient SOL Balance for LaunchLab\n\n"
                f"Current: {current:.6f} SOL\n"
                f"Required: {required:.6f} SOL\n"
                f"Shortfall: {shortfall:.6f} SOL\n\n"
                f"LaunchLab requires minimum 0.1 SOL\n"
                f"Please add {shortfall:.6f} SOL to your wallet and try again."
            )
            
            return {
                'status': 'error',
                'message': error_message,
                'funding_required': required,
                'current_balance': current
            }
        
        # Show funding confirmation
        remaining_balance = funding_check["remaining_after"]
        await progress_message_func(
            f"Wallet Verified for LaunchLab\n\n"
            f"Balance: {funding_check['current_balance']:.6f} SOL\n"
            f"Creation Cost: {funding_check['base_cost']:.6f} SOL\n"
            f"Initial Buy: {funding_check['initial_buy']:.6f} SOL\n"
            f"Remaining: {remaining_balance:.6f} SOL\n\n"
            f"Generating LOCK address..."
        )
        
        # Continue with existing vanity generation logic
        suffix_to_try = CONTRACT_SUFFIX
        logger.info(f"Generating LOCK vanity address ending with '{suffix_to_try}'...")
        
        # Create progress callback
        async def progress_callback(attempts, elapsed, rate):
            progress_text = (
                f"Generating LOCK Address...\n\n"
                f"Target: ...{suffix_to_try}\n"
                f"Attempts: {attempts:,}\n"
                f"Time: {elapsed:.1f}s\n"
                f"Rate: {rate:,.0f}/sec\n\n"
                f"Wallet Ready: {funding_check['current_balance']:.6f} SOL"
            )
            await progress_message_func(progress_text)
        
        # Try to generate vanity address
        vanity_keypair, attempts = await generate_vanity_keypair_with_progress(
            suffix_to_try, 
            progress_callback, 
            max_attempts=10000000
        )
        
        # If failed, use random
        if not vanity_keypair:
            logger.info(f"Lock suffix failed, using secure random address")
            await progress_message_func(
                f"Using secure random address\n\n"
                f"Previous attempts: {attempts:,}\n\n"
                f"Generating secure address..."
            )
            vanity_keypair = SoldersKeypair()
            suffix_to_try = "random"
            attempts += 1
        
        vanity_address = str(vanity_keypair.pubkey())
        logger.info(f"Final LOCK address: {vanity_address}")
        
        # Upload metadata
        await progress_message_func(
            f"Uploading Metadata for LaunchLab...\n\n"
            f"Address: ...{vanity_address[-12:]}\n"
            f"Processing token data...\n\n"
            f"Preparing for Raydium LaunchLab..."
        )
        
        token_metadata = upload_letsbonk_metadata(coin_data)
        
        # Show final launch progress with funding info
        has_initial_buy = funding_check["initial_buy"] > 0
        
        if has_initial_buy:
            await progress_message_func(
                f"Launching on Raydium LaunchLab...\n\n"
                f"Contract: ...{vanity_address[-8:]}\n"
                f"Initial Buy: {funding_check['initial_buy']} SOL\n"
                f"Total Cost: {funding_check['required']} SOL\n\n"
                f"Creating bonding curve..."
            )
        else:
            await progress_message_func(
                f"Launching on Raydium LaunchLab...\n\n"
                f"Contract: ...{vanity_address[-8:]}\n"
                f"Mode: Pure Creation\n"
                f"Cost: {funding_check['base_cost']} SOL\n\n"
                f"Creating token..."
            )
        
        # Create the token using LaunchLab
        result = await create_token_on_raydium_launchlab(
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
                'vanity_suffix': suffix_to_try,
                'platform': 'Raydium LaunchLab',
                'initial_liquidity_sol': funding_check["initial_buy"],
                'trading_enabled': True,
                'pure_creation': not has_initial_buy,
                'funding_used': funding_check["required"],
                'wallet_balance_after': funding_check["current_balance"] - funding_check["required"],
                'funding_target': result.get('funding_target', 85)
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error creating enhanced LOCK token: {e}", exc_info=True)
        return {'status': 'error', 'message': f"Token creation failed: {str(e)}"}

# ----- CORRECTED TOKEN CREATION FUNCTION WITH NODE.JS AVAILABILITY CHECK -----
async def create_token_on_raydium_launchlab(keypair, metadata, coin_data, user_wallet, has_initial_buy, buy_amount):
    """
    FINAL WORKING VERSION: Enhanced token creation using correct Raydium LaunchLab SDK
    Now checks for Node.js availability first
    """
    try:
        mint_address = str(keypair.pubkey())
        logger.info(f"Creating LOCK token on Raydium LaunchLab: {mint_address}")
        
        # Check if Node.js environment is available
        if not NODEJS_AVAILABLE:
            return {
                'status': 'error',
                'message': f'Node.js Setup Required\n\n{NODEJS_SETUP_MESSAGE}\n\nPlease set up the required files and restart the bot.',
                'requires_nodejs_setup': True
            }
        
        # CRITICAL: Verify the address ends with 'lock'
        if not mint_address.lower().endswith('lock'):
            logger.error(f"CRITICAL ERROR: Generated address {mint_address} does not end with 'lock'!")
            return {
                'status': 'error',
                'message': f'Address generation failed - does not end with LOCK. Got: {mint_address}'
            }
        
        logger.info(f"VERIFIED: Token address ends with 'lock': {mint_address}")
        
        # Validate wallet balance - LaunchLab requires more SOL (0.1 minimum)
        current_balance = get_wallet_balance(user_wallet["public"])
        required_balance = 0.1 + (buy_amount if has_initial_buy else 0)  # Higher minimum for LaunchLab
        
        if current_balance < required_balance:
            return {
                'status': 'error',
                'message': f'Insufficient balance. LaunchLab requires minimum 0.1 SOL. Required: {required_balance:.6f} SOL, Current: {current_balance:.6f} SOL'
            }
        
        # Get user keypair
        user_secret = base58.b58decode(user_wallet["private"])
        user_keypair = SoldersKeypair.from_bytes(user_secret)
        
        # Prepare data for Node.js script with LaunchLab parameters
        node_params = {
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
            # LaunchLab specific parameters
            'fundingTarget': 85,  # 85 SOL target
            'migrateType': 'cpmm',  # Use CPMM for better liquidity
        }
        
        # Write parameters to temp file
        params_file = 'token_params.json'
        with open(params_file, 'w') as f:
            json.dump(node_params, f, indent=2)
        
        logger.info(f"Executing official Raydium LaunchLab token creation...")
        
        # Use the correct Node.js scripts in priority order
        node_scripts = [
            'create_raydium_token.js',  # Your actual file
            'create_launchlab_token.js',  # Your other file
            'create_raydium_token_correct.js',  # Fallback
        ]
        
        for script_name in node_scripts:
            if not os.path.exists(script_name):
                logger.warning(f"Script {script_name} not found, trying next...")
                continue
                
            try:
                logger.info(f"Trying {script_name}...")
                result = subprocess.run([
                    'node', script_name, params_file
                ], 
                capture_output=True, 
                text=True, 
                timeout=300,  # 5 minute timeout for LaunchLab
                cwd=os.getcwd()
                )
                
                logger.info(f"Node.js process return code: {result.returncode}")
                logger.info(f"Node.js stdout: {result.stdout}")
                if result.stderr:
                    logger.info(f"Node.js stderr: {result.stderr}")
                
                if result.returncode == 0:
                    # Parse the JSON response
                    output_lines = result.stdout.strip().split('\n')
                    json_output = None
                    
                    # Find the JSON response (should be the last valid JSON line)
                    for line in reversed(output_lines):
                        try:
                            json_output = json.loads(line)
                            break
                        except json.JSONDecodeError:
                            continue
                    
                    if json_output and json_output.get('status') == 'success':
                        logger.info(f"LOCK Token creation successful with {script_name}!")
                        
                        # FINAL VERIFICATION: Check that the returned address ends with 'lock'
                        returned_mint = json_output.get('mintAddress', '')
                        if not returned_mint.lower().endswith('lock'):
                            logger.error(f"CRITICAL: Returned address {returned_mint} doesn't end with LOCK!")
                            return {
                                'status': 'error',
                                'message': f'Token created but address verification failed: {returned_mint}'
                            }
                        
                        logger.info(f"FINAL SUCCESS: LOCK token created with address ending in 'lock': {returned_mint}")
                        logger.info(f"Pool ID: {json_output.get('poolId', 'N/A')}")
                        logger.info(f"Funding Target: {json_output.get('fundingTarget', 85)} SOL")
                        
                        # Wait for confirmation
                        await asyncio.sleep(5)
                        
                        # Verify token exists on chain
                        token_verified = await verify_token_on_chain(returned_mint)
                        
                        return {
                            'status': 'success',
                            'signature': json_output.get('signature'),
                            'mint': returned_mint,
                            'pool_id': json_output.get('poolId'),
                            'pool_address': json_output.get('poolAddress', json_output.get('poolId')),
                            'bonding_curve_address': json_output.get('bondingCurveAddress', json_output.get('poolId')),
                            'initial_buy_signature': json_output.get('initialBuySignature'),
                            'verified_on_chain': token_verified,
                            'verified_lock_suffix': json_output.get('verifiedLockSuffix', False),
                            'funding_target': json_output.get('fundingTarget', 85),
                            'total_supply': json_output.get('totalSupply'),
                            'script_used': script_name
                        }
                    else:
                        # Handle error response from Node.js
                        error_msg = "Token creation failed"
                        if json_output:
                            error_msg = json_output.get('message', error_msg)
                            technical_error = json_output.get('technical_error')
                            if technical_error:
                                logger.error(f"Technical error from {script_name}: {technical_error}")
                        
                        logger.warning(f"Script {script_name} failed: {error_msg}")
                        
                        # If this was the official SDK script and it failed, provide specific guidance
                        if script_name == 'create_raydium_token_correct.js':
                            if 'insufficient' in error_msg.lower():
                                return {
                                    'status': 'error',
                                    'message': f'LaunchLab creation failed: {error_msg}. Minimum 0.1 SOL required for LaunchLab.'
                                }
                        
                        continue
                else:
                    error_msg = result.stderr or result.stdout or f"Unknown error from {script_name}"
                    logger.error(f"Script {script_name} failed with return code {result.returncode}: {error_msg}")
                    
                    # Check for specific Node.js errors
                    if 'module not found' in error_msg.lower() or 'cannot resolve' in error_msg.lower():
                        logger.error("Missing Node.js dependencies! Run 'npm install' to fix.")
                        if script_name == node_scripts[0]:  # First script
                            return {
                                'status': 'error',
                                'message': 'Node.js dependencies missing. Please run "npm install" and try again.'
                            }
                    
                    continue
                    
            except subprocess.TimeoutExpired:
                logger.error(f"Node.js script {script_name} timeout (5 minutes)")
                continue
            except Exception as e:
                logger.error(f"Subprocess error with {script_name}: {e}")
                continue
        
        # If we get here, all scripts failed
        return {
            'status': 'error', 
            'message': 'All LaunchLab creation methods failed. Please ensure:\n1. Node.js 18+ is installed\n2. Run "npm install" to install dependencies\n3. Wallet has at least 0.1 SOL\n4. Network connection is stable'
        }
        
    except Exception as e:
        logger.error(f"Error in LaunchLab token creation: {e}")
        return {'status': 'error', 'message': get_user_friendly_error_message(str(e))}
    finally:
        # Clean up temp file
        try:
            if os.path.exists('token_params.json'):
                os.remove('token_params.json')
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
            await asyncio.sleep(2)
    
    return False

def setup_nodejs_environment():
    """
    Enhanced Node.js environment setup with LaunchLab SDK checks
    Returns: True if ready, False if missing components (but allows bot to start)
    """
    global NODEJS_AVAILABLE, NODEJS_SETUP_MESSAGE
    
    try:
        # Check if Node.js is available
        node_result = subprocess.run(['node', '--version'], capture_output=True, text=True)
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
        
        # Check if creation scripts exist
        script_priorities = [
            'create_raydium_token.js',
            'create_launchlab_token.js', 
            'create_raydium_token_correct.js'
        ]
        
        available_scripts = [script for script in script_priorities if os.path.exists(script)]
        
        if not available_scripts:
            logger.warning("No LaunchLab creation scripts found.")
            NODEJS_SETUP_MESSAGE = (
                "Missing token creation scripts. Please create one of:\n"
                "- create_raydium_token.js\n" 
                "- create_launchlab_token.js\n"
                "- create_raydium_token_correct.js\n\n"
                "These scripts handle the Raydium LaunchLab token creation."
            )
            return False
            
        logger.info(f"Available LaunchLab scripts: {available_scripts}")
        
        # Check if config.js exists (optional but recommended)
        if not os.path.exists('config.js'):
            logger.warning("config.js not found. This file may be required for Raydium SDK initialization.")
            # Don't fail for missing config.js, just warn
        
        # All checks passed
        logger.info("Node.js environment ready for token creation!")
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
        return "Your wallet needs more SOL. Please add at least 0.1 SOL to your wallet and try again."
    elif "insufficient balance" in error_lower or "insufficient funds" in error_lower:
        return "Insufficient SOL balance. LaunchLab requires at least 0.1 SOL. Please add more SOL to your wallet."
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

# ----- UPDATED LAUNCH FLOW FOR LOCK TOKENS -----
LAUNCH_STEPS = [
    ("name", "*LOCK Token Name*\nEnter your token name (e.g., 'Chain Lock'):"), 
    ("ticker", "*Token Symbol*\nEnter your token symbol (e.g., 'CHAIN'):\n\n*Note: All contracts will end with 'lock' for premium branding*"),
    ("description", "*Token Description*\nDescribe your LOCK token project (max 500 characters):"), 
    ("total_supply", "*Total Token Supply*\nChoose your token supply:\n\n1 - 69M\n2 - 420M  \n3 - 1B (Standard)\n4 - 69B\n5 - 420B\n6 - 1T\n7 - Custom\n\nSend the number (1-7) or custom amount:"),
    ("decimals", "*Token Decimals*\nEnter decimals (6-9 recommended):\n\n*6 = Standard (like USDC)*\n*9 = Solana native (like SOL)*"),
    ("image", "*Logo Image*\nSend your LOCK token logo:\n\n• Max 15MB\n• PNG/JPG/GIF recommended\n• Min 1000x1000px\n• Square (1:1) recommended"), 
    ("banner", "*Banner Image (Optional)*\nSend banner for LOCK token page:\n\n• Max 5MB\n• 3:1 ratio (1500x500px)\n• PNG/JPG/GIF only\n\nSend image or type 'skip':"),
    ("website", "*Website (Optional)*\nEnter your project website URL or type 'skip':"), 
    ("twitter", "*Twitter/X (Optional)*\nEnter your Twitter/X profile URL or type 'skip':"), 
    ("telegram", "*Telegram (Optional)*\nEnter your Telegram group/channel URL or type 'skip':"), 
    ("buy_amount", f"*Initial Purchase (Optional)*\nEnter SOL amount for initial buy on Raydium LaunchLab or type 'skip':\n\n• OPTIONAL - LOCK tokens work without initial purchase\n• Creates initial liquidity on bonding curve\n• Range: 0.001 - 50 SOL\n• Type 'skip' for pure token creation\n\nMust be less than total balance.")
]

# Token supply presets
TOKEN_SUPPLY_PRESETS = {
    "1": 69_000_000,      # 69M
    "2": 420_000_000,     # 420M  
    "3": 1_000_000_000,   # 1B (Standard)
    "4": 69_000_000_000,  # 69B
    "5": 420_000_000_000, # 420B
    "6": 1_000_000_000_000, # 1T
    "7": "custom"         # Custom amount
}

def start_launch_flow(context):
    """Start the LOCK launch flow"""
    context.user_data["launch_step_index"] = 0
    context.user_data["coin_data"] = {}

def get_launch_flow_keyboard(context, confirm=False):
    keyboard = []
    if confirm:
        keyboard.append([
            InlineKeyboardButton(f"Generate LOCK Address & Launch", callback_data=CALLBACKS["launch_confirm_yes"]),
            InlineKeyboardButton("Edit Details", callback_data=CALLBACKS["launch_change_buy_amount"])
        ])
    keyboard.append([
        InlineKeyboardButton("My LOCK Tokens", callback_data=CALLBACKS["launched_coins"]),
        InlineKeyboardButton("Cancel", callback_data=CALLBACKS["launch_confirm_no"])
    ])
    return InlineKeyboardMarkup(keyboard)

async def prompt_current_launch_step(update_obj, context):
    index = context.user_data.get("launch_step_index", 0)
    
    if not context.user_data.get("user_id") and hasattr(update_obj, "effective_user"):
        context.user_data["user_id"] = update_obj.effective_user.id
        
    keyboard = get_launch_flow_keyboard(context, confirm=False)
    
    if "last_prompt_msg_id" in context.user_data:
        try:
            if hasattr(update_obj, "message") and update_obj.message:
                await update_obj.message.bot.delete_message(update_obj.message.chat_id, context.user_data["last_prompt_msg_id"])
            elif hasattr(update_obj, "callback_query") and update_obj.callback_query:
                await update_obj.callback_query.message.bot.delete_message(update_obj.callback_query.message.chat_id, context.user_data["last_prompt_msg_id"])
        except Exception:
            pass
            
    if index < len(LAUNCH_STEPS):
        step_key, prompt_text = LAUNCH_STEPS[index]
        
        if hasattr(update_obj, "callback_query") and update_obj.callback_query:
            sent_msg = await update_obj.callback_query.message.reply_text(prompt_text, reply_markup=keyboard, parse_mode="Markdown")
        elif hasattr(update_obj, "message") and update_obj.message:
            sent_msg = await update_obj.message.reply_text(prompt_text, reply_markup=keyboard, parse_mode="Markdown")
        context.user_data["last_prompt_msg_id"] = sent_msg.message_id
    else:
        # Show review screen for LOCK
        coin_data = context.user_data.get("coin_data", {})
        
        # Get generation time estimates
        estimates = estimate_vanity_generation_time(CONTRACT_SUFFIX)
        
        # Handle optional buy amount display
        buy_amount_raw = coin_data.get('buy_amount')
        has_initial_buy = False
        buy_amount_display = "None (Pure Creation)"
        
        if buy_amount_raw is not None and buy_amount_raw != 0:
            try:
                buy_amount = float(buy_amount_raw)
                if buy_amount > 0:
                    has_initial_buy = True
                    buy_amount_display = f"{buy_amount} SOL"
            except (ValueError, TypeError):
                pass
        
        summary = (
            f"*Review Your LOCK Token:*\n\n" +
            f"*Name:* {coin_data.get('name')}\n" +
            f"*Symbol:* {coin_data.get('ticker')}\n" +
            f"*Total Supply:* {coin_data.get('total_supply', 1_000_000_000):,}\n" +
            f"*Decimals:* {coin_data.get('decimals', 9)}\n" +
            f"*Initial Buy:* {buy_amount_display}\n\n" +
            f"*Media:*\n" +
            f"• Logo: {'✓ Uploaded' if coin_data.get('image') else '✗ Missing'}\n" +
            f"• Banner: {'✓ Uploaded' if coin_data.get('banner') else '○ None'}\n\n" +
            f"*Social Links:*\n" +
            f"• Website: {coin_data.get('website') or 'None'}\n" +
            f"• Twitter: {coin_data.get('twitter') or 'None'}\n" +
            f"• Telegram: {coin_data.get('telegram') or 'None'}\n\n" +
            f"*Contract Address:*\n" +
            f"Will end with: *{CONTRACT_SUFFIX}*\n" +
            f"Platform: Raydium LaunchLab\n" +
            f"Funding Target: 85 SOL\n" +
            f"Difficulty: {estimates['difficulty']}\n" +
            f"Est. Generation Time: {estimates['time_estimate']}\n\n"
        )
        
        if has_initial_buy:
            summary += f"*Launch Mode:* With Initial Liquidity\n• Creates bonding curve liquidity\n• Token immediately tradeable on LaunchLab"
        else:
            summary += f"*Launch Mode:* Pure Creation\n• Token created without initial liquidity\n• Add liquidity manually later\n• Lower cost option"
        
        summary += f"\n\nReady to create your LOCK token ending with '{CONTRACT_SUFFIX}'?"
        
        keyboard = get_launch_flow_keyboard(context, confirm=True)
        
        if hasattr(update_obj, "callback_query") and update_obj.callback_query:
            sent_msg = await update_obj.callback_query.message.reply_text(summary, reply_markup=keyboard, parse_mode="Markdown")
        elif hasattr(update_obj, "message") and update_obj.message:
            sent_msg = await update_obj.message.reply_text(summary, reply_markup=keyboard, parse_mode="Markdown")
        context.user_data["last_prompt_msg_id"] = sent_msg.message_id

# ----- ENHANCED LAUNCH CONFIRMATION WITH NODEJS CHECK -----
async def process_launch_confirmation(query, context):
    """
    Enhanced launch confirmation with LOCK address verification and Node.js checks
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
            f"To create LOCK tokens, you need:\n\n"
            f"{NODEJS_SETUP_MESSAGE}\n\n"
            f"Please complete the setup and restart the bot.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Use enhanced token creation with funding checks and LOCK verification
    async def update_progress(message_text):
        try:
            await query.message.edit_text(message_text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Progress update failed: {e}")

    result = await create_lock_token_with_raydium(coin_data, wallet, update_progress)
    
    if result.get('status') != 'success':
        error_message = result.get('message', 'Unknown error occurred')
        
        # Check if it's a Node.js setup issue
        if result.get('requires_nodejs_setup'):
            keyboard = [
                [InlineKeyboardButton("Setup Instructions", callback_data=CALLBACKS["setup_nodejs"])],
                [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
            ]
        # Check if it's a funding issue and provide specific guidance
        elif 'insufficient' in error_message.lower() or 'balance' in error_message.lower():
            required = result.get('funding_required', 0.1)
            current = result.get('current_balance', 0)
            
            keyboard = [
                [InlineKeyboardButton("Check Balance", callback_data=CALLBACKS["refresh_balance"])],
                [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
            ]
            
            funding_message = (
                f"LOCK Token Creation Failed\n\n"
                f"Reason: {error_message}\n\n"
                f"To create LOCK tokens on LaunchLab, you need:\n"
                f"• Minimum 0.1 SOL for token creation\n"
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

    # SUCCESS: Enhanced success handling with LOCK verification
    tx_signature = result.get('signature')
    vanity_address = result.get('mint')
    attempts = result.get('attempts', 0)
    is_pure_creation = result.get('pure_creation', False)
    funding_used = result.get('funding_used', 0)
    balance_after = result.get('wallet_balance_after', 0)
    verified_lock_suffix = result.get('verified_lock_suffix', False)
    funding_target = result.get('funding_target', 85)
    
    # CRITICAL: Final verification that address ends with 'lock'
    if not vanity_address.lower().endswith('lock'):
        logger.error(f"CRITICAL ERROR: Final address doesn't end with LOCK: {vanity_address}")
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text(
            f"CRITICAL ERROR: Token created but address verification failed!\n\n"
            f"Expected: Address ending with 'lock'\n"
            f"Got: {vanity_address}\n\n"
            f"Please contact support.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    
    # Build success message with LOCK verification
    tx_link = f"https://solscan.io/tx/{tx_signature}"
    chart_url = f"https://raydium.io/launchpad/token/?mint={vanity_address}"

    if is_pure_creation:
        mode_description = (
            f"*Launch Mode:* Pure Creation\n"
            f"• Token created without initial liquidity\n"
            f"• Ready for bonding curve trading\n"
            f"• Cost: {funding_used:.6f} SOL"
        )
    else:
        initial_buy = result.get('initial_liquidity_sol', 0)
        mode_description = (
            f"*Launch Mode:* With Bonding Curve Liquidity\n"
            f"• Initial Liquidity: {initial_buy} SOL\n"
            f"• Total Cost: {funding_used:.6f} SOL\n"
            f"• Immediate trading available"
        )

    message = (
        f"LOCK Token Launched Successfully!\n\n"
        f"*{coin_data.get('name')}* ({coin_data.get('ticker')})\n"
        f"*Contract:* `{vanity_address}`\n"
        f"*LOCK Verified:* Ends with '{vanity_address[-4:]}'\n\n"
        f"*Token Details:*\n"
        f"• Supply: {coin_data.get('total_supply', 1_000_000_000):,}\n"
        f"• Generated in: {attempts:,} attempts\n"
        f"• Wallet Balance: {balance_after:.6f} SOL remaining\n"
        f"• LOCK Suffix Verified: {'✅' if verified_lock_suffix else '❌'}\n\n"
        + mode_description + "\n\n"
        f"*LOCK Features:*\n"
        f"• Contract ends with '{CONTRACT_SUFFIX}' ✅\n"
        f"• Raydium LaunchLab bonding curve\n"
        f"• Auto-graduation at {funding_target} SOL\n\n"
        f"Your LOCK token is now live!\n\n"
        f"Contract: `{vanity_address}`"
    )
    
    keyboard = [
        [InlineKeyboardButton("View on Raydium", url=chart_url)],
        [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/{vanity_address}")],
        [InlineKeyboardButton("View Transaction", url=tx_link)],
        [InlineKeyboardButton("Launch Another LOCK", callback_data=CALLBACKS["launch"])],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
    ]

    # Save to user coins with LOCK verification
    if user_id not in user_coins:
        user_coins[user_id] = []
    user_coins[user_id].append({
        "name": coin_data.get("name", "Unnamed LOCK Token"),
        "ticker": coin_data.get("ticker", ""),
        "tx_link": tx_link,
        "chart_url": chart_url,
        "mint": vanity_address,
        "is_vanity": True,
        "vanity_suffix": CONTRACT_SUFFIX,
        "generation_attempts": attempts,
        "has_liquidity": not is_pure_creation,
        "initial_buy_amount": result.get('initial_liquidity_sol', 0),
        "platform": "Raydium LaunchLab",
        "funding_used": funding_used,
        "verified_lock_suffix": verified_lock_suffix,
        "funding_target": funding_target,
        "created_at": datetime.now().isoformat()
    })
    
    # Clear launch data
    context.user_data.pop("launch_step_index", None)
    context.user_data.pop("coin_data", None)
    
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- LAUNCHED TOKENS DISPLAY FOR LOCK TOKENS -----
async def show_launched_coins(update: Update, context):
    """Show user's launched LOCK tokens"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_coins_list = user_coins.get(user_id, [])
    
    if not user_coins_list:
        message = f"You haven't launched any LOCK tokens yet.\n\nStart creating your LOCK collection today!\n\nAll your tokens will have contract addresses ending with '{CONTRACT_SUFFIX}'"
        keyboard = [
            [InlineKeyboardButton("Launch First LOCK Token", callback_data=CALLBACKS["launch"])],
            [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
        ]
    else:
        message = f"Your LOCK Token Portfolio ({len(user_coins_list)} tokens):\n\n"
        
        for i, coin in enumerate(user_coins_list[-10:], 1):  # Show last 10 tokens
            created_date = coin.get("created_at", "")
            attempts = coin.get("generation_attempts", 0)
            has_liquidity = coin.get("has_liquidity", False)
            platform = coin.get("platform", "Raydium LaunchLab")
            verified = coin.get("verified_on_chain", False)
            funding_used = coin.get("funding_used", 0)
            verified_lock_suffix = coin.get("verified_lock_suffix", False)
            
            if created_date:
                try:
                    date_obj = datetime.fromisoformat(created_date.replace('Z', '+00:00'))
                    date_str = date_obj.strftime("%m/%d %H:%M")
                except:
                    date_str = "Unknown"
            else:
                date_str = "Unknown"
            
            # Show last 8 chars to highlight the lock suffix
            contract_display = f"...{coin['mint'][-8:]}" if len(coin['mint']) > 8 else coin['mint']
                
            message += f"{i}. *{coin['ticker']}* - {coin['name']}\n"
            message += f"   Contract: `{contract_display}`\n"
            message += f"   Created: {date_str}\n"
            message += f"   Platform: {platform}\n"
            if attempts > 0:
                message += f"   Generated in {attempts:,} attempts\n"
            message += f"   Mode: {'With Liquidity' if has_liquidity else 'Pure Creation'}\n"
            if funding_used > 0:
                message += f"   Cost: {funding_used:.4f} SOL\n"
            message += f"   Status: {'✅ Verified' if verified else '○ Pending'}\n"
            message += f"   LOCK: {'✅' if verified_lock_suffix else '○'}\n"
            message += f"\n"
        
        if len(user_coins_list) > 10:
            message += f"... and {len(user_coins_list) - 10} more LOCK tokens\n\n"
        
        message += f"All tokens have vanity addresses ending with '{CONTRACT_SUFFIX}'!"
        
        keyboard = [
            [InlineKeyboardButton("Launch Another LOCK", callback_data=CALLBACKS["launch"])],
            [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
        ]
    
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- NODEJS SETUP INSTRUCTIONS -----
async def show_nodejs_setup_instructions(update: Update, context):
    """Show Node.js setup instructions"""
    query = update.callback_query
    await query.answer()
    
    setup_instructions = (
        f"Node.js Setup Instructions\n\n"
        f"To create LOCK tokens ending with '{CONTRACT_SUFFIX}', you need:\n\n"
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
        f"*4. Create Token Script*\n"
        f"Need one of:\n"
        f"• create_raydium_token.js\n"
        f"• create_launchlab_token.js\n\n"
        f"*Current Status:*\n"
        f"{NODEJS_SETUP_MESSAGE}\n\n"
        f"Once setup is complete, restart the bot to enable LOCK token creation."
    )
    
    keyboard = [
        [InlineKeyboardButton("Check Status Again", callback_data=CALLBACKS["settings"])],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
    ]
    
    await query.message.edit_text(setup_instructions, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- MAIN MENU & WELCOME MESSAGE FOR LOCK TOKENS -----
def generate_inline_keyboard():
    return [
        [InlineKeyboardButton("Launch LOCK Token", callback_data=CALLBACKS["launch"])],
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
        
        # Show wallet funding status for LaunchLab requirements
        funding_status = "Ready" if balance >= 0.1 else "Needs Funding"
        nodejs_status = "Ready" if NODEJS_AVAILABLE else "Setup Required"
        
        welcome_message = (
            f"Welcome to the LOCK Token Launcher!\n\n"
            f"Create professional tokens with vanity contract addresses ending in '{CONTRACT_SUFFIX}' using Raydium LaunchLab.\n\n"
            f"Current Balance: {balance:.6f} SOL\n"
            f"Status: {funding_status}\n"
            f"Node.js: {nodejs_status}\n\n"
            "Send SOL to your wallet to get started:\n"
            f"`{wallet_address}`\n\n"
            f"Minimum required: 0.1 SOL for LaunchLab creation\n"
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
        funding_status = "Ready" if balance >= 0.1 else "Needs Funding"
    else:
        wallet_address = "No wallet"
        balance = 0.0
        funding_status = "No wallet"
    
    nodejs_status = "Ready" if NODEJS_AVAILABLE else "Setup Required"
        
    welcome_message = (
        f"Welcome to the LOCK Token Launcher!\n\n"
        f"Create professional tokens with vanity contract addresses ending in '{CONTRACT_SUFFIX}' using Raydium LaunchLab.\n\n"
        f"Current Balance: {balance:.6f} SOL\n"
        f"Status: {funding_status}\n"
        f"Node.js: {nodejs_status}\n\n"
        "Send SOL to your wallet to get started:\n"
        f"`{wallet_address}`\n\n"
        f"Minimum required: 0.1 SOL for LaunchLab creation\n"
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

# ----- REFRESH HANDLER FOR LOCK TOKENS -----
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
    
    # Show funding requirements for LaunchLab
    funding_status = "Ready for LOCK creation" if current_balance >= 0.1 else "Need more SOL"
    funding_color = "✅" if current_balance >= 0.1 else "⚠"
    nodejs_status = "✅ Ready" if NODEJS_AVAILABLE else "⚠ Setup Required"
    
    message = (
        f"LOCK Wallet Balance:\n\nAddress:\n`{wallet_address}`\n\n"
        f"Balance: {current_balance:.6f} SOL\n"
        f"Status: {funding_color} {funding_status}\n"
        f"Node.js: {nodejs_status}\n\n"
        f"Ready to create LOCK tokens ending with '{CONTRACT_SUFFIX}'!\n\n"
        f"LaunchLab Requirements:\n"
        f"• Pure creation: 0.1+ SOL\n"
        f"• With liquidity: 0.1+ SOL + buy amount\n"
        f"• Recommended: 0.15+ SOL\n\n"
        f"Node.js Status: {'Ready' if NODEJS_AVAILABLE else 'Setup Required'}\n\n"
        "(Tap address to copy)"
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
    
    # Count LOCK tokens and total funding used
    tokens_count = len(user_coins.get(user_id, []))
    total_funding_used = sum(coin.get("funding_used", 0) for coin in user_coins.get(user_id, []))
    
    funding_status = "✅ Ready" if balance >= 0.1 else "⚠ Needs SOL"
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
    msg = (f"LOCK Wallet Management\n\nWallet Address:\n`{wallet_address}`\n\n"
           f"Main Balance: {balance:.6f} SOL\nTotal Holdings: {total_holdings:.6f} SOL\n"
           f"Status: {funding_status}\n"
           f"Node.js: {nodejs_status}\n\n"
           f"LOCK Tokens Created: {tokens_count}\n"
           f"Total Spent on Tokens: {total_funding_used:.6f} SOL")
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
    
    funding_status = "✅ Ready for LOCK creation" if balance >= 0.1 else "⚠ Need more SOL"
    nodejs_status = "✅ Ready" if NODEJS_AVAILABLE else "⚠ Setup Required"
    
    message = (
        f"LOCK Wallet Details:\n\nAddress:\n`{wallet['public']}`\n\n"
        f"Main Balance: {balance:.6f} SOL\nTotal Holdings: {total_holdings:.6f} SOL\n"
        f"Status: {funding_status}\n"
        f"Node.js: {nodejs_status}\n\n"
        "Tap address to copy.\nDeposit SOL and tap Refresh to update balance.\n\n"
        f"LaunchLab Creation Requirements:\n"
        f"• Pure creation: 0.1+ SOL\n"
        f"• With liquidity: 0.1+ SOL + buy amount\n\n"
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

# ----- WITHDRAWAL HANDLERS (same as before but with better error messages) -----
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
        context.user_data.pop("awaiting_withdraw_dest", None)
        context.user_data.pop("withdraw_destination", None)
        context.user_data.pop("withdraw_amounts", None)
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
        
        message = (
            f"*Subscription Active!*\n"
            f"Plan: {sub_status['plan'].capitalize()}{time_left_str}\n\n"
            f"Node.js Status: {nodejs_status}\n\n"
            f"You can now create LOCK tokens ending with '{CONTRACT_SUFFIX}' on Raydium LaunchLab!"
        )
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
    else:
        nodejs_status = "Ready" if NODEJS_AVAILABLE else "Setup Required"
        
        message = (
            f"Subscribe to create LOCK tokens:\n\n"
            f"Unlock the ability to create tokens with contract addresses ending in '{CONTRACT_SUFFIX}' on Raydium LaunchLab.\n\n"
            f"Node.js Status: {nodejs_status}"
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
        message = (
            f"{plan.capitalize()} subscription activated!\n\n"
            f"Node.js Status: {nodejs_status}\n\n"
            f"You can now create LOCK tokens ending with '{CONTRACT_SUFFIX}' on Raydium LaunchLab!"
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

async def handle_text_message(update: Update, context):
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
    
    # Handle coin launch flow
    if "launch_step_index" in context.user_data:
        index = context.user_data.get("launch_step_index", 0)
        
        if index >= len(LAUNCH_STEPS):
            return
            
        step_key, _ = LAUNCH_STEPS[index]
        
        if step_key in ["image", "banner"]:
            await update.message.reply_text("Please send an image file, not text.")
            return
        
        # Handle total supply selection
        if step_key == "total_supply":
            if user_input in TOKEN_SUPPLY_PRESETS:
                if user_input == "7":  # Custom
                    await update.message.reply_text("Enter your custom token supply (e.g., 500000000):")
                    context.user_data["awaiting_custom_supply"] = True
                    return
                else:
                    supply = TOKEN_SUPPLY_PRESETS[user_input]
                    context.user_data.setdefault("coin_data", {})[step_key] = supply
            else:
                # Try to parse as number
                try:
                    supply = int(float(user_input))
                    if supply < 1000000:  # Minimum 1M tokens
                        await update.message.reply_text("Minimum token supply is 1,000,000. Please enter a larger amount.")
                        return
                    elif supply > 1000000000000:  # Maximum 1T tokens
                        await update.message.reply_text("Maximum token supply is 1,000,000,000,000 (1T). Please enter a smaller amount.")
                        return
                    context.user_data.setdefault("coin_data", {})[step_key] = supply
                except ValueError:
                    await update.message.reply_text("Invalid input. Please enter a number (1-7) or custom supply amount.")
                    return
        
        # Handle custom supply input
        elif context.user_data.get("awaiting_custom_supply"):
            try:
                supply = int(float(user_input))
                if supply < 1000000:
                    await update.message.reply_text("Minimum token supply is 1,000,000. Please enter a larger amount.")
                    return
                elif supply > 1000000000000:
                    await update.message.reply_text("Maximum token supply is 1,000,000,000,000 (1T). Please enter a smaller amount.")
                    return
                context.user_data.setdefault("coin_data", {})["total_supply"] = supply
                context.user_data.pop("awaiting_custom_supply", None)
            except ValueError:
                await update.message.reply_text("Please enter a valid number for token supply.")
                return
        
        # Handle decimals
        elif step_key == "decimals":
            try:
                decimals = int(user_input)
                if decimals < 0 or decimals > 9:
                    await update.message.reply_text("Decimals must be between 0-9. Recommended: 6 or 9.")
                    return
                context.user_data.setdefault("coin_data", {})[step_key] = decimals
            except ValueError:
                await update.message.reply_text("Please enter a valid number for decimals (0-9).")
                return
        
        # Handle optional buy amount (NEW: supports skip)
        elif step_key == "buy_amount":
            if user_input.lower() in ["skip", "none", ""]:
                # Skip initial buy - pure token creation
                context.user_data.setdefault("coin_data", {})[step_key] = None
            else:
                try:
                    buy_amount = float(user_input)
                    if buy_amount < 0:
                        await update.message.reply_text("Buy amount cannot be negative. Use 'skip' for no initial purchase.")
                        return
                    elif buy_amount > 50:
                        await update.message.reply_text("Maximum initial purchase is 50 SOL for safety.")
                        return
                    
                    # Check if user has enough balance
                    user_id = update.message.from_user.id
                    wallet = user_wallets.get(user_id)
                    if wallet:
                        current_balance = get_wallet_balance(wallet["public"])
                        required_total = 0.1 + buy_amount  # LaunchLab requirement
                        if current_balance < required_total:
                            await update.message.reply_text(
                                f"Insufficient balance.\n"
                                f"Required: {required_total:.6f} SOL (0.1 creation + {buy_amount} buy)\n"
                                f"Current: {current_balance:.6f} SOL\n"
                                f"Please add more SOL or reduce buy amount."
                            )
                            return
                    
                    context.user_data.setdefault("coin_data", {})[step_key] = buy_amount
                except ValueError:
                    await update.message.reply_text("Please enter a valid number for SOL amount or 'skip' for no initial purchase.")
                    return
        
        # Handle banner skip
        elif step_key == "banner" and user_input.lower() == "skip":
            context.user_data.setdefault("coin_data", {})[step_key] = None
        
        # Handle optional fields
        elif step_key in ["website", "twitter", "telegram"] and user_input.lower() in ["skip", "none", ""]:
            context.user_data.setdefault("coin_data", {})[step_key] = None
        
        # Handle regular text inputs
        else:
            # Validate description length
            if step_key == "description" and len(user_input) > 500:
                await update.message.reply_text("Description too long. Please keep it under 500 characters.")
                return
            
            context.user_data.setdefault("coin_data", {})[step_key] = user_input
        
        context.user_data["launch_step_index"] = index + 1
        await prompt_current_launch_step(update, context)
        return
    
    # Default response
    await update.message.reply_text(f"Use the buttons to create LOCK tokens ending with '{CONTRACT_SUFFIX}'.")

async def handle_media_message(update: Update, context):
    if "launch_step_index" in context.user_data:
        index = context.user_data.get("launch_step_index", 0)
        step_key, _ = LAUNCH_STEPS[index]
        
        if step_key in ["image", "banner"]:
            file = None
            file_size_mb = 0
            
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
                file = await context.bot.get_file(file_id)
                file_size_mb = file.file_size / (1024 * 1024)  # Convert to MB
                filename = f"{step_key}.png"
                
                # Check file size limits
                max_size = 15 if step_key == "image" else 5
                if file_size_mb > max_size:
                    await update.message.reply_text(f"File too large. Maximum size for {step_key}: {max_size}MB")
                    return
                    
            elif update.message.video and step_key == "image":  # Only allow video for logo
                file_id = update.message.video.file_id
                file = await context.bot.get_file(file_id)
                file_size_mb = file.file_size / (1024 * 1024)
                filename = f"{step_key}.mp4"
                
                if file_size_mb > 30:  # 30MB limit for videos
                    await update.message.reply_text("Video too large. Maximum size: 30MB")
                    return
            
            if file:
                os.makedirs("./downloads", exist_ok=True)
                file_path = f"./downloads/{filename}"
                await file.download_to_drive(file_path)
                
                context.user_data.setdefault("coin_data", {})[step_key] = file_path
                context.user_data["coin_data"][f"{step_key}_filename"] = filename
                context.user_data["launch_step_index"] = index + 1
                
                keyboard = get_launch_flow_keyboard(context, confirm=False)
                await update.message.reply_text(
                    f"LOCK {step_key.title()} uploaded successfully!\n\nProceeding...",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                await asyncio.sleep(1)
                
                await prompt_current_launch_step(update, context)
                return
            else:
                await update.message.reply_text(f"Please send a valid image for LOCK {step_key}.")
                return
                
    await handle_text_message(update, context)

# ----- MAIN CALLBACK HANDLER FOR LOCK TOKENS -----
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
        elif query.data == CALLBACKS["launch"]:
            user_id = query.from_user.id
            
            # Check if subscription is active (with expiry check)
            if not is_subscription_active(user_id):
                nodejs_status = "Ready" if NODEJS_AVAILABLE else "Setup Required"
                message = (
                    f"Subscribe to create LOCK tokens!\n\n"
                    f"You need an active subscription to create LOCK tokens ending with '{CONTRACT_SUFFIX}' on Raydium LaunchLab.\n\n"
                    f"Node.js Status: {nodejs_status}"
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
                        f"To create LOCK tokens, you need:\n\n"
                        f"{NODEJS_SETUP_MESSAGE}\n\n"
                        f"Please complete the setup and restart the bot.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                    return
                
                # Check wallet funding after Node.js check
                wallet = user_wallets.get(user_id)
                if wallet:
                    current_balance = get_wallet_balance(wallet["public"])
                    if current_balance < 0.1:  # LaunchLab requirement
                        keyboard = [
                            [InlineKeyboardButton("Check Balance", callback_data=CALLBACKS["refresh_balance"])],
                            [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
                        ]
                        await query.message.edit_text(
                            f"Insufficient SOL for LOCK Token Creation\n\n"
                            f"Current Balance: {current_balance:.6f} SOL\n"
                            f"Required: 0.1 SOL minimum (LaunchLab)\n\n"
                            f"Please add SOL to your wallet:\n"
                            f"`{wallet['public']}`",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode="Markdown"
                        )
                        return
                
                # Start LOCK launch flow
                start_launch_flow(context)
                await prompt_current_launch_step(query, context)
        elif query.data == CALLBACKS["launch_confirm_yes"]:
            await process_launch_confirmation(query, context)
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
            
            message = (f"LOCK Token Launcher Settings\n\n"
                       f"Contract Suffix: {CONTRACT_SUFFIX}\n"
                       f"Platform: Raydium LaunchLab\n"
                       f"Funding Target: 85 SOL\n"
                       f"Generation Difficulty: {estimates['difficulty']}\n"
                       f"Est. Time per Token: {estimates['time_estimate']}\n"
                       f"Your LOCK Tokens Created: {user_coins_count}\n"
                       f"Node.js Status: {nodejs_status}\n\n"
                       f"LaunchLab Features:\n"
                       f"• LOCK vanity addresses\n"
                       f"• Raydium LaunchLab bonding curves\n"
                       f"• Optional initial liquidity\n"
                       f"• Auto-graduation at 85 SOL\n"
                       f"• Pure creation mode available\n\n"
                       f"Requirements:\n"
                       f"• Minimum 0.1 SOL for creation\n"
                       f"• Additional SOL for initial liquidity\n"
                       f"• Valid subscription\n"
                       f"• Node.js 18+ with required dependencies")
            keyboard = [
                [InlineKeyboardButton("Setup Instructions", callback_data=CALLBACKS["setup_nodejs"])],
                [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
            ]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif query.data == CALLBACKS["socials"]:
            message = (
                f"LOCK Token Community\n\n"
                f"Join the community of LOCK token creators!\n\n"
                f"Share your vanity contracts ending with '{CONTRACT_SUFFIX}' and connect with other builders.\n\n"
                "• Platform: Raydium LaunchLab\n"
                "• All tokens LOCK compatible\n"
                "• Bonding curve graduation at 85 SOL\n"
                "• Professional token infrastructure\n\n"
                "Community links coming soon..."
            )
            keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await query.message.edit_text("LOCK feature coming soon!")
            
    except Exception as e:
        logger.error(f"Error in button callback for {query.data}: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("An error occurred. Please try again.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")

# ----- MAIN FUNCTION -----
def main():
    """
    Enhanced main function with environment checks and wallet funding validation
    Now allows bot to start even without Node.js setup
    """
    global NODEJS_AVAILABLE, NODEJS_SETUP_MESSAGE
    
    logger.info(f"LOCK Token Launcher Bot starting...")
    logger.info(f"Target suffix: '{CONTRACT_SUFFIX}'")
    
    # Setup Node.js environment (now optional)
    NODEJS_AVAILABLE = setup_nodejs_environment()
    
    if NODEJS_AVAILABLE:
        logger.info("Node.js environment ready for token creation!")
    else:
        logger.warning("Node.js environment not ready. Bot will start with limited functionality.")
        logger.warning(f"Setup message: {NODEJS_SETUP_MESSAGE}")
    
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set.")
    
    # Validate other environment variables
    pinata_key = os.getenv("PINATA_API_KEY")
    if not pinata_key or pinata_key == "demo":
        logger.warning("PINATA_API_KEY not set - using fallback IPFS services")
    
    application = Application.builder().token(bot_token).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media_message))
    
    logger.info(f"LOCK Token Launcher Bot started successfully!")
    logger.info(f"Features enabled:")
    logger.info(f"• Vanity address generation (suffix: '{CONTRACT_SUFFIX}')")
    if NODEJS_AVAILABLE:
        logger.info(f"• Raydium LaunchLab integration")
        logger.info(f"• Full token creation capabilities")
    else:
        logger.info(f"• Limited functionality (Node.js setup required for token creation)")
    logger.info(f"• Wallet management and SOL transfers")
    logger.info(f"• Enhanced error handling")
    logger.info(f"• Subscription system")
    
    application.run_polling()

if __name__ == "__main__":
    main()