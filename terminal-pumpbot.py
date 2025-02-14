import logging
import os
import random
import base58
import json
import requests
from datetime import datetime, timedelta
from mnemonic import Mnemonic
from dotenv import load_dotenv

# --- Solana & Solders Imports ---
from solders.keypair import Keypair as SoldersKeypair
from solders.pubkey import Pubkey as PublicKey

# solana-py for on-chain interactions
from solana.rpc.api import Client
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from solana.keypair import Keypair as SolanaKeypair
from solana.rpc.types import TxOpts

# --- Colorama for colored terminal output ---
from colorama import init, Fore, Style

init(autoreset=True)

# ----- CONFIGURATION CONSTANTS -----
SUBSCRIPTION_WALLET = {
    "address": "84YWzdTEva6zmH43xPTX8oEUbxS47s6yRAkFp2D5esXk",
    "balance": 0,
}
SUBSCRIPTION_PRICING = {
    "weekly": 0.03,
    "monthly": 3,
    "lifetime": 8,
}

# Global “databases” (since terminal version is single–user)
USER_ID = 1
user_wallets = {}       # { user_id: { public, private, mnemonic, balance, bundle } }
user_subscriptions = {} # { user_id: { active, plan, amount, expires_at, tx_signature } }
user_coins = {}         # { user_id: [ coin_data, ... ] }

# ----- HELPER FUNCTIONS FOR ON-CHAIN INTERACTION -----
def get_wallet_balance(public_key: str) -> float:
    rpc_url = os.getenv("SOLANA_RPC_URL")
    client = Client(rpc_url)
    try:
        pk_bytes = base58.b58decode(public_key)
        result = client.get_balance(PublicKey(pk_bytes))
        lamports = result["result"]["value"]
        balance = lamports / 10**9
        logging.info(f"Fetched balance for {public_key}: {balance} SOL")
        return balance
    except Exception as e:
        logging.error(f"Error fetching balance for {public_key}: {e}", exc_info=True)
        return 0.0

def transfer_sol(from_wallet: dict, to_address: str, amount_sol: float) -> dict:
    rpc_url = os.getenv("SOLANA_RPC_URL")
    client = Client(rpc_url)
    lamports = int(amount_sol * 10**9)
    try:
        secret_key = base58.b58decode(from_wallet["private"])
        solana_keypair = SolanaKeypair.from_secret_key(secret_key)
    except Exception as e:
        logging.error("Error decoding private key", exc_info=True)
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
        logging.error("Error building transaction", exc_info=True)
        return {"status": "error", "message": "Error building transaction: " + str(e)}
    try:
        txn.sign(solana_keypair)
        raw_tx = txn.serialize()
        response = client.send_raw_transaction(raw_tx, opts=TxOpts(skip_preflight=True))
        logging.info(f"Transaction response: {response}")
        if isinstance(response, dict) and "result" in response:
            signature = response["result"]
            logging.info(f"Transfer successful: {signature}")
            return {"status": "success", "signature": signature}
        else:
            error_msg = response.get("error", "Unknown error") if isinstance(response, dict) else str(response)
            logging.error(f"Transfer error: {error_msg}")
            return {"status": "error", "message": error_msg}
    except Exception as e:
        logging.error("Error sending transaction: " + str(e), exc_info=True)
        return {"status": "error", "message": "Error sending transaction: " + str(e)}

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
        logging.error(f"Error generating wallet: {e}", exc_info=True)
        raise

# ----- SUBSCRIPTION PAYMENT PROCESSING -----
def process_subscription_payment(user_id, plan):
    subscription_cost = SUBSCRIPTION_PRICING.get(plan, 0)
    wallet = user_wallets.get(user_id)
    if not wallet:
        return {"status": "error", "message": "No wallet found. Please create one first."}
    current_balance = get_wallet_balance(wallet["public"])
    if current_balance < subscription_cost:
        return {"status": "error", "message": f"Insufficient balance. Current balance: {current_balance:.4f} SOL"}
    result = transfer_sol(wallet, SUBSCRIPTION_WALLET["address"], subscription_cost)
    if result["status"] != "success":
        return {"status": "error", "message": f"Transfer failed: {result['message']}"}
    SUBSCRIPTION_WALLET["balance"] = get_wallet_balance(SUBSCRIPTION_WALLET["address"])
    now = datetime.utcnow()
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
        "tx_signature": result.get("signature")
    }
    return {"status": "success", "message": "Subscription payment processed successfully."}

