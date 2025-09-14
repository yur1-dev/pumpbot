// verify_and_activate_token.js - Check token status and activate trading
const { Connection, PublicKey } = require("@solana/web3.js");
const { Raydium, TxVersion } = require("@raydium-io/raydium-sdk-v2");
const BN = require("bn.js");

const RPC_ENDPOINT = "https://api.mainnet-beta.solana.com";
const LAUNCHPAD_PROGRAM_ID = "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj";

// Your token address from the screenshot
const TOKEN_ADDRESS = "3b5C4V7vJqz8SFpPeTEcCKMqXjtEALzy8riPmQ4CLOCk";

async function verifyTokenStatus() {
  console.log("=== VERIFYING TOKEN STATUS ===");
  console.log(`Token: ${TOKEN_ADDRESS}`);

  try {
    const connection = new Connection(RPC_ENDPOINT, "confirmed");

    // 1. Check if token exists
    console.log("\n1. Checking token account...");
    const tokenPubkey = new PublicKey(TOKEN_ADDRESS);
    const tokenInfo = await connection.getAccountInfo(tokenPubkey);

    if (!tokenInfo) {
      console.log("❌ Token account not found");
      return;
    }

    console.log("✅ Token account exists");
    console.log(`   Owner: ${tokenInfo.owner.toString()}`);
    console.log(`   Data length: ${tokenInfo.data.length} bytes`);

    // 2. Check for LaunchLab pool
    console.log("\n2. Checking LaunchLab bonding curve...");

    try {
      // Look for LaunchLab pools associated with this token
      const poolAccounts = await connection.getProgramAccounts(
        new PublicKey(LAUNCHPAD_PROGRAM_ID),
        {
          filters: [
            {
              memcmp: {
                offset: 8, // Skip discriminator
                bytes: TOKEN_ADDRESS,
              },
            },
          ],
        }
      );

      if (poolAccounts.length > 0) {
        console.log("✅ LaunchLab bonding curve found!");
        console.log(`   Pool address: ${poolAccounts[0].pubkey.toString()}`);
        console.log(`   Pools found: ${poolAccounts.length}`);

        // Get the pool data
        for (let i = 0; i < poolAccounts.length; i++) {
          const pool = poolAccounts[i];
          console.log(`\n   Pool ${i + 1}: ${pool.pubkey.toString()}`);
          console.log(`   Data length: ${pool.account.data.length} bytes`);
        }
      } else {
        console.log("❌ No LaunchLab bonding curve found");
        console.log(
          "   This token may be a simple SPL token, not a LaunchLab token"
        );
        return;
      }
    } catch (poolError) {
      console.log("❌ Error checking LaunchLab pools:", poolError.message);
    }

    // 3. Check token metadata
    console.log("\n3. Checking token metadata...");
    try {
      const metadataResponse = await fetch(
        `https://api.solana.fm/v0/tokens/${TOKEN_ADDRESS}`
      );
      if (metadataResponse.ok) {
        const metadata = await metadataResponse.json();
        console.log("✅ Token metadata found:");
        console.log(`   Name: ${metadata.tokenList?.name || "Unknown"}`);
        console.log(`   Symbol: ${metadata.tokenList?.symbol || "Unknown"}`);
      } else {
        console.log("⚠ Token metadata not found on Solana.fm");
      }
    } catch (metaError) {
      console.log("⚠ Could not fetch metadata:", metaError.message);
    }

    // 4. Check recent transactions
    console.log("\n4. Checking transaction history...");
    try {
      const signatures = await connection.getSignaturesForAddress(tokenPubkey, {
        limit: 10,
      });

      if (signatures.length > 0) {
        console.log(`✅ Found ${signatures.length} recent transactions`);
        for (let i = 0; i < Math.min(3, signatures.length); i++) {
          const sig = signatures[i];
          console.log(`   ${i + 1}. ${sig.signature}`);
          console.log(`      Slot: ${sig.slot}`);
          console.log(`      Status: ${sig.confirmationStatus}`);
        }
      } else {
        console.log("⚠ No recent transactions found");
        console.log("   Token may need initial trading activity");
      }
    } catch (txError) {
      console.log("⚠ Could not fetch transactions:", txError.message);
    }

    // 5. Check if tradeable on Raydium
    console.log("\n5. Checking Raydium integration...");
    console.log(
      `   LaunchLab URL: https://raydium.io/launchpad/token/?mint=${TOKEN_ADDRESS}`
    );
    console.log(
      `   DexScreener URL: https://dexscreener.com/solana/${TOKEN_ADDRESS}`
    );

    // 6. Recommendations
    console.log("\n=== RECOMMENDATIONS ===");

    if (poolAccounts.length > 0) {
      console.log("✅ Your token IS on a LaunchLab bonding curve!");
      console.log("✅ It SHOULD be tradeable");
      console.log("\nTo activate trading:");
      console.log(
        "1. Visit: https://raydium.io/launchpad/token/?mint=" + TOKEN_ADDRESS
      );
      console.log("2. Make a small test buy (0.01-0.1 SOL)");
      console.log(
        "3. This will activate the bonding curve and make it discoverable"
      );
      console.log("4. After 1-2 hours, it should appear on DexScreener");

      console.log("\nIf trading doesn't work:");
      console.log("- Check that the pool has proper liquidity setup");
      console.log("- Ensure the bonding curve parameters are correct");
      console.log("- Try making transactions from different wallets");
    } else {
      console.log("❌ No bonding curve found - token is not tradeable");
      console.log(
        "\nThis means your script created an SPL token instead of LaunchLab token"
      );
      console.log("You need to use the fixed script I provided earlier");
    }

    console.log("\n=== NEXT STEPS ===");
    console.log("1. Test trading at the Raydium LaunchLab URL above");
    console.log(
      "2. If it doesn't work, use the fixed script for future tokens"
    );
    console.log(
      "3. Make sure to include initial buy amount for immediate liquidity"
    );
  } catch (error) {
    console.error("❌ Verification failed:", error.message);
  }
}

