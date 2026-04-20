"""
core/comparator.py - Regras de negócio para comparação de preços e determinação de status.
"""
from decimal import Decimal, ROUND_HALF_UP
from utils.helpers import get_logger, to_decimal
from core.database import get_tolerancia

logger = get_logger(__name__)

# Padrão quando não há configuração específica de tolerância
DEFAULT_TOLERANCIA_TIPO = "%"
DEFAULT_TOLERANCIA_VALOR = Decimal("5.0")  # 5% de tolerância padrão


def compare_price(
    cnpj: str,
    codigo_produto: str,
    preco_xml: float,
    preco_api: float,
) -> dict:
    """
    Compara o preço extraído do XML com o preço de referência da API.

    Lógica de status:
        - OK:      diff_abs <= limite
        - ALERTA:  limite < diff_abs <= limite * 2
        - CRITICO: diff_abs > limite * 2

    Retorna um dict com:
        diff_abs, diff_pct, status, tolerancia_tipo, tolerancia_valor, limite
    """
    preco_xml_d = to_decimal(preco_xml)
    preco_api_d = to_decimal(preco_api)

    # Diferença absoluta e percentual
    diff_abs = abs(preco_xml_d - preco_api_d).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    if preco_api_d > 0:
        diff_pct = ((diff_abs / preco_api_d) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        diff_pct = Decimal("0.00")

    # Busca tolerância configurada para este CNPJ + produto
    config = get_tolerancia(cnpj, codigo_produto)

    if config:
        tolerancia_tipo = config["tolerancia_tipo"]
        tolerancia_valor = to_decimal(config["tolerancia_valor"])
    else:
        tolerancia_tipo = DEFAULT_TOLERANCIA_TIPO
        tolerancia_valor = DEFAULT_TOLERANCIA_VALOR
        logger.debug(
            "Tolerância padrão aplicada para CNPJ=%s produto=%s", cnpj, codigo_produto
        )

    # Cálculo do limite conforme tipo
    if tolerancia_tipo == "%":
        limite = (preco_api_d * (tolerancia_valor / 100)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
    else:  # 'VALOR'
        limite = tolerancia_valor.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    # Determinação do status
    if diff_abs <= limite:
        status = "OK"
    elif diff_abs <= limite * 2:
        status = "ALERTA"
    else:
        status = "CRITICO"

    return {
        "diff_abs": float(diff_abs),
        "diff_pct": float(diff_pct),
        "status": status,
        "tolerancia_tipo": tolerancia_tipo,
        "tolerancia_valor": float(tolerancia_valor),
        "limite": float(limite),
    }


def build_result_row(
    nome_arquivo: str,
    cnpj_fornecedor: str,
    item: dict,
    preco_api: float,
    data_processamento: str,
    emitente_nome: str = "",
    emitente_cidade: str = "",
    emitente_uf: str = "",
) -> dict:
    """
    Monta o dict completo de um resultado para inserção no banco ou exportação.

    Parâmetros:
        nome_arquivo: nome do arquivo XML processado
        cnpj_fornecedor: CNPJ do emitente da NF-e
        item: dict com campos extraídos do XML (codigo_produto, descricao, qtd, valor_total, preco_xml)
        preco_api: preço de referência da API (0.0 se não encontrado)
        data_processamento: string com data/hora do processamento
    """
    comparison = compare_price(
        cnpj=cnpj_fornecedor,
        codigo_produto=item["codigo_produto"],
        preco_xml=item["preco_xml"],
        preco_api=preco_api,
    )

    return {
        "nome_arquivo": nome_arquivo,
        "cnpj_fornecedor": cnpj_fornecedor,
        "emitente_nome": emitente_nome,
        "emitente_cidade": emitente_cidade,
        "emitente_uf": emitente_uf,
        "codigo_produto": item["codigo_produto"],
        "descricao": item.get("descricao", ""),
        "qtd": item.get("qtd", 0.0),
        "valor_total": item.get("valor_total", 0.0),
        "preco_xml": item["preco_xml"],
        "preco_api": preco_api,
        "diff_abs": comparison["diff_abs"],
        "diff_pct": comparison["diff_pct"],
        "status": comparison["status"],
        "data_processamento": data_processamento,
    }
