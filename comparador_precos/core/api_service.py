"""
core/api_service.py - Consumo da API de referência de preços e atualização do cache local.
"""
import requests
from utils.helpers import get_logger, now_str
from core.database import upsert_preco_api, get_preco_api

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 15  # segundos


def fetch_and_cache_prices(api_url: str, api_token: str) -> tuple[int, list[str]]:
    """
    Busca todos os preços da API de referência e persiste no cache local.

    Espera que a API retorne um JSON com a seguinte estrutura:
        [{"codigo_produto": "ABC123", "preco_referencia": 10.50}, ...]
    ou
        {"data": [{"codigo_produto": "ABC123", "preco_referencia": 10.50}]}

    Retorna:
        (quantidade_atualizada, lista_de_erros)
    """
    errors = []
    count = 0

    headers = _build_headers(api_token)

    try:
        response = requests.get(api_url, headers=headers, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        msg = f"Timeout ao acessar a API: {api_url}"
        logger.error(msg)
        return 0, [msg]
    except requests.exceptions.ConnectionError as e:
        msg = f"Erro de conexão com a API: {e}"
        logger.error(msg)
        return 0, [msg]
    except requests.exceptions.HTTPError as e:
        msg = f"Erro HTTP da API ({response.status_code}): {e}"
        logger.error(msg)
        return 0, [msg]
    except Exception as e:
        msg = f"Erro inesperado ao chamar API: {e}"
        logger.error(msg)
        return 0, [msg]

    try:
        payload = response.json()
    except Exception as e:
        msg = f"Resposta da API não é JSON válido: {e}"
        logger.error(msg)
        return 0, [msg]

    # Suporte a dois formatos: lista direta ou objeto com chave "data"
    if isinstance(payload, dict):
        items = payload.get("data", payload.get("items", payload.get("produtos", [])))
    elif isinstance(payload, list):
        items = payload
    else:
        return 0, ["Formato de resposta da API não reconhecido."]

    data_atualizacao = now_str()

    for item in items:
        try:
            codigo = str(item.get("codigo_produto", item.get("codigo", ""))).strip()
            preco = float(item.get("preco_referencia", item.get("preco", item.get("valor", 0))))
            if not codigo:
                errors.append(f"Item sem codigo_produto ignorado: {item}")
                continue
            if preco < 0:
                errors.append(f"Preço negativo para produto {codigo}: {preco}")
                continue
            if upsert_preco_api(codigo, preco, data_atualizacao):
                count += 1
            else:
                errors.append(f"Falha ao salvar produto {codigo} no cache.")
        except Exception as e:
            errors.append(f"Erro ao processar item {item}: {e}")
            logger.warning("Erro ao processar item de preço: %s — %s", item, e)

    logger.info("Cache atualizado: %d produtos. Erros: %d", count, len(errors))
    return count, errors


def get_price_from_cache(codigo_produto: str) -> float | None:
    """
    Retorna o preço de referência de um produto a partir do cache local.
    Retorna None se o produto não estiver em cache.
    """
    entry = get_preco_api(codigo_produto)
    if entry:
        return float(entry["preco_referencia"])
    return None


def _build_headers(api_token: str) -> dict:
    """Monta os headers HTTP com autenticação Bearer, se token fornecido."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if api_token and api_token.strip():
        headers["Authorization"] = f"Bearer {api_token.strip()}"
    return headers
