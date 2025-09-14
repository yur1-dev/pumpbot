# config.py - All your constants and configuration in main folder
import os
from dotenv import load_dotenv

load_dotenv()

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

# VANITY ADDRESS CONFIGURATION - LOCK SUFFIX (FIXED)
CONTRACT_SUFFIX = "lock"   # Contract addresses will end with "lock"
VANITY_GENERATION_TIMEOUT = 2400   # FIXED: 40 minutes timeout for lock generation (was 180)
FALLBACK_SUFFIX = "lck"    # FIXED: Fallback to shorter suffix if lock fails

# RAYDIUM LAUNCHLAB CONFIGURATION
RAYDIUM_LAUNCHLAB_PROGRAM = "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"
LETSBONK_METADATA_SERVICE = "https://gateway.pinata.cloud/ipfs/"

# GLOBAL FLAG FOR NODE.JS AVAILABILITY
NODEJS_AVAILABLE = True
NODEJS_SETUP_MESSAGE = "Node.js dependencies installed and ready for LOCK token creation"

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

# LAUNCH STEPS
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

# Global data storage
user_wallets = {}         # { user_id: { public, private, mnemonic, balance, bundle, ... } }
user_subscriptions = {}   # { user_id: { active, plan, amount, expires_at, tx_signature } }
user_coins = {}           # { user_id: [ coin_data, ... ] }
vanity_generation_status = {}  # { user_id: { generating: bool, attempts: int, found: keypair or None } }

# SPEED CACHE - Store generated LOCK addresses for instant reuse
lock_address_cache = {}   # { "LOCK": [keypair1, keypair2, ...], "LCK": [...] }
metadata_cache = {}       # { image_hash: metadata_uri } - avoid re-uploading same images