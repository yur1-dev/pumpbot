// create_raydium_token_correct.js - Using Official Raydium LaunchLab SDK
const {
  Connection,
  Keypair,
  PublicKey,
  Transaction,
  sendAndConfirmTransaction,
  SystemProgram,
  LAMPORTS_PER_SOL,
} = require("@solana/web3.js");
const {
  TOKEN_PROGRAM_ID,
  createInitializeMintInstruction,
  createAssociatedTokenAccountInstruction,
  createMintToInstruction,
  getAssociatedTokenAddress,
  MINT_SIZE,
  getMinimumBalanceForRentExemptMint,
  NATIVE_MINT,
} = require("@solana/spl-token");
const {
  TxVersion,
  LAUNCHPAD_PROGRAM,
  getPdaLaunchpadPoolId,
  Curve,
  PlatformConfig,
  printSimulate,
} = require("@raydium-io/raydium-sdk-v2");
const { initSdk } = require("./config"); // You'll need to create this config file
const fs = require("fs");
const BN = require("bn.js");
const Decimal = require("decimal.js");

// RPC endpoints for reliability
const RPC_ENDPOINTS = [
  "https://api.mainnet-beta.solana.com",
  "https://rpc.ankr.com/solana",
  "https://solana-api.projectserum.com",
];

// Raydium LaunchLab Program ID (mainnet)
const LAUNCHPAD_PROGRAM_ID = new PublicKey(
  "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"
);

async function getConnection() {
  for (const endpoint of RPC_ENDPOINTS) {
    try {
      const connection = new Connection(endpoint, "confirmed");
      await connection.getVersion();
      console.log(`Using RPC endpoint: ${endpoint}`);
      return connection;
    } catch (error) {
      console.log(`Failed to connect to ${endpoint}, trying next...`);
      continue;
    }
  }
  throw new Error("All RPC endpoints failed");
}

async function checkAccountBalance(connection, publicKey, minRequired = 0.01) {
  try {
    const balance = await connection.getBalance(new PublicKey(publicKey));
    const balanceSOL = balance / LAMPORTS_PER_SOL;
    console.log(`Account ${publicKey}: ${balanceSOL.toFixed(6)} SOL`);

    if (balanceSOL < minRequired) {
      throw new Error(
        `Insufficient balance. Required: ${minRequired} SOL, Current: ${balanceSOL.toFixed(
          6
        )} SOL`
      );
    }

    return balanceSOL;
  } catch (error) {
    if (error.message.includes("could not find account")) {
      throw new Error(
        `Account ${publicKey} not found. Please fund this wallet with at least ${minRequired} SOL`
      );
    }
    throw error;
  }
}

async function initializeRaydiumSDK(connection, owner) {
  console.log("Initializing Raydium SDK...");

  try {
    // Initialize SDK using the proper method
    const raydium = await initSdk({
      connection,
      owner,
      cluster: "mainnet",
      programIds: {
        LAUNCHPAD: LAUNCHPAD_PROGRAM_ID,
      },
    });

    console.log("Raydium SDK initialized successfully");
    return raydium;
  } catch (error) {
    console.error("Failed to initialize Raydium SDK:", error);
    throw error;
  }
}

async function createTokenMint(
  connection,
  mintKeypair,
  creatorKeypair,
  decimals
) {
  console.log("Creating token mint account...");

  const mintLamports = await getMinimumBalanceForRentExemptMint(connection);
  console.log(`Mint rent exemption: ${mintLamports / LAMPORTS_PER_SOL} SOL`);

  // Create mint account
  const createMintAccountInstruction = SystemProgram.createAccount({
    fromPubkey: creatorKeypair.publicKey,
    newAccountPubkey: mintKeypair.publicKey,
    lamports: mintLamports,
    space: MINT_SIZE,
    programId: TOKEN_PROGRAM_ID,
  });

  // Initialize mint
  const initializeMintInstruction = createInitializeMintInstruction(
    mintKeypair.publicKey,
    decimals,
    creatorKeypair.publicKey,
    creatorKeypair.publicKey,
    TOKEN_PROGRAM_ID
  );

  const transaction = new Transaction().add(
    createMintAccountInstruction,
    initializeMintInstruction
  );

  const signature = await sendAndConfirmTransaction(
    connection,
    transaction,
    [creatorKeypair, mintKeypair],
    {
      commitment: "confirmed",
      maxRetries: 3,
    }
  );

  console.log(`Token mint created: ${signature}`);
  return signature;
}

