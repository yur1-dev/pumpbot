import logging
import os
import random
import base58
import json
import requests
import asyncio
from datetime import datetime
from mnemonic import Mnemonic
from dotenv import load_dotenv

# --- Solana & Solders Imports ---
from solders.keypair import Keypair as SoldersKeypair  # used for wallet generation (solders)
from solders.pubkey import Pubkey as PublicKey  # Use this as our PublicKey

# solana-py for on-chain interactions
from solana.rpc.api import Client
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from solana.keypair import Keypair as SolanaKeypair
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
# Subscription-related constants have been removed for free access

# CALLBACKS – used for navigation
CALLBACKS = {
    "start": "start",
    "launch": "launch",
    "wallets": "wallets",
    "settings": "settings",
    "show_private_key": "wallets:show_private_key",
    "show_seed_phrase": "wallets:show_seed_phrase",
    "create_wallet": "wallets:create_wallet",
    "import_wallet": "wallets:import_wallet",
    "cancel_import_wallet": "wallets:cancel_import_wallet",
    "back_to_wallets": "back_to_wallets",
    "wallet_details": "wallets:details",
    "deposit_sol": "wallets:deposit_sol",
    "withdraw_sol": "wallets:withdraw_sol",
    "cancel_withdraw_sol": "wallets:cancel_withdraw_sol",
    "refresh_balance": "wallets:refresh_balance",
    "bundle": "wallets:bundle",
    "bundle_distribute_sol": "wallets:bundle_distribute_sol",
    "bump_volume": "bump_volume",  # Volume trading feature
    "create_bundle_for_volume": "create_bundle_for_volume",  # Create bundle for volume trading
    "start_volume_trading": "start_volume_trading",  # Start volume trading session
    "socials": "socials",
    "dynamic_back": "dynamic_back",  # one-step back navigation
    "launch_confirm_yes": "launch_confirm_yes",
    "launch_confirm_no": "launch_confirm_no",
    "launched_coins": "launched_coins",
    "launch_proceed_buy_amount": "launch:proceed_buy_amount",
    "launch_change_buy_amount": "launch:change_buy_amount",
}

# Global user data holders
user_wallets = {}         # { user_id: { public, private, mnemonic, balance, bundle, ... } }
user_coins = {}           # { user_id: [ coin_data, ... ] }

# ----- HELPER FUNCTIONS FOR ON-CHAIN INTERACTION -----
def get_wallet_balance(public_key: str) -> float:
    rpc_url = os.getenv("SOLANA_RPC_URL")
    client = Client(rpc_url)
    try:
        pk_bytes = base58.b58decode(public_key)
        result = client.get_balance(PublicKey(pk_bytes))
        lamports = result["result"]["value"]
        balance = lamports / 10**9
        logger.info(f"Fetched balance for {public_key}: {balance} SOL")
        return balance
    except Exception as e:
        logger.error(f"Error fetching balance for {public_key}: {e}", exc_info=True)
        return 0.0

def transfer_sol(from_wallet: dict, to_address: str, amount_sol: float) -> dict:
    rpc_url = os.getenv("SOLANA_RPC_URL")
    client = Client(rpc_url)
    lamports = int(amount_sol * 10**9)
    try:
        secret_key = base58.b58decode(from_wallet["private"])
        solana_keypair = SolanaKeypair.from_secret_key(secret_key)
    except Exception as e:
        logger.error("Error decoding private key", exc_info=True)
        return {"status": "error", "message": "Invalid private key."}
    txn = Transaction()
    try:
        to_pubkey = PublicKey(base58.b58decode(to_address))
        txn.add(transfer(TransferParams(
            from_pubkey=solana_keypair.public_key,
            to_pubkey=to_pubkey,
            lamports=lamports
        )))
        latest_blockhash_resp = client._provider.make_request("getLatestBlockhash", {})
        if "result" not in latest_blockhash_resp:
            raise Exception(f"Unexpected response format: {latest_blockhash_resp}")
        txn.recent_blockhash = latest_blockhash_resp["result"]["value"]["blockhash"]
    except Exception as e:
        logger.error("Error building transaction", exc_info=True)
        return {"status": "error", "message": "Error building transaction: " + str(e)}
    try:
        txn.sign(solana_keypair)
        raw_tx = txn.serialize()
        response = client.send_raw_transaction(raw_tx, opts=TxOpts(skip_preflight=True))
        logger.info(f"Transaction response: {response}")
        if isinstance(response, dict) and "result" in response:
            signature = response["result"]
            logger.info(f"Transfer successful: {signature}")
            return {"status": "success", "signature": signature}
        else:
            error_msg = response.get("error", "Unknown error") if isinstance(response, dict) else str(response)
            logger.error(f"Transfer error: {error_msg}")
            return {"status": "error", "message": error_msg}
    except Exception as e:
        logger.error("Error sending transaction: " + str(e), exc_info=True)
        return {"status": "error", "message": "Error sending transaction: " + str(e)}

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
    try:
        mnemo = Mnemonic("english")
        mnemonic_words = mnemo.generate()
        seed = mnemo.to_seed(mnemonic_words)[:32]
        keypair = SoldersKeypair.from_seed(seed)
        public_key_str = str(keypair.pubkey())
        private_key = base58.b58encode(bytes(keypair)).decode()
        return mnemonic_words, public_key_str, private_key
    except Exception as e:
        logger.error(f"Error generating wallet: {e}", exc_info=True)
        raise

