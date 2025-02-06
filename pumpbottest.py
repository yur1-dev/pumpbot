import logging
import os
import random
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
    "balance": 0,
}

# Subscription pricing (SOL amounts)
SUBSCRIPTION_PRICING = {
    "weekly": 0.9,
    "monthly": 3.15,
    "lifetime": 13.5,
}

# Bot main menu and other callback names
CALLBACKS = {
    "start": "start",
    "launch": "launch",  # When clicked, triggers subscription check then sequential coin creation
    "subscription": "subscription",
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
}

# In-memory storage for user wallets and subscriptions.
user_wallets = {}
user_subscriptions = {}  # Maps Telegram user_id -> subscription details

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
        logger.error(f"Error generating wallet: {str(e)}")
        raise

# ----- MAIN MENU -----

def generate_inline_keyboard():
    # Main menu with text-only buttons.
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
        # Create wallet if not exists.
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
        # ORIGINAL INTRO (unchanged)
        welcome_message = f"""
Welcome to PumpBot!
The fastest way to launch and manage assets, created by a team of friends from the PUMP community.

You currently have no SOL balance. To get started with launching coin, subscribe first (Subscription) and send some SOL to your pumpbot wallet address:

`{wallet_address}` (tap to copy)

Once done, tap refresh and your balance will appear here.

For more info on your account and to retrieve your private key, tap the wallet button below.
Remember: We guarantee the safety of user funds on PumpBot, but if you expose your private key your funds will not be safe.
"""
        await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}")
        await update.message.reply_text("An error occurred while starting the bot. Please try again.")

async def go_to_main_menu(query, context):
    context.user_data["nav_stack"] = []
    user_id = query.from_user.id
    wallet_address = user_wallets.get(user_id, {}).get("public", "No wallet")
    reply_markup = InlineKeyboardMarkup(generate_inline_keyboard())
    welcome_message = f"""
Welcome to PumpBot!
Your wallet address: `{wallet_address}`

Send SOL to your wallet and tap Refresh to update your balance.
"""
    await query.message.edit_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")

