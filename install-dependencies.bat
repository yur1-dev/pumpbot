@echo off
echo Installing Node.js dependencies for LOCK token creation...

:: Clean install
if exist node_modules (
    echo Removing old node_modules...
    rmdir /s /q node_modules
)

if exist package-lock.json (
    echo Removing package-lock.json...
    del package-lock.json
)

:: Install dependencies
echo Installing fresh dependencies...
npm install

echo.
echo Verifying installation...
npm ls decimal.js
npm ls @raydium-io/raydium-sdk-v2
npm ls @solana/web3.js

echo.
echo Dependencies installed! You can now create LOCK tokens.
pause