@echo off
echo === FIXING NODE.JS DEPENDENCIES FOR LOCK TOKEN BOT ===
echo.

echo Step 1: Cleaning old dependencies...
if exist node_modules rmdir /s /q node_modules
if exist package-lock.json del package-lock.json
echo    Cleaned

echo Step 2: Clearing npm cache...
npm cache clean --force
echo    Cache cleared

echo Step 3: Installing fresh dependencies...
npm install @raydium-io/raydium-sdk-v2@latest
npm install @solana/web3.js@latest
npm install @solana/spl-token@latest
npm install bn.js@latest
npm install decimal.js@latest
npm install base58@latest
echo    Dependencies installed

echo Step 4: Rebuilding native modules...
npm rebuild
echo    Native modules rebuilt

echo Step 5: Testing Node.js environment...
node --version
echo    Node.js version checked

echo Step 6: Testing SDK imports...
node -e "try { const sdk = require('@raydium-io/raydium-sdk-v2'); console.log('SDK imported successfully'); console.log('Available exports:', Object.keys(sdk)); } catch (e) { console.log('SDK import failed:', e.message); process.exit(1); }"

echo.
echo DEPENDENCIES FIXED!
echo.
echo Now test with: python pumpbot.py
pause