# ----- WALLET MANAGEMENT FUNCTIONS (UNCHANGED, with spacing improvements) -----

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
        # "Back to Menu" is always left; "Back" is always right.
        [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"]),
         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])],
    ]
    
    push_nav_state(context, {"message_text": query.message.text,
                             "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                             "parse_mode": "Markdown"})
    
    await query.message.edit_text(
        f"Wallet Management\n\nWallet Address: `{wallet_address}`\n\nMain Balance: {balance} SOL\nTotal Holdings: {total_holdings} SOL\n",
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

Address: `{wallet["public"]}`  
Main Balance: {balance} SOL  
Total Holdings: {total_holdings} SOL

Tap the address to copy.  
Send SOL to deposit and then tap Refresh to update your balance.
"""
    keyboard = [
        [InlineKeyboardButton("Deposit SOL", callback_data=CALLBACKS["deposit_sol"]),
         InlineKeyboardButton("Withdraw SOL", callback_data=CALLBACKS["withdraw_sol"])],
        [InlineKeyboardButton("Refresh Balance", callback_data=CALLBACKS["refresh_balance"])],
        [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/`{wallet['public']}`")],
        [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"]),
         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])],
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
        message += f"{idx}. Address: `{b_wallet['public']}`  \n   Balance: {b_wallet['balance']} SOL\n\n"
    message += "\nUse 'Distribute SOL' to distribute your main wallet's SOL among these bundle wallets."
    keyboard = [
        [InlineKeyboardButton("Distribute SOL", callback_data=CALLBACKS["bundle_distribute_sol"])],
        [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"]),
         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])],
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
        message += f"{idx}. Address: `{b_wallet['public']}`  \nNew Balance: {b_wallet['balance']} SOL\n"
    message += "\nMain wallet's SOL has been distributed to the bundle wallets."
    keyboard = [
        [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"]),
         InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"])],
    ]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- SUBSCRIPTION FEATURE (MANUAL CONFIRMATION) -----

async def show_subscription_details(update: Update, context):
    """
    Display subscription details:
      - Subscription wallet details
      - Current subscription status
      - Pricing for each plan
    """
    query = update.callback_query
    await query.answer()
    wallet = SUBSCRIPTION_WALLET
    subscription_status = user_subscriptions.get(query.from_user.id, {"active": False})
    status_text = "You do not have an active subscription yet." if not subscription_status.get("active") else "Your subscription is active."
    message = (
        "Your Account:\n"
        f"Subscription Wallet Address: `{wallet['address']}`  \n"
        f"Subscription Wallet Private Key: `{wallet['private_key']}`  \n"
        f"Subscription Wallet Balance: `{wallet['balance']}` SOL\n\n"
        "Your Subscription:\n"
        f"{status_text}\n\n"
        "Pricing:\n"
        f"Weekly Subscription Price: {SUBSCRIPTION_PRICING['weekly']} SOL (discount 10%)  \n"
        f"Monthly Subscription Price: {SUBSCRIPTION_PRICING['monthly']} SOL (discount 10%)  \n"
        f"Lifetime Subscription Price: {SUBSCRIPTION_PRICING['lifetime']} SOL (discount 10%)"
    )
    keyboard = [
        [InlineKeyboardButton("Weekly - " + str(SUBSCRIPTION_PRICING["weekly"]) + " SOL", callback_data="subscription:weekly")],
        [InlineKeyboardButton("Monthly - " + str(SUBSCRIPTION_PRICING["monthly"]) + " SOL", callback_data="subscription:monthly")],
        [InlineKeyboardButton("Lifetime - " + str(SUBSCRIPTION_PRICING["lifetime"]) + " SOL", callback_data="subscription:lifetime")],
        [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])],
    ]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def process_subscription_plan(update: Update, context):
    """
    Process the chosen subscription plan by showing payment instructions.
    In this manual mode, the user is instructed to send the SOL amount to the given wallet address,
    then tap the "I have paid" button.
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
        "After you have completed the payment, tap the 'I have paid' button below."
    )
    user_subscriptions[query.from_user.id] = {"active": False, "plan": plan, "amount": sol_amount}
    keyboard = [
        [InlineKeyboardButton("I have paid", callback_data=f"subscription:confirm:{plan}")],
        [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])],
    ]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def confirm_subscription_payment(update: Update, context):
    """
    Simulate manual confirmation of the subscription payment.
    In a future update, this can be replaced with on-chain verification.
    """
    query = update.callback_query
    await query.answer()
    plan = query.data.split(":")[2]
    user_subscriptions[query.from_user.id]["active"] = True
    message = (
        f"Payment confirmed for your {plan} subscription plan.\n\n"
        "Your subscription is now active and you have full access to the bot's features."
    )
    keyboard = [
        [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])],
    ]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- STRICT, SEQUENTIAL LAUNCH COIN FLOW -----
# This flow asks one question at a time and then shows a confirmation summary.

LAUNCH_STEPS = [
    ("name", "Please enter the *Coin Name*:"),
    ("ticker", "Please enter the *Coin Ticker*:"),
    ("price", "Please enter the *Price in $*:"),
    ("description", "Please enter the *Coin Description*:"),
    ("media", "Please enter the *Media URL* (image or video):")
]

def start_launch_flow(context):
    """Initialize the launch conversation."""
    context.user_data["launch_step_index"] = 0
    context.user_data["coin_data"] = {}

