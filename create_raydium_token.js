// create_raydium_token_correct.js - FIXED VERSION respecting your original structure
const {
  Connection,
  Keypair,
  PublicKey,
  LAMPORTS_PER_SOL,
} = require("@solana/web3.js");
const { NATIVE_MINT, TOKEN_PROGRAM_ID } = require("@solana/spl-token");
const {
  TxVersion,
  LAUNCHPAD_PROGRAM,
  Raydium, // Use Raydium directly
} = require("@raydium-io/raydium-sdk-v2");
const {
  loadRaydiumSdk,
  createConnection,
  LAUNCHLAB_CONFIG,
} = require("./config");
const fs = require("fs");
const BN = require("bn.js");
const Decimal = require("decimal.js");

async function createLockToken() {
  let connection, raydium;

  try {
    console.log("=== CREATING LOCK TOKEN WITH LAUNCHLAB ===");

    // Read parameters
    if (!fs.existsSync("token_params.json")) {
      throw new Error("token_params.json not found");
    }

    const params = JSON.parse(fs.readFileSync("token_params.json", "utf8"));
    console.log("Parameters loaded successfully");

    // FIXED: Use your config.js functions
    connection = await createConnection(
      params.rpc_url || "https://api.mainnet-beta.solana.com"
    );

    // Convert keypairs from your format
    const mintKeypair = Keypair.fromSecretKey(
      Buffer.from(params.mintKeypair || params.mint_keypair_bytes, "base64")
    );
    const creatorKeypair = Keypair.fromSecretKey(
      Buffer.from(
        params.creatorKeypair || params.creator_keypair_bytes,
        "base64"
      )
    );

    const mintAddress = mintKeypair.publicKey.toString();
    console.log(`Mint address: ${mintAddress}`);
    console.log(`Creator: ${creatorKeypair.publicKey.toString()}`);

    // CRITICAL: Verify address ends with "lock" (case-insensitive)
    if (
      !mintAddress.toLowerCase().endsWith("lock") &&
      !mintAddress.toLowerCase().endsWith("lck")
    ) {
      console.warn(
        `WARNING: Address ${mintAddress} does not end with 'lock' or 'lck' - continuing anyway`
      );
    } else {
      console.log("✓ VERIFIED: Address ends with lock/lck suffix");
    }

    // Check creator balance with your requirements (0.005 + initial buy)
    const balance = await connection.getBalance(creatorKeypair.publicKey);
    const balanceSOL = balance / LAMPORTS_PER_SOL;
    console.log(`Creator balance: ${balanceSOL.toFixed(6)} SOL`);

    // FIXED: Use your actual requirements (0.005 base cost)
    const minRequired = (params.initialBuyAmount || 0) + 0.005;
    if (balanceSOL < minRequired) {
      throw new Error(
        `Insufficient balance. Need ${minRequired.toFixed(
          6
        )} SOL, have ${balanceSOL.toFixed(6)} SOL`
      );
    }

    // FIXED: Use your config's loadRaydiumSdk function
    console.log("Initializing Raydium SDK...");
    raydium = await loadRaydiumSdk({
      connection,
      owner: creatorKeypair.publicKey,
      cluster: "mainnet-beta",
    });
    console.log("Raydium SDK initialized");

    // Prepare LaunchLab parameters using your config
    const totalSupplyBN = new BN(params.totalSupply || 1_000_000_000);
    const totalSellAmount = totalSupplyBN
      .mul(new BN(LAUNCHLAB_CONFIG.SELL_PERCENTAGE))
      .div(new BN(100));
    const totalFundRaising = new BN(LAUNCHLAB_CONFIG.FUNDING_TARGET_SOL).mul(
      new BN(LAMPORTS_PER_SOL)
    );

    console.log("LaunchLab Parameters:");
    console.log(`- Total Supply: ${totalSupplyBN.toString()}`);
    console.log(`- For Sale: ${totalSellAmount.toString()}`);
    console.log(`- Funding Target: ${LAUNCHLAB_CONFIG.FUNDING_TARGET_SOL} SOL`);

    // Create LaunchLab token with proper parameters
    console.log("Creating LaunchLab bonding curve...");

    const createParams = {
      baseMint: mintKeypair.publicKey, // Your LOCK address
      quoteMint: NATIVE_MINT,
      supply: totalSupplyBN,
      totalSellA: totalSellAmount,
      totalFundRaisingB: totalFundRaising,
      decimals: params.decimals || 9,
      totalLockedAmount: new BN(0),
      cliffPeriod: new BN(0),
      unlockPeriod: new BN(0),
      migrateType: LAUNCHLAB_CONFIG.MIGRATION_TYPE,
      txVersion: LAUNCHLAB_CONFIG.TX_VERSION,
    };

    console.log("Create params prepared");

    // Execute LaunchLab creation
    const { execute, extInfo } = await raydium.launchpad.createLaunchpad(
      createParams
    );
    console.log("Executing transaction...");

    const result = await execute();
    console.log(`Transaction successful: ${result.txId}`);

    // Get pool info
    const poolId = extInfo ? extInfo.poolId : "Unknown";
    console.log(`Pool ID: ${poolId}`);

    // Handle initial buy if specified
    let buyTxSignature = null;
    const initialBuy = params.initialBuyAmount || 0;

    if (initialBuy > 0) {
      console.log(`Executing initial buy: ${initialBuy} SOL`);

      try {
        await new Promise((resolve) => setTimeout(resolve, 2000)); // Wait for pool

        const buyAmount = new BN(initialBuy * LAMPORTS_PER_SOL);
        const { execute: buyExecute } = await raydium.launchpad.buy({
          poolId: poolId,
          amountIn: buyAmount,
          amountOut: new BN(1), // Minimum tokens out
          fixedSide: "in",
          txVersion: LAUNCHLAB_CONFIG.TX_VERSION,
        });

        const buyResult = await buyExecute();
        buyTxSignature = buyResult.txId;
        console.log(`Initial buy completed: ${buyTxSignature}`);
      } catch (buyError) {
        console.log(`Initial buy failed (non-critical): ${buyError.message}`);
      }
    }

    // Final verification
    const finalVerification =
      mintAddress.toLowerCase().endsWith("lock") ||
      mintAddress.toLowerCase().endsWith("lck");
    console.log(`FINAL VERIFICATION: Ends with lock/lck: ${finalVerification}`);

    // Success response in your expected format
    const response = {
      status: "success",
      signature: result.txId,
      mintAddress: mintAddress,
      poolId: poolId.toString(),
      poolAddress: poolId.toString(),
      bondingCurveAddress: poolId.toString(),
      initialBuySignature: buyTxSignature,
      verifiedLockSuffix: finalVerification,
      totalSupply: params.totalSupply,
      fundingTarget: LAUNCHLAB_CONFIG.FUNDING_TARGET_SOL,
    };

    console.log("=== LOCK TOKEN CREATED SUCCESSFULLY ===");
    console.log(JSON.stringify(response, null, 2));

    return response;
  } catch (error) {
    console.error("LOCK token creation failed:", error.message);

    // Enhanced error messages matching your format
    let userFriendlyMessage = error.message;

    if (error.message.includes("Attempt to debit an account")) {
      userFriendlyMessage =
        "Wallet needs more SOL. Add at least 0.01 SOL and try again.";
    } else if (error.message.includes("insufficient funds")) {
      userFriendlyMessage = "Insufficient SOL balance for LaunchLab creation.";
    } else if (error.message.includes("Account not found")) {
      userFriendlyMessage = "Wallet not found on-chain. Fund with SOL first.";
    } else if (
      error.message.includes("SDK") ||
      error.message.includes("load")
    ) {
      userFriendlyMessage =
        "Raydium SDK initialization failed. Check dependencies.";
    } else if (error.message.includes("config not found")) {
      userFriendlyMessage =
        "LaunchLab configuration missing. This may be a platform setup issue.";
    }

    const errorResponse = {
      status: "error",
      message: userFriendlyMessage,
      technical_error: error.message,
    };

    console.error(JSON.stringify(errorResponse, null, 2));
    process.exit(1);
  }
}

// Execute
if (require.main === module) {
  createLockToken()
    .then(() => {
      console.log("Script completed successfully");
      process.exit(0);
    })
    .catch((error) => {
      console.error("Script failed:", error.message);
      process.exit(1);
    });
}

module.exports = { createLockToken };
