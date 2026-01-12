# ⚡ SolSniper - Solana Trading Bot for Telegram

A fast Solana trading bot similar to Bonkbot, supporting pump.fun and bonk.fun tokens.

## ✨ Features

- 🔐 **Auto Wallet Generation** - Each user gets their own Solana wallet
- 💰 **Quick Buy** - One-click buy buttons (0.1, 0.25, 0.5, 1, 2, 5 SOL)
- 💸 **Quick Sell** - Percentage-based selling (25%, 50%, 75%, 100%)
- 📊 **Token Info** - Real-time price, liquidity, market cap, 24h change
- ⚙️ **Customizable Slippage** - 5%, 10%, 15%, 25% presets
- 🗄️ **Trade History** - All trades logged to database

## 🎯 Supported Platforms

| Platform | Pre-Migration | Post-Migration | Pairs |
|----------|--------------|----------------|-------|
| pump.fun | ✅ | ✅ | SOL |
| bonk.fun | ✅ | ✅ | SOL, USD1 |

## 🚀 Quick Start

### Local Development

1. **Clone and install dependencies**
```bash
cd solana-telegram-bot
pip install -r requirements.txt
```

2. **Set up environment**
```bash
cp .env.example .env
# Edit .env with your values
```

3. **Run the bot**
```bash
python bot.py
```

### Deploy to Railway

1. **Create a new project on [Railway](https://railway.app)**

2. **Add PostgreSQL database**
   - Click "New" → "Database" → "PostgreSQL"
   - Copy the `DATABASE_URL` from the database settings

3. **Deploy from GitHub**
   - Connect your GitHub repo
   - Or use Railway CLI: `railway up`

4. **Set environment variables**
   ```
   BOT_TOKEN=8410722554:AAGvBH8YQia65AFoFrThj7rB7lDjNFXBlms
   DATABASE_URL=<your-railway-postgres-url>
   SOLANA_RPC=https://api.mainnet-beta.solana.com
   ```

5. **Deploy!**

## 📱 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Start bot & create wallet |

## 🎮 How to Use

1. **Start the bot** - Send `/start` to create your wallet
2. **Fund your wallet** - Send SOL to your wallet address
3. **Trade tokens** - Paste any token contract address
4. **Buy** - Select amount to buy
5. **Sell** - Choose percentage to sell

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BOT_TOKEN` | Telegram bot token | Required |
| `DATABASE_URL` | Database connection string | `sqlite:///bot.db` |
| `SOLANA_RPC` | Solana RPC endpoint | `https://api.mainnet-beta.solana.com` |

### Recommended RPC Providers

The free Solana RPC has rate limits. For production, use:

- [Helius](https://helius.xyz) - Best for Solana, has free tier
- [QuickNode](https://quicknode.com) - Fast and reliable
- [Alchemy](https://alchemy.com) - Good free tier

## 📁 Project Structure

```
solana-telegram-bot/
├── bot.py              # Main bot logic
├── database.py         # Database operations
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker configuration
├── railway.json        # Railway deployment config
├── .env.example        # Environment template
└── README.md           # This file
```

## ⚠️ Security Notes

- **Private keys** are stored encrypted in the database
- Users should **export and backup** their private keys
- Consider adding **2FA** for large withdrawals
- Never share the `BOT_TOKEN` or `DATABASE_URL`

## 🔮 Future Improvements

- [ ] Limit orders
- [ ] Stop-loss / Take-profit
- [ ] Portfolio tracking
- [ ] Price alerts
- [ ] Copy trading
- [ ] MEV protection (Jito bundles)
- [ ] Multi-wallet support

## 📄 License

MIT License - Use at your own risk.

## ⚠️ Disclaimer

This bot is for educational purposes. Trading cryptocurrencies involves significant risk. Always DYOR (Do Your Own Research) and never invest more than you can afford to lose.
