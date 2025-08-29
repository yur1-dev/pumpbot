# lock_token_creator.py
"""
LOCK Token Creator Module
Handles generation of Solana tokens with contract addresses ending in 'LOCK'
"""

import logging
import os
import time
import json
import requests
import base58
from solders.keypair import Keypair as SoldersKeypair
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logger = logging.getLogger(__name__)

# ----- LOCK CONTRACT GENERATION -----

def generate_lock_contract():
    """
    Generate Solana keypair where public key (contract address) ends with 'LOCK'
    
    Performance: 4-character suffix = ~5.7M attempts expected
    Time: 30 seconds to 5 minutes on any modern PC
    
    Returns:
        SoldersKeypair: Keypair with public key ending in 'LOCK'
    """
    start_time = time.time()
    attempts = 0
    
    logger.info("Starting LOCK contract generation...")
    
    while True:
        mint_keypair = SoldersKeypair()
        contract_address = str(mint_keypair.pubkey())
        attempts += 1
        
        if contract_address.endswith('LOCK'):
            elapsed = time.time() - start_time
            logger.info(f"LOCK contract generated: {contract_address}")
            logger.info(f"Found after {attempts:,} attempts in {elapsed:.1f} seconds")
            return mint_keypair
        
        # Progress logging every 100k attempts
        if attempts % 100000 == 0:
            elapsed = time.time() - start_time
            rate = attempts / elapsed if elapsed > 0 else 0
            logger.info(f"Searching... {attempts:,} attempts, {rate:,.0f}/sec")

async def generate_lock_with_telegram_updates(telegram_message):
    """
    Generate LOCK contract with live progress updates to Telegram message
    
    Args:
        telegram_message: Telegram message object to update with progress
        
    Returns:
        SoldersKeypair: Generated keypair ending with 'LOCK'
    """
    start_time = time.time()
    attempts = 0
    last_telegram_update = 0
    
    while True:
        mint_keypair = SoldersKeypair()
        contract_address = str(mint_keypair.pubkey())
        attempts += 1
        
        if contract_address.endswith('LOCK'):
            # Success - show final result
            final_message = (
                f"LOCK Contract Generated!\n\n"
                f"`{contract_address}`\n\n"
                f"Found after {attempts:,} attempts in {time.time() - start_time:.1f}s\n\n"
                f"Now deploying token..."
            )
            
            try:
                await telegram_message.edit_text(final_message, parse_mode="Markdown")
            except:
                pass  # Ignore Telegram rate limit errors
                
            return mint_keypair
        
        # Update Telegram every 20 seconds
        current_time = time.time()
        if current_time - last_telegram_update > 20:
            elapsed = current_time - start_time
            rate = attempts / elapsed if elapsed > 0 else 0
            estimated_remaining = (5700000 - attempts) / rate / 60 if rate > 0 else 0
            
            progress_text = (
                f"Generating LOCK Contract...\n\n"
                f"Attempts: {attempts:,}\n"
                f"Speed: {rate:,.0f}/sec\n"
                f"Time: {elapsed:.0f}s\n"
                f"Est. remaining: {estimated_remaining:.1f}min\n\n"
                f"Searching for address ending with LOCK..."
            )
            
            try:
                await telegram_message.edit_text(progress_text, parse_mode="Markdown")
                last_telegram_update = current_time
            except:
                pass  # Ignore rate limits

# ----- METADATA UPLOAD FUNCTIONS -----

