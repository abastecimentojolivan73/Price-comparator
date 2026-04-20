"""
utils/helpers.py - Funções auxiliares, logging e formatação.
"""
import logging
import os
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import datetime


LOG_FILE = "comparador_precos.log"


def setup_logging():
    """Configura o logging para arquivo e console."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger(__name__).info("Logging inicializado. Arquivo: %s", LOG_FILE)


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger nomeado."""
    return logging.getLogger(name)


def to_decimal(value, default: Decimal = Decimal("0"), places: int = 4) -> Decimal:
    """
    Converte um valor para Decimal com arredondamento seguro.
    Retorna `default` em caso de falha de conversão.
    """
    try:
        d = Decimal(str(value))
        quantize_str = Decimal("1." + "0" * places)
        return d.quantize(quantize_str, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return default


def format_currency(value: Decimal) -> str:
    """Formata um Decimal como moeda brasileira (2 casas decimais)."""
    try:
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def format_percent(value: Decimal) -> str:
    """Formata um Decimal como percentual com 2 casas decimais."""
    try:
        return f"{value:.2f}%"
    except Exception:
        return "0,00%"


def now_str() -> str:
    """Retorna a data/hora atual formatada para exibição."""
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def safe_str(value, default: str = "") -> str:
    """Converte valor para string de forma segura."""
    if value is None:
        return default
    return str(value).strip()


def ensure_dir(path: str):
    """Cria o diretório se não existir."""
    os.makedirs(path, exist_ok=True)


def format_cnpj(value) -> str:
    """Formata um CNPJ para o padrão 00.000.000/0000-00 quando possível."""
    raw = safe_str(value)
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 14:
        return raw
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
