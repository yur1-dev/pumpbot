import base58
from solana.keypair import Keypair
from mnemonic import Mnemonic
import logging

# Logger setup
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def generate_solana_wallet():
    """Generate a new Solana wallet with mnemonic and keypair"""
    try:
        # Create a new English mnemonic
        mnemo = Mnemonic("english")
        mnemonic_words = mnemo.generate()
        logger.info(f"Mnemonic: {mnemonic_words}")  # Debug print to verify mnemonic

        # Generate seed from mnemonic
        seed = mnemo.to_seed(mnemonic_words)
        logger.info(f"Seed: {seed.hex()}")  # Debug print to verify seed

        # Ensure the seed is exactly 32 bytes long for Solana (truncate if needed)
        seed = seed[:32]  # Truncate to the first 32 bytes

        # Generate keypair from the 32-byte seed
        keypair = Keypair.from_seed(seed)

        # Get public key
        public_key = str(keypair.public_key)
        logger.info(f"Public Key: {public_key}")  # Debug print to verify public key

        # Get private key as raw bytes
        private_key_bytes = bytes(keypair.secret())  # 64-byte private key
        logger.info(f"Private Key Bytes: {private_key_bytes.hex()}")  # Debug print to verify private key bytes

        # Base58 encode the private key to match the expected format for wallets
        private_key_base58 = base58.b58encode(private_key_bytes).decode()  # Base58-encoded private key
        logger.info(f"Private Key (Base58): {private_key_base58}")  # Debug print to verify Base58 private key

        return mnemonic_words, public_key, private_key_base58

    except Exception as e:
        logger.error(f"Error generating wallet: {str(e)}")
        raise

# Example Usage
mnemonic, public_key, private_key = generate_solana_wallet()
print("Mnemonic:", mnemonic)
print("Public Key:", public_key)
print("Private Key:", private_key)
