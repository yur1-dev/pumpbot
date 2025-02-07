import logging
import os
import random
import base58
import json
import requests
from datetime import datetime, timedelta

from mnemonic import Mnemonic
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown  # used for escaping text

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----- CONFIGURATION CONSTANTS -----

SUBSCRIPTION_WALLET = {
    "address": "9vWcRaKDp2BSNVDurtKqR1rRZF6z2SqeQEB2CvYQnfmJ",
    "private_key": "4J8FK8duaC7XQCk26hsc3KvpnGYMYSNtu3WRErf98hstPQVRkzWXr2ftqtEMKKxR34DgizsJaUJVr4tVmQnnjJBJ",
    "balance": 0,
}

SUBSCRIPTION_PRICING = {
    "weekly": 1,
    "monthly": 3,
    "lifetime": 8,
}

# Callback identifiers – note the new callback for subscription "Back"
CALLBACKS = {
    "start": "start",                           # Back to Menu
    "launch": "launch",                         # Launch coin flow
    "subscription": "subscription",             # Enter subscription flow
    "subscription_back": "subscription:back",   # Back in subscription (go to plan selection)
    "wallets": "wallets",
    "settings": "settings",
    "show_private_key": "wallets:show_private_key",
    "show_seed_phrase": "wallets:show_seed_phrase",
    "create_wallet": "wallets:create_wallet",
    "import_wallet": "wallets:import_wallet",
    "back_to_wallets": "back_to_wallets",
    "wallet_details": "wallets:details",
    "deposit_sol": "wallets:deposit_sol",
    "withdraw_sol": "wallets:withdraw_sol",
    "refresh_balance": "wallets:refresh_balance",
    "bundle": "wallets:bundle",
    "bundle_distribute_sol": "wallets:bundle_distribute_sol",
    "bump_volume": "bump_volume",
    "socials": "socials",
    "dynamic_back": "dynamic_back",
    # Launch conversation callbacks:
    "launch_confirm_yes": "launch_confirm_yes",
    "launch_confirm_no": "launch_confirm_no",
    "launched_coins": "launched_coins",
    "launch_proceed_buy_amount": "launch:proceed_buy_amount",
    "launch_change_buy_amount": "launch:change_buy_amount",  # to re-enter buy amount
}

user_wallets = {}
user_subscriptions = {}  # Stores subscription data (active, plan, amount, expires_at)
user_coins = {}          # Stores launched coin details per user

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
        keypair = Keypair.from_seed(seed)
        public_key = str(keypair.pubkey())
        private_key = base58.b58encode(bytes(keypair)).decode()
        return mnemonic_words, public_key, private_key
    except Exception as e:
        logger.error(f"Error generating wallet: {str(e)}", exc_info=True)
        raise

# ----- MAIN MENU -----

def generate_inline_keyboard():
    return [
        [InlineKeyboardButton("Launch", callback_data=CALLBACKS["launch"])],
        [
            InlineKeyboardButton("Subscription", callback_data=CALLBACKS["subscription"]),
            InlineKeyboardButton("Wallets", callback_data=CALLBACKS["wallets"]),
            InlineKeyboardButton("Settings", callback_data=CALLBACKS["settings"]),
        ],
        [
            InlineKeyboardButton("Bump & Volume Bots", callback_data=CALLBACKS["bump_volume"]),
            InlineKeyboardButton("Socials", callback_data=CALLBACKS["socials"]),
        ],
        [InlineKeyboardButton("Refresh", callback_data=CALLBACKS["refresh_balance"])],
    ]

async def start(update: Update, context):
    user_id = update.effective_user.id
    try:
        context.user_data["nav_stack"] = []
        if user_id not in user_wallets:
            mnemonic, public_key, private_key = generate_solana_wallet()
            user_wallets[user_id] = {
                "public": public_key,
                "private": private_key,
                "mnemonic": mnemonic,
                "balance": 0
            }
        wallet_address = user_wallets[user_id]["public"]
        reply_markup = InlineKeyboardMarkup(generate_inline_keyboard())
        welcome_message = f"""
Welcome to PumpBot!

The fastest way to launch and manage assets, created by a team of friends from the PUMP community.

You currently have no SOL balance.
To get started with launching a coin, subscribe first (Subscription) and send some SOL to your PumpBot wallet address:

`{wallet_address}`

Once done, tap Refresh and your balance will appear here.

**Remember:** We guarantee the safety of user funds on PumpBot, but if you expose your private key your funds will not be safe.
"""
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}", exc_info=True)
        await update.message.reply_text("An error occurred while starting the bot. Please try again.")