def upload_pump_metadata(coin_data):
    """Upload metadata to pump.fun IPFS"""
    try:
        form_data = {
            'name': coin_data.get('name'),
            'symbol': coin_data.get('ticker'), 
            'description': coin_data.get('description'),
            'twitter': coin_data.get('twitter', ''),
            'telegram': coin_data.get('telegram', ''),
            'website': coin_data.get('website', ''),
            'showName': 'true'
        }
        
        image_path = coin_data.get('image')
        if not image_path or not os.path.exists(image_path):
            raise Exception("Image file not found")
        
        with open(image_path, 'rb') as f:
            file_content = f.read()
        
        files = {
            'file': (os.path.basename(image_path), file_content, 'image/png')
        }
        
        logger.info(f"Uploading pump metadata for: {form_data['name']}")
        
        metadata_response = requests.post(
            "https://pump.fun/api/ipfs", 
            data=form_data, 
            files=files,
            timeout=60
        )
        
        if metadata_response.status_code != 200:
            raise Exception(f"Pump metadata upload failed: {metadata_response.status_code} - {metadata_response.text}")
        
        metadata_json = metadata_response.json()
        
        return {
            'name': form_data['name'],
            'symbol': form_data['symbol'],
            'uri': metadata_json['metadataUri']
        }
        
    except Exception as e:
        logger.error(f"Error uploading pump metadata: {e}")
        raise

def upload_bonk_metadata(coin_data):
    """Upload metadata to bonk.fun storage"""
    try:
        image_path = coin_data.get('image')
        if not image_path or not os.path.exists(image_path):
            raise Exception("Image file not found")
        
        with open(image_path, 'rb') as f:
            file_content = f.read()
        
        files = {
            'image': (os.path.basename(image_path), file_content, 'image/png')
        }
        
        # Upload image
        img_response = requests.post(
            "https://nft-storage.letsbonk22.workers.dev/upload/img", 
            files=files,
            timeout=60
        )
        img_response.raise_for_status()
        img_uri = img_response.text
        
        # Upload metadata
        metadata_payload = {
            'createdOn': "https://bonk.fun",
            'description': coin_data.get('description'),
            'image': img_uri,
            'name': coin_data.get('name'),
            'symbol': coin_data.get('ticker'),
            'website': coin_data.get('website', '')
        }
        
        metadata_response = requests.post(
            "https://nft-storage.letsbonk22.workers.dev/upload/meta",
            headers={'Content-Type': 'application/json'},
            data=json.dumps(metadata_payload),
            timeout=60
        )
        metadata_response.raise_for_status()
        metadata_uri = metadata_response.text
        
        return {
            'name': coin_data.get('name'),
            'symbol': coin_data.get('ticker'),
            'uri': metadata_uri
        }
        
    except Exception as e:
        logger.error(f"Error uploading bonk metadata: {e}")
        raise

# ----- MAIN TOKEN CREATION FUNCTION -----