async def prompt_current_launch_step(query, context):
    """Prompt the user for the current launch step."""
    index = context.user_data.get("launch_step_index", 0)
    if index < len(LAUNCH_STEPS):
        step_key, prompt_text = LAUNCH_STEPS[index]
        await query.message.edit_text(prompt_text, parse_mode="Markdown")
    else:
        # All required steps completed; show confirmation summary.
        coin_data = context.user_data.get("coin_data", {})
        summary = (
            "*Review your coin data:*\n\n" +
            f"*Name:* {coin_data.get('name')}\n" +
            f"*Ticker:* {coin_data.get('ticker')}\n" +
            f"*Price:* {coin_data.get('price')}\n" +
            f"*Description:* {coin_data.get('description')}\n" +
            f"*Media URL:* {coin_data.get('media')}\n\n" +
            "Are you sure you want to create this coin? This action cannot be changed later."
        )
        keyboard = [
            [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"]),
             InlineKeyboardButton("Back", callback_data=CALLBACKS["launch_confirm_no"])],
            [InlineKeyboardButton("Confirm", callback_data=CALLBACKS["launch_confirm_yes"])]
        ]
        await query.message.edit_text(summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def process_launch_confirmation(query, context):
    """Simulate coin creation and display a success message."""
    coin_data = context.user_data.get("coin_data", {})
    message = (
        "Creating Coin...\n\n" +
        f"Name: {coin_data.get('name')}\n" +
        f"Ticker: {coin_data.get('ticker')}\n" +
        f"Price: {coin_data.get('price')}\n" +
        f"Description: {coin_data.get('description')}\n" +
        f"Media URL: {coin_data.get('media')}\n\n" +
        "Your coin is now being deployed with PumpFun's bonding curve. When it completes, you'll receive 0.5 SOL."
    )
    keyboard = [
        [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]
    ]
    # Clear launch conversation data.
    context.user_data.pop("launch_step_index", None)
    context.user_data.pop("coin_data", None)
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ----- CALLBACK HANDLER -----

async def button_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    try:
        # Wallet and subscription features.
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
            push_nav_state(context, {"message_text": query.message.text,
                                     "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                     "parse_mode": "Markdown"})
            await query.message.edit_text(
                f"Your new wallet:\nPublic Key: {public_key}\n\nSave your private key and seed phrase securely. Check your private messages for the sensitive information.",
                parse_mode="Markdown"
            )
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=f"Your Wallet Details\nPrivate Key: {private_key}\nSeed Phrase: {mnemonic}\n\nKeep this information safe and never share it!",
                parse_mode="Markdown"
            )
        elif query.data == CALLBACKS["import_wallet"]:
            push_nav_state(context, {"message_text": query.message.text,
                                     "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                     "parse_mode": "Markdown"})
            await query.message.edit_text(
                "Import Wallet\nPlease send your private key as a message.\n\nMake sure you're sending this in a private message to the bot!",
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
            keyboard = [
                [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"]),
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
            push_nav_state(context, {"message_text": query.message.text,
                                     "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                     "parse_mode": "Markdown"})
            mnemonic = user_wallets[user_id]["mnemonic"]
            keyboard = [
                [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"]),
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
            message = f"Deposit SOL\n\nSend SOL to your wallet address:\n`{wallet['public']}`\n\n(Tap to copy)"
            keyboard = [
                [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"]),
                 InlineKeyboardButton("Back", callback_data=CALLBACKS["wallet_details"])]
            ]
            await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        elif query.data == CALLBACKS["withdraw_sol"]:
            push_nav_state(context, {"message_text": query.message.text,
                                     "keyboard": query.message.reply_markup.inline_keyboard if query.message.reply_markup else [],
                                     "parse_mode": "Markdown"})
            context.user_data["awaiting_withdraw"] = True
            message = "Withdraw SOL\n\nReply with the destination address where you want to send SOL."
            await query.message.edit_text(message, parse_mode="Markdown")
        elif query.data == CALLBACKS["refresh_balance"]:
            user_id = query.from_user.id
            wallet = user_wallets.get(user_id)
            balance = wallet.get("balance", 0)
            message = f"""
Your Wallet:

Address: `{wallet["public"]}`  
Balance: {balance} SOL

Tap the address to copy and send SOL to deposit.
Once done, tap Refresh to update your balance.
"""
            keyboard = [
                [InlineKeyboardButton("Deposit SOL", callback_data=CALLBACKS["deposit_sol"]),
                 InlineKeyboardButton("Withdraw SOL", callback_data=CALLBACKS["withdraw_sol"])],
                [InlineKeyboardButton("Refresh Balance", callback_data=CALLBACKS["refresh_balance"])],
                [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/`{wallet['public']}`")],
                [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"]),
                 InlineKeyboardButton("Back", callback_data=CALLBACKS["wallets"])],
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
        # ----- Launch Flow (Sequential) -----
        elif query.data == CALLBACKS["launch"]:
            # Before starting the launch conversation, check subscription status.
            user_id = query.from_user.id
            subscription = user_subscriptions.get(user_id, {})
            if not subscription.get("active"):
                message = ("You must subscribe to use the Launch feature.\n\n"
                           "Please subscribe first to unlock full access to all PumpBot features.")
                keyboard = [
                    [InlineKeyboardButton("Subscribe", callback_data=CALLBACKS["subscription"]),
                     InlineKeyboardButton("Docs", url="https://yourgitbooklink.com")],
                    [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"])]
                ]
                await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            else:
                # Start the launch conversation.
                start_launch_flow(context)
                await prompt_current_launch_step(query, context)
        elif query.data == CALLBACKS["launch_confirm_yes"]:
            await process_launch_confirmation(query, context)
        elif query.data == CALLBACKS["launch_confirm_no"]:
            # Cancel launch and clear conversation data.
            context.user_data.pop("launch_step_index", None)
            context.user_data.pop("coin_data", None)
            await query.message.edit_text("Coin creation cancelled.", parse_mode="Markdown")
        else:
            responses = {
                CALLBACKS["bump_volume"]: "Tools to increase your token's visibility and trading volume.",
                CALLBACKS["socials"]: "Connect with our community on Telegram, Twitter, YouTube, and more.",
            }
            await query.message.edit_text(responses.get(query.data, "Feature coming soon!"))
    
    except Exception as e:
        logger.error(f"Error in button callback: {str(e)}")
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
        await update.message.reply_text(f"Wallet imported successfully:\n{public_key}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error importing wallet:\n{str(e)}", parse_mode="Markdown")

async def handle_withdraw_address(update: Update, context):
    if context.user_data.get("awaiting_withdraw"):
        destination = update.message.text.strip()
        user_id = update.message.from_user.id
        await update.message.reply_text(f"Withdrawal requested to address:\n{destination}\n(This feature is not fully implemented yet.)", parse_mode="Markdown")
        context.user_data["awaiting_withdraw"] = False
    else:
        await import_private_key(update, context)

async def handle_text_message(update: Update, context):
    """
    This function handles text messages for:
      - Launch conversation (sequential coin creation)
      - Wallet import / withdrawal messages (if not in a launch conversation)
    """
    if "launch_step_index" in context.user_data:
        index = context.user_data.get("launch_step_index", 0)
        if index < len(LAUNCH_STEPS):
            step_key, prompt_text = LAUNCH_STEPS[index]
            if "coin_data" not in context.user_data:
                context.user_data["coin_data"] = {}
            context.user_data["coin_data"][step_key] = update.message.text.strip()
            context.user_data["launch_step_index"] = index + 1
            # If there are more steps, prompt the next one.
            if context.user_data["launch_step_index"] < len(LAUNCH_STEPS):
                next_prompt = LAUNCH_STEPS[context.user_data["launch_step_index"]][1]
                await update.message.reply_text(next_prompt, parse_mode="Markdown")
            else:
                # All steps complete; show confirmation summary.
                coin_data = context.user_data.get("coin_data", {})
                summary = (
                    "*Review your coin data:*\n\n" +
                    f"*Name:* {coin_data.get('name')}\n" +
                    f"*Ticker:* {coin_data.get('ticker')}\n" +
                    f"*Price:* {coin_data.get('price')}\n" +
                    f"*Description:* {coin_data.get('description')}\n" +
                    f"*Media URL:* {coin_data.get('media')}\n\n" +
                    "Are you sure you want to create this coin? This action cannot be changed later."
                )
                keyboard = [
                    [InlineKeyboardButton("Back to Menu", callback_data=CALLBACKS["start"]),
                     InlineKeyboardButton("Back", callback_data=CALLBACKS["launch_confirm_no"])],
                    [InlineKeyboardButton("Confirm", callback_data=CALLBACKS["launch_confirm_yes"])]
                ]
                await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return
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
    # application.job_queue.run_repeating(check_subscription_payments, interval=60, first=10)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    logger.info("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()