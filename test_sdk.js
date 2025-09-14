// test_sdk.js - Run this FIRST
const { Raydium } = require("@raydium-io/raydium-sdk-v2");
const { Connection, Keypair } = require("@solana/web3.js");

async function test() {
  try {
    const connection = new Connection("https://api.mainnet-beta.solana.com");
    const testKey = Keypair.generate();
    const raydium = await Raydium.load({
      connection,
      owner: testKey,
      cluster: "mainnet-beta",
      disableFeatureCheck: true,
    });

    console.log("SDK loaded successfully");
    console.log(
      "Available launchpad methods:",
      Object.keys(raydium.launchpad || {})
    );

    if (raydium.launchpad && raydium.launchpad.createLaunchpad) {
      console.log("✅ createLaunchpad method found - READY TO CREATE TOKENS");
    } else {
      console.log("❌ createLaunchpad method NOT found");
    }
  } catch (error) {
    console.error("SDK test failed:", error.message);
  }
}

test();