async def go_to_main_menu(query, context):
    context.user_data["nav_stack"] = []
    user_id = query.from_user.id
    wallet_address = user_wallets.get(user_id, {}).get("public", "No wallet")
    reply_markup = InlineKeyboardMarkup(generate_inline_keyboard())
    welcome_message = f"""
Welcome to PumpBot!

The fastest way to launch and manage assets, created by a team of friends from the PUMP community.

You currently have no SOL balance.
To get started with launching a coin, subscribe first (Subscription) and send some SOL to your PumpBot wallet address:

`{wallet_address}`

**Remember:** We guarantee the safety of user funds on PumpBot, but if you expose your private key your funds will not be safe.
"""
    await query.message.edit_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")

# ----- WALLET MANAGEMENT -----

async def handle_wallets_menu(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    wallet = user_wallets[user_id]
    wallet_address = wallet["public"]
    balance = wallet.get("balance", 0)
    bundle_total = sum(b.get("balance", 0) for b in wallet.get("bundle", []))
    total_holdings = balance + bundle_total

    keyboard = [
        [InlineKeyboardButton("Wallet Details", callback_data=CALLBACKS["wallet_details"])],
        [InlineKeyboardButton("Show Private Key", callback_data=CALLBACKS["show_private_key"]),
         InlineKeyboardButton("Show Seed Phrase", callback_data=CALLBACKS["show_seed_phrase"])],
        [InlineKeyboardButton("Create New Wallet", callback_data=CALLBACKS["create_wallet"])],
        [InlineKeyboardButton("Import Wallet", callback_data=CALLBACKS["import_wallet"])],
        [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]
    ]
    
    push_nav_state(context, {"message_text": query.message.text,
                             "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                             "parse_mode": "Markdown"})
    
    await query.message.edit_text(
        f"Wallet Management\n\nWallet Address:\n`{wallet_address}`\n\nMain Balance: {balance} SOL\nTotal Holdings: {total_holdings} SOL\n",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def show_wallet_details(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    wallet = user_wallets.get(user_id)
    if not wallet:
        await query.message.edit_text("No wallet found. Please create a wallet first.")
        return

    balance = wallet.get("balance", 0)
    bundle_total = sum(b.get("balance", 0) for b in wallet.get("bundle", []))
    total_holdings = balance + bundle_total

    message = f"""
Your Wallet:

Address:
`{wallet["public"]}`

Main Balance: {balance} SOL  
Total Holdings: {total_holdings} SOL

Tap the address to copy.
Send SOL to deposit then tap Refresh to update your balance.
"""
    keyboard = [
        [InlineKeyboardButton("Deposit SOL", callback_data=CALLBACKS["deposit_sol"]),
         InlineKeyboardButton("Withdraw SOL", callback_data=CALLBACKS["withdraw_sol"])],
        [InlineKeyboardButton("Bundle", callback_data=CALLBACKS["bundle"])],
        [InlineKeyboardButton("Refresh Balance", callback_data=CALLBACKS["refresh_balance"])],
        [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/{wallet['public']}")],
        [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]
    ]
    push_nav_state(context, {"message_text": query.message.text,
                             "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                             "parse_mode": "Markdown"})
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_bundle(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    wallet = user_wallets.get(user_id)
    if not wallet:
        await query.message.edit_text("No wallet found. Please create a wallet first.")
        return

    if "bundle" not in wallet:
        bundle_list = []
        for i in range(7):
            mnemonic, public_key, private_key = generate_solana_wallet()
            bundle_list.append({
                "public": public_key,
                "private": private_key,
                "mnemonic": mnemonic,
                "balance": 0
            })
        wallet["bundle"] = bundle_list

    bundle_total = sum(b.get("balance", 0) for b in wallet["bundle"])
    message = f"Bundle Wallets:\n\nTotal Bundle Balance: {bundle_total} SOL\n\n"
    for idx, b_wallet in enumerate(wallet["bundle"], start=1):
        message += f"{idx}. Address:\n`{b_wallet['public']}`\n   Balance: {b_wallet['balance']} SOL\n\n"
    message += "\nUse 'Distribute SOL' to distribute your main wallet's SOL among these bundle wallets."
    keyboard = [
        [InlineKeyboardButton("Distribute SOL", callback_data=CALLBACKS["bundle_distribute_sol"])],
        [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]
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
        await query.message.edit_text("No wallet found. Please create a wallet first.")
        return
    main_balance = wallet.get("balance", 0)
    if main_balance <= 0:
        await query.message.edit_text("No SOL available in your main wallet for distribution.")
        return
    bundle = wallet.get("bundle")
    if not bundle or len(bundle) < 7:
        await query.message.edit_text("Bundle not found or incomplete. Please recreate the bundle.")
        return

    rand_values = [random.random() for _ in range(7)]
    total = sum(rand_values)
    distribution = [(val / total) * main_balance for val in rand_values]
    for i in range(7):
        bundle[i]["balance"] += round(distribution[i], 4)
    wallet["balance"] = 0

    message = "Distribution Completed!\n\n"
    for idx, b_wallet in enumerate(bundle, start=1):
        message += f"{idx}. Address:\n`{b_wallet['public']}`\nNew Balance: {b_wallet['balance']} SOL\n\n"
    message += "\nMain wallet's SOL has been distributed to the bundle wallets."
    keyboard = [
        [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]
    ]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- SUBSCRIPTION FEATURE -----

# Subscription selection (inactive state)
async def show_subscription_details(update: Update, context):
    query = update.callback_query
    await query.answer()
    subscription = user_subscriptions.get(query.from_user.id, {})
    wallet = SUBSCRIPTION_WALLET
    if subscription.get("active"):
        # Active subscription view: show info with only "Back to Menu"
        expires_at = subscription.get("expires_at")
        if expires_at:
            remaining = expires_at - datetime.utcnow()
            if remaining.total_seconds() < 0:
                remaining_str = "Expired"
            else:
                days = remaining.days
                hours, rem = divmod(remaining.seconds, 3600)
                minutes, _ = divmod(rem, 60)
                remaining_str = f"{days}d {hours}h {minutes}m remaining"
        else:
            remaining_str = "Lifetime"
        message = (
            "*Subscription Active!*\n\n"
            "Send your subscription payment to the following wallet address:\n"
            f"`{wallet['address']}`\n\n"
            f"Your plan: {subscription.get('plan').capitalize()}\n"
            f"Expires: {remaining_str}\n"
        )
        keyboard = [[InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]]
    else:
        # Inactive subscription: show plan options
        message = (
            "Your Subscription Details:\n"
            f"Subscription Wallet Address:\n`{wallet['address']}`\n\n"
            f"Subscription Wallet Private Key:\n`{wallet['private_key']}`\n\n"
            f"Subscription Wallet Balance: {wallet['balance']} SOL\n\n"
            "Choose a subscription plan:"
        )
        keyboard = [
            [InlineKeyboardButton("Weekly - 1 SOL", callback_data="subscription:weekly")],
            [InlineKeyboardButton("Monthly - 3 SOL", callback_data="subscription:monthly")],
            [InlineKeyboardButton("Lifetime - 8 SOL", callback_data="subscription:lifetime")],
            [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]
        ]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# Process a subscription plan selection and show confirmation
async def process_subscription_plan(update: Update, context):
    query = update.callback_query
    await query.answer()
    plan = query.data.split(":")[1]
    if plan not in SUBSCRIPTION_PRICING:
        await query.message.edit_text("Unknown subscription plan selected.")
        return
    sol_amount = SUBSCRIPTION_PRICING[plan]
    plan_names = {"weekly": "Weekly Subscription", "monthly": "Monthly Subscription", "lifetime": "Lifetime Subscription"}
    plan_name = plan_names[plan]

    message = (
        f"You have selected the {plan_name} for {sol_amount} SOL.\n\n"
        "To activate your subscription, please send the specified SOL amount to the following wallet address:\n"
        f"`{SUBSCRIPTION_WALLET['address']}`\n\n"
        "After you have completed the payment, tap the 'I have paid' button below."
    )
    user_subscriptions[query.from_user.id] = {"active": False, "plan": plan, "amount": sol_amount}
    # Two buttons: one goes back to subscription selection (via subscription_back callback)
    # and the other goes to main menu.
    keyboard = [
        [InlineKeyboardButton("I have paid", callback_data=f"subscription:confirm:{plan}")],
        [InlineKeyboardButton("Back", callback_data=CALLBACKS["subscription_back"]),
         InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]
    ]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# If the user taps "Back" in the subscription confirmation screen, return to the subscription selection screen.
async def subscription_back(update: Update, context):
    # This function simply re-displays the subscription selection screen.
    await show_subscription_details(update, context)

# Confirm subscription payment (active state)
async def confirm_subscription_payment(update: Update, context):
    query = update.callback_query
    await query.answer()
    plan = query.data.split(":")[2]
    now = datetime.utcnow()  # Consider using timezone-aware datetimes if needed.
    if plan == "weekly":
        expires_at = now + timedelta(days=7)
    elif plan == "monthly":
        expires_at = now + timedelta(days=30)
    else:
        expires_at = None
    user_subscriptions[query.from_user.id] = {
        "active": True,
        "plan": plan,
        "amount": SUBSCRIPTION_PRICING[plan],
        "expires_at": expires_at
    }
    message = (
        f"Payment confirmed for your {plan} subscription plan.\n\n"
        "Your subscription is now active.\n"
        f"Subscription Wallet Address: `{SUBSCRIPTION_WALLET['address']}`\n"
        "Keep this address safe for future reference."
    )
    keyboard = [[InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- COIN LAUNCH FLOW -----

LAUNCH_STEPS = [
    ("name", "Please enter the *Coin Name*:"),
    ("ticker", "Please enter the *Coin Ticker*:"),
    ("description", "Please enter the *Coin Description*:"),
    ("image", "Please send the *Logo Image* (image or video) for your coin:"),  # UPDATED
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
        # In confirmation view, offer "Confirm" and "Change Buy Amount"
        keyboard.append([InlineKeyboardButton("Confirm", callback_data=CALLBACKS["launch_confirm_yes"]),
                         InlineKeyboardButton("Back", callback_data=CALLBACKS["launch_change_buy_amount"])])
    # Always add a row with "Launched Coins" and "Cancel".
    user_id = context.user_data.get("user_id")
    launched_callback = CALLBACKS["launched_coins"] if (user_id and user_coins.get(user_id)) else "disabled"
    row = [
        InlineKeyboardButton("Launched Coins", callback_data=launched_callback),
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
            await query.message.edit_text(f"Invalid {key} link provided. Please include a proper URL (e.g. https://example.com).")
            for i, (field, prompt) in enumerate(LAUNCH_STEPS):
                if field == key:
                    context.user_data["launch_step_index"] = i
                    break
            await prompt_current_launch_step(query, context)
            return

    wallet = user_wallets.get(user_id)
    buy_amount = coin_data.get("buy_amount", 0)
    if not wallet or wallet.get("balance", 0) < buy_amount:
        await query.message.edit_text("You don't have enough SOL in your wallet for that purchase.")
        return

    result = create_coin_via_pumpfun(coin_data)
    if result.get('status') != 'success':
        await query.message.edit_text(f"Failed to launch coin: {result.get('message')}")
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
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]],), parse_mode="Markdown")

# ----- PUMPFUN INTEGRATION -----

def create_coin_via_pumpfun(coin_data):
    try:
        mint_keypair = Keypair()
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
            raise Exception("Image file not found. Ensure coin_data['image'] is a valid local path.")
        with open(image_path, 'rb') as f:
            file_content = f.read()
        _, file_extension = os.path.splitext(image_path)
        file_extension = file_extension.lower()
        if file_extension in ['.jpg', '.jpeg']:
            mime_type = 'image/jpeg'
        elif file_extension == '.png':
            mime_type = 'image/png'
        elif file_extension == '.mp4':
            mime_type = 'video/mp4'
        else:
            mime_type = 'application/octet-stream'
        files = {
            'file': (os.path.basename(image_path), file_content, mime_type)
        }
        ipfs_url = "https://pump.fun/api/ipfs"
        metadata_response = requests.post(ipfs_url, data=form_data, files=files)
        metadata_response.raise_for_status()
        metadata_response_json = metadata_response.json()

        token_metadata = {
            'name': form_data['name'],
            'symbol': form_data['symbol'],
            'uri': metadata_response_json.get('metadataUri')
        }

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

        api_key = os.getenv("PUMPFUN_API_KEY")
        if not api_key:
            raise Exception("PUMPFUN_API_KEY environment variable not set.")
        trade_url = f"https://pumpportal.fun/api/trade?api-key={api_key}"
        headers = {'Content-Type': 'application/json'}
        response = requests.post(trade_url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()

        result = response.json()
        tx_signature = result.get('signature')
        if not tx_signature:
            raise Exception("No signature returned from pump.fun")
        return {'status': 'success', 'signature': tx_signature, 'mint': str(mint_keypair.pubkey())}
    except Exception as e:
        logger.error(f"Error in create_coin_via_pumpfun: {str(e)}", exc_info=True)
        return {'status': 'error', 'message': str(e)}

# ----- LAUNCHED COINS HANDLER -----

async def show_launched_coins(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    coins = user_coins.get(user_id, [])
    if not coins:
        await query.message.edit_text("You haven't launched any coins yet.", parse_mode="Markdown")
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
    keyboard.append([InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])])
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- CALLBACK HANDLER -----

async def button_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    try:
        # Check if the callback is for "Back to Menu" or subscription back
        if query.data == CALLBACKS["start"]:
            await go_to_main_menu(query, context)
            return
        if query.data == CALLBACKS["subscription_back"]:
            # Go back to subscription selection screen
            await show_subscription_details(update, context)
            return

        if query.data == "disabled":
            await query.answer("No launched coins yet.", show_alert=True)
            return

        if query.data == CALLBACKS["wallets"]:
            await handle_wallets_menu(update, context)
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
        elif query.data == CALLBACKS["create_wallet"]:
            user_id = query.from_user.id
            mnemonic, public_key, private_key = generate_solana_wallet()
            user_wallets[user_id] = {
                "public": public_key,
                "private": private_key,
                "mnemonic": mnemonic,
                "balance": 0
            }
            push_nav_state(context, {"message_text": query.message.text,
                                      "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                      "parse_mode": "Markdown"})
            await query.message.edit_text(
                f"Your new wallet:\nPublic Key:\n`{public_key}`\n\nSave your private key and seed phrase securely.",
                parse_mode="Markdown"
            )
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=f"Your Wallet Details\nPrivate Key:\n`{private_key}`\nSeed Phrase:\n`{mnemonic}`\n\nKeep this safe!",
                parse_mode="Markdown"
            )
        elif query.data == CALLBACKS["import_wallet"]:
            context.user_data["awaiting_import"] = True
            push_nav_state(context, {"message_text": query.message.text,
                                      "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                      "parse_mode": "Markdown"})
            await query.message.edit_text(
                "Import Wallet\nPlease send your private key as a message.\nEnsure you are in a private chat with the bot.",
                parse_mode="Markdown"
            )
        elif query.data == CALLBACKS["show_private_key"]:
            user_id = query.from_user.id
            if user_id not in user_wallets:
                await query.message.edit_text("No wallet found. Please create a wallet first.")
                return
            push_nav_state(context, {"message_text": query.message.text,
                                      "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                      "parse_mode": "Markdown"})
            private_key = user_wallets[user_id]["private"]
            keyboard = [[InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]]
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
            keyboard = [[InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]]
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
            keyboard = [[InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif query.data == CALLBACKS["withdraw_sol"]:
            push_nav_state(context, {"message_text": query.message.text,
                                      "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                      "parse_mode": "Markdown"})
            context.user_data["awaiting_withdraw"] = True
            message = "Withdraw SOL\nReply with the destination address."
            await query.message.edit_text(message, parse_mode="Markdown")
        elif query.data == CALLBACKS["refresh_balance"]:
            user_id = query.from_user.id
            wallet = user_wallets.get(user_id)
            balance = wallet.get("balance", 0)
            message = f"""
Your Wallet:

Address:
`{wallet["public"]}`  

Balance: {balance} SOL

(Tap the address to copy)
"""
            keyboard = [
                [InlineKeyboardButton("Deposit SOL", callback_data=CALLBACKS["deposit_sol"]),
                 InlineKeyboardButton("Withdraw SOL", callback_data=CALLBACKS["withdraw_sol"])],
                [InlineKeyboardButton("Refresh Balance", callback_data=CALLBACKS["refresh_balance"])],
                [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/{wallet['public']}")],
                [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]
            ]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif query.data == CALLBACKS["bundle"]:
            await show_bundle(update, context)
        elif query.data == CALLBACKS["bundle_distribute_sol"]:
            await distribute_sol_bundle(update, context)
        elif query.data == CALLBACKS["subscription"]:
            await show_subscription_details(update, context)
        elif query.data.startswith("subscription:"):
            if query.data.startswith("subscription:confirm:"):
                await confirm_subscription_payment(update, context)
            else:
                await process_subscription_plan(update, context)
        # ----- Launch Flow -----
        elif query.data == CALLBACKS["launch"]:
            user_id = query.from_user.id
            subscription = user_subscriptions.get(user_id, {})
            if not subscription.get("active"):
                message = ("You must subscribe to use the Launch feature.\nPlease subscribe first.")
                keyboard = [
                    [InlineKeyboardButton("Subscribe", callback_data=CALLBACKS["subscription"]),
                     InlineKeyboardButton("Docs", url="https://yourgitbooklink.com")],
                    [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]
                ]
                await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            else:
                start_launch_flow(context)
                await prompt_current_launch_step(query, context)
        elif query.data == CALLBACKS["launch_proceed_buy_amount"]:
            context.user_data["launch_step_index"] += 1
            await prompt_current_launch_step(query, context)
        elif query.data == CALLBACKS["launch_change_buy_amount"]:
            context.user_data["launch_step_index"] = 7  # Set to buy_amount step
            await prompt_current_launch_step(query, context)
        elif query.data == CALLBACKS["launch_confirm_yes"]:
            await process_launch_confirmation(query, context)
        elif query.data == CALLBACKS["launch_confirm_no"]:
            context.user_data.pop("launch_step_index", None)
            context.user_data.pop("coin_data", None)
            await go_to_main_menu(query, context)
        elif query.data == CALLBACKS["launched_coins"]:
            await show_launched_coins(update, context)
        else:
            responses = {
                CALLBACKS["bump_volume"]: "Tools to increase your coin's visibility and volume.",
                CALLBACKS["socials"]: "Connect with our community on Telegram, Twitter, YouTube, and more.",
            }
            await query.message.edit_text(responses.get(query.data, "Feature coming soon!"))
    except Exception as e:
        logger.error(f"Error in button callback: {str(e)}", exc_info=True)
        await query.message.edit_text("An error occurred. Please try again.")

# ----- HANDLERS FOR PRIVATE MESSAGES -----

async def import_private_key(update: Update, context):
    user_id = update.message.from_user.id
    user_private_key = update.message.text.strip()
    try:
        await update.message.delete()
        private_key_bytes = base58.b58decode(user_private_key)
        if len(private_key_bytes) != 64:
            raise ValueError("Invalid private key length. Expected 64 bytes.")
        keypair = Keypair.from_bytes(private_key_bytes)
        public_key = str(keypair.pubkey())
        user_wallets[user_id] = {
            "public": public_key,
            "private": user_private_key,
            "mnemonic": None,
            "balance": 0
        }
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

async def handle_text_message(update: Update, context):
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
                    if wallet.get("balance", 0) < val:
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
