"""
core/comparator.py - Regras de negócio para comparação de preços e determinação de status.
"""
from decimal import Decimal, ROUND_HALF_UP
from utils.helpers import get_logger, to_decimal
from core.database import get_tolerancia

logger = get_logger(__name__)

# Padrão quando não há configuração específica de tolerância
DEFAULT_TOLERANCIA_TIPO = "VALOR"
DEFAULT_TOLERANCIA_VALOR = Decimal("0.01")  # 1 centavo de tolerância padrão


def compare_price(
    cnpj: str,
    codigo_produto: str,
    preco_xml: float,
    preco_api: float,
    tipo_combustivel: str = "",
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

    # Diferença assinada e percentual assinado em relação ao preço da API
    diff_signed = (preco_xml_d - preco_api_d).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    diff_abs = abs(diff_signed).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    if preco_api_d > 0:
        diff_pct = ((diff_signed / preco_api_d) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        diff_pct = Decimal("0.00")

    # Busca tolerância configurada para este CNPJ + produto
    config = get_tolerancia(cnpj, codigo_produto, tipo_combustivel)

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
    elif diff_signed < 0:
        status = "REDUCAO"
    elif diff_abs <= limite * 2:
        status = "ALERTA"
    else:
        status = "CRITICO"

    return {
        "diff_abs": float(diff_signed),
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
    numero_nota: str = "",
    tipo_combustivel: str = "",
    posto_referencia: str = "",
    motivo: str = "",
    origem_comparacao: str = "cache_codigo",
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
        tipo_combustivel=tipo_combustivel,
    )

    return {
        "nome_arquivo": nome_arquivo,
        "cnpj_fornecedor": cnpj_fornecedor,
        "emitente_nome": emitente_nome,
        "emitente_cidade": emitente_cidade,
        "emitente_uf": emitente_uf,
        "numero_nota": numero_nota,
        "tipo_combustivel": tipo_combustivel,
        "posto_referencia": posto_referencia,
        "motivo": motivo,
        "origem_comparacao": origem_comparacao,
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
