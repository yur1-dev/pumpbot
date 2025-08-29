// config.js - Raydium SDK Configuration
const { Connection, PublicKey } = require("@solana/web3.js");
const { Raydium, TxVersion } = require("@raydium-io/raydium-sdk-v2");

// Program IDs for mainnet
const PROGRAM_IDS = {
  LAUNCHPAD: new PublicKey("LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"),
  // Add other program IDs as needed
};

async function initSdk({
  connection,
  owner,
  cluster = "mainnet",
  programIds = PROGRAM_IDS,
}) {
  console.log(`Initializing Raydium SDK for ${cluster}...`);

  try {
    const raydium = await Raydium.load({
      connection,
      owner,
      cluster,
      disableFeatureCheck: true,
      disableLoadToken: false,
      blockhashCommitment: "confirmed",
    });

    console.log("Raydium SDK loaded successfully");
    return raydium;
  } catch (error) {
    console.error("Failed to initialize Raydium SDK:", error);
    throw error;
  }
}

module.exports = {
  initSdk,
  PROGRAM_IDS,
};