async function createLockToken(params) {
  let connection, raydium;

  try {
    console.log(
      "Starting LOCK token creation with official Raydium LaunchLab SDK..."
    );

    // Get reliable connection
    connection = await getConnection();

    // Parse parameters
    const {
      mintKeypair: mintKeypairB64,
      creatorKeypair: creatorKeypairB64,
      name,
      symbol,
      decimals,
      totalSupply,
      uri,
      initialBuyAmount = 0,
    } = params;

    // Convert base64 to keypairs
    const mintKeypair = Keypair.fromSecretKey(
      Buffer.from(mintKeypairB64, "base64")
    );
    const creatorKeypair = Keypair.fromSecretKey(
      Buffer.from(creatorKeypairB64, "base64")
    );

    const mintAddress = mintKeypair.publicKey.toString();
    console.log(`Creating token: ${name} (${symbol})`);
    console.log(`Mint address: ${mintAddress}`);
    console.log(`Creator address: ${creatorKeypair.publicKey.toString()}`);

    // CRITICAL: Verify this address ends with "lock"
    if (!mintAddress.toLowerCase().endsWith("lock")) {
      throw new Error(
        `CRITICAL ERROR: Generated address ${mintAddress} does not end with 'lock'`
      );
    }

    console.log(`✓ VERIFIED: Address ends with 'lock': ${mintAddress}`);

    // Check creator wallet balance
    const minRequiredSOL = initialBuyAmount > 0 ? initialBuyAmount + 0.1 : 0.1; // Higher minimum for LaunchLab
    await checkAccountBalance(
      connection,
      creatorKeypair.publicKey.toString(),
      minRequiredSOL
    );

    // Create the token mint first
    await createTokenMint(connection, mintKeypair, creatorKeypair, decimals);

    // Wait for confirmation
    console.log("Waiting for mint confirmation...");
    await new Promise((resolve) => setTimeout(resolve, 3000));

    // Initialize Raydium SDK
    raydium = await initializeRaydiumSDK(connection, creatorKeypair);

    // Calculate LaunchLab parameters
    const totalSupplyBN = new BN(totalSupply);
    const totalSellAmount = totalSupplyBN.mul(new BN(80)).div(new BN(100)); // 80% for sale
    const totalFundRaising = new BN(85).mul(new BN(LAMPORTS_PER_SOL)); // 85 SOL target

    console.log("Creating Raydium LaunchLab bonding curve...");
    console.log(`Total Supply: ${totalSupply}`);
    console.log(`Total Sell Amount: ${totalSellAmount.toString()}`);
    console.log(
      `Total Fund Raising: ${totalFundRaising.toString()} lamports (85 SOL)`
    );

    // Create LaunchLab bonding curve using the correct method
    const createLaunchpadParams = {
      baseMint: mintKeypair.publicKey,
      quoteMint: NATIVE_MINT, // SOL
      supply: totalSupplyBN,
      totalSellA: totalSellAmount,
      totalFundRaisingB: totalFundRaising,
      decimals: decimals,
      // Optional parameters
      totalLockedAmount: new BN(0), // No locked tokens
      cliffPeriod: new BN(0),
      unlockPeriod: new BN(0),
      migrateType: "cpmm", // Use CPMM for better liquidity
      // Use existing platform or create new one
      platformId: null, // Will use default platform
      txVersion: TxVersion.V0,
    };

    // Get create launchpad instruction
    const { execute, extInfo } = await raydium.launchpad.createLaunchpad(
      createLaunchpadParams
    );

    console.log("Executing LaunchLab creation transaction...");
    const createResult = await execute();

    console.log(`LaunchLab bonding curve created successfully!`);
    console.log(`Transaction: ${createResult.txId}`);
    console.log(`Pool ID: ${extInfo.poolId}`);

    // Handle initial buy if specified
    let buyTxSignature = null;
    if (initialBuyAmount > 0) {
      console.log(`Executing initial buy: ${initialBuyAmount} SOL`);

      try {
        // Wait a bit for the pool to be ready
        await new Promise((resolve) => setTimeout(resolve, 5000));

        const buyAmount = new BN(initialBuyAmount * LAMPORTS_PER_SOL);
        const minTokensOut = new BN(1); // Minimum tokens to receive

        const { execute: buyExecute } = await raydium.launchpad.buy({
          poolId: extInfo.poolId,
          amountIn: buyAmount,
          amountOut: minTokensOut,
          fixedSide: "in", // Fixed input amount
          txVersion: TxVersion.V0,
        });

        const buyResult = await buyExecute();
        buyTxSignature = buyResult.txId;
        console.log(`Initial buy executed: ${buyTxSignature}`);
      } catch (buyError) {
        console.log(`Initial buy failed (non-critical): ${buyError.message}`);
      }
    }

    // Final verification that address ends with "lock"
    console.log(
      `FINAL VERIFICATION: Token address ${mintAddress} ends with: ${mintAddress.slice(
        -4
      )}`
    );

    // Return success response
    const response = {
      status: "success",
      signature: createResult.txId,
      mintAddress: mintAddress,
      poolId: extInfo.poolId.toString(),
      poolAddress: extInfo.poolId.toString(),
      bondingCurveAddress: extInfo.poolId.toString(),
      initialBuySignature: buyTxSignature,
      verifiedLockSuffix: mintAddress.toLowerCase().endsWith("lock"),
      totalSupply: totalSupply,
      fundingTarget: 85, // 85 SOL
    };

    console.log("LOCK token creation completed successfully!");
    console.log(JSON.stringify(response));

    return response;
  } catch (error) {
    console.error("Error creating LOCK token:", error);

    // Enhanced error handling
    let errorMessage = error.message;
    let userFriendlyMessage = errorMessage;

    if (
      errorMessage.includes(
        "Attempt to debit an account but found no record of a prior credit"
      )
    ) {
      userFriendlyMessage =
        "Creator wallet needs more SOL. Please add at least 0.1 SOL to your wallet and try again.";
    } else if (errorMessage.includes("insufficient funds")) {
      userFriendlyMessage =
        "Insufficient SOL balance. Please add more SOL to your wallet.";
    } else if (errorMessage.includes("Account not found")) {
      userFriendlyMessage =
        "Wallet account not found. Please fund your wallet with at least 0.1 SOL.";
    } else if (errorMessage.includes("blockhash")) {
      userFriendlyMessage = "Network congestion. Please try again in a moment.";
    } else if (errorMessage.includes("LOCK")) {
      userFriendlyMessage =
        "Vanity address generation failed - address doesn't end with 'lock'.";
    }

    const errorResult = {
      status: "error",
      message: userFriendlyMessage,
      technical_error: errorMessage,
    };

    console.error(JSON.stringify(errorResult));
    throw error;
  }
}

