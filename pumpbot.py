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

# Configuration constants
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
    
    # New Wallet Details & transaction features
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
    "referral": "referral",
    "dynamic_back": "dynamic_back",
}

# User wallet store (for now, one wallet per user)
user_wallets = {}

# Navigation state tracking
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
            InlineKeyboardButton("Referral", callback_data=CALLBACKS["referral"]),
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
*Welcome to PumpBot!*
The fastest way to launch and manage assets, created by a team of friends from the PUMP community.

You currently have no SOL balance. To get started with launching coin, subscribe first (Subscription) and send some SOL to your pumpbot wallet address:

`{wallet_address}` (tap to copy)

Once done tap refresh and your balance will appear here.

For more info on your account and to retrieve your private key, tap the wallet button below.
*Remember:* We guarantee the safety of user funds on PumpBot, but if you expose your private key your funds will not be safe.
"""
        await update.message.reply_text(
            welcome_message, reply_markup=reply_markup, parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in start command: {str(e)}")
        await update.message.reply_text(
            "An error occurred while starting the bot. Please try again."
        )

async def go_to_main_menu(query, context):
    """Helper function to reset navigation and show the main menu."""
    context.user_data["nav_stack"] = []  # clear navigation stack
    user_id = query.from_user.id
    wallet_address = user_wallets.get(user_id, {}).get("public", "No wallet")
    reply_markup = InlineKeyboardMarkup(generate_inline_keyboard())
    welcome_message = f"""
*Welcome to PumpBot!*
The fastest way to launch and manage assets, created by a team of friends from the PUMP community.

Your wallet address: `{wallet_address}`

Send SOL to your wallet and tap Refresh to update your balance.
"""
    await query.message.edit_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_wallets_menu(update: Update, context):
    """Display the wallets management menu with total holdings."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    wallet = user_wallets[user_id]
    wallet_address = wallet["public"]
    balance = wallet.get("balance", 0)
    bundle_total = 0
    if "bundle" in wallet:
        for b in wallet["bundle"]:
            bundle_total += b.get("balance", 0)
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
        f"🔐 *Wallet Management*\n\n🪪 *Wallet Address:* `{wallet_address}`\n*Total Holdings:* {total_holdings} SOL\n\nChoose an option below:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def show_wallet_details(update: Update, context):
    """Show a detailed view of the wallet with deposit/withdraw options, total holdings, and Bundle button."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    wallet = user_wallets.get(user_id)
    if not wallet:
        await query.message.edit_text("❌ No wallet found. Please create a wallet first.")
        return

    balance = wallet.get("balance", 0)
    bundle_total = 0
    if "bundle" in wallet:
        for b in wallet["bundle"]:
            bundle_total += b.get("balance", 0)
    total_holdings = balance + bundle_total

    message = f"""
*Your Wallet:*

*Address:* `{wallet["public"]}` (tap to copy)
*Main Balance:* {balance} SOL
*Total Holdings:* {total_holdings} SOL