# ----- PUMPFUN INTEGRATION -----
def create_coin_via_pumpfun(coin_data):
    """
    Uploads the coin’s metadata to Pump.fun (via IPFS),
    then calls the pumpportal.fun API to create the coin on-chain.
    """
    try:
        mint_keypair = SoldersKeypair()  # new mint keypair
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
        files = {'file': (os.path.basename(image_path), file_content, mime_type)}
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
            raise Exception("PUMPFUN_API_KEY environment variable not set. Please obtain a valid key from Pump.fun.")
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
        logging.error(f"Error in create_coin_via_pumpfun: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}

# ----- ASCII ART & MENU DESIGN -----
def print_header():
    # Custom ASCII art for PUMPbot using a simple, clear style
    ascii_art = f"""{Fore.LIGHTGREEN_EX}{Style.BRIGHT}
   ____   _    _   _   ___     ____  
  |  _ \ | |  | | | | / _ \   / ___| 
  | |_) || |  | | | || | | |  \___ \ 
  |  __/ | |__| | | || |_| |   ___) |
  |_|     \____/  |_| \___/   |____/ 
                                    
       P U M P b o t   T E A M
{Style.RESET_ALL}
"""
    print(ascii_art)

# ----- TERMINAL INTERFACE FUNCTIONS -----
def show_wallet_details():
    wallet = user_wallets.get(USER_ID)
    if not wallet:
        print(f"{Fore.RED}No wallet found. Please create one first.{Style.RESET_ALL}\n")
        return
    balance = get_wallet_balance(wallet["public"])
    wallet["balance"] = balance
    print(f"\n{Fore.LIGHTGREEN_EX}{Style.BRIGHT}=== Wallet Details ==={Style.RESET_ALL}")
    print(f"{Fore.CYAN}Public Key:{Style.RESET_ALL} {wallet['public']}")
    print(f"{Fore.CYAN}Balance:{Style.RESET_ALL} {balance:.4f} SOL")
    if "bundle" in wallet:
        bundle_total = sum(b.get("balance", 0) for b in wallet.get("bundle", []))
        print(f"{Fore.CYAN}Bundle Total:{Style.RESET_ALL} {bundle_total:.4f} SOL")
    print(f"{Fore.LIGHTGREEN_EX}{'='*25}{Style.RESET_ALL}\n")

def refresh_balance():
    wallet = user_wallets.get(USER_ID)
    if not wallet:
        print(f"{Fore.RED}No wallet found. Please create one first.{Style.RESET_ALL}\n")
        return
    new_balance = get_wallet_balance(wallet["public"])
    wallet["balance"] = new_balance
    print(f"{Fore.BLUE}Wallet balance refreshed:{Style.RESET_ALL} {new_balance:.4f} SOL\n")

def wallet_management_menu():
    while True:
        print(f"{Fore.MAGENTA}{Style.BRIGHT}=== Wallet Management ==={Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[1]{Style.RESET_ALL}{Fore.CYAN} Show Private Key{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[2]{Style.RESET_ALL}{Fore.CYAN} Show Seed Phrase{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[3]{Style.RESET_ALL}{Fore.CYAN} Import Wallet{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[4]{Style.RESET_ALL}{Fore.CYAN} Back to Main Menu{Style.RESET_ALL}")
        choice = input(f"{Fore.BLUE}--> {Style.RESET_ALL}").strip()
        if choice == "1":
            wallet = user_wallets.get(USER_ID)
            if not wallet:
                print(f"{Fore.RED}No wallet found. Please create one first.{Style.RESET_ALL}\n")
            else:
                print(f"{Fore.CYAN}Private Key:{Style.RESET_ALL} {wallet['private']}\n")
        elif choice == "2":
            wallet = user_wallets.get(USER_ID)
            if not wallet:
                print(f"{Fore.RED}No wallet found. Please create one first.{Style.RESET_ALL}\n")
            else:
                mnemonic = wallet.get("mnemonic")
                if mnemonic:
                    print(f"{Fore.CYAN}Seed Phrase:{Style.RESET_ALL} {mnemonic}\n")
                else:
                    print(f"{Fore.RED}No seed phrase available for an imported wallet.{Style.RESET_ALL}\n")
        elif choice == "3":
            priv_key = input(f"{Fore.BLUE}Enter your private key: {Style.RESET_ALL}").strip()
            try:
                private_key_bytes = base58.b58decode(priv_key)
                if len(private_key_bytes) != 64:
                    raise ValueError("Invalid private key length. Expected 64 bytes.")
                keypair = SoldersKeypair.from_bytes(private_key_bytes)
                public_key = str(keypair.pubkey())
                user_wallets[USER_ID] = {"public": public_key, "private": priv_key, "mnemonic": None, "balance": 0}
                print(f"{Fore.GREEN}Wallet imported successfully. New public key: {public_key}{Style.RESET_ALL}\n")
            except Exception as e:
                print(f"{Fore.RED}Error importing wallet: {str(e)}{Style.RESET_ALL}\n")
        elif choice == "4":
            break
        else:
            print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}\n")