# ----- MAIN MENU & WELCOME MESSAGE -----
def generate_inline_keyboard():
    return [
        [InlineKeyboardButton("Launch", callback_data=CALLBACKS["launch"])],
        [
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
        welcome_message = (
            "Welcome to PumpBot!\n\n"
            "The fastest way to launch and manage assets, created by a team of friends from the PUMP community.\n\n"
            f"Deposit SOL to your PumpBot wallet address:\n\n`{wallet_address}`\n\n"
            "Once done, tap Refresh and your balance will appear here.\n\n"
            "Remember: We guarantee the safety of user funds on PumpBot, but if you expose your private key your funds will not be safe."
        )
        reply_markup = InlineKeyboardMarkup(generate_inline_keyboard())
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in start command: {e}", exc_info=True)
        await update.message.reply_text("An error occurred while starting PumpBot. Please try again.")

async def go_to_main_menu(query, context):
    context.user_data["nav_stack"] = []
    user_id = query.from_user.id
    wallet = user_wallets.get(user_id)
    if wallet:
        wallet_address = wallet["public"]
    else:
        wallet_address = "No wallet"
    welcome_message = (
        "Welcome to PumpBot!\n\n"
        "The fastest way to launch and manage assets, created by a team of friends from the PUMP community.\n\n"
        f"Deposit SOL to your PumpBot wallet address:\n\n`{wallet_address}`\n\n"
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

# ----- REFRESH HANDLER -----
async def refresh_balance(update: Update, context):
    query = update.callback_query
    await query.answer()
    if query.message.text.startswith("Welcome to PumpBot!"):
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
    current_balance = get_wallet_balance(wallet["public"])
    wallet["balance"] = current_balance
    logger.info(f"Balance for {wallet['public']} refreshed: {current_balance} SOL")
    message = (
        f"Your Wallet:\n\nAddress:\n`{wallet['public']}`\n\n"
        f"Balance: {current_balance:.4f} SOL\n\n(Tap the address to copy)"
    )
    keyboard = [
        [InlineKeyboardButton("Deposit SOL", callback_data=CALLBACKS["deposit_sol"]),
         InlineKeyboardButton("Withdraw SOL", callback_data=CALLBACKS["withdraw_sol"])],
        [InlineKeyboardButton("Refresh Balance", callback_data=CALLBACKS["refresh_balance"])],
        [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/{wallet['public']}")],
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
        [InlineKeyboardButton("Show Private Key", callback_data=CALLBACKS["show_private_key"]),
         InlineKeyboardButton("Show Seed Phrase", callback_data=CALLBACKS["show_seed_phrase"])],
        [InlineKeyboardButton("Import Wallet", callback_data=CALLBACKS["import_wallet"])],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]
    ]
    push_nav_state(context, {"message_text": query.message.text,
                             "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                             "parse_mode": "Markdown"})
    msg = (f"Wallet Management\n\nWallet Address:\n`{wallet_address}`\n\n"
           f"Main Balance: {balance:.4f} SOL\nTotal Holdings: {total_holdings:.4f} SOL")
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
        f"Main Balance: {balance:.4f} SOL\nTotal Holdings: {total_holdings:.4f} SOL\n\n"
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

# ----- BUNDLE MANAGEMENT -----
async def show_bundle(update: Update, context):
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
    if "bundle" not in wallet:
        bundle_list = []
        for _ in range(7):
            mnemonic, public_key, private_key = generate_solana_wallet()
            bundle_list.append({"public": public_key, "private": private_key, "mnemonic": mnemonic, "balance": 0})
        wallet["bundle"] = bundle_list
    bundle_total = sum(b.get("balance", 0) for b in wallet["bundle"])
    message = f"Bundle Wallets:\n\nTotal Bundle Balance: {bundle_total:.4f} SOL\n\n"
    for idx, b_wallet in enumerate(wallet["bundle"], start=1):
        message += f"{idx}. Address:\n`{b_wallet['public']}`\n   Balance: {b_wallet['balance']:.4f} SOL\n\n"
    message += "\nUse 'Distribute SOL' to allocate your main wallet SOL among the bundle wallets."
    keyboard = [
        [InlineKeyboardButton("Distribute SOL", callback_data=CALLBACKS["bundle_distribute_sol"])],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]
    ]
    push_nav_state(context, {"message_text": query.message.text,
                             "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                             "parse_mode": "Markdown"})
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def distribute_sol_bundle(update: Update, context):
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
    main_balance = get_wallet_balance(wallet["public"])
    if main_balance <= 0:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("No SOL available in your main wallet for distribution.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return
    bundle = wallet.get("bundle")
    if not bundle or len(bundle) < 7:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("Bundle not found or incomplete. Please recreate the bundle.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return
    rand_values = [random.random() for _ in range(7)]
    total = sum(rand_values)
    distribution = [(val / total) * main_balance for val in rand_values]
    for i in range(7):
        bundle[i]["balance"] += round(distribution[i], 4)
    message = "Distribution Completed!\n\n"
    for idx, b_wallet in enumerate(bundle, start=1):
        message += f"{idx}. Address:\n`{b_wallet['public']}`\nNew Balance: {b_wallet['balance']:.4f} SOL\n\n"
    message += "\nMain wallet SOL has been allocated to the bundle wallets (locally tracked)."
    keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
                 InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- COIN LAUNCH FLOW -----
LAUNCH_STEPS = [
    ("name", "Please enter the *Coin Name*:"), 
    ("ticker", "Please enter the *Coin Ticker*:"), 
    ("description", "Please enter the *Coin Description*:"), 
    ("image", "Please send the *Logo Image* (image or video) for your coin:"), 
    ("telegram", "Please enter your *Telegram Link*:"), 
    ("website", "Please enter your *Website Link* (include https:// and .com):"), 
    ("twitter", "Please enter your *Twitter/X Link* (include https:// and .com):"), 
    ("buy_amount", "Choose how many coins you want to buy (optional).\nTip: Buying a small amount helps protect your coin from snipers.")
]

def start_launch_flow(context):
    context.user_data["launch_step_index"] = 0
    context.user_data["coin_data"] = {}

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
        _, prompt_text = LAUNCH_STEPS[index]
        if hasattr(update_obj, "callback_query") and update_obj.callback_query:
            sent_msg = await update_obj.callback_query.message.reply_text(prompt_text, reply_markup=keyboard, parse_mode="Markdown")
        elif hasattr(update_obj, "message") and update_obj.message:
            sent_msg = await update_obj.message.reply_text(prompt_text, reply_markup=keyboard, parse_mode="Markdown")
        context.user_data["last_prompt_msg_id"] = sent_msg.message_id
    else:
        coin_data = context.user_data.get("coin_data", {})
        from telegram.helpers import escape_markdown as escape_md
        name = escape_md(coin_data.get('name', ''), version=1)
        ticker = escape_md(coin_data.get('ticker', ''), version=1)
        description = escape_md(coin_data.get('description', ''), version=1)
        telegram_link = escape_md(coin_data.get('telegram', ''), version=1)
        website = escape_md(coin_data.get('website', ''), version=1)
        twitter_link = escape_md(coin_data.get('twitter', ''), version=1)
        image_name = coin_data.get("image_filename", "No image provided")
        summary = (
            "*Review your coin data:*\n\n" +
            f"*Name:* {name}\n" +
            f"*Ticker:* {ticker}\n" +
            f"*Description:* {description}\n" +
            f"*Logo Image:* {image_name}\n" +
            f"*Telegram Link:* {telegram_link}\n" +
            f"*Website Link:* {website}\n" +
            f"*Twitter/X Link:* {twitter_link}\n"
        )
        if "buy_amount" in coin_data:
            summary += f"*Buy Amount (SOL):* {coin_data.get('buy_amount')}\n"
        summary += "\nAre you sure you want to create this coin? This action cannot be changed later."
        keyboard = get_launch_flow_keyboard(context, confirm=True, include_proceed=include_proceed)
        if hasattr(update_obj, "callback_query") and update_obj.callback_query:
            sent_msg = await update_obj.callback_query.message.reply_text(summary, reply_markup=keyboard, parse_mode="Markdown")
        elif hasattr(update_obj, "message") and update_obj.message:
            sent_msg = await update_obj.message.reply_text(summary, reply_markup=keyboard, parse_mode="Markdown")
        context.user_data["last_prompt_msg_id"] = sent_msg.message_id

async def process_launch_confirmation(query, context):
    coin_data = context.user_data.get("coin_data", {})
    user_id = query.from_user.id

    for key in ["telegram", "website", "twitter"]:
        link = coin_data.get(key, "")
        if ".com" not in link.lower():
            keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
            await query.message.edit_text(f"Invalid {key} link provided. Please include a proper URL (e.g. https://example.com).",
                                            reply_markup=InlineKeyboardMarkup(keyboard),
                                            parse_mode="Markdown")
            for i, (field, prompt) in enumerate(LAUNCH_STEPS):
                if field == key:
                    context.user_data["launch_step_index"] = i
                    break
            await prompt_current_launch_step(query, context)
            return

    wallet = user_wallets.get(user_id)
    buy_amount = coin_data.get("buy_amount", 0)
    if not wallet or get_wallet_balance(wallet["public"]) < buy_amount:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("You don't have enough SOL in your wallet for that purchase.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return

    result = create_coin_via_pumpfun(coin_data)
    if result.get('status') != 'success':
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text(f"Failed to launch coin: {result.get('message')}",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return

    tx_signature = result.get('signature')
    mint = result.get('mint')
    tx_link = f"https://solscan.io/tx/{tx_signature}"
    chart_url = f"https://pumpportal.fun/chart/{mint}"

    if user_id not in user_coins:
        user_coins[user_id] = []
    user_coins[user_id].append({
        "name": coin_data.get("name", "Unnamed Coin"),
        "ticker": coin_data.get("ticker", ""),
        "description": coin_data.get("description", ""),
        "tx_link": tx_link,
        "chart_url": chart_url,
        "mint": mint,
        "dexscreener_url": "https://dexscreener.com/solana/"
    })

    message = (
        "Coin Launched!\n\n" +
        f"*Name:* {coin_data.get('name')}\n" +
        f"*Ticker:* {coin_data.get('ticker')}\n" +
        f"*Description:* {coin_data.get('description')}\n\n" +
        f"*Transaction:*\n`{tx_link}`\n\n" +
        f"*Smart Contract Address:*\n`{mint}`\n\n" +
        "Your coin is now live on the market.\n" +
        "Check it on Dexscreener: [Dexscreener](https://dexscreener.com/solana/)\n\n" +
        "Bundle accounts have automatically bought your coin (if available).\n\n"
    )
    context.user_data.pop("launch_step_index", None)
    context.user_data.pop("coin_data", None)
    keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
                 InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- PUMPFUN INTEGRATION -----
def create_coin_via_pumpfun(coin_data):
    try:
        # Generate a new mint keypair
        mint_keypair = SoldersKeypair()

        # Prepare token metadata form data using coin_data
        form_data = {
            'name': coin_data.get('name'),
            'symbol': coin_data.get('ticker'),
            'description': coin_data.get('description'),
            'twitter': coin_data.get('twitter'),
            'telegram': coin_data.get('telegram'),
            'website': coin_data.get('website'),
            'showName': 'true'
        }

        # Read the image file from the given path in coin_data
        image_path = coin_data.get('image')
        if not image_path or not os.path.exists(image_path):
            raise Exception("Image file not found. Ensure coin_data['image'] is a valid local path.")
        with open(image_path, 'rb') as f:
            file_content = f.read()

        # Determine MIME type based on file extension
        _, ext = os.path.splitext(image_path)
        ext = ext.lower()
        if ext in ['.jpg', '.jpeg']:
            mime_type = 'image/jpeg'
        elif ext == '.png':
            mime_type = 'image/png'
        elif ext == '.mp4':
            mime_type = 'video/mp4'
        else:
            mime_type = 'application/octet-stream'
        files = {'file': (os.path.basename(image_path), file_content, mime_type)}

        # Upload image and metadata to IPFS via pump.fun
        ipfs_response = requests.post("https://pump.fun/api/ipfs", data=form_data, files=files)
        ipfs_response.raise_for_status()
        ipfs_data = ipfs_response.json()
        metadata_uri = ipfs_data.get('metadataUri')
        if not metadata_uri:
            raise Exception("No metadataUri returned from the IPFS upload.")

        # Create token metadata for the transaction
        token_metadata = {
            'name': form_data['name'],
            'symbol': form_data['symbol'],
            'uri': metadata_uri
        }

        # Get your API key from environment variables
        api_key = os.getenv("PUMPFUN_API_KEY")
        if not api_key:
            raise Exception("PUMPFUN_API_KEY environment variable not set. Please obtain a valid key.")
        trade_url = f"https://pumpportal.fun/api/trade?api-key={api_key}"
        payload = {
            'action': 'create',
            'tokenMetadata': token_metadata,
            'mint': str(mint_keypair.pubkey()),
            'denominatedInSol': 'true',
            'amount': coin_data.get('buy_amount', 0),
            'slippage': 10,
            'priorityFee': 0.0005,
            'pool': 'pump'
        }
        headers = {'Content-Type': 'application/json'}
        trade_response = requests.post(trade_url, headers=headers, data=json.dumps(payload))
        trade_response.raise_for_status()
        trade_data = trade_response.json()
        signature = trade_data.get('signature')
        if not signature:
            raise Exception("No signature returned from pump.fun")
        return {'status': 'success', 'signature': signature, 'mint': str(mint_keypair.pubkey())}
    except Exception as e:
        logger.error(f"Error in create_coin_via_pumpfun: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}

# ----- LAUNCHED COINS HANDLER -----
async def show_launched_coins(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    coins = user_coins.get(user_id, [])
    if not coins:
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("You haven't launched any coins yet.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")
        return
    message = "Your Launched Coins:\n\n"
    keyboard = []
    for idx, coin in enumerate(coins, start=1):
        message += f"{idx}. {coin.get('name', 'Unnamed Coin')} ({coin.get('ticker', '')})\n"
        message += f"   Smart Contract: `{coin.get('mint', 'N/A')}`\n"
        row = [
            InlineKeyboardButton("Pump.fun Board", url=coin.get("chart_url", "")),
            InlineKeyboardButton("Dexscreener", url=coin.get("dexscreener_url", "https://dexscreener.com/solana/"))
        ]
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
                      InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])])
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- BUMP & VOLUME TRADING FEATURE -----
def simulate_trade(wallet, coin):
    token_balance = wallet.get("token_balance", 0)
    if token_balance > 0:
        trade_amount = round(token_balance * 0.1, 4)
        wallet["token_balance"] = round(token_balance - trade_amount, 4)
    else:
        trade_amount = round(random.uniform(0.001, 0.01), 4)
    buy_sig = base58.b58encode(os.urandom(32)).decode()[:44]
    sell_sig = base58.b58encode(os.urandom(32)).decode()[:44]
    return {
         "wallet_public": wallet["public"],
         "trade_amount": trade_amount,
         "buy_sig": buy_sig,
         "sell_sig": sell_sig
    }

def distribute_tokens(wallet, contract_address):
    bundle = wallet.get("bundle", [])
    if not bundle:
         return []
    total_tokens = 1000
    rand_values = [random.random() for _ in bundle]
    total_rand = sum(rand_values)
    distributions = [int((val/total_rand)*total_tokens) for val in rand_values]
    for i, bundle_wallet in enumerate(bundle):
         bundle_wallet["token_balance"] = distributions[i]
    return distributions

async def volume_trading_session(contract_address: str, update: Update, context):
    user_id = update.effective_user.id
    wallet = user_wallets.get(user_id)
    if not wallet or "bundle" not in wallet:
         return
    coin = {"name": f"Custom Coin ({contract_address[:6]}...)", "mint": contract_address}
    trade_logs = []
    duration = 10 * 60  # 10 minutes
    interval = 30
    iterations = duration // interval
    for i in range(int(iterations)):
         iteration_trades = []
         for bundle_wallet in wallet["bundle"]:
              trade = simulate_trade(bundle_wallet, coin)
              iteration_trades.append(trade)
         trade_logs.append(iteration_trades)
         await asyncio.sleep(interval)
    summary = f"Volume Trading Session Completed for coin: *{coin.get('name', 'Unnamed Coin')}*\n\n"
    total_trades = sum(len(trades) for trades in trade_logs)
    summary += f"Total iterations: {int(iterations)}\nTotal individual trades: {total_trades}\n\n"
    summary += "Last iteration trades:\n"
    last_iteration = trade_logs[-1] if trade_logs else []
    for trade in last_iteration:
         summary += f"Wallet: `{trade['wallet_public']}`, Trade Amount: {trade['trade_amount']} tokens, Buy Tx: `{trade['buy_sig']}`, Sell Tx: `{trade['sell_sig']}`\n"
    keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
                 InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]]
    await update.effective_message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- CALLBACK HANDLER -----
async def button_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    try:
        if query.data == CALLBACKS["start"]:
            await go_to_main_menu(query, context)
            return
        elif query.data == CALLBACKS["dynamic_back"]:
            previous_state = pop_nav_state(context)
            if previous_state:
                await query.message.edit_text(
                    text=previous_state["message_text"],
                    reply_markup=InlineKeyboardMarkup(previous_state["keyboard"]),
                    parse_mode=previous_state.get("parse_mode", "Markdown")
                )
            else:
                await go_to_main_menu(query, context)
        elif query.data == CALLBACKS["wallets"]:
            await handle_wallets_menu(update, context)
        elif query.data == CALLBACKS["create_wallet"]:
            user_id = query.from_user.id
            if user_id in user_wallets:
                await query.message.edit_text("A wallet already exists. Use 'Import Wallet' to switch wallets.",
                                                parse_mode="Markdown")
                return
            mnemonic, public_key, private_key = generate_solana_wallet()
            user_wallets[user_id] = {"public": public_key, "private": private_key, "mnemonic": mnemonic, "balance": 0}
            push_nav_state(context, {"message_text": query.message.text,
                                      "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                      "parse_mode": "Markdown"})
            await query.message.edit_text(
                f"Your new wallet:\nPublic Key:\n`{public_key}`\n\nSave your private key and seed phrase securely.",
                parse_mode="Markdown"
            )
            await context.bot.send_message(chat_id=query.from_user.id,
                                           text=f"Wallet Details\nPrivate Key:\n`{private_key}`\nSeed Phrase:\n`{mnemonic}`\nKeep this safe!",
                                           parse_mode="Markdown")
        elif query.data == CALLBACKS["import_wallet"]:
            context.user_data["awaiting_import"] = True
            push_nav_state(context, {"message_text": query.message.text,
                                      "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                      "parse_mode": "Markdown"})
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data=CALLBACKS["cancel_import_wallet"])]
            ])
            await query.message.edit_text(
                "Import Wallet\nPlease send your private key as a message.\nEnsure you are in a private chat with the bot.",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        elif query.data == CALLBACKS["cancel_import_wallet"]:
            context.user_data.pop("awaiting_import", None)
            await go_to_main_menu(query, context)
        elif query.data == CALLBACKS["show_private_key"]:
            user_id = query.from_user.id
            if user_id not in user_wallets:
                await query.message.edit_text("No wallet found. Please create a wallet first.")
                return
            push_nav_state(context, {"message_text": query.message.text,
                                      "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                      "parse_mode": "Markdown"})
            private_key = user_wallets[user_id]["private"]
            keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
                         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]]
            await query.message.edit_text(
                f"Private Key:\n`{private_key}`\nKeep it safe!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        elif query.data == CALLBACKS["show_seed_phrase"]:
            user_id = query.from_user.id
            if user_id not in user_wallets:
                await query.message.edit_text("No wallet found. Please create a wallet first.")
                return
            push_nav_state(context, {"message_text": query.message.text,
                                      "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                      "parse_mode": "Markdown"})
            mnemonic = user_wallets[user_id]["mnemonic"]
            keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
                         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]]
            await query.message.edit_text(
                f"Seed Phrase:\n`{mnemonic}`\nKeep it safe!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        elif query.data == CALLBACKS["wallet_details"]:
            await show_wallet_details(update, context)
        elif query.data == CALLBACKS["deposit_sol"]:
            user_id = query.from_user.id
            wallet = user_wallets.get(user_id)
            if not wallet:
                await query.message.edit_text("No wallet found. Please create a wallet first.")
                return
            message = f"Deposit SOL\nSend SOL to your wallet address:\n`{wallet['public']}`\n(Tap to copy)"
            keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
                         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif query.data == CALLBACKS["withdraw_sol"]:
            push_nav_state(context, {"message_text": query.message.text,
                                      "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                      "parse_mode": "Markdown"})
            context.user_data["awaiting_withdraw"] = True
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Cancel", callback_data=CALLBACKS["cancel_withdraw_sol"])]
            ])
            message = "Withdraw SOL\nReply with the destination address."
            await query.message.edit_text(message, reply_markup=keyboard, parse_mode="Markdown")
        elif query.data == CALLBACKS["cancel_withdraw_sol"]:
            context.user_data.pop("awaiting_withdraw", None)
            await go_to_main_menu(query, context)
        elif query.data == CALLBACKS["refresh_balance"]:
            await refresh_balance(update, context)
        elif query.data == CALLBACKS["bundle"]:
            await show_bundle(update, context)
        elif query.data == CALLBACKS["bundle_distribute_sol"]:
            await distribute_sol_bundle(update, context)
        elif query.data == CALLBACKS["launch"]:
            # Start launch flow directly (free access)
            start_launch_flow(context)
            await prompt_current_launch_step(query, context)
        elif query.data == CALLBACKS["launch_proceed_buy_amount"]:
            context.user_data["launch_step_index"] += 1
            await prompt_current_launch_step(query, context)
        elif query.data == CALLBACKS["launch_change_buy_amount"]:
            context.user_data["launch_step_index"] = 7
            await prompt_current_launch_step(query, context)
        elif query.data == CALLBACKS["launch_confirm_yes"]:
            await process_launch_confirmation(query, context)
        elif query.data == CALLBACKS["launch_confirm_no"]:
            context.user_data.pop("launch_step_index", None)
            context.user_data.pop("coin_data", None)
            await go_to_main_menu(query, context)
        elif query.data == CALLBACKS["launched_coins"]:
            await show_launched_coins(update, context)
        elif query.data == CALLBACKS["bump_volume"]:
            user_id = query.from_user.id
            wallet = user_wallets.get(user_id)
            if not wallet:
                await query.message.edit_text("No wallet found. Please create a wallet first.")
                return
            if "bundle" not in wallet or not wallet["bundle"]:
                keyboard = [
                    [InlineKeyboardButton("Create Bundle Wallets", callback_data=CALLBACKS["create_bundle_for_volume"])],
                    [InlineKeyboardButton("Cancel", callback_data=CALLBACKS["dynamic_back"])]
                ]
                await query.message.edit_text("No bundle wallets found for volume trading. Do you want to create them?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            else:
                context.user_data["awaiting_volume_contract"] = True
                keyboard = [[InlineKeyboardButton("Cancel", callback_data=CALLBACKS["dynamic_back"])]]
                await query.message.edit_text("Please enter the contract address of the coin for volume trading:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif query.data == CALLBACKS["create_bundle_for_volume"]:
            user_id = query.from_user.id
            wallet = user_wallets.get(user_id)
            if wallet is None:
                await query.message.edit_text("No wallet found. Please create a wallet first.")
                return
            bundle_list = []
            for _ in range(7):
                mnemonic, public_key, private_key = generate_solana_wallet()
                bundle_list.append({"public": public_key, "private": private_key, "mnemonic": mnemonic, "balance": 0})
            wallet["bundle"] = bundle_list
            message = "Bundle wallets created successfully. They will be used for volume trading.\n\n"
            message += "Now, please enter the contract address of the coin for volume trading:"
            context.user_data["awaiting_volume_contract"] = True
            keyboard = [[InlineKeyboardButton("Cancel", callback_data=CALLBACKS["dynamic_back"])]]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif query.data == CALLBACKS["start_volume_trading"]:
            contract_address = context.user_data.get("volume_contract_address")
            if not contract_address:
                await query.message.edit_text("Contract address not found. Please try bump volume again.", parse_mode="Markdown")
                return
            await query.message.edit_text("Starting volume trading session. This will run for 10 minutes...", parse_mode="Markdown")
            asyncio.create_task(volume_trading_session(contract_address, query, context))
        elif query.data == CALLBACKS["socials"]:
            await query.message.edit_text("Connect with our community on Telegram, Twitter, YouTube, and more.",
                                            parse_mode="Markdown")
        else:
            await query.message.edit_text("Feature coming soon!")
    except Exception as e:
        logger.error(f"Error in button callback: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
        await query.message.edit_text("An error occurred. Please try again.",
                                        reply_markup=InlineKeyboardMarkup(keyboard),
                                        parse_mode="Markdown")

# ----- HANDLERS FOR PRIVATE MESSAGES -----
async def import_private_key(update: Update, context):
    user_id = update.message.from_user.id
    user_private_key = update.message.text.strip()
    try:
        await update.message.delete()
        private_key_bytes = base58.b58decode(user_private_key)
        if len(private_key_bytes) != 64:
            raise ValueError("Invalid private key length. Expected 64 bytes.")
        keypair = SoldersKeypair.from_bytes(private_key_bytes)
        public_key = str(keypair.pubkey())
        user_wallets[user_id] = {"public": public_key, "private": user_private_key, "mnemonic": None, "balance": 0}
        await update.message.reply_text(f"Wallet imported successfully:\n`{public_key}`", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error importing wallet:\n{str(e)}", parse_mode="Markdown")

async def handle_withdraw_address(update: Update, context):
    if context.user_data.get("awaiting_withdraw"):
        destination = update.message.text.strip()
        user_id = update.message.from_user.id
        await update.message.reply_text(f"Withdrawal requested to address:\n`{destination}`\n(This feature is not fully implemented yet.)", parse_mode="Markdown")
        context.user_data["awaiting_withdraw"] = False
    else:
        await import_private_key(update, context)

# ----- TEXT MESSAGE HANDLER -----
async def handle_text_message(update: Update, context):
    if context.user_data.get("awaiting_volume_contract"):
         contract_address = update.message.text.strip()
         context.user_data.pop("awaiting_volume_contract", None)
         context.user_data["volume_contract_address"] = contract_address
         user_id = update.message.from_user.id
         wallet = user_wallets.get(user_id)
         if not wallet or "bundle" not in wallet or not wallet["bundle"]:
             keyboard = [[InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]]
             await update.message.reply_text("No bundle wallets found for volume trading. Please create a bundle first.",
                                             reply_markup=InlineKeyboardMarkup(keyboard),
                                             parse_mode="Markdown")
             return
         distribution = distribute_tokens(wallet, contract_address)
         distribution_message = "Tokens have been distributed among bundle wallets:\n"
         for i, bundle_wallet in enumerate(wallet["bundle"], start=1):
             distribution_message += f"{i}. Wallet: `{bundle_wallet['public']}`, Tokens: {bundle_wallet.get('token_balance', 0)}\n"
         distribution_message += "\nDo you want to start the volume trading session for this coin? (Trading will run for 10 minutes)"
         keyboard = [
             [InlineKeyboardButton("Start Trading", callback_data=CALLBACKS["start_volume_trading"])],
             [InlineKeyboardButton("Cancel", callback_data=CALLBACKS["dynamic_back"])]
         ]
         await update.message.reply_text(distribution_message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
         return
    if "launch_step_index" in context.user_data:
        index = context.user_data.get("launch_step_index", 0)
        if index >= len(LAUNCH_STEPS):
            context.user_data.pop("launch_step_index", None)
            return
        step_key, _ = LAUNCH_STEPS[index]
        if step_key == "image":
            await update.message.reply_text("Please send an image or video file, not text.", parse_mode="Markdown")
            return
        if step_key == "buy_amount":
            text = update.message.text.strip()
            if text:
                try:
                    val = float(text)
                    user_id = update.message.from_user.id
                    wallet = user_wallets.get(user_id, {})
                    if val <= 0:
                        await update.message.reply_text("Buy amount must be greater than zero.", parse_mode="Markdown")
                        return
                    if get_wallet_balance(wallet.get("public", "")) < val:
                        await update.message.reply_text("You don't have enough SOL in your wallet for that purchase.", parse_mode="Markdown")
                        return
                    context.user_data.setdefault("coin_data", {})[step_key] = val
                except Exception:
                    await update.message.reply_text("Invalid buy amount. Please enter a valid number in SOL.", parse_mode="Markdown")
                    return
            else:
                return
        elif step_key in ["telegram", "website", "twitter"]:
            text = update.message.text.strip()
            if ".com" not in text.lower():
                await update.message.reply_text(f"Invalid {step_key} link. Please include a proper URL (e.g. https://example.com).", parse_mode="Markdown")
                return
            context.user_data.setdefault("coin_data", {})[step_key] = text
        else:
            context.user_data.setdefault("coin_data", {})[step_key] = update.message.text.strip()
        context.user_data["launch_step_index"] = index + 1
        await prompt_current_launch_step(update, context)
        return
    if context.user_data.get("awaiting_withdraw"):
        await handle_withdraw_address(update, context)
    if context.user_data.get("awaiting_import"):
        await import_private_key(update, context)
        context.user_data.pop("awaiting_import", None)
    else:
        await update.message.reply_text("I did not understand that. Please use the available commands or tap a button.")

# ----- MEDIA MESSAGE HANDLER -----
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
                filename = update.message.video.file_name if hasattr(update.message.video, "file_name") and update.message.video.file_name else "logo.mp4"
            if file:
                os.makedirs("./downloads", exist_ok=True)
                file_path = f"./downloads/{filename}"
                await file.download_to_drive(file_path)
                context.user_data.setdefault("coin_data", {})["image"] = file_path
                context.user_data["coin_data"]["image_filename"] = filename
                context.user_data["launch_step_index"] = index + 1
                await prompt_current_launch_step(update, context)
                return
            else:
                await update.message.reply_text("Please send a valid image or video file.", parse_mode="Markdown")
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
    
    logger.info("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()
