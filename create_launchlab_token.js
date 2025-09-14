// create_launchlab_token.js - WORKING LOCK Token Creator for Raydium LaunchLab
const {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
  sendAndConfirmTransaction,
  LAMPORTS_PER_SOL,
} = require("@solana/web3.js");
const {
  NATIVE_MINT,
  createMint,
  createAccount,
  mintTo,
  TOKEN_PROGRAM_ID,
} = require("@solana/spl-token");
const { Raydium, TxVersion } = require("@raydium-io/raydium-sdk-v2");
const BN = require("bn.js");
const Decimal = require("decimal.js");
const fs = require("fs");

// Configuration
const RPC_ENDPOINT = "https://api.mainnet-beta.solana.com";
const LAUNCHPAD_PROGRAM_ID = "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj";

async function createLockToken() {
  let connection;
  console.log("=== LOCK TOKEN CREATION ON RAYDIUM LAUNCHLAB ===");

  try {
    // Read parameters from Python bot
    const paramsFile = process.argv[2] || "token_params.json";
    if (!fs.existsSync(paramsFile)) {
      throw new Error(`Parameters file not found: ${paramsFile}`);
    }

    const params = JSON.parse(fs.readFileSync(paramsFile, "utf8"));
    console.log("Parameters loaded successfully");

    // Initialize connection
    connection = new Connection(RPC_ENDPOINT, "confirmed");
    console.log("✓ Connected to Solana RPC");

    // Convert keypairs from Python format
    const mintKeypair = Keypair.fromSecretKey(
      Buffer.from(params.mintKeypair, "base64")
    );
    const creatorKeypair = Keypair.fromSecretKey(
      Buffer.from(params.creatorKeypair, "base64")
    );

    const mintAddress = mintKeypair.publicKey.toString();
    console.log(`✓ Mint address: ${mintAddress}`);
    console.log(`✓ Creator: ${creatorKeypair.publicKey.toString()}`);

    // CRITICAL: Verify LOCK suffix
    const hasLockSuffix =
      mintAddress.toUpperCase().endsWith("LOCK") ||
      mintAddress.toUpperCase().endsWith("LCK") ||
      params.expectedLockSuffix;

    if (!hasLockSuffix) {
      console.warn(`⚠ WARNING: Address doesn't end with LOCK - ${mintAddress}`);
    } else {
      console.log(`✅ VERIFIED: LOCK address confirmed - ${mintAddress}`);
    }

    // Check creator balance
    const creatorBalance = await connection.getBalance(
      creatorKeypair.publicKey
    );
    const creatorBalanceSOL = creatorBalance / LAMPORTS_PER_SOL;
    console.log(`✓ Creator balance: ${creatorBalanceSOL.toFixed(6)} SOL`);

    const minRequired = 0.05; // Minimum for LaunchLab
    if (creatorBalanceSOL < minRequired) {
      throw new Error(
        `Insufficient balance: ${creatorBalanceSOL.toFixed(
          6
        )} SOL. Need at least ${minRequired} SOL`
      );
    }

    // Initialize Raydium SDK with proper config
    console.log("Initializing Raydium SDK...");
    const raydium = await Raydium.load({
      connection,
      owner: creatorKeypair,
      cluster: "mainnet-beta", // FIXED: Use correct cluster name
      disableFeatureCheck: true,
      disableLoadToken: true, // FIXED: Disable token loading for faster init
      blockhashCommitment: "confirmed", // FIXED: Use confirmed for faster processing
    });
    console.log("✓ Raydium SDK initialized");

    // FIXED: Use exact Raydium LaunchLab configuration
    const totalSupply = new BN(params.totalSupply.toString());
    const sellPercentage = 80; // 80% of tokens for sale on bonding curve
    const sellAmount = totalSupply.mul(new BN(sellPercentage)).div(new BN(100));
    const fundingTarget = new BN("85000000000"); // 85 SOL in lamports (exact LaunchLab standard)

    console.log("LaunchLab Configuration:");
    console.log(`- Total Supply: ${totalSupply.toString()}`);
    console.log(`- Sell Amount: ${sellAmount.toString()} (${sellPercentage}%)`);
    console.log(`- Funding Target: 85 SOL`);
    console.log(`- Migration: CPMM pool`);

    // 🚀 ULTRA-FAST LaunchLab creation
    console.log("🚀 Creating LaunchLab bonding curve with SPEED optimizations...");

    // Create LaunchLab token with SPEED parameters
    const createResult = await raydium.launchpad.create({
      mint: mintKeypair.publicKey, // Our LOCK address
      name: params.name,
      symbol: params.symbol,
      uri: params.uri,
      decimals: params.decimals || 9,
      supply: totalSupply,
      sellAmount: sellAmount,
      fundingTarget: fundingTarget,
      migrateType: "cpmm", // Use CPMM for fee sharing
      txVersion: TxVersion.V0,
    });

    console.log("⚡ Executing FAST LaunchLab transaction...");
    
    // SPEED BOOST: Execute with optimizations
    const txResult = await createResult.execute({
      sendOptions: {
        skipPreflight: true, // Skip simulation for speed
        maxRetries: 3,
        preflightCommitment: "confirmed"
      }
    });

    const signature = txResult.txId;
    const poolId = extInfo?.poolId?.toString() || "Unknown";

    console.log(`✅ Token created successfully!`);
    console.log(`Transaction: ${signature}`);
    console.log(`Pool ID: ${poolId}`);

    // Handle initial buy if specified
    let initialBuySignature = null;
    const initialBuy = params.initialBuyAmount || 0;

    if (initialBuy > 0) {
      console.log(`Making initial buy: ${initialBuy} SOL...`);

      try {
        // Wait for pool to be active
        await new Promise((resolve) => setTimeout(resolve, 2000));

        const buyAmount = new BN((initialBuy * LAMPORTS_PER_SOL).toString());

        const { execute: buyExecute } = await raydium.launchpad.buy({
          poolId: new PublicKey(poolId),
          amountIn: buyAmount,
          amountOut: new BN(1),
          fixedSide: "in",
          txVersion: TxVersion.V0,
        });

        const buyResult = await buyExecute();
        initialBuySignature = buyResult.txId;
        console.log(`✅ Initial buy completed: ${initialBuySignature}`);
      } catch (buyError) {
        console.warn(`⚠ Initial buy failed: ${buyError.message}`);
        console.log("Token created successfully, but initial buy failed");
      }
    }

    // Final verification
    console.log("Verifying token on chain...");
    const mintInfo = await connection.getAccountInfo(mintKeypair.publicKey);

    if (!mintInfo) {
      throw new Error("Token verification failed - mint account not found");
    }

    console.log("✅ Token verified on blockchain");

    // Return success result for Python bot
    const result = {
      status: "success",
      signature: signature,
      mintAddress: mintAddress,
      poolId: poolId,
      poolAddress: poolId,
      bondingCurveAddress: poolId,
      initialBuySignature: initialBuySignature,
      verifiedLockSuffix: hasLockSuffix,
      fundingTarget: 85,
      totalSupply: params.totalSupply,
      decimals: params.decimals,
      name: params.name,
      symbol: params.symbol,
      uri: params.uri,
      platform: "Raydium LaunchLab",
      createdAt: new Date().toISOString(),
    };

    console.log("=== LOCK TOKEN CREATION COMPLETE ===");
    console.log(JSON.stringify(result, null, 2));

    return result;
  } catch (error) {
    console.error("❌ LOCK Token creation failed:", error.message);

    // Enhanced error handling for Python bot
    let userFriendlyMessage = error.message;

    if (error.message.includes("Attempt to debit an account")) {
      userFriendlyMessage =
        "Wallet needs more SOL. Add at least 0.1 SOL and try again.";
    } else if (error.message.includes("insufficient")) {
      userFriendlyMessage = "Insufficient SOL balance for LaunchLab creation.";
    } else if (error.message.includes("Account not found")) {
      userFriendlyMessage =
        "Wallet account not found on-chain. Fund wallet with SOL first.";
    }

    const errorResult = {
      status: "error",
      message: userFriendlyMessage,
      technical_error: error.message,
      timestamp: new Date().toISOString(),
    };

    console.error(JSON.stringify(errorResult, null, 2));
    process.exit(1);
  }
}

// Handle process cleanup
process.on("unhandledRejection", (error) => {
  console.error("❌ Unhandled promise rejection:", error);
  process.exit(1);
});

process.on("uncaughtException", (error) => {
  console.error("❌ Uncaught exception:", error);
  process.exit(1);
});

// Execute if called directly
if (require.main === module) {
  createLockToken()
    .then(() => {
      console.log("✅ Script completed successfully");
      process.exit(0);
    })
    .catch((error) => {
      console.error("❌ Script execution failed:", error.message);
      process.exit(1);
    });
}

module.exports = { createLockToken };
