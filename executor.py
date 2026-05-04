"""
Transaction Executor — исполнение арбитражных транзакций на Polygon
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional, Tuple
from web3 import Web3
from web3.middleware import geth_poa_middleware

logger = logging.getLogger(__name__)

# ABI контракта FlashLoanArbitrage (минимальный набор)
CONTRACT_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "routeId", "type": "uint256"}],
        "name": "executeArbitrage",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "dexA", "type": "address"},
                    {"internalType": "address", "name": "dexB", "type": "address"},
                    {"internalType": "uint8", "name": "dexAType", "type": "uint8"},
                    {"internalType": "uint8", "name": "dexBType", "type": "uint8"},
                    {"internalType": "address", "name": "tokenBorrow", "type": "address"},
                    {"internalType": "address", "name": "tokenIntermed", "type": "address"},
                    {"internalType": "uint24", "name": "feeA", "type": "uint24"},
                    {"internalType": "uint24", "name": "feeB", "type": "uint24"},
                    {"internalType": "uint256", "name": "amount", "type": "uint256"},
                    {"internalType": "uint256", "name": "minProfit", "type": "uint256"}
                ],
                "internalType": "struct FlashLoanArbitrage.ArbitrageRoute",
                "name": "route",
                "type": "tuple"
            }
        ],
        "name": "addRoute",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "address", "name": "token", "type": "address"}],
        "name": "withdrawToken",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "totalProfit",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "address", "name": "token", "type": "address"}],
        "name": "getTokenBalance",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "tokenBorrow", "type": "address"},
            {"indexed": False, "name": "amount", "type": "uint256"},
            {"indexed": False, "name": "profit", "type": "uint256"},
            {"indexed": False, "name": "dexA", "type": "address"},
            {"indexed": False, "name": "dexB", "type": "address"}
        ],
        "name": "ArbitrageExecuted",
        "type": "event"
    }
]

DEX_TYPE_MAP = {"V2": 0, "V3": 1}


class ArbitrageExecutor:
    """Исполняет арбитражные транзакции через смарт-контракт."""

    def __init__(self, w3: Web3, contract_address: str, private_key: str, wallet: str):
        self.w3 = w3
        self.private_key = private_key
        self.wallet = Web3.to_checksum_address(wallet)
        self.contract = w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=CONTRACT_ABI
        )
        self.nonce = w3.eth.get_transaction_count(self.wallet)
        self.executed_count = 0
        self.total_profit_usd = 0.0

    def setup_routes_on_chain(self, routes: list, token_decimals: dict) -> list:
        """
        Добавить маршруты в смарт-контракт (нужно сделать один раз).
        Returns list of on-chain route IDs.
        """
        route_ids = []
        for i, route in enumerate(routes):
            token_borrow_sym = self._get_token_symbol(route["tokenBorrow"], token_decimals)
            decimals_borrow = token_decimals.get(token_borrow_sym, 18)

            flash_amount_wei = int(route["flashAmount"] * (10 ** decimals_borrow))
            min_profit_wei = int(route["minProfitUSD"] * (10 ** decimals_borrow))

            route_tuple = (
                Web3.to_checksum_address(route["dexA"]),
                Web3.to_checksum_address(route["dexB"]),
                DEX_TYPE_MAP.get(route["dexAType"], 0),
                DEX_TYPE_MAP.get(route["dexBType"], 0),
                Web3.to_checksum_address(route["tokenBorrow"]),
                Web3.to_checksum_address(route["tokenIntermed"]),
                route.get("feeA", 3000),
                route.get("feeB", 3000),
                flash_amount_wei,
                min_profit_wei
            )

            tx_hash = self._send_tx(
                self.contract.functions.addRoute(route_tuple)
            )
            if tx_hash:
                logger.info(f"Route {i} '{route['name']}' added: {tx_hash.hex()}")
                route_ids.append(i)
            else:
                logger.error(f"Failed to add route {i}")

        return route_ids

    def execute_arbitrage(
        self,
        route_id: int,
        gas_price_wei: int,
        gas_limit: int = 500_000,
        gas_multiplier: float = 1.2
    ) -> Optional[str]:
        """
        Исполнить арбитражную сделку.
        Returns tx hash или None при ошибке.
        """
        boosted_gas = int(gas_price_wei * gas_multiplier)

        try:
            tx = self.contract.functions.executeArbitrage(route_id).build_transaction({
                "from": self.wallet,
                "gas": gas_limit,
                "gasPrice": boosted_gas,
                "nonce": self._get_nonce(),
            })

            signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)

            logger.info(f"🚀 Tx sent: {tx_hash.hex()}")
            return tx_hash.hex()

        except Exception as e:
            logger.error(f"Execute error: {e}")
            return None

    def wait_for_receipt(self, tx_hash: str, timeout: int = 120) -> Optional[dict]:
        """Ждать подтверждения транзакции."""
        try:
            receipt = self.w3.eth.wait_for_transaction_receipt(
                tx_hash, timeout=timeout
            )
            if receipt["status"] == 1:
                logger.info(f"✅ Tx confirmed in block {receipt['blockNumber']}")
                self.executed_count += 1
                return receipt
            else:
                logger.warning(f"❌ Tx reverted: {tx_hash}")
                return None
        except Exception as e:
            logger.error(f"Receipt error: {e}")
            return None

    def withdraw_profits(self, token_address: str) -> Optional[str]:
        """Вывести накопленную прибыль."""
        try:
            balance = self.contract.functions.getTokenBalance(
                Web3.to_checksum_address(token_address)
            ).call()

            if balance == 0:
                logger.info("Nothing to withdraw")
                return None

            tx_hash = self._send_tx(
                self.contract.functions.withdrawToken(
                    Web3.to_checksum_address(token_address)
                )
            )
            logger.info(f"💰 Profit withdrawn: {tx_hash}")
            return tx_hash
        except Exception as e:
            logger.error(f"Withdraw error: {e}")
            return None

    def _send_tx(self, func, gas: int = 200_000) -> Optional[bytes]:
        gas_price = self.w3.eth.gas_price
        try:
            tx = func.build_transaction({
                "from": self.wallet,
                "gas": gas,
                "gasPrice": gas_price,
                "nonce": self._get_nonce(),
            })
            signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            return tx_hash
        except Exception as e:
            logger.error(f"Tx error: {e}")
            return None

    def _get_nonce(self) -> int:
        on_chain = self.w3.eth.get_transaction_count(self.wallet, "pending")
        nonce = max(self.nonce, on_chain)
        self.nonce = nonce + 1
        return nonce

    def _get_token_symbol(self, address: str, token_decimals: dict) -> str:
        from config import TOKENS
        for sym, addr in TOKENS.items():
            if addr.lower() == address.lower():
                return sym
        return "UNKNOWN"
