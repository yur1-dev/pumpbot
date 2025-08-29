const { Connection, Keypair, PublicKey } = require("@solana/web3.js");
const { Raydium } = require("@raydium-io/raydium-sdk-v2");
const fs = require("fs");

async function createLockToken() {
  try {
    // Read parameters from Python
    const params = JSON.parse(fs.readFileSync("token_params.json", "utf8"));

    // Convert base58 keypairs back to Keypair objects
    const mintKeypair = Keypair.fromSecretKey(
      Buffer.from(params.mintKeypair, "base64")
    );

    const creatorKeypair = Keypair.fromSecretKey(
      Buffer.from(params.creatorKeypair, "base64")
    );

    // Initialize connection
    const connection = new Connection(
      "https://api.mainnet-beta.solana.com",
      "confirmed"
    );

    // Initialize Raydium SDK
    const raydium = await Raydium.load({
      connection,
      owner: creatorKeypair,
      cluster: "mainnet-beta",
    });

    // Create LaunchLab token
    const { execute } = await raydium.launchpad.createLaunchpad({
      mint: mintKeypair.publicKey,
      name: params.name,
      symbol: params.symbol,
      decimals: params.decimals,
      totalSupply: params.totalSupply,
      uri: params.uri,
      // Add other LaunchLab parameters as needed
    });

    const result = await execute();

    console.log(
      JSON.stringify({
        signature: result.txId,
        poolAddress: result.poolId,
        bondingCurveAddress: result.poolId,
      })
    );
  } catch (error) {
    console.error(JSON.stringify({ error: error.message }));
    process.exit(1);
  }
}

createLockToken().catch(console.error);