// Main execution
async function main() {
  try {
    // Read parameters from file
    const paramsFile = process.argv[2] || "token_params.json";

    if (!fs.existsSync(paramsFile)) {
      throw new Error(`Parameters file not found: ${paramsFile}`);
    }

    const params = JSON.parse(fs.readFileSync(paramsFile, "utf8"));

    // Verify the mint keypair generates an address ending with "lock"
    const mintKeypair = Keypair.fromSecretKey(
      Buffer.from(params.mintKeypair, "base64")
    );
    const mintAddress = mintKeypair.publicKey.toString();

    console.log(`Verifying LOCK address: ${mintAddress}`);
    console.log(
      `Ends with 'lock': ${mintAddress.toLowerCase().endsWith("lock")}`
    );

    if (!mintAddress.toLowerCase().endsWith("lock")) {
      throw new Error(
        `FATAL: Provided keypair does not generate LOCK address. Got: ${mintAddress}`
      );
    }

    const result = await createLockToken(params);

    // Output final result
    console.log(JSON.stringify(result));
    process.exit(0);
  } catch (error) {
    console.error("Main error:", error.message);

    const errorResult = {
      status: "error",
      message: error.message,
    };

    console.error(JSON.stringify(errorResult));
    process.exit(1);
  }
}

if (require.main === module) {
  main();
}

module.exports = { createLockToken };