def subscription_menu():
    wallet = user_wallets.get(USER_ID)
    if not wallet:
        print(f"{Fore.RED}No wallet found. Please create one first.{Style.RESET_ALL}\n")
        return
    user_wallet_balance = get_wallet_balance(wallet["public"])
    sub = user_subscriptions.get(USER_ID)
    if sub and sub.get("active"):
        expires_at = sub.get("expires_at")
        if expires_at:
            remaining = expires_at - datetime.utcnow()
            remaining_str = ("Expired" if remaining.total_seconds() < 0
                             else f"{remaining.days}d {remaining.seconds//3600}h {(remaining.seconds % 3600)//60}m remaining")
        else:
            remaining_str = "Lifetime"
        print(f"\n{Fore.LIGHTGREEN_EX}{Style.BRIGHT}=== Subscription Active ==={Style.RESET_ALL}")
        print(f"{Fore.CYAN}Plan:{Style.RESET_ALL} {sub.get('plan').capitalize()}")
        print(f"{Fore.CYAN}Expires:{Style.RESET_ALL} {remaining_str}")
        print(f"{Fore.CYAN}Transaction Signature:{Style.RESET_ALL} {sub.get('tx_signature')}")
        print(f"{Fore.LIGHTGREEN_EX}{'='*25}{Style.RESET_ALL}\n")
        input("Press Enter to return to the main menu...")
        return
    else:
        print(f"\n{Fore.MAGENTA}{Style.BRIGHT}=== Subscription Payment ==={Style.RESET_ALL}")
        print(f"{Fore.CYAN}Subscription Wallet Address:{Style.RESET_ALL} {SUBSCRIPTION_WALLET['address']}")
        print(f"{Fore.CYAN}Your Wallet Balance:{Style.RESET_ALL} {user_wallet_balance:.4f} SOL")
        print("Choose a subscription plan:")
        print(f"{Fore.MAGENTA}[1]{Style.RESET_ALL}{Fore.CYAN} Weekly (Cost: {SUBSCRIPTION_PRICING['weekly']:.4f} SOL){Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[2]{Style.RESET_ALL}{Fore.CYAN} Monthly (Cost: {SUBSCRIPTION_PRICING['monthly']:.4f} SOL){Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[3]{Style.RESET_ALL}{Fore.CYAN} Lifetime (Cost: {SUBSCRIPTION_PRICING['lifetime']:.4f} SOL){Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[4]{Style.RESET_ALL}{Fore.CYAN} Back to Main Menu{Style.RESET_ALL}")
        choice = input(f"{Fore.BLUE}--> {Style.RESET_ALL}").strip()
        if choice == "1":
            plan = "weekly"
        elif choice == "2":
            plan = "monthly"
        elif choice == "3":
            plan = "lifetime"
        elif choice == "4":
            return
        else:
            print(f"{Fore.RED}Invalid choice.{Style.RESET_ALL}\n")
            return
        confirm = input(f"Confirm payment for {plan} subscription (Cost: {SUBSCRIPTION_PRICING[plan]} SOL)? (Y/N): ").strip().lower()
        if confirm == "y":
            result = process_subscription_payment(USER_ID, plan)
            if result["status"] != "success":
                print(f"{Fore.RED}Error: {result['message']}{Style.RESET_ALL}\n")
            else:
                print(f"{Fore.GREEN}Subscription payment processed successfully!{Style.RESET_ALL}\n")
        else:
            print(f"{Fore.RED}Subscription cancelled.{Style.RESET_ALL}\n")

