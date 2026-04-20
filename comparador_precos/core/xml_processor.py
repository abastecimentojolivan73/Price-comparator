"""
core/xml_processor.py - Parser seguro de NF-e (XML fiscal brasileiro).
Usa lxml com namespaces do Portal da Fazenda e retorna itens via generator.
"""
import os
from decimal import Decimal
from lxml import etree
from utils.helpers import get_logger, to_decimal, safe_str

logger = get_logger(__name__)

# Namespace oficial da NF-e
NF_NS = "http://www.portalfiscal.inf.br/nfe"
NS = {"nfe": NF_NS}


def _find(element, xpath_expr: str):
    """Helper que busca um elemento via XPath e retorna None se não encontrado."""
    results = element.xpath(xpath_expr, namespaces=NS)
    return results[0] if results else None


def _text(element, xpath_expr: str, default: str = "") -> str:
    """Retorna o texto de um elemento XPath de forma segura."""
    el = _find(element, xpath_expr)
    if el is None:
        return default
    text = el.text if hasattr(el, 'text') else el
    return safe_str(text, default)


def parse_nfe_file(filepath: str) -> tuple[dict | None, list]:
    """
    Faz o parse de um arquivo XML de NF-e e extrai os dados relevantes.

    Retorna:
        (nfe_data, erros)
        nfe_data: dict com dados do emitente e 'itens' (lista de dicts)
        erros: lista de strings com mensagens de erro/aviso
    """
    erros = []

    if not os.path.isfile(filepath):
        return None, [f"Arquivo não encontrado: {filepath}"]

    try:
        tree = etree.parse(filepath)
        root = tree.getroot()
    except etree.XMLSyntaxError as e:
        erros.append(f"XML malformado em '{os.path.basename(filepath)}': {e}")
        logger.error("XMLSyntaxError em %s: %s", filepath, e)
        return None, erros
    except Exception as e:
        erros.append(f"Erro ao abrir '{os.path.basename(filepath)}': {e}")
        logger.error("Erro ao abrir %s: %s", filepath, e)
        return None, erros

    # Detecta o namespace dinamicamente caso seja diferente
    tag = root.tag
    if "{" in tag:
        detected_ns = tag.split("}")[0].strip("{")
        ns = {"nfe": detected_ns}
    else:
        ns = NS

    try:
        # Caminho para a NF-e pode estar envolvido em nfeProc ou diretamente
        nfe_node = root.find(".//nfe:NFe/nfe:infNFe", ns)
        if nfe_node is None:
            nfe_node = root.find("nfe:infNFe", ns)
        if nfe_node is None:
            erros.append(f"Estrutura NF-e não encontrada em '{os.path.basename(filepath)}'")
            return None, erros

        # Dados do emitente/posto
        cnpj_el = nfe_node.find(".//nfe:emit/nfe:CNPJ", ns)
        cnpj_emitente = safe_str(cnpj_el.text if cnpj_el is not None else "")
        emitente_nome = safe_str(
            nfe_node.findtext(".//nfe:emit/nfe:xFant", namespaces=ns)
            or nfe_node.findtext(".//nfe:emit/nfe:xNome", namespaces=ns)
        )
        emitente_cidade = safe_str(
            nfe_node.findtext(".//nfe:emit/nfe:enderEmit/nfe:xMun", namespaces=ns)
        )
        emitente_uf = safe_str(
            nfe_node.findtext(".//nfe:emit/nfe:enderEmit/nfe:UF", namespaces=ns)
        )

        if not cnpj_emitente:
            erros.append(f"CNPJ do emitente não encontrado em '{os.path.basename(filepath)}'")

        itens = list(_extract_items(nfe_node, ns, os.path.basename(filepath), erros))

        return {
            "cnpj_emitente": cnpj_emitente,
            "emitente_nome": emitente_nome,
            "emitente_cidade": emitente_cidade,
            "emitente_uf": emitente_uf,
            "itens": itens,
        }, erros

    except Exception as e:
        msg = f"Erro inesperado ao processar '{os.path.basename(filepath)}': {e}"
        erros.append(msg)
        logger.error(msg)
        return None, erros


def _extract_items(nfe_node, ns: dict, filename: str, erros: list):
    """
    Generator que percorre os elementos <det> de uma NF-e e extrai os campos de cada item.
    Usa Decimal para precisão financeira.
    """
    det_nodes = nfe_node.findall("nfe:det", ns)

    if not det_nodes:
        erros.append(f"Nenhum item (det) encontrado em '{filename}'")
        return

    for det in det_nodes:
        try:
            prod = det.find("nfe:prod", ns)
            if prod is None:
                erros.append(f"Elemento <prod> ausente em item de '{filename}'")
                continue

            c_prod = safe_str(prod.findtext("nfe:cProd", namespaces=ns))
            x_prod = safe_str(prod.findtext("nfe:xProd", namespaces=ns))
            q_com_raw = prod.findtext("nfe:qCom", namespaces=ns)
            v_prod_raw = prod.findtext("nfe:vProd", namespaces=ns)
            v_desc_raw = prod.findtext("nfe:vDesc", namespaces=ns)

            q_com = to_decimal(q_com_raw)
            v_prod = to_decimal(v_prod_raw)
            v_desc = to_decimal(v_desc_raw, default=Decimal("0"))

            if q_com == 0:
                erros.append(
                    f"Quantidade zero para produto '{c_prod}' em '{filename}' — item ignorado"
                )
                continue

            # Preço unitário líquido: (vProd - vDesc) / qCom
            preco_unitario = (v_prod - v_desc) / q_com
            preco_unitario = preco_unitario.quantize(Decimal("0.0001"))

            yield {
                "codigo_produto": c_prod,
                "descricao": x_prod,
                "qtd": float(q_com),
                "valor_total": float(v_prod - v_desc),
                "preco_xml": float(preco_unitario),
            }

        except Exception as e:
            erros.append(f"Erro ao processar item em '{filename}': {e}")
            logger.warning("Erro ao extrair item de %s: %s", filename, e)


def iter_xml_files(folder: str):
    """
    Generator que produz os caminhos completos de arquivos .xml em uma pasta.
    Não percorre subdiretórios.
    """
    if not os.path.isdir(folder):
        logger.warning("Pasta não encontrada: %s", folder)
        return

    for filename in os.listdir(folder):
        if filename.lower().endswith(".xml"):
            yield os.path.join(folder, filename)
