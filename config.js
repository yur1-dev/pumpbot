// config.js - FIXED Raydium SDK Configuration based on test results
const { Connection, PublicKey } = require("@solana/web3.js");
const { Raydium, TxVersion } = require("@raydium-io/raydium-sdk-v2");

// Program IDs for mainnet
const PROGRAM_IDS = {
  LAUNCHPAD: new PublicKey("LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"),
  // Add other program IDs as needed
};

// FIXED: Use Raydium.load() directly instead of non-existent initSdk
async function loadRaydiumSdk({
  connection,
  owner,
  cluster = "mainnet-beta", // Use correct cluster name
  programIds = PROGRAM_IDS,
}) {
  console.log(`Loading Raydium SDK for ${cluster}...`);

  try {
    const raydium = await Raydium.load({
      connection,
      owner,
      cluster,
      disableFeatureCheck: true, // Disable feature checks for compatibility
      disableLoadToken: false,
      blockhashCommitment: "confirmed",
    });

    console.log("Raydium SDK loaded successfully");
    return raydium;
  } catch (error) {
    console.error("Failed to load Raydium SDK:", error);
    throw error;
  }
}

// ULTRA-FAST RPC endpoints for maximum speed
const FAST_RPC_ENDPOINTS = [
  "https://solana-mainnet.g.alchemy.com/v2/demo", // Alchemy fast
  "https://api.mainnet-beta.solana.com", // Official
  "https://rpc.ankr.com/solana", // Ankr fast
  "https://solana-api.projectserum.com", // Serum
];

// Helper function to create fastest connection
async function createConnection(rpcUrl = null) {
  if (rpcUrl) {
    // Use provided RPC
    const connection = new Connection(rpcUrl, "confirmed");
    await connection.getVersion();
    console.log(`⚡ Fast connection: ${rpcUrl}`);
    return connection;
  }

  // Auto-select fastest RPC endpoint
  console.log("🚀 Finding fastest RPC endpoint...");
  
  const connectionPromises = FAST_RPC_ENDPOINTS.map(async (endpoint) => {
    try {
      const start = Date.now();
      const connection = new Connection(endpoint, "confirmed");
      await connection.getVersion();
      const latency = Date.now() - start;
      return { connection, endpoint, latency };
    } catch (error) {
      return null;
    }
  });

  const results = await Promise.allSettled(connectionPromises);
  const validConnections = results
    .filter(r => r.status === 'fulfilled' && r.value !== null)
    .map(r => r.value)
    .sort((a, b) => a.latency - b.latency);

  if (validConnections.length === 0) {
    throw new Error("All RPC endpoints failed");
  }

  const fastest = validConnections[0];
  console.log(`⚡ Fastest RPC: ${fastest.endpoint} (${fastest.latency}ms)`);
  return fastest.connection;
}

// ULTRA-FAST LaunchLab Configuration
const LAUNCHLAB_CONFIG = {
  FUNDING_TARGET_SOL: 85,
  SELL_PERCENTAGE: 80, // 80% of supply for sale
  MIGRATION_TYPE: "cpmm",
  TX_VERSION: TxVersion.V0,
  // SPEED OPTIMIZATIONS
  PRIORITY_FEE: 0.01, // Higher fee = faster confirmation
  COMMITMENT: "confirmed", // Faster than finalized
  SKIP_PREFLIGHT: true, // Skip simulation for speed
  MAX_RETRIES: 3,
};

module.exports = {
  loadRaydiumSdk, // FIXED: Export working function instead of initSdk
  createConnection,
  PROGRAM_IDS,
  LAUNCHLAB_CONFIG,
  TxVersion,
};
