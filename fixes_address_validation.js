// FIXED: Address validation function that actually works
function validateLockAddress(address) {
  console.log(`🔍 Validating address: ${address}`);

  if (!address || typeof address !== "string") {
    console.log("❌ Address is empty or not a string");
    return false;
  }

  if (address.length < 32 || address.length > 44) {
    console.log(`❌ Invalid address length: ${address.length}`);
    return false;
  }

  // FIXED: Simple uppercase check - works for ALL variations
  const addressUpper = address.toUpperCase();
  const endsWithLock = addressUpper.endsWith("LOCK");

  console.log(`📝 Address (uppercase): ${addressUpper}`);
  console.log(`🔒 Ends with LOCK: ${endsWithLock}`);

  if (endsWithLock) {
    const actualSuffix = address.slice(-4);
    console.log(`✅ Valid LOCK address found: ${address}`);
    console.log(`   Actual suffix: "${actualSuffix}"`);
    return true;
  }

  // Also check for LCK variations
  const endsWithLCK = addressUpper.endsWith("LCK");
  if (endsWithLCK) {
    const actualSuffix = address.slice(-3);
    console.log(`✅ Valid LCK address found: ${address}`);
    console.log(`   Actual suffix: "${actualSuffix}"`);
    return true;
  }

  console.log(`❌ Address does not end with LOCK or LCK variations`);
  console.log(`   Last 4 chars: "${address.slice(-4)}"`);
  console.log(`   Last 3 chars: "${address.slice(-3)}"`);

  return false;
}

// Test the function with your failing address
console.log("=== TESTING ADDRESS VALIDATION ===");
const testAddress = "6mG12mRJhHbEiuRBUDvqSDCA4hswABGkFrwS6hcBLocK";
const isValid = validateLockAddress(testAddress);
console.log(`\nFINAL RESULT: ${isValid ? "✅ VALID" : "❌ INVALID"}`);

// Test with more variations
const testAddresses = [
  "6mG12mRJhHbEiuRBUDvqSDCA4hswABGkFrwS6hcBLocK", // Your failing one
  "SomeFakeAddressEndingWithLOCK",
  "AnotherTestAddressWithLock",
  "TestingLCK",
  "SomeRandomAddress123",
];

console.log("\n=== TESTING MULTIPLE ADDRESSES ===");
testAddresses.forEach((addr, i) => {
  console.log(`\nTest ${i + 1}:`);
  const result = validateLockAddress(addr);
  console.log(`Result: ${result ? "✅ PASS" : "❌ FAIL"}`);
});

module.exports = { validateLockAddress };
