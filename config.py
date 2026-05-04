"""
MEV Arbitrage Bot — Конфигурация для Polygon
============================================
⚠️  ВАЖНО: Никогда не загружай этот файл с реальным PRIVATE_KEY в публичный репозиторий!
    Используй переменные окружения или .env файл.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── RPC Подключение ──────────────────────────────────────────────────────────
POLYGON_RPC_URL = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
# Рекомендуется использовать приватный RPC для скорости:
# Alchemy: https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY
# Infura:  https://polygon-mainnet.infura.io/v3/YOUR_KEY
# QuickNode: https://xxx.matic.quiknode.pro/YOUR_KEY

# ─── Кошелёк ─────────────────────────────────────────────────────────────────
PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")          # 0x... приватный ключ
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "")    # 0x... адрес кошелька

# ─── Контракт ─────────────────────────────────────────────────────────────────
CONTRACT_ADDRESS = os.getenv("CONTRACT_ADDRESS", "")  # После деплоя

# ─── Aave V3 на Polygon ───────────────────────────────────────────────────────
AAVE_POOL_ADDRESS_PROVIDER = "0xa97684ead0e402dC232d5A977953DF7ECBaB3CDb"

# ─── DEX Роутеры на Polygon ───────────────────────────────────────────────────
DEX_ROUTERS = {
    "uniswap_v3":  "0xE592427A0AEce92De3Edee1F18E0157C05861564",
    "quickswap_v2": "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff",
    "sushiswap":   "0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506",
    "uniswap_v2":  "0xedf6066a2b290C185783862C7F4776A2C8077AD1",
}

# ─── Токены на Polygon ────────────────────────────────────────────────────────
TOKENS = {
    "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
    "WETH":   "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
    "USDC":   "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "USDT":   "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
    "DAI":    "0x8f3Cf7ad23Cd3CaDbD9735AFf958023239c6A063",
    "WBTC":   "0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6",
}

# ─── Арбитражные маршруты ─────────────────────────────────────────────────────
# Каждый маршрут: покупаем на DEX A, продаём на DEX B
ARBITRAGE_ROUTES = [
    {
        "name": "USDC → WETH: QuickSwap→Uniswap",
        "dexA": DEX_ROUTERS["quickswap_v2"],
        "dexB": DEX_ROUTERS["uniswap_v3"],
        "dexAType": "V2",
        "dexBType": "V3",
        "tokenBorrow": TOKENS["USDC"],
        "tokenIntermed": TOKENS["WETH"],
        "feeB": 500,           # 0.05% pool на Uniswap V3
        "flashAmount": 10_000,  # 10,000 USDC (в обычных единицах, не wei)
        "minProfitUSD": 5,     # мин. прибыль $5
    },
    {
        "name": "USDC → WMATIC: SushiSwap→QuickSwap",
        "dexA": DEX_ROUTERS["sushiswap"],
        "dexB": DEX_ROUTERS["quickswap_v2"],
        "dexAType": "V2",
        "dexBType": "V2",
        "tokenBorrow": TOKENS["USDC"],
        "tokenIntermed": TOKENS["WMATIC"],
        "feeB": 3000,
        "flashAmount": 5_000,
        "minProfitUSD": 3,
    },
    {
        "name": "WMATIC → USDC: Uniswap→SushiSwap",
        "dexA": DEX_ROUTERS["uniswap_v3"],
        "dexB": DEX_ROUTERS["sushiswap"],
        "dexAType": "V3",
        "dexBType": "V2",
        "tokenBorrow": TOKENS["WMATIC"],
        "tokenIntermed": TOKENS["USDC"],
        "feeA": 3000,
        "feeB": 3000,
        "flashAmount": 5_000,  # 5000 WMATIC
        "minProfitUSD": 3,
    },
    {
        "name": "WETH → USDT: QuickSwap→SushiSwap",
        "dexA": DEX_ROUTERS["quickswap_v2"],
        "dexB": DEX_ROUTERS["sushiswap"],
        "dexAType": "V2",
        "dexBType": "V2",
        "tokenBorrow": TOKENS["WETH"],
        "tokenIntermed": TOKENS["USDT"],
        "feeB": 3000,
        "flashAmount": 5,      # 5 WETH
        "minProfitUSD": 5,
    },
]

# ─── Параметры исполнения ─────────────────────────────────────────────────────
GAS_LIMIT = 500_000          # газ лимит для арбитражной транзакции
GAS_MULTIPLIER = 1.2         # множитель к текущей цене газа
MAX_GAS_GWEI = 500           # не исполнять если газ > 500 Gwei
SLIPPAGE_TOLERANCE = 0.005   # 0.5% slippage

# ─── Мониторинг ──────────────────────────────────────────────────────────────
SCAN_INTERVAL_SEC = 1.0      # интервал проверки цен (секунды)
MIN_PROFIT_USD = 3.0         # минимальная прибыль в USD для исполнения
LOG_LEVEL = "INFO"           # DEBUG / INFO / WARNING

# ─── Aave Flash Loan fee ─────────────────────────────────────────────────────
AAVE_FLASH_LOAN_FEE = 0.0009  # 0.09%

# ─── Количество десятичных знаков токенов ─────────────────────────────────────
TOKEN_DECIMALS = {
    "WMATIC": 18,
    "WETH":   18,
    "USDC":   6,
    "USDT":   6,
    "DAI":    18,
    "WBTC":   8,
}