def create_lock_token(coin_data, user_wallet, mint_keypair=None):
    """
    Create token with LOCK contract address
    
    Args:
        coin_data (dict): Token information (name, ticker, description, etc.)
        user_wallet (dict): User's wallet info for payment
        mint_keypair (SoldersKeypair, optional): Pre-generated LOCK keypair
        
    Returns:
        dict: Result with status, signature, mint address
    """
    platform = coin_data.get("platform", "pump")
    
    try:
        # Use provided keypair or generate new LOCK keypair
        if mint_keypair is None:
            logger.info("Generating new LOCK contract...")
            mint_keypair = generate_lock_contract()
        
        contract_address = str(mint_keypair.pubkey())
        logger.info(f"Creating token with LOCK contract: {contract_address}")
        
        # Upload metadata based on platform
        if platform == "pump":
            token_metadata = upload_pump_metadata(coin_data)
        elif platform in ["bonk", "moonshot"]:
            token_metadata = upload_bonk_metadata(coin_data)
        else:
            raise Exception(f"Unsupported platform: {platform}")
        
        logger.info(f"Metadata uploaded for {platform}")
        
        # Get API key
        api_key = os.getenv("PUMPFUN_API_KEY")
        if not api_key:
            raise Exception("PUMPFUN_API_KEY environment variable not set")
        
        # Build payload for PumpPortal API
        payload = {
            'action': 'create',
            'tokenMetadata': token_metadata,
            'mint': str(mint_keypair),  # LOCK keypair
            'denominatedInSol': 'true',
            'amount': coin_data.get('buy_amount', 1),
            'slippage': 10,
            'priorityFee': 0.0005 if platform == "pump" else 0.00005,
            'pool': platform
        }
        
        # Platform-specific adjustments
        if platform == "moonshot":
            payload['amount'] = coin_data.get('buy_amount', 1)  # USDC for moonshot
        
        logger.info(f"Deploying LOCK token on {platform}")
        
        # Send request to PumpPortal
        trade_url = f"https://pumpportal.fun/api/trade?api-key={api_key}"
        headers = {'Content-Type': 'application/json'}
        
        response = requests.post(
            trade_url, 
            headers=headers, 
            data=json.dumps(payload),
            timeout=120
        )
        
        logger.info(f"API Response: {response.status_code}")
        
        if response.status_code != 200:
            raise Exception(f"API error {response.status_code}: {response.text}")
        
        result = response.json()
        tx_signature = result.get('signature')
        
        if not tx_signature:
            raise Exception(f"No transaction signature returned: {result}")
        
        logger.info(f"LOCK token created successfully!")
        logger.info(f"Contract: {contract_address}")
        logger.info(f"Transaction: {tx_signature}")
        
        return {
            'status': 'success',
            'signature': tx_signature,
            'mint': contract_address,
            'platform': platform,
            'metadata': token_metadata
        }
        
    except Exception as e:
        logger.error(f"LOCK token creation failed: {e}")
        return {
            'status': 'error', 
            'message': str(e)
        }

# ----- ASYNC CREATION WITH TELEGRAM INTEGRATION -----

async def create_lock_token_async(coin_data, user_wallet, telegram_message):
    """
    Async LOCK token creation with live Telegram progress updates
    
    Args:
        coin_data (dict): Token information
        user_wallet (dict): User's wallet for payment  
        telegram_message: Telegram message object for progress updates
        
    Returns:
        dict: Creation result with status, signature, contract address
    """
    platform = coin_data.get("platform", "pump")
    
    try:
        # Step 1: Generate LOCK contract with live updates
        await telegram_message.edit_text(
            "Creating LOCK Token...\n\n"
            "Step 1: Generating LOCK contract address\n"
            "Step 2: Upload metadata\n" 
            "Step 3: Deploy on blockchain\n\n"
            "Starting generation...",
            parse_mode="Markdown"
        )
        
        mint_keypair = await generate_lock_with_telegram_updates(telegram_message)
        contract_address = str(mint_keypair.pubkey())
        
        # Step 2: Upload metadata
        await telegram_message.edit_text(
            f"LOCK Contract Generated!\n\n"
            f"`{contract_address}`\n\n"
            f"Uploading metadata to {platform.title()}...",
            parse_mode="Markdown"
        )
        
        if platform == "pump":
            token_metadata = upload_pump_metadata(coin_data)
        elif platform in ["bonk", "moonshot"]:
            token_metadata = upload_bonk_metadata(coin_data)
        else:
            raise Exception(f"Platform {platform} not supported")
        
        # Step 3: Deploy token
        await telegram_message.edit_text(
            f"Metadata Ready!\n\n"
            f"`{contract_address}`\n\n"
            f"Deploying on {platform.title()}...",
            parse_mode="Markdown"
        )
        
        api_key = os.getenv("PUMPFUN_API_KEY")
        if not api_key:
            raise Exception("PUMPFUN_API_KEY not configured")
        
        payload = {
            'action': 'create',
            'tokenMetadata': token_metadata,
            'mint': str(mint_keypair),
            'denominatedInSol': 'true',
            'amount': coin_data.get('buy_amount', 1),
            'slippage': 10,
            'priorityFee': 0.0005 if platform == "pump" else 0.00005,
            'pool': platform
        }
        
        if platform == "moonshot":
            payload['amount'] = coin_data.get('buy_amount', 1)  # USDC
        
        trade_url = f"https://pumpportal.fun/api/trade?api-key={api_key}"
        response = requests.post(
            trade_url,
            headers={'Content-Type': 'application/json'},
            data=json.dumps(payload),
            timeout=120
        )
        
        if response.status_code != 200:
            raise Exception(f"Deployment failed: {response.status_code} - {response.text}")
        
        result = response.json()
        tx_signature = result.get('signature')
        
        if not tx_signature:
            raise Exception(f"No transaction signature: {result}")
        
        # Success
        return {
            'status': 'success',
            'signature': tx_signature,
            'mint': contract_address,
            'platform': platform,
            'metadata': token_metadata
        }
        
    except Exception as e:
        logger.error(f"Async LOCK token creation failed: {e}")
        return {
            'status': 'error',
            'message': str(e)
        }

