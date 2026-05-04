"""
MEV Arbitrage Bot — Polygon
============================
Главный скрипт. Мониторит цены на DEX и автоматически исполняет арбитраж.

Запуск:
    python bot.py                  # обычный режим
    python bot.py --dry-run        # только мониторинг, без реальных сделок
    python bot.py --setup-routes   # добавить маршруты в контракт (один раз)
    python bot.py --withdraw       # вывести прибыль с контракта
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from web3 import Web3
from web3.middleware import geth_poa_middleware

import config
from dex_monitor import DEXMonitor
from executor import ArbitrageExecutor

# ─── Логирование ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("MEV_BOT")

# ASCII баннер
BANNER = """
╔══════════════════════════════════════════════╗
║     MEV ARBITRAGE BOT — POLYGON NETWORK     ║
║   Uniswap V3 | QuickSwap | SushiSwap        ║
╚══════════════════════════════════════════════╝
"""


class MEVBot:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.running = True
        self.scan_count = 0
        self.found_opportunities = 0
        self.executed_trades = 0
        self.total_profit_usd = 0.0
        self.start_time = datetime.now()

        # ─── Подключение к Polygon ───────────────────────────────────────────
        logger.info(f"Подключаюсь к Polygon: {config.POLYGON_RPC_URL}")
        self.w3 = Web3(Web3.HTTPProvider(config.POLYGON_RPC_URL))
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)  # Polygon PoS

        if not self.w3.is_connected():
            logger.error("❌ Не удалось подключиться к Polygon!")
            sys.exit(1)

        chain_id = self.w3.eth.chain_id
        block = self.w3.eth.block_number
        logger.info(f"✅ Подключён к Polygon | Chain ID: {chain_id} | Block: {block}")

        # ─── Проверка баланса ────────────────────────────────────────────────
        if config.WALLET_ADDRESS:
            balance = self.w3.eth.get_balance(
                Web3.to_checksum_address(config.WALLET_ADDRESS)
            )
            balance_matic = balance / 1e18
            logger.info(f"💰 Баланс кошелька: {balance_matic:.4f} MATIC")
            if balance_matic < 0.5:
                logger.warning("⚠️  Мало MATIC для газа! Нужно минимум 0.5 MATIC.")

        # ─── Инициализация компонентов ───────────────────────────────────────
        self.monitor = DEXMonitor(self.w3)

        if not dry_run:
            assert config.PRIVATE_KEY, "PRIVATE_KEY не задан в .env!"
            assert config.CONTRACT_ADDRESS, "CONTRACT_ADDRESS не задан в .env!"
            self.executor = ArbitrageExecutor(
                w3=self.w3,
                contract_address=config.CONTRACT_ADDRESS,
                private_key=config.PRIVATE_KEY,
                wallet=config.WALLET_ADDRESS
            )
        else:
            self.executor = None
            logger.info("🔍 DRY RUN режим — сделки не будут исполняться")

    def run(self):
        """Основной цикл мониторинга и арбитража."""
        print(BANNER)
        logger.info(f"Старт! Мониторю {len(config.ARBITRAGE_ROUTES)} маршрутов...")
        logger.info(f"Интервал сканирования: {config.SCAN_INTERVAL_SEC}s")
        logger.info(f"Мин. прибыль: ${config.MIN_PROFIT_USD}")
        logger.info("-" * 50)

        # Кэш: last_executed[route_name] = timestamp
        last_executed: dict = {}
        cooldown_sec = 30  # не исполнять один маршрут чаще раза в 30 сек

        while self.running:
            try:
                self.scan_count += 1
                self._scan_and_execute(last_executed, cooldown_sec)

                # Каждые 100 сканов — выводим статистику
                if self.scan_count % 100 == 0:
                    self._print_stats()

                time.sleep(config.SCAN_INTERVAL_SEC)

            except KeyboardInterrupt:
                logger.info("\n⛔ Бот остановлен пользователем.")
                self._print_stats()
                break
            except Exception as e:
                logger.error(f"Ошибка в главном цикле: {e}", exc_info=True)
                time.sleep(5)

    def _scan_and_execute(self, last_executed: dict, cooldown: int):
        """Один цикл проверки всех маршрутов."""
        gas_price_wei, gas_gwei = self.monitor.get_gas_price()

        # Пропускаем если газ слишком высокий
        if gas_gwei > config.MAX_GAS_GWEI:
            logger.debug(f"⛽ Газ слишком высокий: {gas_gwei:.0f} Gwei > {config.MAX_GAS_GWEI}")
            return

        matic_usd = self.monitor.get_matic_price_usd()

        for route_id, route in enumerate(config.ARBITRAGE_ROUTES):
            try:
                # Cooldown проверка
                last_exec = last_executed.get(route["name"], 0)
                if time.time() - last_exec < cooldown:
                    continue

                # Определяем decimals токенов
                token_borrow_sym = self._token_symbol(route["tokenBorrow"])
                token_intermed_sym = self._token_symbol(route["tokenIntermed"])
                dec_borrow = config.TOKEN_DECIMALS.get(token_borrow_sym, 18)
                dec_intermed = config.TOKEN_DECIMALS.get(token_intermed_sym, 18)

                # Проверяем возможность
                is_profitable, profit_usd, details = self.monitor.check_arbitrage_opportunity(
                    route=route,
                    token_decimals_borrow=dec_borrow,
                    token_decimals_intermed=dec_intermed,
                    matic_price_usd=matic_usd,
                    gas_price_gwei=gas_gwei
                )

                if is_profitable:
                    self.found_opportunities += 1
                    logger.info(
                        f"🎯 OPPORTUNITY! {route['name']}\n"
                        f"   Прибыль: ${profit_usd:.2f} | "
                        f"Газ: {gas_gwei:.0f} Gwei | "
                        f"Out: {details['out_amount_human']:.4f}"
                    )

                    if not self.dry_run:
                        self._execute(route_id, gas_price_wei, last_executed, profit_usd)
                    else:
                        logger.info("   [DRY RUN] Сделка не исполнена.")

                else:
                    logger.debug(
                        f"  {route['name']}: ${details.get('net_profit_usd', 0):.3f}"
                        f" (нет прибыли)"
                    )

            except Exception as e:
                logger.debug(f"Route {route.get('name', route_id)} error: {e}")

    def _execute(
        self,
        route_id: int,
        gas_price_wei: int,
        last_executed: dict,
        expected_profit: float
    ):
        """Исполнить арбитражную сделку."""
        route = config.ARBITRAGE_ROUTES[route_id]
        logger.info(f"🚀 Исполняю арбитраж: {route['name']}...")

        tx_hash = self.executor.execute_arbitrage(
            route_id=route_id,
            gas_price_wei=gas_price_wei,
            gas_limit=config.GAS_LIMIT,
            gas_multiplier=config.GAS_MULTIPLIER
        )

        if tx_hash:
            receipt = self.executor.wait_for_receipt(tx_hash)
            if receipt:
                self.executed_trades += 1
                self.total_profit_usd += expected_profit
                last_executed[route["name"]] = time.time()
                logger.info(
                    f"✅ УСПЕХ! Tx: {tx_hash}\n"
                    f"   Прибыль ≈ ${expected_profit:.2f} | "
                    f"Всего сделок: {self.executed_trades}"
                )
            else:
                logger.warning(f"⚠️  Транзакция откатилась: {tx_hash}")
        else:
            logger.error("❌ Не удалось отправить транзакцию")

    def setup_routes(self):
        """Добавить маршруты в смарт-контракт (нужно один раз)."""
        assert self.executor, "Нужен реальный режим (не dry-run)"
        logger.info("Добавляю маршруты в смарт-контракт...")
        ids = self.executor.setup_routes_on_chain(
            config.ARBITRAGE_ROUTES,
            config.TOKEN_DECIMALS
        )
        logger.info(f"✅ Добавлено маршрутов: {len(ids)}")

    def withdraw(self):
        """Вывести прибыль с контракта."""
        assert self.executor, "Нужен реальный режим (не dry-run)"
        for sym, addr in config.TOKENS.items():
            logger.info(f"Проверяю баланс {sym}...")
            self.executor.withdraw_profits(addr)

    def _print_stats(self):
        uptime = datetime.now() - self.start_time
        logger.info(
            f"\n{'='*50}\n"
            f"📊 СТАТИСТИКА\n"
            f"   Uptime:          {uptime}\n"
            f"   Сканирований:    {self.scan_count:,}\n"
            f"   Найдено возм-й:  {self.found_opportunities}\n"
            f"   Исполнено сделок:{self.executed_trades}\n"
            f"   Прибыль ≈ USD:   ${self.total_profit_usd:.2f}\n"
            f"{'='*50}"
        )

    def _token_symbol(self, address: str) -> str:
        for sym, addr in config.TOKENS.items():
            if addr.lower() == address.lower():
                return sym
        return "UNKNOWN"


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MEV Arbitrage Bot — Polygon")
    parser.add_argument("--dry-run", action="store_true",
                        help="Только мониторинг, без реальных сделок")
    parser.add_argument("--setup-routes", action="store_true",
                        help="Добавить маршруты в контракт (один раз)")
    parser.add_argument("--withdraw", action="store_true",
                        help="Вывести прибыль с контракта")
    args = parser.parse_args()

    bot = MEVBot(dry_run=args.dry_run or args.setup_routes or args.withdraw)

    if args.setup_routes:
        bot.dry_run = False
        bot.executor = ArbitrageExecutor(
            w3=bot.w3,
            contract_address=config.CONTRACT_ADDRESS,
            private_key=config.PRIVATE_KEY,
            wallet=config.WALLET_ADDRESS
        )
        bot.setup_routes()
    elif args.withdraw:
        bot.dry_run = False
        bot.executor = ArbitrageExecutor(
            w3=bot.w3,
            contract_address=config.CONTRACT_ADDRESS,
            private_key=config.PRIVATE_KEY,
            wallet=config.WALLET_ADDRESS
        )
        bot.withdraw()
    else:
        bot.run()
