import logging
import os
import random
import asyncio
from mnemonic import Mnemonic
from solders.keypair import Keypair
import base58
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
# We'll use solana-py's asynchronous client for transaction checking.
from solana.rpc.async_api import AsyncClient

# Load environment variables from the .env file
load_dotenv()

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----- CONFIGURATION CONSTANTS -----

# Your SOL subscription receiving wallet details (replace with your real details)
SUBSCRIPTION_WALLET = {
    "address": "9vWcRaKDp2BSNVDurtKqR1rRZF6z2SqeQEB2CvYQnfmJ",
    "private_key": "4J8FK8duaC7XQCk26hsc3KvpnGYMYSNtu3WRErf98hstPQVRkzWXr2ftqtEMKKxR34DgizsJaUJVr4tVmQnnjJBJ",
    "balance": 0,  # For display; you might update this dynamically if needed.
}

# Subscription pricing (SOL amounts without emojis)
SUBSCRIPTION_PRICING = {
    "weekly": 0.9,
    "monthly": 3.15,
    "lifetime": 13.5,
}

# Bot main menu and other callback names
CALLBACKS = {
    # Main menu
    "start": "start",
    "launch": "launch",
    "subscription": "subscription",
    "wallets": "wallets",
    "settings": "settings",
    
    # Wallets submenu
    "show_private_key": "wallets:show_private_key",
    "show_seed_phrase": "wallets:show_seed_phrase",
    "create_wallet": "wallets:create_wallet",
    "import_wallet": "wallets:import_wallet",
    "back_to_wallets": "back_to_wallets",
    
    # Wallet details and transactions
    "wallet_details": "wallets:details",
    "deposit_sol": "wallets:deposit_sol",
    "withdraw_sol": "wallets:withdraw_sol",
    "refresh_balance": "wallets:refresh_balance",
    
    # Bundle feature callbacks
    "bundle": "wallets:bundle",
    "bundle_distribute_sol": "wallets:bundle_distribute_sol",
    
    # Other features
    "commenter": "commenter",
    "bump_volume": "bump_volume",
    "socials": "socials",
    # Referral replaced with refresh button in main menu
    "dynamic_back": "dynamic_back",
}

# In-memory storage for user wallets and subscriptions.
user_wallets = {}
user_subscriptions = {}  # Maps Telegram user_id -> subscription details

# Global variable to store the last checked signature for subscription payments.
LAST_CHECKED_SIGNATURE = None

# ----- NAVIGATION HELPERS -----

def push_nav_state(context, state_data):
    """Push a comprehensive navigation state."""
    if "nav_stack" not in context.user_data:
        context.user_data["nav_stack"] = []
    context.user_data["nav_stack"].append(state_data)

def pop_nav_state(context):
    """Pop and return the last navigation state."""
    if context.user_data.get("nav_stack"):
        return context.user_data["nav_stack"].pop()
    return None

# ----- WALLET GENERATION -----

def generate_solana_wallet():
    """Generate a new Solana wallet with mnemonic and keypair."""
    try:
        mnemo = Mnemonic("english")
        mnemonic_words = mnemo.generate()
        seed = mnemo.to_seed(mnemonic_words)[:32]
        keypair = Keypair.from_seed(seed)
        public_key = str(keypair.pubkey())
        private_key = base58.b58encode(bytes(keypair)).decode()
        return mnemonic_words, public_key, private_key
    except Exception as e:
        logger.error(f"Error generating wallet: {str(e)}")
        raise

# ----- MAIN MENU -----

def generate_inline_keyboard():
    """Main menu keyboard."""
    return [
        [InlineKeyboardButton("Launch", callback_data=CALLBACKS["launch"])],
        [
            InlineKeyboardButton("Subscription", callback_data=CALLBACKS["subscription"]),
            InlineKeyboardButton("Wallets", callback_data=CALLBACKS["wallets"]),
            InlineKeyboardButton("Settings", callback_data=CALLBACKS["settings"]),
        ],
        [
            InlineKeyboardButton("Commenter", callback_data=CALLBACKS["commenter"]),
            InlineKeyboardButton("Bump & Volume", callback_data=CALLBACKS["bump_volume"]),
        ],
        [
            InlineKeyboardButton("Socials", callback_data=CALLBACKS["socials"]),
            InlineKeyboardButton("Refresh", callback_data=CALLBACKS["refresh_balance"]),
        ],
    ]