def launch_coin_flow():
    LAUNCH_STEPS = [
        ("name",       "Please enter the Coin Name:"),
        ("ticker",     "Please enter the Coin Ticker:"),
        ("description","Please enter the Coin Description:"),
        ("image",      "Provide the file path for the Logo Image (image or video):"),
        ("telegram",   "Please enter your Telegram Link:"),
        ("website",    "Please enter your Website Link (include https:// and .com):"),
        ("twitter",    "Please enter your Twitter/X Link (include https:// and .com):"),
        ("buy_amount", "Enter the Buy Amount in SOL (optional, press Enter to skip):")
    ]
    coin_data = {}
    print(f"\n{Fore.MAGENTA}{Style.BRIGHT}=== Launch Coin Flow ==={Style.RESET_ALL}")
    for field, prompt in LAUNCH_STEPS:
        while True:
            response = input(f"{Fore.BLUE}{prompt}{Style.RESET_ALL} ").strip()
            if field in ["telegram", "website", "twitter"]:
                if ".com" not in response.lower():
                    print(f"{Fore.RED}Invalid link. Please include a proper URL (e.g. https://example.com).{Style.RESET_ALL}")
                    continue
            if field == "image":
                if not os.path.exists(response):
                    print(f"{Fore.RED}File does not exist. Please provide a valid file path.{Style.RESET_ALL}")
                    continue
            if field == "buy_amount":
                if response == "":
                    coin_data[field] = 0
                    break
                try:
                    val = float(response)
                    wallet = user_wallets.get(USER_ID)
                    if wallet and get_wallet_balance(wallet["public"]) < val:
                        print(f"{Fore.RED}You don't have enough SOL in your wallet for that purchase. Try a lower amount.{Style.RESET_ALL}")
                        continue
                    coin_data[field] = val
                except Exception:
                    print(f"{Fore.RED}Invalid buy amount. Please enter a valid number in SOL.{Style.RESET_ALL}")
                    continue
                break
            else:
                coin_data[field] = response
                break
    print(f"\n{Fore.MAGENTA}{Style.BRIGHT}=== Review Your Coin Data ==={Style.RESET_ALL}")
    print(f"{Fore.CYAN}Name:{Style.RESET_ALL} {coin_data.get('name', '')}")
    print(f"{Fore.CYAN}Ticker:{Style.RESET_ALL} {coin_data.get('ticker', '')}")
    print(f"{Fore.CYAN}Description:{Style.RESET_ALL} {coin_data.get('description', '')}")
    print(f"{Fore.CYAN}Logo Image Path:{Style.RESET_ALL} {coin_data.get('image', '')}")
    print(f"{Fore.CYAN}Telegram Link:{Style.RESET_ALL} {coin_data.get('telegram', '')}")
    print(f"{Fore.CYAN}Website Link:{Style.RESET_ALL} {coin_data.get('website', '')}")
    print(f"{Fore.CYAN}Twitter/X Link:{Style.RESET_ALL} {coin_data.get('twitter', '')}")
    print(f"{Fore.CYAN}Buy Amount (SOL):{Style.RESET_ALL} {coin_data.get('buy_amount', 0)}")
    confirm = input(f"{Fore.BLUE}Are you sure you want to create this coin? (Y/N): {Style.RESET_ALL}").strip().lower()
    if confirm != "y":
        print(f"{Fore.RED}Coin launch cancelled.{Style.RESET_ALL}\n")
        return
    result = create_coin_via_pumpfun(coin_data)
    if result.get('status') != 'success':
        print(f"{Fore.RED}Failed to launch coin: {result.get('message', 'Unknown error')}{Style.RESET_ALL}\n")
        return
    tx_signature = result.get('signature')
    mint = result.get('mint')
    tx_link = f"https://solscan.io/tx/{tx_signature}"
    chart_url = f"https://pumpportal.fun/chart/{mint}"
    if USER_ID not in user_coins:
        user_coins[USER_ID] = []
    user_coins[USER_ID].append({
        "name": coin_data.get('name', 'Unnamed Coin'),
        "ticker": coin_data.get('ticker', ''),
        "description": coin_data.get('description', ''),
        "tx_link": tx_link,
        "chart_url": chart_url,
        "mint": mint,
        "dexscreener_url": "https://dexscreener.com/solana/"
    })
    print(f"\n{Fore.GREEN}{Style.BRIGHT}=== Coin Launched! ==={Style.RESET_ALL}")
    print(f"{Fore.CYAN}Name:{Style.RESET_ALL} {coin_data.get('name')}")
    print(f"{Fore.CYAN}Ticker:{Style.RESET_ALL} {coin_data.get('ticker')}")
    print(f"{Fore.CYAN}Description:{Style.RESET_ALL} {coin_data.get('description')}")
    print(f"{Fore.CYAN}Transaction Link:{Style.RESET_ALL} {tx_link}")
    print(f"{Fore.CYAN}Smart Contract Address (Mint):{Style.RESET_ALL} {mint}")
    print(f"{Fore.GREEN}Your coin is now live on the market.{Style.RESET_ALL}\n")

