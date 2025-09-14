// create_simple_lock_token.js - Simplified LOCK Token Creator
const {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
  sendAndConfirmTransaction,
  LAMPORTS_PER_SOL,
} = require("@solana/web3.js");
const {
  createMint,
  createAccount,
  mintTo,
  TOKEN_PROGRAM_ID,
} = require("@solana/spl-token");
const fs = require("fs");

// Configuration
const RPC_ENDPOINT = "https://api.mainnet-beta.solana.com";

async function createSimpleLockToken() {
  console.log("=== CREATING SIMPLE LOCK TOKEN ===");

  try {
    // Read parameters
    const paramsFile = process.argv[2] || "token_params.json";
    if (!fs.existsSync(paramsFile)) {
      throw new Error(`Parameters file not found: ${paramsFile}`);
    }

    const params = JSON.parse(fs.readFileSync(paramsFile, "utf8"));
    console.log("Parameters loaded successfully");

    // Initialize connection
    const connection = new Connection(RPC_ENDPOINT, "confirmed");
    console.log("Connected to Solana RPC");

    // Convert keypairs
    const mintKeypair = Keypair.fromSecretKey(
      Buffer.from(params.mintKeypair, "base64")
    );
    const creatorKeypair = Keypair.fromSecretKey(
      Buffer.from(params.creatorKeypair, "base64")
    );

    const mintAddress = mintKeypair.publicKey.toString();
    console.log(`Mint address: ${mintAddress}`);

    // VERIFY LOCK SUFFIX
    const hasLockSuffix =
      mintAddress.toUpperCase().endsWith("LOCK") ||
      mintAddress.toUpperCase().endsWith("LCK");

    if (!hasLockSuffix) {
      console.warn(`WARNING: Address doesn't end with LOCK - ${mintAddress}`);
    } else {
      console.log(`VERIFIED: LOCK address confirmed - ${mintAddress}`);
    }

    // Check balance
    const balance = await connection.getBalance(creatorKeypair.publicKey);
    const balanceSOL = balance / LAMPORTS_PER_SOL;
    console.log(`Creator balance: ${balanceSOL.toFixed(6)} SOL`);

    if (balanceSOL < 0.01) {
      throw new Error(`Insufficient balance: ${balanceSOL.toFixed(6)} SOL`);
    }

    // Create the mint (this is the LOCK token creation)
    console.log("Creating LOCK token mint...");
    const mint = await createMint(
      connection,
      creatorKeypair, // Payer
      creatorKeypair.publicKey, // Mint authority
      null, // Freeze authority (none)
      params.decimals || 9, // Decimals
      mintKeypair // Use the LOCK address keypair
    );

    console.log(`LOCK Token mint created: ${mint.toString()}`);

    // Create token account for creator
    console.log("Creating token account...");
    const tokenAccount = await createAccount(
      connection,
      creatorKeypair,
      mint,
      creatorKeypair.publicKey
    );

    console.log(`Token account created: ${tokenAccount.toString()}`);

    // Mint initial supply
    console.log("Minting initial supply...");
    const totalSupply = params.totalSupply || 1000000000;
    const mintAmount = totalSupply * Math.pow(10, params.decimals || 9);

    const mintSignature = await mintTo(
      connection,
      creatorKeypair,
      mint,
      tokenAccount,
      creatorKeypair.publicKey,
      mintAmount
    );

    console.log(`Minted ${totalSupply.toLocaleString()} tokens`);
    console.log(`Mint signature: ${mintSignature}`);

    // Success result
    const result = {
      status: "success",
      signature: mintSignature,
      mintAddress: mint.toString(),
      poolId: null,
      poolAddress: null,
      bondingCurveAddress: null,
      initialBuySignature: null,
      verifiedLockSuffix: hasLockSuffix,
      fundingTarget: 0,
      totalSupply: totalSupply,
      decimals: params.decimals || 9,
      name: params.name,
      symbol: params.symbol,
      uri: params.uri,
      platform: "Simple SPL Token",
      createdAt: new Date().toISOString(),
    };

    console.log("=== LOCK TOKEN CREATED SUCCESSFULLY ===");
    console.log(JSON.stringify(result, null, 2));

    return result;
  } catch (error) {
    console.error("LOCK token creation failed:", error.message);

    const errorResult = {
      status: "error",
      message: error.message,
      technical_error: error.stack,
      timestamp: new Date().toISOString(),
    };

    console.error(JSON.stringify(errorResult, null, 2));
    process.exit(1);
  }
}

// Execute
if (require.main === module) {
  createSimpleLockToken()
    .then(() => {
      console.log("Script completed successfully");
      process.exit(0);
    })
    .catch((error) => {
      console.error("Script failed:", error.message);
      process.exit(1);
    });
}
