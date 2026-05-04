"""
DEX Price Monitor — мониторинг цен на Uniswap V3, QuickSwap, SushiSwap
"""

import logging
from decimal import Decimal
from typing import Optional, Tuple
from web3 import Web3

logger = logging.getLogger(__name__)

# ─── ABI фрагменты ────────────────────────────────────────────────────────────
UNISWAP_V2_ROUTER_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                   {"internalType": "address[]", "name": "path", "type": "address[]"}],
        "name": "getAmountsOut",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function"
    }
]

UNISWAP_V3_QUOTER_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenIn", "type": "address"},
            {"internalType": "address", "name": "tokenOut", "type": "address"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"},
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
        ],
        "name": "quoteExactInputSingle",
        "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

# Uniswap V3 Quoter на Polygon
UNISWAP_V3_QUOTER = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"


class DEXMonitor:
    """Мониторинг цен на нескольких DEX одновременно."""

    def __init__(self, w3: Web3):
        self.w3 = w3
        self.quoter_v3 = w3.eth.contract(
            address=Web3.to_checksum_address(UNISWAP_V3_QUOTER),
            abi=UNISWAP_V3_QUOTER_ABI
        )

    def get_price_v2(
        self,
        router_address: str,
        token_in: str,
        token_out: str,
        amount_in_wei: int
    ) -> Optional[int]:
        """Получить котировку с V2-совместимой DEX (QuickSwap, SushiSwap)."""
        try:
            router = self.w3.eth.contract(
                address=Web3.to_checksum_address(router_address),
                abi=UNISWAP_V2_ROUTER_ABI
            )
            path = [
                Web3.to_checksum_address(token_in),
                Web3.to_checksum_address(token_out)
            ]
            amounts = router.functions.getAmountsOut(amount_in_wei, path).call()
            return amounts[-1]
        except Exception as e:
            logger.debug(f"V2 price error ({router_address}): {e}")
            return None

    def get_price_v3(
        self,
        token_in: str,
        token_out: str,
        fee: int,
        amount_in_wei: int
    ) -> Optional[int]:
        """Получить котировку с Uniswap V3."""
        try:
            amount_out = self.quoter_v3.functions.quoteExactInputSingle(
                Web3.to_checksum_address(token_in),
                Web3.to_checksum_address(token_out),
                fee,
                amount_in_wei,
                0
            ).call()
            return amount_out
        except Exception as e:
            logger.debug(f"V3 price error: {e}")
            return None

    def get_quote(
        self,
        router: str,
        dex_type: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        fee: int = 3000
    ) -> Optional[int]:
        """Универсальный метод получения котировки."""
        if dex_type == "V3":
            return self.get_price_v3(token_in, token_out, fee, amount_in)
        else:
            return self.get_price_v2(router, token_in, token_out, amount_in)

    def check_arbitrage_opportunity(
        self,
        route: dict,
        token_decimals_borrow: int,
        token_decimals_intermed: int,
        matic_price_usd: float = 0.8,
        gas_price_gwei: float = 100,
        gas_used: int = 400_000
    ) -> Tuple[bool, float, dict]:
        """
        Проверить арбитражную возможность для маршрута.

        Returns:
            (is_profitable, expected_profit_usd, details)
        """
        flash_amount = route["flashAmount"]
        amount_in_wei = int(flash_amount * (10 ** token_decimals_borrow))

        # Шаг 1: tokenBorrow → tokenIntermed на DEX A
        mid_amount = self.get_quote(
            router=route["dexA"],
            dex_type=route["dexAType"],
            token_in=route["tokenBorrow"],
            token_out=route["tokenIntermed"],
            amount_in=amount_in_wei,
            fee=route.get("feeA", 3000)
        )

        if mid_amount is None or mid_amount == 0:
            return False, 0, {"error": "No quote from DEX A"}

        # Шаг 2: tokenIntermed → tokenBorrow на DEX B
        out_amount = self.get_quote(
            router=route["dexB"],
            dex_type=route["dexBType"],
            token_in=route["tokenIntermed"],
            token_out=route["tokenBorrow"],
            amount_in=mid_amount,
            fee=route.get("feeB", 3000)
        )

        if out_amount is None or out_amount == 0:
            return False, 0, {"error": "No quote from DEX B"}

        # ─── Расчёт прибыли ───────────────────────────────────────────────
        # Комиссия Aave flash loan: 0.09%
        aave_fee = int(amount_in_wei * 9 // 10000)
        total_owed = amount_in_wei + aave_fee

        # Стоимость газа в MATIC → USD
        gas_cost_matic = (gas_price_gwei * 1e-9) * gas_used
        gas_cost_usd = gas_cost_matic * matic_price_usd

        # Прибыль в токенах займа
        profit_tokens = out_amount - total_owed
        profit_human = profit_tokens / (10 ** token_decimals_borrow)

        # Конвертация прибыли в USD (упрощённо, если токен = USDC/USDT)
        # Для WMATIC/WETH нужно умножать на текущую цену
        profit_usd = profit_human  # для стейблкоинов = USD

        net_profit_usd = profit_usd - gas_cost_usd

        details = {
            "route": route["name"],
            "flash_amount": flash_amount,
            "mid_amount_human": mid_amount / (10 ** token_decimals_intermed),
            "out_amount_human": out_amount / (10 ** token_decimals_borrow),
            "profit_tokens": profit_human,
            "aave_fee_tokens": aave_fee / (10 ** token_decimals_borrow),
            "gas_cost_usd": gas_cost_usd,
            "net_profit_usd": net_profit_usd,
            "profitable": net_profit_usd > route["minProfitUSD"]
        }

        is_profitable = net_profit_usd > route["minProfitUSD"]
        return is_profitable, net_profit_usd, details

    def get_gas_price(self) -> Tuple[int, float]:
        """Получить текущую цену газа в wei и Gwei."""
        gas_price = self.w3.eth.gas_price
        gas_gwei = gas_price / 1e9
        return gas_price, gas_gwei

    def get_matic_price_usd(self) -> float:
        """
        Получить цену MATIC в USD через QuickSwap.
        WMATIC/USDC пара.
        """
        from config import TOKENS, DEX_ROUTERS
        try:
            amount_in = int(1e18)  # 1 MATIC
            price = self.get_price_v2(
                DEX_ROUTERS["quickswap_v2"],
                TOKENS["WMATIC"],
                TOKENS["USDC"],
                amount_in
            )
            if price:
                return price / 1e6  # USDC имеет 6 decimals
        except Exception:
            pass
        return 0.8  # fallback цена