def show_launched_coins():
    coins = user_coins.get(USER_ID, [])
    if not coins:
        print(f"{Fore.RED}You haven't launched any coins yet.{Style.RESET_ALL}\n")
        return
    print(f"\n{Fore.MAGENTA}{Style.BRIGHT}=== Your Launched Coins ==={Style.RESET_ALL}")
    for idx, coin in enumerate(coins, start=1):
        print(f"{Fore.MAGENTA}{idx}.{Style.RESET_ALL}{Fore.CYAN} {coin.get('name', 'Unnamed Coin')} ({coin.get('ticker', '')}){Style.RESET_ALL}")
        print(f"   {Fore.CYAN}Smart Contract:{Style.RESET_ALL} {coin.get('mint', 'N/A')}")
        print(f"   {Fore.CYAN}Transaction:{Style.RESET_ALL} {coin.get('tx_link', '')}")
        print(f"   {Fore.CYAN}Chart:{Style.RESET_ALL} {coin.get('chart_url', '')}\n")
    input("Press Enter to return to the main menu...")

def main_menu():
    while True:
        print(f"{Fore.MAGENTA}[1]{Style.RESET_ALL}{Fore.CYAN} Show Wallet Details{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[2]{Style.RESET_ALL}{Fore.CYAN} Refresh Wallet Balance{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[3]{Style.RESET_ALL}{Fore.CYAN} Wallet Management{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[4]{Style.RESET_ALL}{Fore.CYAN} Subscription{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[5]{Style.RESET_ALL}{Fore.CYAN} Launch Coin{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[6]{Style.RESET_ALL}{Fore.CYAN} Show Launched Coins{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}[7]{Style.RESET_ALL}{Fore.CYAN} Exit{Style.RESET_ALL}")
        choice = input(f"{Fore.BLUE}--> {Style.RESET_ALL}").strip()
        if choice == "1":
            show_wallet_details()
        elif choice == "2":
            refresh_balance()
        elif choice == "3":
            wallet_management_menu()
        elif choice == "4":
            subscription_menu()
        elif choice == "5":
            launch_coin_flow()
        elif choice == "6":
            show_launched_coins()
        elif choice == "7":
            print(f"{Fore.RED}Exiting PUMPbot Terminal. Goodbye!{Style.RESET_ALL}")
            break
        else:
            print(f"{Fore.RED}Invalid choice. Please try again.{Style.RESET_ALL}\n")

# ----- MAIN FUNCTION -----
def main():
    load_dotenv()
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO
    )
    print_header()
    if USER_ID not in user_wallets:
        print(f"{Fore.BLUE}No wallet found. Generating a new wallet...{Style.RESET_ALL}")
        mnemonic, public_key, private_key = generate_solana_wallet()
        user_wallets[USER_ID] = {"public": public_key, "private": private_key, "mnemonic": mnemonic, "balance": 0}
        print(f"\n{Fore.GREEN}{Style.BRIGHT}=== New Wallet Generated ==={Style.RESET_ALL}")
        print(f"{Fore.CYAN}Public Key:{Style.RESET_ALL} {public_key}")
        print(f"{Fore.CYAN}Private Key:{Style.RESET_ALL} {private_key}")
        print(f"{Fore.CYAN}Seed Phrase:{Style.RESET_ALL} {mnemonic}")
        print(f"{Fore.RED}Please save these details securely.{Style.RESET_ALL}\n")
    main_menu()

if __name__ == "__main__":
    main()