// Also check if we can find trading pairs
async function checkTradingPairs() {
  console.log("\n=== CHECKING FOR TRADING PAIRS ===");

  try {
    // Check various DEX APIs for this token
    const apis = [
      {
        name: "Jupiter",
        url: `https://price.jup.ag/v4/price?ids=${TOKEN_ADDRESS}`,
      },
      {
        name: "DexScreener",
        url: `https://api.dexscreener.com/latest/dex/tokens/${TOKEN_ADDRESS}`,
      },
    ];

    for (const api of apis) {
      try {
        console.log(`\nChecking ${api.name}...`);
        const response = await fetch(api.url);

        if (response.ok) {
          const data = await response.json();

          if (api.name === "Jupiter") {
            if (data.data && Object.keys(data.data).length > 0) {
              console.log(`✅ ${api.name}: Token found and tradeable!`);
              console.log(
                `   Price: $${data.data[TOKEN_ADDRESS]?.price || "Unknown"}`
              );
            } else {
              console.log(
                `⚠ ${api.name}: Token not found (may need time to index)`
              );
            }
          } else if (api.name === "DexScreener") {
            if (data.pairs && data.pairs.length > 0) {
              console.log(
                `✅ ${api.name}: Found ${data.pairs.length} trading pairs!`
              );
              data.pairs.forEach((pair, i) => {
                console.log(`   Pair ${i + 1}: ${pair.dexId} - ${pair.url}`);
              });
            } else {
              console.log(`⚠ ${api.name}: No trading pairs found yet`);
            }
          }
        } else {
          console.log(`⚠ ${api.name}: API request failed (${response.status})`);
        }
      } catch (apiError) {
        console.log(`⚠ ${api.name}: Error - ${apiError.message}`);
      }
    }
  } catch (error) {
    console.log("❌ Trading pair check failed:", error.message);
  }
}

// Run verification
async function main() {
  await verifyTokenStatus();
  await checkTradingPairs();

  console.log("\n=== SUMMARY ===");
  console.log("If your token shows 'isOnCurve: TRUE' but isn't tradeable:");
  console.log("1. The bonding curve exists but needs activation");
  console.log("2. Try making a small purchase on Raydium LaunchLab");
  console.log("3. This will activate trading and make it discoverable");
  console.log("4. Wait 1-2 hours for DEX indexing");

  console.log(
    "\nFor future tokens, use the fixed script I provided to ensure:"
  );
  console.log("- Proper bonding curve creation");
  console.log("- Immediate trading activation");
  console.log("- Automatic DEX listing");
}

main().catch(console.error);