async def start(update: Update, context):
    """Command handler for /start. Resets navigation and shows main menu."""
    user_id = update.effective_user.id
    try:
        context.user_data["nav_stack"] = []
        if user_id not in user_wallets:
            mnemonic, public_key, private_key = generate_solana_wallet()
            # Start with 0 SOL in the main wallet
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

You currently have no SOL balance. To get started with launching coin, subscribe first (Subscription) and send some SOL to your pumpbot wallet address:

{wallet_address} (tap to copy)

Once done, tap refresh and your balance will appear here.

For more info on your account and to retrieve your private key, tap the wallet button below.
Remember: We guarantee the safety of user funds on PumpBot, but if you expose your private key your funds will not be safe.
"""
        await update.message.reply_text(
            welcome_message, reply_markup=reply_markup, parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}")
        await update.message.reply_text("An error occurred while starting the bot. Please try again.")

async def go_to_main_menu(query, context):
    """Helper function to reset navigation and show the main menu."""
    context.user_data["nav_stack"] = []  # clear navigation stack
    user_id = query.from_user.id
    wallet_address = user_wallets.get(user_id, {}).get("public", "No wallet")
    reply_markup = InlineKeyboardMarkup(generate_inline_keyboard())
    welcome_message = f"""
Welcome to PumpBot!
The fastest way to launch and manage assets, created by a team of friends from the PUMP community.

Your wallet address: {wallet_address}

Send SOL to your wallet and tap Refresh to update your balance.
"""
    await query.message.edit_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")

# ----- WALLET MANAGEMENT FUNCTIONS -----

async def handle_wallets_menu(update: Update, context):
    """Display the wallets management menu with total holdings."""
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
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])],
    ]
    
    push_nav_state(context, {
        "message_text": query.message.text,
        "keyboard": query.message.reply_markup.inline_keyboard,
        "parse_mode": "Markdown"
    })
    
    await query.message.edit_text(
        f"Wallet Management\n\nWallet Address: {wallet_address}\nTotal Holdings: {total_holdings} SOL\n\nChoose an option below:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def show_wallet_details(update: Update, context):
    """Show a detailed view of the wallet with deposit/withdraw options and bundle info."""
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

Address: {wallet["public"]} (tap to copy)
Main Balance: {balance} SOL
Total Holdings: {total_holdings} SOL

Tap to copy the address and send SOL to deposit.
Once done, tap refresh and your balance will appear here.
"""
    # Reorder buttons: Main Menu first, then Back.
    keyboard = [
        [InlineKeyboardButton("Deposit SOL", callback_data=CALLBACKS["deposit_sol"]),
         InlineKeyboardButton("Withdraw SOL", callback_data=CALLBACKS["withdraw_sol"])],
        [InlineKeyboardButton("Refresh Balance", callback_data=CALLBACKS["refresh_balance"])],
        [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/{wallet['public']}")],
        [InlineKeyboardButton("Bundle", callback_data=CALLBACKS["bundle"])],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])],
    ]
    push_nav_state(context, {
        "message_text": query.message.text,
        "keyboard": query.message.reply_markup.inline_keyboard,
        "parse_mode": "Markdown"
    })
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_bundle(update: Update, context):
    """Show the bundle view which displays 7 bundled wallets and their balances."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    wallet = user_wallets.get(user_id)
    if not wallet:
        await query.message.edit_text("No wallet found. Please create a wallet first.")
        return

    # Create bundle if not present
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
        message += f"{idx}. Address: {b_wallet['public']}\n   Balance: {b_wallet['balance']} SOL\n\n"
    message += "\nUse 'Distribute SOL' to distribute your main wallet's SOL among these bundle wallets."
    keyboard = [
        [InlineKeyboardButton("Distribute SOL", callback_data=CALLBACKS["bundle_distribute_sol"])],
        [InlineKeyboardButton("Back", callback_data=CALLBACKS["wallet_details"]),
         InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
    ]
    push_nav_state(context, {
        "message_text": query.message.text,
        "keyboard": query.message.reply_markup.inline_keyboard,
        "parse_mode": "Markdown"
    })
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def distribute_sol_bundle(update: Update, context):
    """Randomly distribute the main wallet's SOL among the 7 bundled wallets."""
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
        message += f"{idx}. Address: {b_wallet['public']}, New Balance: {b_wallet['balance']} SOL\n"
    message += "\nMain wallet's SOL has been distributed to the bundle wallets."
    keyboard = [
        [InlineKeyboardButton("Back to Bundle", callback_data=CALLBACKS["bundle"])],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
    ]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- SUBSCRIPTION FEATURE (AUTOMATIC PAYMENT VERIFICATION) -----

