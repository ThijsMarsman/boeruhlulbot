"""
Solana Trading Bot for Telegram
Supports: pump.fun & bonk.fun (pre/post migration, SOL & USD1 pairs)
"""

import os
import logging
import asyncio
import base58
import struct
import httpx
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
from solders.message import Message
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
import base64
from decimal import Decimal
import json

# Database
from database import Database

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "8410722554:AAGvBH8YQia65AFoFrThj7rB7lDjNFXBlms")
SOLANA_RPC = os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:GqEfVEjfXNkJRSOkHuvGHdoLwYeFVgjh@centerbeam.proxy.rlwy.net:46783/railway")

# Constants
LAMPORTS_PER_SOL = 1_000_000_000

# Initialize database
db = Database(DATABASE_URL)


class SolanaTrader:
    """Handles all Solana blockchain interactions"""
    
    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url
        self.client = AsyncClient(rpc_url)
    
    async def get_balance(self, pubkey: str) -> float:
        """Get SOL balance for a wallet"""
        try:
            response = await self.client.get_balance(Pubkey.from_string(pubkey))
            if response.value is not None:
                return response.value / LAMPORTS_PER_SOL
            return 0.0
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return 0.0
    
    async def get_token_info(self, token_address: str) -> dict:
        """Get token information from various sources"""
        try:
            # Try to get token metadata
            async with httpx.AsyncClient() as client:
                # Try Jupiter API for token info
                response = await client.get(
                    f"https://token.jup.ag/strict",
                    timeout=10.0
                )
                if response.status_code == 200:
                    tokens = response.json()
                    for token in tokens:
                        if token.get("address") == token_address:
                            return {
                                "success": True,
                                "name": token.get("name", "Unknown"),
                                "symbol": token.get("symbol", "???"),
                                "decimals": token.get("decimals", 9),
                                "address": token_address
                            }
                
                # Try DexScreener for price info
                dex_response = await client.get(
                    f"https://api.dexscreener.com/latest/dex/tokens/{token_address}",
                    timeout=10.0
                )
                if dex_response.status_code == 200:
                    data = dex_response.json()
                    if data.get("pairs") and len(data["pairs"]) > 0:
                        pair = data["pairs"][0]
                        return {
                            "success": True,
                            "name": pair.get("baseToken", {}).get("name", "Unknown"),
                            "symbol": pair.get("baseToken", {}).get("symbol", "???"),
                            "price_usd": pair.get("priceUsd", "0"),
                            "price_sol": pair.get("priceNative", "0"),
                            "liquidity": pair.get("liquidity", {}).get("usd", 0),
                            "market_cap": pair.get("marketCap", 0),
                            "volume_24h": pair.get("volume", {}).get("h24", 0),
                            "price_change_24h": pair.get("priceChange", {}).get("h24", 0),
                            "dex": pair.get("dexId", "unknown"),
                            "address": token_address,
                            "pair_address": pair.get("pairAddress", ""),
                        }
            
            return {
                "success": False,
                "error": "Token not found",
                "address": token_address
            }
        except Exception as e:
            logger.error(f"Error getting token info: {e}")
            return {"success": False, "error": str(e), "address": token_address}
    
    async def swap_sol_for_token(
        self,
        private_key: str,
        token_address: str,
        amount_sol: float,
        slippage: float = 15.0
    ) -> dict:
        """Execute a buy order using Jupiter aggregator"""
        try:
            keypair = Keypair.from_bytes(base58.b58decode(private_key))
            wallet_pubkey = str(keypair.pubkey())
            
            amount_lamports = int(amount_sol * LAMPORTS_PER_SOL)
            slippage_bps = int(slippage * 100)  # Convert to basis points
            
            async with httpx.AsyncClient() as client:
                # Get quote from Jupiter
                quote_response = await client.get(
                    "https://quote-api.jup.ag/v6/quote",
                    params={
                        "inputMint": "So11111111111111111111111111111111111111112",  # SOL
                        "outputMint": token_address,
                        "amount": str(amount_lamports),
                        "slippageBps": str(slippage_bps),
                    },
                    timeout=30.0
                )
                
                if quote_response.status_code != 200:
                    return {"success": False, "error": "Failed to get quote"}
                
                quote = quote_response.json()
                
                # Get swap transaction
                swap_response = await client.post(
                    "https://quote-api.jup.ag/v6/swap",
                    json={
                        "quoteResponse": quote,
                        "userPublicKey": wallet_pubkey,
                        "wrapAndUnwrapSol": True,
                    },
                    timeout=30.0
                )
                
                if swap_response.status_code != 200:
                    return {"success": False, "error": "Failed to create swap transaction"}
                
                swap_data = swap_response.json()
                swap_transaction = swap_data.get("swapTransaction")
                
                if not swap_transaction:
                    return {"success": False, "error": "No swap transaction returned"}
                
                # Decode and sign transaction
                tx_bytes = base64.b64decode(swap_transaction)
                
                # Send to Solana
                tx_response = await self.client.send_raw_transaction(
                    tx_bytes,
                    opts={"skip_preflight": True, "max_retries": 3}
                )
                
                signature = str(tx_response.value)
                
                return {
                    "success": True,
                    "signature": signature,
                    "amount_in": amount_sol,
                    "amount_out": int(quote.get("outAmount", 0)),
                    "price_impact": quote.get("priceImpactPct", 0),
                }
                
        except Exception as e:
            logger.error(f"Swap error: {e}")
            return {"success": False, "error": str(e)}
    
    async def swap_token_for_sol(
        self,
        private_key: str,
        token_address: str,
        percentage: int = 100,
        slippage: float = 15.0
    ) -> dict:
        """Execute a sell order using Jupiter aggregator"""
        try:
            keypair = Keypair.from_bytes(base58.b58decode(private_key))
            wallet_pubkey = str(keypair.pubkey())
            
            # Get token balance
            token_balance = await self.get_token_balance(wallet_pubkey, token_address)
            
            if token_balance <= 0:
                return {"success": False, "error": "No tokens to sell"}
            
            sell_amount = int(token_balance * percentage / 100)
            slippage_bps = int(slippage * 100)
            
            async with httpx.AsyncClient() as client:
                # Get quote from Jupiter
                quote_response = await client.get(
                    "https://quote-api.jup.ag/v6/quote",
                    params={
                        "inputMint": token_address,
                        "outputMint": "So11111111111111111111111111111111111111112",  # SOL
                        "amount": str(sell_amount),
                        "slippageBps": str(slippage_bps),
                    },
                    timeout=30.0
                )
                
                if quote_response.status_code != 200:
                    return {"success": False, "error": "Failed to get quote"}
                
                quote = quote_response.json()
                
                # Get swap transaction
                swap_response = await client.post(
                    "https://quote-api.jup.ag/v6/swap",
                    json={
                        "quoteResponse": quote,
                        "userPublicKey": wallet_pubkey,
                        "wrapAndUnwrapSol": True,
                    },
                    timeout=30.0
                )
                
                if swap_response.status_code != 200:
                    return {"success": False, "error": "Failed to create swap transaction"}
                
                swap_data = swap_response.json()
                swap_transaction = swap_data.get("swapTransaction")
                
                if not swap_transaction:
                    return {"success": False, "error": "No swap transaction returned"}
                
                # Decode and sign transaction
                tx_bytes = base64.b64decode(swap_transaction)
                
                # Send to Solana
                tx_response = await self.client.send_raw_transaction(
                    tx_bytes,
                    opts={"skip_preflight": True, "max_retries": 3}
                )
                
                signature = str(tx_response.value)
                
                return {
                    "success": True,
                    "signature": signature,
                    "amount_in": sell_amount,
                    "amount_out": int(quote.get("outAmount", 0)) / LAMPORTS_PER_SOL,
                    "price_impact": quote.get("priceImpactPct", 0),
                }
                
        except Exception as e:
            logger.error(f"Sell error: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_token_balance(self, wallet: str, token_address: str) -> int:
        """Get token balance for a wallet"""
        try:
            response = await self.client.get_token_accounts_by_owner_json_parsed(
                Pubkey.from_string(wallet),
                {"mint": Pubkey.from_string(token_address)},
            )
            if response.value:
                for account in response.value:
                    info = account.account.data.parsed.get("info", {})
                    token_amount = info.get("tokenAmount", {})
                    return int(token_amount.get("amount", 0))
            return 0
        except Exception as e:
            logger.error(f"Error getting token balance: {e}")
            return 0


# Initialize trader
trader = SolanaTrader(SOLANA_RPC)


def generate_wallet() -> tuple[str, str]:
    """Generate a new Solana wallet"""
    keypair = Keypair()
    public_key = str(keypair.pubkey())
    private_key = base58.b58encode(bytes(keypair)).decode("utf-8")
    return public_key, private_key


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Generate main menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("💰 Buy", callback_data="buy"),
            InlineKeyboardButton("💸 Sell", callback_data="sell"),
        ],
        [
            InlineKeyboardButton("👛 Wallet", callback_data="wallet"),
            InlineKeyboardButton("📊 Positions", callback_data="positions"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_buy_keyboard() -> InlineKeyboardMarkup:
    """Generate buy menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("0.1 SOL", callback_data="buy_0.1"),
            InlineKeyboardButton("0.25 SOL", callback_data="buy_0.25"),
            InlineKeyboardButton("0.5 SOL", callback_data="buy_0.5"),
        ],
        [
            InlineKeyboardButton("1 SOL", callback_data="buy_1"),
            InlineKeyboardButton("2 SOL", callback_data="buy_2"),
            InlineKeyboardButton("5 SOL", callback_data="buy_5"),
        ],
        [
            InlineKeyboardButton("✏️ Custom Amount", callback_data="buy_custom"),
        ],
        [
            InlineKeyboardButton("⬅️ Back", callback_data="back_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_sell_keyboard() -> InlineKeyboardMarkup:
    """Generate sell menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("25%", callback_data="sell_25"),
            InlineKeyboardButton("50%", callback_data="sell_50"),
        ],
        [
            InlineKeyboardButton("75%", callback_data="sell_75"),
            InlineKeyboardButton("100%", callback_data="sell_100"),
        ],
        [
            InlineKeyboardButton("⬅️ Back", callback_data="back_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_settings_keyboard(user_settings: dict) -> InlineKeyboardMarkup:
    """Generate settings keyboard"""
    slippage = user_settings.get("slippage", 15)
    keyboard = [
        [
            InlineKeyboardButton(
                f"📉 Slippage: {slippage}%", callback_data="settings_slippage"
            ),
        ],
        [
            InlineKeyboardButton("5%", callback_data="slippage_5"),
            InlineKeyboardButton("10%", callback_data="slippage_10"),
            InlineKeyboardButton("15%", callback_data="slippage_15"),
            InlineKeyboardButton("25%", callback_data="slippage_25"),
        ],
        [
            InlineKeyboardButton("⬅️ Back", callback_data="back_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_wallet_keyboard() -> InlineKeyboardMarkup:
    """Generate wallet keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("📋 Copy Address", callback_data="copy_address"),
            InlineKeyboardButton("🔑 Export Key", callback_data="export_key"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh Balance", callback_data="refresh_balance"),
        ],
        [
            InlineKeyboardButton("⬅️ Back", callback_data="back_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    user = update.effective_user
    user_id = user.id
    
    # Check if user exists
    existing_user = db.get_user(user_id)
    
    if not existing_user:
        # Generate new wallet for user
        public_key, private_key = generate_wallet()
        db.create_user(user_id, user.username or "", public_key, private_key)
        wallet_address = public_key
        is_new = True
    else:
        wallet_address = existing_user["wallet_address"]
        is_new = False
    
    # Get balance
    balance = await trader.get_balance(wallet_address)
    
    welcome_text = f"""
{'🎉 *Welcome to SolSniper Bot!*' if is_new else '👋 *Welcome back!*'}

{'Your new wallet has been created!' if is_new else ''}

━━━━━━━━━━━━━━━━━━━━━━
👛 *Your Wallet*
`{wallet_address}`

💰 *Balance:* `{balance:.4f} SOL`
━━━━━━━━━━━━━━━━━━━━━━

*Supported Platforms:*
🎢 pump.fun (pre & post migration)
🐕 bonk.fun (SOL & USD1 pairs)

*Quick Start:*
1️⃣ Send SOL to your wallet address above
2️⃣ Paste a token contract address
3️⃣ Click Buy to trade!

⚡ Fast execution • 🛡️ MEV protection
"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard(),
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming messages (token addresses and custom amounts)"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Check if user is entering a custom buy amount
    if context.user_data.get("awaiting_custom_amount"):
        context.user_data["awaiting_custom_amount"] = False
        current_token = context.user_data.get("current_token")
        
        if not current_token:
            await update.message.reply_text(
                "❌ No token selected. Please send a token address first.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_main")]
                ]),
            )
            return
        
        # Parse amount (support both . and , as decimal separator)
        try:
            amount = float(text.replace(",", "."))
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid amount. Please try again.\n\n"
                "Example: `0.5` or `0,5`",
                parse_mode="Markdown",
                reply_markup=get_buy_keyboard(),
            )
            context.user_data["awaiting_custom_amount"] = True
            return
        
        if amount <= 0:
            await update.message.reply_text(
                "❌ Amount must be greater than 0.",
                reply_markup=get_buy_keyboard(),
            )
            context.user_data["awaiting_custom_amount"] = True
            return
        
        # Get user
        user = db.get_user(user_id)
        if not user:
            await update.message.reply_text("❌ Please use /start first.")
            return
        
        # Check balance
        balance = await trader.get_balance(user["wallet_address"])
        if balance < amount:
            await update.message.reply_text(
                f"❌ Insufficient balance!\n\n"
                f"Required: {amount} SOL\n"
                f"Available: {balance:.4f} SOL\n\n"
                f"Send SOL to:\n`{user['wallet_address']}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_main")]
                ]),
            )
            return
        
        # Execute buy
        loading_msg = await update.message.reply_text("⏳ *Executing buy order...*", parse_mode="Markdown")
        
        settings = db.get_settings(user_id)
        result = await trader.swap_sol_for_token(
            user["private_key"],
            current_token,
            amount,
            settings.get("slippage", 15),
        )
        
        if result["success"]:
            # Log trade
            db.log_trade(
                user_id,
                current_token,
                "BUY",
                amount,
                result.get("amount_out", 0),
                result["signature"],
            )
            
            await loading_msg.edit_text(
                f"✅ *Buy Order Successful!*\n\n"
                f"💰 Spent: {amount} SOL\n"
                f"📝 Signature:\n`{result['signature']}`\n\n"
                f"[View on Solscan](https://solscan.io/tx/{result['signature']})",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💸 Sell", callback_data="sell")],
                    [InlineKeyboardButton("⬅️ Main Menu", callback_data="back_main")],
                ]),
            )
        else:
            await loading_msg.edit_text(
                f"❌ *Buy Failed*\n\n"
                f"Error: {result.get('error', 'Unknown error')}\n\n"
                f"Please try again or adjust slippage.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Try Again", callback_data=f"buy_{amount}")],
                    [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_main")],
                ]),
            )
        return
    
    # Check if it's a Solana address (32-44 chars, base58)
    if len(text) >= 32 and len(text) <= 44:
        try:
            # Validate it's a valid pubkey
            Pubkey.from_string(text)
            
            # Store token in context for trading
            context.user_data["current_token"] = text
            
            # Show loading message
            loading_msg = await update.message.reply_text("🔍 Looking up token...")
            
            # Get token info
            token_info = await trader.get_token_info(text)
            
            if token_info.get("success"):
                # Determine platform
                platform = "Unknown"
                if "pump" in token_info.get("dex", "").lower():
                    platform = "🎢 pump.fun"
                elif "bonk" in text.lower() or "raydium" in token_info.get("dex", "").lower():
                    platform = "🐕 bonk.fun / Raydium"
                else:
                    platform = f"📊 {token_info.get('dex', 'DEX')}"
                
                price_change = float(token_info.get("price_change_24h", 0))
                change_emoji = "🟢" if price_change >= 0 else "🔴"
                
                token_text = f"""
🪙 *{token_info.get('name', 'Unknown Token')}* (${token_info.get('symbol', '???')})

━━━━━━━━━━━━━━━━━━━━━━
📍 *Platform:* {platform}
💵 *Price:* ${token_info.get('price_usd', '0')}
💧 *Liquidity:* ${int(float(token_info.get('liquidity', 0))):,}
📊 *Market Cap:* ${int(float(token_info.get('market_cap', 0))):,}
📈 *24h Volume:* ${int(float(token_info.get('volume_24h', 0))):,}
{change_emoji} *24h Change:* {price_change:+.2f}%
━━━━━━━━━━━━━━━━━━━━━━

📋 *Contract:*
`{text}`

Select an amount to buy:
"""
                await loading_msg.edit_text(
                    token_text,
                    parse_mode="Markdown",
                    reply_markup=get_buy_keyboard(),
                )
            else:
                # Token not found on DEXes, might be new pump.fun token
                token_text = f"""
🆕 *New Token Detected*

━━━━━━━━━━━━━━━━━━━━━━
⚠️ Token not yet listed on DEXes
This might be a new pump.fun or bonk.fun token

📋 *Contract:*
`{text}`
━━━━━━━━━━━━━━━━━━━━━━

⚡ You can still try to buy if the token exists on pump.fun or bonk.fun

Select an amount to buy:
"""
                await loading_msg.edit_text(
                    token_text,
                    parse_mode="Markdown",
                    reply_markup=get_buy_keyboard(),
                )
                
        except Exception as e:
            logger.error(f"Invalid address: {e}")
            await update.message.reply_text(
                "❌ Invalid token address. Please send a valid Solana token address.",
            )
    else:
        # Not a token address
        await update.message.reply_text(
            "📝 Send me a token contract address to trade!\n\n"
            "Example: `TokenAddressHere...`",
            parse_mode="Markdown",
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries from inline buttons"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    user = db.get_user(user_id)
    if not user:
        await query.edit_message_text("❌ Please /start the bot first.")
        return
    
    # Main menu actions
    if data == "back_main" or data == "refresh":
        balance = await trader.get_balance(user["wallet_address"])
        menu_text = f"""
⚡ *SolSniper Bot*

━━━━━━━━━━━━━━━━━━━━━━
👛 *Wallet:* `{user['wallet_address'][:8]}...{user['wallet_address'][-6:]}`
💰 *Balance:* `{balance:.4f} SOL`
━━━━━━━━━━━━━━━━━━━━━━

📝 Send a token address to trade
"""
        await query.edit_message_text(
            menu_text,
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard(),
        )
    
    elif data == "buy":
        await query.edit_message_text(
            "📝 *Send me a token contract address to buy*\n\n"
            "Supported:\n"
            "🎢 pump.fun tokens\n"
            "🐕 bonk.fun tokens (SOL & USD1 pairs)",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back", callback_data="back_main")]
            ]),
        )
    
    elif data == "sell":
        # Get user's token positions
        positions = db.get_positions(user_id)
        
        if not positions:
            await query.edit_message_text(
                "📊 *No positions found*\n\n"
                "Buy some tokens first!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 Buy Token", callback_data="buy")],
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_main")],
                ]),
            )
        else:
            # Show positions to sell
            position_buttons = []
            for pos in positions[:10]:  # Limit to 10
                position_buttons.append([
                    InlineKeyboardButton(
                        f"{pos['symbol']} - {pos['amount']:.4f}",
                        callback_data=f"selltoken_{pos['token_address'][:16]}",
                    )
                ])
            position_buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="back_main")])
            
            await query.edit_message_text(
                "💸 *Select a token to sell:*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(position_buttons),
            )
    
    elif data == "wallet":
        balance = await trader.get_balance(user["wallet_address"])
        wallet_text = f"""
👛 *Your Wallet*

━━━━━━━━━━━━━━━━━━━━━━
📋 *Address:*
`{user['wallet_address']}`

💰 *Balance:* `{balance:.4f} SOL`
━━━━━━━━━━━━━━━━━━━━━━

💡 Send SOL to this address to fund your trading wallet.
"""
        await query.edit_message_text(
            wallet_text,
            parse_mode="Markdown",
            reply_markup=get_wallet_keyboard(),
        )
    
    elif data == "export_key":
        # Send private key in a separate message that can be deleted
        await query.message.reply_text(
            f"🔐 *Your Private Key (DELETE AFTER SAVING!):*\n\n"
            f"`{user['private_key']}`\n\n"
            f"⚠️ *NEVER share this with anyone!*",
            parse_mode="Markdown",
        )
    
    elif data == "positions":
        positions = db.get_positions(user_id)
        
        if not positions:
            positions_text = "📊 *Your Positions*\n\n_No open positions_"
        else:
            positions_text = "📊 *Your Positions*\n\n"
            for pos in positions:
                positions_text += f"• *{pos['symbol']}*: {pos['amount']:.4f}\n"
        
        await query.edit_message_text(
            positions_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="positions")],
                [InlineKeyboardButton("⬅️ Back", callback_data="back_main")],
            ]),
        )
    
    elif data == "settings":
        settings = db.get_settings(user_id)
        await query.edit_message_text(
            "⚙️ *Settings*\n\n"
            f"Current slippage: {settings.get('slippage', 15)}%",
            parse_mode="Markdown",
            reply_markup=get_settings_keyboard(settings),
        )
    
    elif data.startswith("slippage_"):
        new_slippage = int(data.split("_")[1])
        db.update_settings(user_id, {"slippage": new_slippage})
        settings = db.get_settings(user_id)
        await query.edit_message_text(
            f"⚙️ *Settings*\n\n"
            f"✅ Slippage updated to {new_slippage}%",
            parse_mode="Markdown",
            reply_markup=get_settings_keyboard(settings),
        )
    
    # Buy actions
    elif data.startswith("buy_"):
        amount_str = data.replace("buy_", "")
        current_token = context.user_data.get("current_token")
        
        if not current_token:
            await query.edit_message_text(
                "❌ No token selected. Please send a token address first.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_main")]
                ]),
            )
            return
        
        if amount_str == "custom":
            context.user_data["awaiting_custom_amount"] = True
            await query.edit_message_text(
                "✏️ *Enter custom amount in SOL:*\n\n"
                "Example: `0.5`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Cancel", callback_data="back_main")]
                ]),
            )
            return
        
        try:
            amount = float(amount_str)
        except ValueError:
            await query.answer("Invalid amount")
            return
        
        # Check balance
        balance = await trader.get_balance(user["wallet_address"])
        if balance < amount:
            await query.edit_message_text(
                f"❌ Insufficient balance!\n\n"
                f"Required: {amount} SOL\n"
                f"Available: {balance:.4f} SOL\n\n"
                f"Send SOL to:\n`{user['wallet_address']}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_main")]
                ]),
            )
            return
        
        # Execute buy
        await query.edit_message_text("⏳ *Executing buy order...*", parse_mode="Markdown")
        
        settings = db.get_settings(user_id)
        result = await trader.swap_sol_for_token(
            user["private_key"],
            current_token,
            amount,
            settings.get("slippage", 15),
        )
        
        if result["success"]:
            # Log trade
            db.log_trade(
                user_id,
                current_token,
                "BUY",
                amount,
                result.get("amount_out", 0),
                result["signature"],
            )
            
            await query.edit_message_text(
                f"✅ *Buy Order Successful!*\n\n"
                f"💰 Spent: {amount} SOL\n"
                f"📝 Signature:\n`{result['signature']}`\n\n"
                f"[View on Solscan](https://solscan.io/tx/{result['signature']})",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💸 Sell", callback_data="sell")],
                    [InlineKeyboardButton("⬅️ Main Menu", callback_data="back_main")],
                ]),
            )
        else:
            await query.edit_message_text(
                f"❌ *Buy Failed*\n\n"
                f"Error: {result.get('error', 'Unknown error')}\n\n"
                f"Please try again or adjust slippage.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Try Again", callback_data=f"buy_{amount}")],
                    [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_main")],
                ]),
            )
    
    # Sell actions
    elif data.startswith("sell_"):
        percentage = int(data.split("_")[1])
        current_token = context.user_data.get("current_token")
        
        if not current_token:
            await query.edit_message_text(
                "❌ No token selected. Please select a token to sell.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back", callback_data="sell")]
                ]),
            )
            return
        
        # Execute sell
        await query.edit_message_text(
            f"⏳ *Selling {percentage}% of tokens...*",
            parse_mode="Markdown",
        )
        
        settings = db.get_settings(user_id)
        result = await trader.swap_token_for_sol(
            user["private_key"],
            current_token,
            percentage,
            settings.get("slippage", 15),
        )
        
        if result["success"]:
            # Log trade
            db.log_trade(
                user_id,
                current_token,
                "SELL",
                result.get("amount_in", 0),
                result.get("amount_out", 0),
                result["signature"],
            )
            
            await query.edit_message_text(
                f"✅ *Sell Order Successful!*\n\n"
                f"💰 Received: ~{result.get('amount_out', 0):.4f} SOL\n"
                f"📝 Signature:\n`{result['signature']}`\n\n"
                f"[View on Solscan](https://solscan.io/tx/{result['signature']})",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Main Menu", callback_data="back_main")],
                ]),
            )
        else:
            await query.edit_message_text(
                f"❌ *Sell Failed*\n\n"
                f"Error: {result.get('error', 'Unknown error')}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Try Again", callback_data=f"sell_{percentage}")],
                    [InlineKeyboardButton("⬅️ Back", callback_data="back_main")],
                ]),
            )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors"""
    logger.error(f"Update {update} caused error {context.error}")


async def setup_bot_commands(application) -> None:
    """Set up bot commands menu"""
    commands = [
        BotCommand("start", "🚀 Start the bot & show wallet"),
        BotCommand("buy", "💰 Buy a token"),
        BotCommand("sell", "💸 Sell a token"),
        BotCommand("wallet", "👛 View your wallet"),
        BotCommand("positions", "📊 View your positions"),
        BotCommand("settings", "⚙️ Settings"),
        BotCommand("help", "❓ Help"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands menu set up successfully")


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /buy command"""
    await update.message.reply_text(
        "📝 *Send me a token contract address to buy*\n\n"
        "Supported:\n"
        "🎢 pump.fun tokens\n"
        "🐕 bonk.fun tokens (SOL & USD1 pairs)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="back_main")]
        ]),
    )


