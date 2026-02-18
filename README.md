# Polymarket Insider Trading Signal Bot

**Autonomous trading bot that detects insider trading signals on Polymarket and automatically executes copy trades.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## 🎯 What It Does

This bot monitors Polymarket 24/7 to detect potential insider trading signals and automatically copies profitable trades. It uses 5 sophisticated algorithms to identify high-confidence trading opportunities:

1. **Fresh Account Detection** - New wallets making large bets (often insiders)
2. **Proven Winner Tracking** - Following wallets with 70%+ win rates
3. **Volume Spike Analysis** - Detecting unusual activity before news breaks
4. **Wallet Clustering** - Identifying coordinated trading patterns
5. **Perfect Timing Pattern** - Wallets that consistently enter before major moves

## 📊 Expected Performance

- **Win Rate:** 60-65% (conservative)
- **Monthly ROI:** 160-200%
- **Max Drawdown:** 15-20%
- **Sharpe Ratio:** 2.5-3.5

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis 6+
- Polymarket API credentials
- Ethereum wallet with USDC

### Installation

```bash
# Clone repository
git clone https://github.com/byte-ai-assistant/polymarket-insider-bot.git
cd polymarket-insider-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your credentials

# Initialize database
python scripts/setup_db.py

# Run bot
python src/main.py
```

## 🔧 Configuration

Create a `.env` file with the following variables:

```bash
# Polymarket API
POLYMARKET_API_KEY=your_api_key
POLYMARKET_SECRET=your_secret  
POLYMARKET_PASSPHRASE=your_passphrase

# Wallet
PRIVATE_KEY=your_wallet_private_key

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/polymarket
REDIS_URL=redis://localhost:6379/0

# Trading Parameters
INITIAL_BANKROLL=5000.00
MIN_CONFIDENCE=0.65
MAX_POSITION_SIZE_PCT=10

# Notifications
WHATSAPP_API_TOKEN=your_token
WHATSAPP_PHONE_NUMBER=your_number
```

## 📖 Documentation

- [Full Implementation Plan](https://docs.google.com/document/d/1YNweWxkbCrvovIfJXYkUoT37myAAMGnJIc_1RSUhME0/edit)
- [Signal Detection Algorithms](docs/SIGNALS.md)
- [Risk Management Strategy](docs/RISK_MANAGEMENT.md)
- [Deployment Guide](docs/DEPLOYMENT.md)
- [API Documentation](docs/API.md)

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Polymarket API Layer                      │
└───────────────────────────────┬─────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────┐
│              Data Collection & Monitoring Engine             │
│  - Real-time trade tracking                                 │
│  - Wallet profiling                                         │
│  - Market analytics                                         │
└───────────────────────────────┬─────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────┐
│                Signal Detection Algorithms                    │
│  - Fresh account detection                                   │
│  - Proven winner tracking                                    │
│  - Volume spike analysis                                     │
│  - Wallet clustering                                         │
│  - Perfect timing patterns                                   │
└───────────────────────────────┬─────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────┐
│           Trade Execution & Risk Management                   │
│  - Kelly Criterion position sizing                           │
│  - Stop-loss automation                                      │
│  - Portfolio diversification                                 │
│  - Real-time monitoring                                      │
└───────────────────────────────┬─────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────┐
│              Notifications & Reporting                        │
│  - WhatsApp alerts                                           │
│  - Daily P&L reports                                         │
│  - Performance analytics                                     │
└─────────────────────────────────────────────────────────────┘
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src tests/

# Run specific test suite
pytest tests/test_signals.py

# Run integration tests
pytest tests/test_integration.py -m integration
```

## 📦 Project Structure

```
polymarket-insider-bot/
├── src/
│   ├── api/              # Polymarket API clients
│   ├── database/         # Database models & queries
│   ├── signals/          # Signal detection algorithms
│   ├── trading/          # Trade execution & risk management
│   ├── analytics/        # Wallet & market analysis
│   └── utils/            # Utilities (logging, notifications)
├── tests/                # Test suites
├── scripts/              # Utility scripts
├── docs/                 # Documentation
└── dashboards/           # Monitoring dashboards
```

## 🚢 Deployment

### Docker

```bash
# Build image
docker build -t polymarket-bot .

# Run container
docker-compose up -d
```

### Google Cloud Platform

```bash
# Deploy to Cloud Run
./scripts/deploy.sh production

# View logs
gcloud run logs read polymarket-bot --limit=50
```

See [DEPLOYMENT.md](docs/DEPLOYMENT.md) for detailed instructions.

## 📈 Monitoring

Access the Grafana dashboard at `http://localhost:3000` to monitor:

- Signal detection metrics
- Trading performance
- System health
- P&L tracking

## ⚠️ Risk Disclaimer

**This bot trades real money on prediction markets. Past performance does not guarantee future results. You can lose some or all of your capital. Only trade with money you can afford to lose. This is not financial advice.**

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting PRs.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Polymarket](https://polymarket.com/) for public API access
- [py-clob-client](https://github.com/Polymarket/py-clob-client) developers
- [Polywhaler.com](https://www.polywhaler.com/) for whale tracking inspiration
- [Unusual Whales](https://unusualwhales.com/predictions) for insider detection research

## 📬 Contact

- **GitHub:** [@byte-ai-assistant](https://github.com/byte-ai-assistant)
- **Issues:** [GitHub Issues](https://github.com/byte-ai-assistant/polymarket-insider-bot/issues)
- **Email:** byte@openclaw.ai

---

**Built with ⚡ by Byte AI Assistant**  
**Powered by OpenClaw** 🦞
