// create_real_launchlab_token.js - FULLY FIXED VERSION FOR LAUNCHLAB
// Updated to use initializeV2 from Raydium SDK V2 docs
// Fixed address validation
// Enhanced error handling
// Added mainnet platform ID from Raydium config (low fee tier)

const {
  Connection,
  Keypair,
  PublicKey,
  LAMPORTS_PER_SOL,
  SystemProgram,
  Transaction,
  sendAndConfirmTransaction,
} = require("@solana/web3.js");

const {
  createInitializeMintInstruction,
  createAssociatedTokenAccountInstruction,
  createMintToInstruction,
  getAssociatedTokenAddress,
  MINT_SIZE,
  TOKEN_PROGRAM_ID,
  NATIVE_MINT,
} = require("@solana/spl-token");

const fs = require("fs");
const BN = require("bn.js");
const Decimal = require("decimal.js");

// Import Raydium SDK
let Raydium, TxVersion, ENDPOINT, LAUNCHPAD_PROGRAM_ID, TOKEN_PROGRAM_ID_2022;

try {
  const sdk = require("@raydium-io/raydium-sdk-v2");
  Raydium = sdk.Raydium;
  TxVersion = sdk.TxVersion || { V0: "v0", LEGACY: "legacy" };
  ENDPOINT = sdk.ENDPOINT;
  LAUNCHPAD_PROGRAM_ID = sdk.LAUNCHPAD_PROGRAM_ID;
  TOKEN_PROGRAM_ID_2022 = sdk.TOKEN_2022_PROGRAM_ID;

  console.log("✅ SDK imported successfully");
} catch (error) {
  console.error("❌ SDK import failed:", error.message);
  process.exit(1);
}

// Fast RPC endpoints
const RPC_ENDPOINTS = [
  "https://api.mainnet-beta.solana.com",
  "https://rpc.ankr.com/solana",
  "https://solana-api.projectserum.com",
];

// Mainnet platform ID (from https://api-v3.raydium.io/main/cpmm-config - low fee tier)
const MAINNET_PLATFORM_ID = new PublicKey(
  "D4FPEruKEHrG5TenZ2mpDGEfu1iUvTiqBxvpU8HLBvC2"
);

async function createTradableLockToken() {
  console.log("=== TRADEABLE LOCK TOKEN CREATION - FIXED FOR LAUNCHLAB ===");
  console.log("🔧 Uses initializeV2 from SDK docs");
  console.log("🔧 Fixed address validation");
  console.log("🔧 Enhanced error handling");

  try {
    // Load parameters
    const paramsFile = process.argv[2] || "lock_token_params.json";
    if (!fs.existsSync(paramsFile)) {
      throw new Error(`Parameters file not found: ${paramsFile}`);
    }

    let params = JSON.parse(fs.readFileSync(paramsFile, "utf8"));
    console.log(`Creating token: ${params.name} (${params.symbol})`);

    // Decode keypairs
    let mintKeypair = Keypair.fromSecretKey(
      Buffer.from(params.mintKeypair, "base64")
    );
    let creatorKeypair = Keypair.fromSecretKey(
      Buffer.from(params.creatorKeypair, "base64")
    );
    console.log("✅ Keypairs decoded");

    const mintAddress = mintKeypair.publicKey.toString();
    console.log(`🔍 Mint address: ${mintAddress}`);

    // Validate LOCK address
    if (!validateLockAddressFixed(mintAddress)) {
      throw new Error(`Invalid LOCK address: ${mintAddress}`);
    }
    console.log("✅ Address validated");

    // Get connection
    const connection = await getFastestConnection();
    console.log("✅ Connected to Solana");

    // Check balance
    const balance = await connection.getBalance(creatorKeypair.publicKey);
    const balanceSOL = balance / LAMPORTS_PER_SOL;
    console.log(`Creator balance: ${balanceSOL.toFixed(6)} SOL`);

    const requiredBalance = 0.01 + (params.initialBuyAmount || 0);
    if (balanceSOL < requiredBalance) {
      throw new Error(
        `Insufficient balance: need ${requiredBalance.toFixed(6)} SOL`
      );
    }

    // Initialize Raydium SDK
    const raydium = await Raydium.load({
      owner: creatorKeypair,
      connection,
      cluster: "mainnet-beta",
      disableFeatureCheck: true,
      disableLoadToken: false,
      blockhashCommitment: "finalized",
    });
    console.log("✅ Raydium SDK loaded");

    // Token config
    const supply = new BN(params.totalSupply || 1000000000);
    const decimals = params.decimals || 9;
    const initialBuyAmount = params.initialBuyAmount || 0;
    const hasInitialBuy = params.hasInitialBuy || initialBuyAmount > 0;

    // Calculated params
    const totalSellA = supply.mul(new BN(20)).div(new BN(100)); // 20% example
    const totalLockedAmount = new BN(0);
    const cliffPeriod = new BN(0);
    const unlockPeriod = new BN(0);
    const totalFundRaisingB = new Decimal(85);
    const amountB = new Decimal(initialBuyAmount);

    // Create LaunchLab token
    console.log("🚀 Creating LaunchLab token with initializeV2...");
    const { execute } = await raydium.launchpad.initializeV2({
      platformID: MAINNET_PLATFORM_ID,
      migrateType: params.migrateType || "cpmm",
      supply,
      totalSellA,
      totalLockedAmount,
      decimals,
      cliffPeriod,
      unlockPeriod,
      totalFundRaisingB,
      amountB,
      name: params.name,
      symbol: params.symbol,
      uri: params.uri,
      txVersion: TxVersion.V0,
    });

    const result = await execute({ sendAndConfirm: true });
    console.log("✅ Token created! TX: " + result.txId);

    // Result
    const tokenResult = {
      status: "success",
      signature: result.txId,
      mintAddress: mintAddress,
      poolId: result.poolId || "N/A",
      bondingCurveAddress: result.bondingCurveAddress || "N/A",
      initialBuySignature: result.initialBuySignature || null,
      totalSupply: params.totalSupply,
      fundingTarget: 85,
      raydiumUrl: `https://raydium.io/swap/?inputCurrency=sol&outputCurrency=${mintAddress}`,
      solscanUrl: `https://solscan.io/token/${mintAddress}`,
    };

    console.log(JSON.stringify(tokenResult));
  } catch (error) {
    const errorResult = {
      status: "error",
      message: error.message,
      technical_error: error.stack,
    };
    console.log(JSON.stringify(errorResult));
    process.exit(1);
  }
}

// FIXED: Address validation
function validateLockAddressFixed(address) {
  if (
    !address ||
    typeof address !== "string" ||
    address.length < 32 ||
    address.length > 44
  ) {
    return false;
  }
  const upper = address.toUpperCase();
  return upper.endsWith("LOCK") || upper.endsWith("LCK");
}

// Get fastest connection
async function getFastestConnection() {
  for (const endpoint of RPC_ENDPOINTS) {
    try {
      const connection = new Connection(endpoint, "confirmed");
      await connection.getVersion();
      return connection;
    } catch {}
  }
  throw new Error("No RPC available");
}

if (require.main === module) {
  createTradableLockToken();
}