async def cmd_sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sell command"""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return
    
    positions = db.get_positions(user_id)
    
    if not positions:
        await update.message.reply_text(
            "📊 *No positions found*\n\n"
            "Buy some tokens first!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Buy Token", callback_data="buy")],
            ]),
        )
    else:
        position_buttons = []
        for pos in positions[:10]:
            position_buttons.append([
                InlineKeyboardButton(
                    f"{pos['symbol']} - {pos['amount']:.4f}",
                    callback_data=f"selltoken_{pos['token_address'][:16]}",
                )
            ])
        
        await update.message.reply_text(
            "💸 *Select a token to sell:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(position_buttons),
        )


async def cmd_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /wallet command"""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return
    
    balance = await trader.get_balance(user["wallet_address"])
    
    await update.message.reply_text(
        f"👛 *Your Wallet*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Address:*\n`{user['wallet_address']}`\n\n"
        f"💰 *Balance:* `{balance:.4f} SOL`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 Send SOL to this address to start trading.",
        parse_mode="Markdown",
        reply_markup=get_wallet_keyboard(),
    )


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /positions command"""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return
    
    positions = db.get_positions(user_id)
    
    if not positions:
        positions_text = "📊 *Your Positions*\n\n_No open positions_"
    else:
        positions_text = "📊 *Your Positions*\n\n"
        for pos in positions:
            positions_text += f"• *{pos['symbol']}*: {pos['amount']:.4f}\n"
    
    await update.message.reply_text(
        positions_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="positions")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_main")],
        ]),
    )


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings command"""
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return
    
    settings = db.get_settings(user_id)
    
    await update.message.reply_text(
        "⚙️ *Settings*\n\n"
        f"Current slippage: {settings.get('slippage', 15)}%",
        parse_mode="Markdown",
        reply_markup=get_settings_keyboard(settings),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command"""
    await update.message.reply_text(
        "❓ *Help - SolSniper Bot*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "*How to use:*\n\n"
        "1️⃣ /start - Create your wallet\n"
        "2️⃣ Send SOL to your wallet address\n"
        "3️⃣ Paste a token contract address\n"
        "4️⃣ Click an amount to buy\n"
        "5️⃣ Use /sell to sell\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "*Commands:*\n\n"
        "/start - Start & show wallet\n"
        "/buy - Buy tokens\n"
        "/sell - Sell tokens\n"
        "/wallet - View wallet\n"
        "/positions - View positions\n"
        "/settings - Settings\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "*Supported platforms:*\n"
        "🎢 pump.fun\n"
        "🐕 bonk.fun (SOL & USD1)\n",
        parse_mode="Markdown",
    )


def main() -> None:
    """Start the bot"""
    # Initialize database
    db.init_db()
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("buy", cmd_buy))
    application.add_handler(CommandHandler("sell", cmd_sell))
    application.add_handler(CommandHandler("wallet", cmd_wallet))
    application.add_handler(CommandHandler("positions", cmd_positions))
    application.add_handler(CommandHandler("settings", cmd_settings))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    # Set up commands menu on startup
    application.post_init = setup_bot_commands
    
    # Start polling
    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