# ----- UTILITY FUNCTIONS -----

def test_lock_generation_speed():
    """
    Test hardware performance for LOCK generation
    
    Returns:
        dict: Performance statistics
    """
    start_time = time.time()
    test_attempts = 10000
    
    logger.info("Testing hardware performance...")
    
    for _ in range(test_attempts):
        SoldersKeypair()
    
    elapsed = time.time() - start_time
    rate = test_attempts / elapsed
    
    # Expected attempts for LOCK = 58^4 / 2 ≈ 5.7M
    expected_attempts = 5658248
    estimated_seconds = expected_attempts / rate
    estimated_minutes = estimated_seconds / 60
    
    logger.info(f"Hardware test completed:")
    logger.info(f"Generation rate: {rate:,.0f} keypairs/second")
    logger.info(f"Estimated LOCK time: {estimated_minutes:.1f} minutes")
    
    return {
        "rate": rate,
        "estimated_minutes": estimated_minutes,
        "expected_attempts": expected_attempts
    }

def validate_coin_data(coin_data):
    """
    Validate coin data before token creation
    
    Args:
        coin_data (dict): Coin information to validate
        
    Returns:
        dict: Validation result
    """
    required_fields = ['name', 'ticker', 'description', 'image', 'platform']
    missing_fields = []
    
    for field in required_fields:
        if not coin_data.get(field):
            missing_fields.append(field)
    
    if missing_fields:
        return {
            'valid': False,
            'message': f"Missing required fields: {', '.join(missing_fields)}"
        }
    
    # Validate image file exists
    image_path = coin_data.get('image')
    if not os.path.exists(image_path):
        return {
            'valid': False,
            'message': f"Image file not found: {image_path}"
        }
    
    # Validate platform
    supported_platforms = ['pump', 'bonk', 'moonshot']
    if coin_data.get('platform') not in supported_platforms:
        return {
            'valid': False,
            'message': f"Unsupported platform. Use: {', '.join(supported_platforms)}"
        }
    
    return {'valid': True, 'message': 'Valid'}

# ----- MAIN CREATION FUNCTIONS -----

def create_lock_token_sync(coin_data, user_wallet):
    """
    Synchronous LOCK token creation (no Telegram updates)
    
    Args:
        coin_data (dict): Token information
        user_wallet (dict): User wallet for payment
        
    Returns:
        dict: Creation result
    """
    # Validate input
    validation = validate_coin_data(coin_data)
    if not validation['valid']:
        return {'status': 'error', 'message': validation['message']}
    
    logger.info(f"Creating LOCK token: {coin_data.get('name')}")
    
    # Generate LOCK contract
    mint_keypair = generate_lock_contract()
    
    # Create token
    return create_lock_token(coin_data, user_wallet, mint_keypair)

# ----- EXPORT FUNCTIONS FOR BOT -----

__all__ = [
    'create_lock_token_async',
    'create_lock_token_sync', 
    'generate_lock_contract',
    'test_lock_generation_speed',
    'validate_coin_data'
]