async def show_subscription_details(update: Update, context):
    """
    Display the subscription details:
      - Subscription wallet details
      - Current subscription status
      - Pricing for each plan
    """
    query = update.callback_query
    await query.answer()
    wallet = SUBSCRIPTION_WALLET  # fixed subscription wallet details
    subscription_status = user_subscriptions.get(query.from_user.id, {"active": False})
    status_text = "You do not have an active subscription yet." if not subscription_status.get("active") else "Your subscription is active."
    message = (
        "Your Account:\n"
        f"Subscription Wallet Address: {wallet['address']}\n"
        f"Subscription Wallet Private Key: {wallet['private_key']}\n"
        f"Subscription Wallet Balance: {wallet['balance']} SOL\n\n"
        "Your Subscription:\n"
        f"{status_text}\n\n"
        "Pricing:\n"
        f"Weekly Subscription Price: {SUBSCRIPTION_PRICING['weekly']} SOL (discount 10%)\n"
        f"Monthly Subscription Price: {SUBSCRIPTION_PRICING['monthly']} SOL (discount 10%)\n"
        f"Lifetime Subscription Price: {SUBSCRIPTION_PRICING['lifetime']} SOL (discount 10%)"
    )
    keyboard = [
        [InlineKeyboardButton("Weekly - " + str(SUBSCRIPTION_PRICING["weekly"]) + " SOL", callback_data="subscription:weekly")],
        [InlineKeyboardButton("Monthly - " + str(SUBSCRIPTION_PRICING["monthly"]) + " SOL", callback_data="subscription:monthly")],
        [InlineKeyboardButton("Lifetime - " + str(SUBSCRIPTION_PRICING["lifetime"]) + " SOL", callback_data="subscription:lifetime")],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])],
    ]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def process_subscription_plan(update: Update, context):
    """
    Process the chosen subscription plan by showing payment instructions.
    Instruct the user to include their Telegram ID in the memo (e.g., "TID:<user_id>").
    A background job will automatically verify the payment.
    """
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
        f"{SUBSCRIPTION_WALLET['address']}\n\n"
        "IMPORTANT: In the transaction memo, include your Telegram user ID in the format: TID:<your Telegram id>\n\n"
        "Your subscription will be automatically activated once your payment is detected on-chain."
    )
    keyboard = [
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
    ]
    # Save the user's desired subscription plan so that when payment is detected we know what plan to activate.
    user_subscriptions[query.from_user.id] = {"active": False, "plan": plan, "amount": sol_amount}
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def check_subscription_payments(context):
    """
    Background job that periodically checks for incoming SOL payments to the subscription wallet.
    For each transaction, it looks for a memo containing "TID:<user_id>" and verifies that the amount matches a subscription plan.
    If a matching transaction is found and confirmed, the user's subscription is marked as active.
    """
    global LAST_CHECKED_SIGNATURE
    rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    async with AsyncClient(rpc_url) as client:
        # Get confirmed signatures for the subscription wallet address.
        try:
            response = await client.get_signatures_for_address(SUBSCRIPTION_WALLET["address"], limit=10)
            if not response["result"]:
                return
            signatures = response["result"]
            # Process new signatures since LAST_CHECKED_SIGNATURE
            new_signatures = []
            for sig_info in signatures:
                sig = sig_info["signature"]
                if LAST_CHECKED_SIGNATURE is None or sig != LAST_CHECKED_SIGNATURE:
                    new_signatures.append(sig)
                else:
                    break
            if new_signatures:
                LAST_CHECKED_SIGNATURE = new_signatures[0]
            # For each new signature, fetch transaction details.
            for signature in new_signatures:
                tx_resp = await client.get_transaction(signature, encoding="jsonParsed")
                if not tx_resp["result"]:
                    continue
                tx = tx_resp["result"]
                # Look for memo instructions and the SOL transfer amount.
                # (This is simplified; in production you should handle multiple instructions, confirmations, etc.)
                memo = None
                lamports = 0
                if "transaction" in tx and "message" in tx["transaction"]:
                    for instr in tx["transaction"]["message"]["instructions"]:
                        if instr["program"] == "spl-memo":
                            memo = instr.get("parsed")
                    # Also look at the SOL transfer (native transfer) in the transaction.
                    for instr in tx["transaction"]["message"]["instructions"]:
                        if instr["program"] == "system":
                            # This instruction represents a SOL transfer.
                            try:
                                lamports = int(instr["parsed"]["info"]["lamports"])
                            except (KeyError, ValueError):
                                pass
                sol_received = lamports / 1_000_000_000  # convert lamports to SOL
                # If a memo exists and matches the format "TID:<user_id>" then process payment.
                if memo and isinstance(memo, str) and memo.startswith("TID:"):
                    try:
                        user_id = int(memo.split(":")[1])
                    except ValueError:
                        continue
                    # Check if this user has a pending subscription request.
                    sub_req = user_subscriptions.get(user_id)
                    if sub_req and not sub_req.get("active"):
                        expected_amount = sub_req["amount"]
                        # A tolerance may be applied here.
                        if abs(sol_received - expected_amount) < 0.01:
                            # Mark subscription as active.
                            user_subscriptions[user_id]["active"] = True
                            logger.info(f"Activated subscription for user {user_id} with plan {sub_req['plan']}")
                            # Optionally, you can send a message to the user notifying them.
                            try:
                                await context.bot.send_message(
                                    chat_id=user_id,
                                    text="Payment confirmed. Your subscription is now active."
                                )
                            except Exception as e:
                                logger.error(f"Failed to send subscription confirmation to user {user_id}: {e}")
        except Exception as e:
            logger.error(f"Error checking subscription payments: {e}")

