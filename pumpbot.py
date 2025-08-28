import logging
import os
import random
import base58
import json
import requests
import asyncio
import time
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

# CALLBACKS – Enhanced with platform selection and percentage withdrawals
CALLBACKS = {
    "start": "start",
    "launch": "launch",
    "launch_platform_pump": "launch_platform_pump",
    "launch_platform_bonk": "launch_platform_bonk",
    "launch_platform_moonshot": "launch_platform_moonshot",
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
}

user_wallets = {}         # { user_id: { public, private, mnemonic, balance, bundle, ... } }
user_subscriptions = {}   # { user_id: { active, plan, amount, expires_at, tx_signature } }
user_coins = {}           # { user_id: [ coin_data, ... ] }

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

# ----- METADATA UPLOAD FUNCTIONS -----
def upload_pump_metadata(coin_data):
    """Upload metadata to pump.fun IPFS following exact API documentation"""
    try:
        # Define token metadata exactly as in docs
        form_data = {
            'name': coin_data.get('name'),
            'symbol': coin_data.get('ticker'), 
            'description': coin_data.get('description'),
            'twitter': coin_data.get('twitter'),
            'telegram': coin_data.get('telegram'),
            'website': coin_data.get('website'),
            'showName': 'true'
        }
        
        image_path = coin_data.get('image')
        if not image_path or not os.path.exists(image_path):
            raise Exception("Image file not found")
        
        # Read the image file exactly as in docs
        with open(image_path, 'rb') as f:
            file_content = f.read()
        
        files = {
            'file': (os.path.basename(image_path), file_content, 'image/png')
        }
        
        logger.info(f"Uploading pump metadata: {form_data}")
        
        # Create IPFS metadata storage - exact API call from docs
        metadata_response = requests.post("https://pump.fun/api/ipfs", data=form_data, files=files)
        
        logger.info(f"Pump IPFS response status: {metadata_response.status_code}")
        logger.info(f"Pump IPFS response: {metadata_response.text}")
        
        metadata_response.raise_for_status()
        metadata_response_json = metadata_response.json()
        
        # Return token metadata in exact format from docs
        return {
            'name': form_data['name'],
            'symbol': form_data['symbol'],
            'uri': metadata_response_json['metadataUri']
        }
        
    except Exception as e:
        logger.error(f"Error uploading pump metadata: {e}")
        raise

def upload_bonk_metadata(coin_data):
    """Upload metadata to bonk.fun storage endpoints following exact API documentation"""
    try:
        image_path = coin_data.get('image')
        if not image_path or not os.path.exists(image_path):
            raise Exception("Image file not found")
        
        # Read the image file exactly as in docs
        with open(image_path, 'rb') as f:
            file_content = f.read()
        
        files = {
            'image': (os.path.basename(image_path), file_content, 'image/png')
        }
        
        logger.info("Uploading bonk image...")
        
        # Create IPFS metadata storage - exact API call from docs
        img_response = requests.post("https://nft-storage.letsbonk22.workers.dev/upload/img", files=files)
        img_response.raise_for_status()
        img_uri = img_response.text
        
        logger.info(f"Bonk image upload response: {img_uri}")
        
        # Upload metadata - exact format from docs
        metadata_payload = {
            'createdOn': "https://bonk.fun",
            'description': coin_data.get('description'),
            'image': img_uri,
            'name': coin_data.get('name'),
            'symbol': coin_data.get('ticker'),
            'website': coin_data.get('website')
        }
        
        logger.info(f"Uploading bonk metadata: {metadata_payload}")
        
        metadata_response = requests.post(
            "https://nft-storage.letsbonk22.workers.dev/upload/meta",
            headers={'Content-Type': 'application/json'},
            data=json.dumps(metadata_payload)
        )
        metadata_response.raise_for_status()
        metadata_uri = metadata_response.text
        
        logger.info(f"Bonk metadata upload response: {metadata_uri}")
        
        # Return token metadata in exact format from docs
        return {
            'name': coin_data.get('name'),
            'symbol': coin_data.get('ticker'),
            'uri': metadata_uri
        }
        
    except Exception as e:
        logger.error(f"Error uploading bonk metadata: {e}")
        raise

