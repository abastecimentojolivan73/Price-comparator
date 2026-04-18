"""
core/api_service.py - Consumo da API de referência de preços e atualização do cache local.
"""
import requests
from utils.helpers import get_logger, now_str, clean_cnpj
from core.database import upsert_preco_api, get_preco_api

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 15  # segundos


def fetch_and_cache_prices(api_url: str, api_token: str) -> tuple[int, list[str]]:
    """
    Busca todos os preços da API de referência e persiste no cache local.
    Suporta formato com 'cnpj' (podendo ter múltiplos via ///) e 'preço'.
    Como a API é apenas de Diesel, mapeia para os códigos DIESEL-S10 e DIESEL-S500.
    """
    errors = []
    count = 0

    headers = _build_headers(api_token)

    try:
        response = requests.get(api_url, headers=headers, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
    except Exception as e:
        msg = f"Erro ao acessar a API: {e}"
        logger.error(msg)
        return 0, [msg]

    try:
        payload = response.json()
    except Exception as e:
        msg = f"Resposta da API não é JSON válido: {e}"
        logger.error(msg)
        return 0, [msg]

    if isinstance(payload, dict):
        items = payload.get("data", payload.get("items", payload.get("produtos", [])))
        # Se for um objeto mas não tiver as chaves acima, tenta ver se o próprio payload é o item (raro)
        if not items and "cnpj" in payload:
            items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        return 0, ["Formato de resposta da API não reconhecido."]

    data_atualizacao = now_str()
    # Códigos de produto diesel que usaremos para mapear a API
    DIESEL_CODES = ["DIESEL-S10", "DIESEL-S500"]

    for item in items:
        try:
            raw_cnpj = str(item.get("cnpj", "")).strip()
            # Tenta 'preço' ou 'preco' ou 'preco_referencia'
            raw_preco = item.get("preço", item.get("preco", item.get("preco_referencia", 0)))
            
            # Limpeza do preço se for string (ex: "R$ 6,39")
            if isinstance(raw_preco, str):
                cleaned_preco = raw_preco.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".").strip()
                preco = float(cleaned_preco)
            else:
                preco = float(raw_preco)
            
            if not raw_cnpj:
                errors.append(f"Item sem cnpj ignorado: {item}")
                continue
            
            if preco <= 0:
                errors.append(f"Preço inválido para cnpj {raw_cnpj}: {preco}")
                continue

            # Trata múltiplos CNPJs (ex: "CNPJ1///CNPJ2")
            cnpjs_to_process = [c.strip() for c in raw_cnpj.split("///") if c.strip()]
            
            for single_cnpj in cnpjs_to_process:
                clean_c = clean_cnpj(single_cnpj)
                if not clean_c:
                    continue
                
                # Para cada CNPJ, salva o preço para todos os tipos de diesel suportados
                for d_code in DIESEL_CODES:
                    if upsert_preco_api(clean_c, d_code, preco, data_atualizacao):
                        count += 1
                    else:
                        errors.append(f"Falha ao salvar cnpj {clean_c} produto {d_code} no cache.")

        except Exception as e:
            errors.append(f"Erro ao processar item {item}: {e}")
            logger.warning("Erro ao processar item de preço: %s — %s", item, e)

    logger.info("Cache atualizado: %d entradas (CNPJ x Produto). Erros: %d", count, len(errors))
    return count, errors


def get_price_from_cache(cnpj: str, codigo_produto: str) -> float | None:
    """
    Retorna o preço de referência de um produto/fornecedor a partir do cache local.
    Retorna None se não estiver em cache.
    """
    entry = get_preco_api(cnpj, codigo_produto)
    if entry:
        return float(entry["preco_referencia"])
    return None


def _build_headers(api_token: str) -> dict:
    """Monta os headers HTTP com autenticação Bearer, se token fornecido."""
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if api_token and api_token.strip():
        headers["Authorization"] = f"Bearer {api_token.strip()}"
    return headers