# ----- CALLBACK HANDLER -----

async def button_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    try:
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
        elif query.data == CALLBACKS["start"]:
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
            push_nav_state(context, {
                "message_text": query.message.text,
                "keyboard": query.message.reply_markup.inline_keyboard,
                "parse_mode": "Markdown"
            })
            await query.message.edit_text(
                f"Your new wallet:\nPublic Key: {public_key}\n\nSave your private key and seed phrase securely. Check your private messages for the sensitive information.",
                parse_mode="Markdown"
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Your Wallet Details\nPrivate Key: {private_key}\nSeed Phrase: {mnemonic}\n\nKeep this information safe and never share it!",
                parse_mode="Markdown"
            )
        elif query.data == CALLBACKS["import_wallet"]:
            push_nav_state(context, {
                "message_text": query.message.text,
                "keyboard": query.message.reply_markup.inline_keyboard,
                "parse_mode": "Markdown"
            })
            await query.message.edit_text(
                "Import Wallet\nPlease send your private key as a message.\n\nMake sure you're sending this in a private message to the bot!",
                parse_mode="Markdown"
            )
        elif query.data == CALLBACKS["show_private_key"]:
            user_id = query.from_user.id
            if user_id not in user_wallets:
                await query.message.edit_text("No wallet found. Please create a wallet first.")
                return
            push_nav_state(context, {
                "message_text": query.message.text,
                "keyboard": query.message.reply_markup.inline_keyboard,
                "parse_mode": "Markdown"
            })
            private_key = user_wallets[user_id]["private"]
            keyboard = [
                [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
                 InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]
            ]
            await query.message.edit_text(
                f"Private Key:\n{private_key}\n\nKeep this private key safe!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        elif query.data == CALLBACKS["show_seed_phrase"]:
            user_id = query.from_user.id
            if user_id not in user_wallets:
                await query.message.edit_text("No wallet found. Please create a wallet first.")
                return
            push_nav_state(context, {
                "message_text": query.message.text,
                "keyboard": query.message.reply_markup.inline_keyboard,
                "parse_mode": "Markdown"
            })
            mnemonic = user_wallets[user_id]["mnemonic"]
            keyboard = [
                [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"]),
                 InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])]
            ]
            await query.message.edit_text(
                f"Seed Phrase:\n{mnemonic}\n\nKeep this seed phrase safe!",
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
            message = f"Deposit SOL\n\nSend SOL to your wallet address:\n{wallet['public']}\n\n(Tap to copy)"
            keyboard = [
                [InlineKeyboardButton("Back", callback_data=CALLBACKS["wallet_details"]),
                 InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
            ]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif query.data == CALLBACKS["withdraw_sol"]:
            push_nav_state(context, {
                "message_text": query.message.text,
                "keyboard": query.message.reply_markup.inline_keyboard,
                "parse_mode": "Markdown"
            })
            context.user_data["awaiting_withdraw"] = True
            message = "Withdraw SOL\n\nReply with the destination address where you want to send SOL."
            await query.message.edit_text(message, parse_mode="Markdown")
        elif query.data == CALLBACKS["refresh_balance"]:
            user_id = query.from_user.id
            wallet = user_wallets.get(user_id)
            balance = wallet.get("balance", 0)
            message = f"""
Your Wallet:

Address: {wallet["public"]} (tap to copy)
Balance: {balance} SOL

Tap to copy the address and send SOL to deposit.
Once done, tap refresh and your balance will appear here.
"""
            keyboard = [
                [InlineKeyboardButton("Deposit SOL", callback_data=CALLBACKS["deposit_sol"]),
                 InlineKeyboardButton("Withdraw SOL", callback_data=CALLBACKS["withdraw_sol"])],
                [InlineKeyboardButton("Refresh Balance", callback_data=CALLBACKS["refresh_balance"])],
                [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/{wallet['public']}")],
                [InlineKeyboardButton("Back", callback_data=CALLBACKS["wallets"]),
                 InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])],
            ]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        # Bundle feature callbacks
        elif query.data == CALLBACKS["bundle"]:
            await show_bundle(update, context)
        elif query.data == CALLBACKS["bundle_distribute_sol"]:
            await distribute_sol_bundle(update, context)
        # Subscription feature
        elif query.data == CALLBACKS["subscription"]:
            await show_subscription_details(update, context)
        elif query.data.startswith("subscription:"):
            # Process subscription plan selection.
            await process_subscription_plan(update, context)
        else:
            responses = {
                CALLBACKS["launch"]: "Launch feature - Prepare to deploy your token with dev wallet protection.",
                CALLBACKS["settings"]: "Customize your transaction settings, slippage, and gas fees.",
                CALLBACKS["commenter"]: "Automatic commenting system for token pages.",
                CALLBACKS["bump_volume"]: "Tools to increase your token's visibility and trading volume.",
                CALLBACKS["socials"]: "Connect with our community across various platforms.",
            }
            await query.message.edit_text(responses.get(query.data, "Feature coming soon!"))
    
    except Exception as e:
        logger.error(f"Error in button callback: {str(e)}")
        await query.message.edit_text("An error occurred. Please try again.")

# ----- HANDLERS FOR PRIVATE MESSAGES (IMPORT/ WITHDRAW) -----

async def import_private_key(update: Update, context):
    """
    This handler is for importing a wallet by pasting a private key.
    It will only be used if we're NOT awaiting a withdrawal destination.
    """
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
        await update.message.reply_text(
            f"Wallet imported successfully:\n{public_key}",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(
            f"Error importing wallet:\n{str(e)}",
            parse_mode="Markdown"
        )

async def handle_withdraw_address(update: Update, context):
    """
    This handler processes the withdrawal destination address.
    In a complete implementation, you would verify the address and trigger a SOL transfer transaction.
    """
    if context.user_data.get("awaiting_withdraw"):
        destination = update.message.text.strip()
        user_id = update.message.from_user.id
        await update.message.reply_text(
            f"Withdrawal requested to address:\n{destination}\n(This feature is not fully implemented yet.)",
            parse_mode="Markdown"
        )
        context.user_data["awaiting_withdraw"] = False
    else:
        await import_private_key(update, context)

async def handle_text_message(update: Update, context):
    """
    Delegate incoming text messages to the correct handler depending on whether we're awaiting a withdrawal address.
    """
    if context.user_data.get("awaiting_withdraw"):
        await handle_withdraw_address(update, context)
    else:
        await import_private_key(update, context)

# ----- MAIN FUNCTION -----

def main():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set.")
    application = Application.builder().token(bot_token).build()
    # Add the job for checking subscription payments every 60 seconds.
    application.job_queue.run_repeating(check_subscription_payments, interval=60, first=10)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    logger.info("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()