# ----- TOKEN CREATION FUNCTION -----
def create_token_multi_platform(coin_data, user_wallet):
    """
    Create token on specified platform using PumpPortal API
    Supports: pump, bonk, moonshot
    """
    platform = coin_data.get("platform", "pump")
    
    try:
        # Generate new mint keypair
        mint_keypair = SoldersKeypair()
        
        # Upload metadata based on platform
        if platform == "pump":
            token_metadata = upload_pump_metadata(coin_data)
        elif platform in ["bonk", "moonshot"]:
            token_metadata = upload_bonk_metadata(coin_data)
        else:
            raise Exception(f"Unsupported platform: {platform}")
        
        # Get API key
        api_key = os.getenv("PUMPFUN_API_KEY")
        if not api_key:
            raise Exception("PUMPFUN_API_KEY environment variable not set")
        
        # Prepare trade payload following exact API documentation
        payload = {
            'action': 'create',
            'tokenMetadata': token_metadata,
            'mint': str(mint_keypair),  # Pass the full keypair secret for Lightning API
            'denominatedInSol': 'true',
            'amount': coin_data.get('buy_amount', 1),  # Default 1 SOL dev buy
            'slippage': 10,
            'priorityFee': 0.0005 if platform == "pump" else 0.00005,
            'pool': platform
        }
        
        # Platform-specific adjustments
        if platform == "moonshot":
            payload['denominatedInSol'] = 'true'  # ignored for moonshot, always USDC
            payload['amount'] = coin_data.get('buy_amount', 1)  # 1 USDC default
        
        logger.info(f"Creating token on {platform} with payload: {json.dumps(payload, indent=2)}")
        
        # Send create request to PumpPortal
        trade_url = f"https://pumpportal.fun/api/trade?api-key={api_key}"
        headers = {'Content-Type': 'application/json'}
        
        response = requests.post(trade_url, headers=headers, data=json.dumps(payload))
        
        logger.info(f"API Response Status: {response.status_code}")
        logger.info(f"API Response Content: {response.text}")
        
        if response.status_code != 200:
            raise Exception(f"API returned status {response.status_code}: {response.text}")
        
        result = response.json()
        tx_signature = result.get('signature')
        
        if not tx_signature:
            raise Exception(f"No signature returned from PumpPortal API. Response: {result}")
        
        logger.info(f"Token created successfully on {platform}. Signature: {tx_signature}")
        
        return {
            'status': 'success', 
            'signature': tx_signature, 
            'mint': str(mint_keypair.pubkey()),
            'platform': platform
        }
        
    except Exception as e:
        logger.error(f"Error creating token on {platform}: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}

# ----- MAIN MENU & WELCOME MESSAGE -----
def generate_inline_keyboard():
    return [
        [InlineKeyboardButton("Launch", callback_data=CALLBACKS["launch"])],
        [
            InlineKeyboardButton("Subscription", callback_data=CALLBACKS["subscription"]),
            InlineKeyboardButton("Wallets", callback_data=CALLBACKS["wallets"]),
            InlineKeyboardButton("Settings", callback_data=CALLBACKS["settings"]),
        ],
        [
            InlineKeyboardButton("Volume Bots", callback_data=CALLBACKS["bump_volume"]),
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
        
        welcome_message = (
            "Welcome to PumpBot!\n\n"
            "The fastest way to launch and manage assets, created by a team of friends from the PUMP community.\n\n"
            f"You currently have {balance:.6f} SOL balance.\n"
            "To get started, subscribe first and send some SOL to your PumpBot wallet address:\n\n"
            f"`{wallet_address}`\n\n"
            "Once done, tap Refresh and your balance will appear here.\n\n"
            "Remember: We guarantee the safety of user funds on PumpBot, but if you expose your private key your funds will not be safe."
        )
        reply_markup = InlineKeyboardMarkup(generate_inline_keyboard())
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in start command: {e}", exc_info=True)
        await update.message.reply_text("An error occurred while starting PUMPbot. Please try again.")

async def go_to_main_menu(query, context):
    context.user_data["nav_stack"] = []
    user_id = query.from_user.id
    wallet = user_wallets.get(user_id)
    if wallet:
        wallet_address = wallet["public"]
        balance = get_wallet_balance(wallet_address)
        wallet["balance"] = balance
    else:
        wallet_address = "No wallet"
        balance = 0.0
    welcome_message = (
        "Welcome to PumpBot!\n\n"
        "The fastest way to launch and manage assets, created by a team of friends from the PUMP community.\n\n"
        f"You currently have {balance:.6f} SOL balance.\n"
        "To get started, subscribe first and send some SOL to your PumpBot wallet address:\n\n"
        f"`{wallet_address}`\n\n"
        "Once done, tap Refresh and your balance will appear here.\n\n"
        "Remember: We guarantee the safety of user funds on PumpBot, but if you expose your private key your funds will not be safe."
    )
    reply_markup = InlineKeyboardMarkup(generate_inline_keyboard())
    try:
        await query.message.edit_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("go_to_main_menu: Message not modified; ignoring error.")
        else:
            raise e

# ----- PLATFORM SELECTION FOR LAUNCH -----
async def show_platform_selection(update: Update, context):
    """Show platform selection for token launch"""
    query = update.callback_query
    await query.answer()
    
    message = (
        "Choose Launch Platform:\n\n"
        "*Pump.fun* - Original meme coin launchpad\n"
        "• SOL-based trading\n"
        "• High liquidity and volume\n"
        "• Most popular platform\n\n"
        "*Bonk.fun (LetsBonk)* - Community-driven platform\n"
        "• Built on Raydium Launchlab\n"
        "• WSOL trading pairs\n"
        "• Bonding curve mechanics\n\n"
        "*Moonshot* - Advanced features\n"
        "• USDC-denominated\n"
        "• Professional trading tools\n"
        "• Institutional-grade infrastructure"
    )
    
    keyboard = [
        [InlineKeyboardButton("Pump.fun", callback_data=CALLBACKS["launch_platform_pump"])],
        [InlineKeyboardButton("Bonk.fun", callback_data=CALLBACKS["launch_platform_bonk"])],
        [InlineKeyboardButton("Moonshot", callback_data=CALLBACKS["launch_platform_moonshot"])],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]
    ]
    
    push_nav_state(context, {
        "message_text": query.message.text,
        "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
        "parse_mode": "Markdown"
    })
    
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- LAUNCH FLOW STEPS -----
LAUNCH_STEPS = [
    ("name", "Please enter the *Coin Name*:"), 
    ("ticker", "Please enter the *Coin Ticker*:"), 
    ("description", "Please enter the *Coin Description*:"), 
    ("image", "Please send the *Logo Image* (image or video) for your coin:"), 
    ("telegram", "Please enter your *Telegram Link*:"), 
    ("website", "Please enter your *Website Link* (include https:// and .com):"), 
    ("twitter", "Please enter your *Twitter/X Link* (include https:// and .com):"), 
    ("buy_amount", "Choose how many SOL you want to spend buying your coin (optional).\nTip: Buying a small amount helps protect your coin from snipers.")
]

def start_launch_flow(context, platform):
    context.user_data["launch_step_index"] = 0
    context.user_data["coin_data"] = {"platform": platform}

def get_launch_flow_keyboard(context, confirm=False, include_proceed=False):
    keyboard = []
    if include_proceed:
        keyboard.append([InlineKeyboardButton("Proceed", callback_data=CALLBACKS["launch_proceed_buy_amount"])])
    if confirm:
        keyboard.append([
            InlineKeyboardButton("Confirm", callback_data=CALLBACKS["launch_confirm_yes"]),
            InlineKeyboardButton("Back", callback_data=CALLBACKS["launch_change_buy_amount"])
        ])
    row = [
        InlineKeyboardButton("Launched Coins", callback_data=CALLBACKS["launched_coins"]),
        InlineKeyboardButton("Cancel", callback_data=CALLBACKS["launch_confirm_no"])
    ]
    keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

async def prompt_current_launch_step(update_obj, context):
    index = context.user_data.get("launch_step_index", 0)
    platform = context.user_data.get("coin_data", {}).get("platform", "pump")
    include_proceed = (index < len(LAUNCH_STEPS)) and (LAUNCH_STEPS[index][0] == "buy_amount")
    
    if not context.user_data.get("user_id") and hasattr(update_obj, "effective_user"):
        context.user_data["user_id"] = update_obj.effective_user.id
        
    keyboard = get_launch_flow_keyboard(context, confirm=False, include_proceed=include_proceed)
    
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
        
        # Customize buy_amount prompt based on platform
        if step_key == "buy_amount":
            if platform == "pump":
                prompt_text = "Choose how many SOL you want to spend buying your coin (optional).\nTip: Buying a small amount helps protect your coin from snipers."
            elif platform == "bonk":
                prompt_text = "Choose your initial buy amount (optional).\nNote: Bonk.fun uses WSOL for trading.\nTip: Buying helps establish initial liquidity."
            elif platform == "moonshot":
                prompt_text = "Choose your initial buy amount in USDC (optional).\nNote: Moonshot uses USDC for all trades.\nTip: Initial buys help with price discovery."
        
        if hasattr(update_obj, "callback_query") and update_obj.callback_query:
            sent_msg = await update_obj.callback_query.message.reply_text(prompt_text, reply_markup=keyboard, parse_mode="Markdown")
        elif hasattr(update_obj, "message") and update_obj.message:
            sent_msg = await update_obj.message.reply_text(prompt_text, reply_markup=keyboard, parse_mode="Markdown")
        context.user_data["last_prompt_msg_id"] = sent_msg.message_id
    else:
        # Show review screen (shortened for brevity)
        coin_data = context.user_data.get("coin_data", {})
        platform_display = {"pump": "Pump.fun", "bonk": "Bonk.fun", "moonshot": "Moonshot"}.get(platform, platform)
        
        summary = (
            "*Review your coin data:*\n\n" +
            f"*Platform:* {platform_display}\n" +
            f"*Name:* {coin_data.get('name')}\n" +
            f"*Ticker:* {coin_data.get('ticker')}\n\n" +
            "Are you sure you want to create this coin?"
        )
        
        keyboard = get_launch_flow_keyboard(context, confirm=True, include_proceed=False)
        
        if hasattr(update_obj, "callback_query") and update_obj.callback_query:
            sent_msg = await update_obj.callback_query.message.reply_text(summary, reply_markup=keyboard, parse_mode="Markdown")
        elif hasattr(update_obj, "message") and update_obj.message:
            sent_msg = await update_obj.message.reply_text(summary, reply_markup=keyboard, parse_mode="Markdown")
        context.user_data["last_prompt_msg_id"] = sent_msg.message_id

async def process_launch_confirmation(query, context):
    coin_data = context.user_data.get("coin_data", {})
    user_id = query.from_user.id
    platform = coin_data.get("platform", "pump")

    # Check wallet balance
    wallet = user_wallets.get(user_id)
    if not wallet:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("No wallet found. Please create a wallet first.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return
        
    buy_amount = coin_data.get("buy_amount", 1)
    current_balance = get_wallet_balance(wallet["public"])
    
    if current_balance < buy_amount:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text(f"You don't have enough SOL. Current: {current_balance:.6f} SOL, Required: {buy_amount} SOL",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return

    # Show processing message
    await query.message.edit_text("Creating your token... Please wait.", parse_mode="Markdown")

    # Create token
    result = create_token_multi_platform(coin_data, wallet)
    
    if result.get('status') != 'success':
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text(f"Failed to launch coin: {result.get('message')}",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return

    tx_signature = result.get('signature')
    mint = result.get('mint')
    tx_link = f"https://solscan.io/tx/{tx_signature}"
    chart_url = f"https://pump.fun/{mint}" if platform == "pump" else f"https://dexscreener.com/solana/{mint}"

    # Save to user coins
    if user_id not in user_coins:
        user_coins[user_id] = []
    user_coins[user_id].append({
        "name": coin_data.get("name", "Unnamed Coin"),
        "ticker": coin_data.get("ticker", ""),
        "platform": platform,
        "tx_link": tx_link,
        "chart_url": chart_url,
        "mint": mint,
    })

    message = (
        f"Coin Launched!\n\n" +
        f"*Name:* {coin_data.get('name')}\n" +
        f"*Ticker:* {coin_data.get('ticker')}\n" +
        f"*Contract:* `{mint}`\n\n" +
        "Your coin is now live!"
    )
    
    # Clear launch data
    context.user_data.pop("launch_step_index", None)
    context.user_data.pop("coin_data", None)
    
    keyboard = [
        [InlineKeyboardButton("View Chart", url=chart_url)],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
    ]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- REFRESH HANDLER -----
async def refresh_balance(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    if query.message.text.startswith("Welcome to PUMPbot!"):
        await go_to_main_menu(query, context)
        return
        
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
    
    message = (
        f"Your Wallet:\n\nAddress:\n`{wallet_address}`\n\n"
        f"Balance: {current_balance:.6f} SOL\n\n(Tap the address to copy)"
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
    msg = (f"Wallet Management\n\nWallet Address:\n`{wallet_address}`\n\n"
           f"Main Balance: {balance:.6f} SOL\nTotal Holdings: {total_holdings:.6f} SOL")
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
    
    message = (
        f"Your Wallet:\n\nAddress:\n`{wallet['public']}`\n\n"
        f"Main Balance: {balance:.6f} SOL\nTotal Holdings: {total_holdings:.6f} SOL\n\n"
        "Tap the address to copy.\nDeposit SOL and tap Refresh to update your balance."
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

# ----- ULTIMATE FIXED WITHDRAWAL HANDLERS -----
async def handle_percentage_withdrawal(update: Update, context, percentage: str):
    """
    ULTIMATE FIXED: Handle withdrawal with proper account status checking
    """
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
        
        # Execute withdrawal using the ultimate fixed function
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
                f"SUCCESS! Withdrawal Complete\n\n"
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
                solution = "\n\nFIX: Your account needs activation\n1. Deposit 0.005+ SOL total\n2. Wait 2-3 minutes\n3. Try again"
            elif "rent exemption" in error_msg:
                solution = "\n\nFIX: Leave minimum SOL in wallet\n1. Try smaller withdrawal amount\n2. Keep 0.001 SOL minimum"
            else:
                solution = "\n\nTry again in a few minutes"
            
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
            f"Critical error. Your funds are safe.\nPlease try again.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

async def handle_withdraw_address_input(update: Update, context):
    """
    Enhanced withdrawal address handler with validation
    """
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

# ----- SUBSCRIPTION FEATURES (Simplified) -----
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
        "expires_at": expires_at,
        "tx_signature": fake_signature
    }
    return {"status": "success", "message": "Subscription activated"}

async def show_subscription_details(update: Update, context):
    query = update.callback_query
    await query.answer()
    subscription = user_subscriptions.get(query.from_user.id, {})
    
    if subscription.get("active"):
        message = f"*Subscription Active!*\nPlan: {subscription.get('plan').capitalize()}"
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
    else:
        message = "Choose subscription plan:"
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
        message = f"{plan.capitalize()} subscription activated!"
    else:
        message = f"Subscription failed: {result['message']}"
    
    keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- SIMPLIFIED BUNDLE MANAGEMENT -----
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
    
    message = "Bundle Wallets Created\n\n"
    for idx, b_wallet in enumerate(wallet["bundle"], start=1):
        message += f"{idx}. `{b_wallet['public']}`\n"
    
    keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- MAIN CALLBACK HANDLER -----
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
                    f"Insufficient balance.\nCurrent: {current_balance:.6f} SOL\nMinimum: {transaction_fee:.6f} SOL",
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
                f"Private Key:\n`{private_key}`\nKeep it safe!",
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
            subscription = user_subscriptions.get(user_id, {})
            if not subscription.get("active"):
                message = "You must subscribe to use Launch feature."
                keyboard = [
                    [InlineKeyboardButton("Subscribe", callback_data=CALLBACKS["subscription"])],
                    [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
                ]
                await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            else:
                await show_platform_selection(update, context)
        elif query.data.startswith("launch_platform_"):
            platform = query.data.split("_")[-1]
            start_launch_flow(context, platform)
            await prompt_current_launch_step(query, context)
        elif query.data == CALLBACKS["launch_confirm_yes"]:
            await process_launch_confirmation(query, context)
        elif query.data == CALLBACKS["launch_confirm_no"]:
            context.user_data.pop("launch_step_index", None)
            context.user_data.pop("coin_data", None)
            await go_to_main_menu(query, context)
        elif query.data == CALLBACKS["settings"]:
            message = "Settings\n\nConfiguration coming soon."
            keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif query.data == CALLBACKS["socials"]:
            message = "Connect with our community!"
            keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await query.message.edit_text("Feature coming soon!")
            
    except Exception as e:
        logger.error(f"Error in button callback for {query.data}: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("An error occurred. Please try again.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")

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
    
    # Handle withdraw address input - ULTIMATE FIXED
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
        
        if step_key == "image":
            await update.message.reply_text("Please send an image file, not text.")
            return
            
        context.user_data.setdefault("coin_data", {})[step_key] = user_input
        context.user_data["launch_step_index"] = index + 1
        await prompt_current_launch_step(update, context)
        return
    
    # Default response
    await update.message.reply_text("Please use the buttons or commands.")

async def handle_media_message(update: Update, context):
    if "launch_step_index" in context.user_data:
        index = context.user_data.get("launch_step_index", 0)
        step_key, _ = LAUNCH_STEPS[index]
        if step_key == "image":
            file = None
            if update.message.photo:
                file_id = update.message.photo[-1].file_id
                file = await context.bot.get_file(file_id)
                filename = "logo.png"
            elif update.message.video:
                file_id = update.message.video.file_id
                file = await context.bot.get_file(file_id)
                filename = "logo.mp4"
            if file:
                os.makedirs("./downloads", exist_ok=True)
                file_path = f"./downloads/{filename}"
                await file.download_to_drive(file_path)
                context.user_data.setdefault("coin_data", {})["image"] = file_path
                context.user_data["coin_data"]["image_filename"] = filename
                context.user_data["launch_step_index"] = index + 1
                await prompt_current_launch_step(update, context)
                return
    await handle_text_message(update, context)

# ----- MAIN FUNCTION -----
def main():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set.")
    application = Application.builder().token(bot_token).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media_message))
    
    logger.info("ULTIMATE FIXED PumpBot started - withdrawal system fully operational!")
    application.run_polling()

if __name__ == "__main__":
    main()