Tap to copy the address and send SOL to deposit.
Once done, tap refresh and your balance will appear here.
"""
    keyboard = [
        [InlineKeyboardButton("Deposit SOL", callback_data=CALLBACKS["deposit_sol"]),
         InlineKeyboardButton("Withdraw SOL", callback_data=CALLBACKS["withdraw_sol"])],
        [InlineKeyboardButton("Refresh Balance", callback_data=CALLBACKS["refresh_balance"])],
        [InlineKeyboardButton("View on Solscan", url=f"https://solscan.io/account/{wallet['public']}")],
        [InlineKeyboardButton("Bundle", callback_data=CALLBACKS["bundle"])],
        [InlineKeyboardButton("Back", callback_data=CALLBACKS["dynamic_back"]),
         InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])],
    ]
    push_nav_state(context, {
        "message_text": query.message.text,
        "keyboard": query.message.reply_markup.inline_keyboard,
        "parse_mode": "Markdown"
    })
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def show_bundle(update: Update, context):
    """Show the bundle view which displays 7 bundled wallets, their balances, and total bundle balance."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    wallet = user_wallets.get(user_id)
    if not wallet:
        await query.message.edit_text("❌ No wallet found. Please create a wallet first.")
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
    message = f"*Bundle Wallets:*\n\n*Total Bundle Balance:* {bundle_total} SOL\n\n"
    for idx, b_wallet in enumerate(wallet["bundle"], start=1):
        message += f"*{idx}.* Address: `{b_wallet['public']}`\n\n Balance: {b_wallet['balance']} SOL\n\n"
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
        await query.message.edit_text("❌ No wallet found. Please create a wallet first.")
        return
    main_balance = wallet.get("balance", 0)
    if main_balance <= 0:
        await query.message.edit_text("No SOL available in your main wallet for distribution.")
        return
    bundle = wallet.get("bundle")
    if not bundle or len(bundle) < 7:
        await query.message.edit_text("Bundle not found or incomplete. Please recreate the bundle.")
        return

    # Generate 7 random ratios to distribute the main_balance
    rand_values = [random.random() for _ in range(7)]
    total = sum(rand_values)
    distribution = [(val / total) * main_balance for val in rand_values]
    for i in range(7):
        bundle[i]["balance"] += round(distribution[i], 4)
    # Set main wallet's balance to 0 after distribution.
    wallet["balance"] = 0

    message = "*Distribution Completed!*\n\n"
    for idx, b_wallet in enumerate(bundle, start=1):
        message += f"*{idx}.* Address: `{b_wallet['public']}`, New Balance: {b_wallet['balance']} SOL\n"
    message += "\nMain wallet's SOL has been distributed to the bundle wallets."
    keyboard = [
        [InlineKeyboardButton("Back to Bundle", callback_data=CALLBACKS["bundle"])],
        [InlineKeyboardButton("Main Menu", callback_data=CALLBACKS["start"])]
    ]
    await query.message.edit_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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
                f"✅ *Your new wallet:*\nPublic Key: `{public_key}`\n\n⚠️ Save your private key and seed phrase securely! Check your private messages for the sensitive information.",
                parse_mode="Markdown"
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🔐 *Your Wallet Details*\nPrivate Key: `{private_key}`\nSeed Phrase: `{mnemonic}`\n\n⚠️ Keep this information safe and never share it!",
                parse_mode="Markdown"
            )

        elif query.data == CALLBACKS["import_wallet"]:
            push_nav_state(context, {
                "message_text": query.message.text,
                "keyboard": query.message.reply_markup.inline_keyboard,
                "parse_mode": "Markdown"
            })
            await query.message.edit_text(
                "📥 *Import Wallet*\nPlease send your private key as a message.\n\n⚠️ Make sure you're sending this in a private message to the bot!",
                parse_mode="Markdown"
            )

        elif query.data == CALLBACKS["show_private_key"]:
            user_id = query.from_user.id
            if user_id not in user_wallets:
                await query.message.edit_text("❌ No wallet found. Please create a wallet first.")
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
                f"🔑 *Private Key*:\n`{private_key}`\n\n⚠️ Keep this private key safe!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

        elif query.data == CALLBACKS["show_seed_phrase"]:
            user_id = query.from_user.id
            if user_id not in user_wallets:
                await query.message.edit_text("❌ No wallet found. Please create a wallet first.")
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
                f"🧳 *Seed Phrase*:\n`{mnemonic}`\n\n⚠️ Keep this seed phrase safe!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

        elif query.data == CALLBACKS["wallet_details"]:
            await show_wallet_details(update, context)

        elif query.data == CALLBACKS["deposit_sol"]:
            user_id = query.from_user.id
            wallet = user_wallets.get(user_id)
            if not wallet:
                await query.message.edit_text("❌ No wallet found. Please create a wallet first.")
                return
            message = f"💰 *Deposit SOL*\n\nSend SOL to your wallet address:\n`{wallet['public']}`\n\n(Tap to copy)"
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
            message = "🚀 *Withdraw SOL*\n\nReply with the destination address where you want to send SOL."
            await query.message.edit_text(message, parse_mode="Markdown")

        elif query.data == CALLBACKS["refresh_balance"]:
            balance = user_wallets[query.from_user.id].get("balance", 0)
            user_id = query.from_user.id
            wallet = user_wallets.get(user_id)
            message = f"""
*Your Wallet:*

*Address:* `{wallet["public"]}` (tap to copy)
*Balance:* {balance} SOL

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

        else:
            responses = {
                CALLBACKS["launch"]: "Launch feature - Prepare to deploy your token with dev wallet protection.",
                CALLBACKS["subscription"]: "Subscription plans - Unlock advanced features and capabilities.",
                CALLBACKS["settings"]: "Customize your transaction settings, slippage, and gas fees.",
                CALLBACKS["commenter"]: "Automatic commenting system for token pages.",
                CALLBACKS["bump_volume"]: "Tools to increase your token's visibility and trading volume.",
                CALLBACKS["socials"]: "Connect with our community across various platforms.",
                CALLBACKS["referral"]: "Earn rewards by sharing our bot with others.",
            }
            await query.message.edit_text(responses.get(query.data, "Feature coming soon!"))
    
    except Exception as e:
        logger.error(f"Error in button callback: {str(e)}")
        await query.message.edit_text("An error occurred. Please try again.")

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
            f"✅ *Wallet imported successfully:*\n`{public_key}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ *Error importing wallet:*\n{str(e)}",
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
            f"Withdrawal requested to address:\n`{destination}`\n(This feature is not fully implemented yet.)",
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

def main():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set.")
    application = Application.builder().token(bot_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    logger.info("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()
