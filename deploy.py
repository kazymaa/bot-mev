"""
deploy.py — Деплой контракта FlashLoanArbitrage на Polygon

Требования:
    pip install web3 python-dotenv py-solc-x

Запуск:
    python deploy.py
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from web3 import Web3
from web3.middleware import geth_poa_middleware

load_dotenv()

def deploy_contract():
    print("=" * 55)
    print("  FlashLoanArbitrage — Деплой на Polygon Mainnet")
    print("=" * 55)

    # ─── Подключение ────────────────────────────────────────────
    rpc_url = os.getenv("POLYGON_RPC_URL", "https://polygon-rpc.com")
    private_key = os.getenv("PRIVATE_KEY", "")
    wallet = os.getenv("WALLET_ADDRESS", "")

    if not private_key or not wallet:
        print("❌ Задай PRIVATE_KEY и WALLET_ADDRESS в .env файле!")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    if not w3.is_connected():
        print(f"❌ Не удалось подключиться к {rpc_url}")
        sys.exit(1)

    balance = w3.eth.get_balance(Web3.to_checksum_address(wallet))
    matic = balance / 1e18
    print(f"✅ Подключён к Polygon | Баланс: {matic:.4f} MATIC")

    if matic < 1.0:
        print("⚠️  Нужно минимум 1 MATIC для деплоя!")
        sys.exit(1)

    # ─── Компиляция через py-solc-x ────────────────────────────
    try:
        from solcx import compile_files, install_solc
        print("Устанавливаю solc 0.8.20...")
        install_solc("0.8.20")

        print("Компилирую контракт...")
        compiled = compile_files(
            ["contracts/FlashLoanArbitrage.sol"],
            output_values=["abi", "bin"],
            solc_version="0.8.20",
            import_remappings={
                "@aave/core-v3": "node_modules/@aave/core-v3",
                "@openzeppelin": "node_modules/@openzeppelin",
            }
        )

        contract_key = "contracts/FlashLoanArbitrage.sol:FlashLoanArbitrage"
        abi = compiled[contract_key]["abi"]
        bytecode = compiled[contract_key]["bin"]

    except ImportError:
        print("\n⚠️  py-solc-x не установлен.")
        print("Установи: pip install py-solc-x")
        print("\nАльтернативно — скомпилируй контракт через Remix IDE:")
        print("  https://remix.ethereum.org")
        print("И передай ABI и bytecode вручную.")
        sys.exit(1)

    # ─── Деплой ─────────────────────────────────────────────────
    AAVE_POOL_ADDRESS_PROVIDER = "0xa97684ead0e402dC232d5A977953DF7ECBaB3CDb"

    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(wallet))
    gas_price = w3.eth.gas_price

    print(f"Деплою контракт... (газ: {gas_price/1e9:.0f} Gwei)")

    tx = Contract.constructor(AAVE_POOL_ADDRESS_PROVIDER).build_transaction({
        "from": Web3.to_checksum_address(wallet),
        "nonce": nonce,
        "gasPrice": gas_price,
        "gas": 3_000_000,
    })

    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
    print(f"Tx: {tx_hash.hex()}")
    print("Жду подтверждения...")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

    if receipt["status"] == 1:
        contract_addr = receipt["contractAddress"]
        print(f"\n✅ КОНТРАКТ ЗАДЕПЛОЕН!")
        print(f"   Адрес: {contract_addr}")
        print(f"   Block: {receipt['blockNumber']}")
        print(f"   Gas:   {receipt['gasUsed']:,}")
        print(f"\n📝 Добавь в .env файл:")
        print(f"   CONTRACT_ADDRESS={contract_addr}")

        # Сохраняем ABI
        with open("abi/FlashLoanArbitrage.json", "w") as f:
            json.dump(abi, f, indent=2)
        print(f"\n💾 ABI сохранён в abi/FlashLoanArbitrage.json")

    else:
        print("❌ Деплой неудачен! Проверь газ и баланс.")
        sys.exit(1)


if __name__ == "__main__":
    deploy_contract()
