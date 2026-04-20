"""
core/price_analysis.py - Normalização e cruzamento de preços externos com notas processadas.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from core.comparator import compare_price
from utils.helpers import get_logger, safe_str

logger = get_logger(__name__)

SUPPORTED_FUEL_TYPES = {"diesel", "arla"}
DEFAULT_NAME_MATCH_THRESHOLD = 0.72


def normalize_api_payload(payload, tipo: str) -> tuple[list[dict], list[str]]:
    """
    Normaliza o payload da API externa para um formato comum ao cruzamento.
    """
    errors: list[str] = []
    normalized: list[dict] = []
    tipo_normalizado = _normalize_fuel_type(tipo)

    items = _extract_payload_items(payload)
    for raw_item in items:
        try:
            preco_api = _to_float(raw_item.get("preço", raw_item.get("preco", raw_item.get("valor"))))
            if preco_api is None:
                errors.append(f"Item com preço inválido ignorado: {raw_item}")
                continue

            normalized_item = {
                "tipo": tipo_normalizado,
                "codigo": _normalize_code(raw_item.get("codigo")),
                "cnpj": safe_str(raw_item.get("cnpj")),
                "cnpjs_normalizados": _split_cnpjs(raw_item.get("cnpj")),
                "estado": _normalize_text(raw_item.get("estado")),
                "cidade": _normalize_text(raw_item.get("cidade")),
                "posto": safe_str(raw_item.get("posto")),
                "posto_normalizado": _normalize_text(raw_item.get("posto")),
                "uf": _normalize_text(raw_item.get("uf", raw_item.get("estado"))),
                "bandeira": safe_str(raw_item.get("bandeira")),
                "preco_api": preco_api,
                "payload_original": raw_item,
            }

            if not normalized_item["cnpjs_normalizados"] and not normalized_item["posto_normalizado"]:
                errors.append(f"Item sem CNPJ e sem posto identificável ignorado: {raw_item}")
                continue

            normalized.append(normalized_item)
        except Exception as exc:
            errors.append(f"Erro ao normalizar item da API {raw_item}: {exc}")
            logger.warning("Erro ao normalizar item da API %s: %s", raw_item, exc)

    return normalized, errors


def normalize_processed_notes(notas_processadas: list[dict], tipo: str) -> list[dict]:
    """
    Normaliza resultados já processados pelo sistema para a estrutura usada no cruzamento.
    """
    tipo_normalizado = _normalize_fuel_type(tipo)
    normalized: list[dict] = []

    for row in notas_processadas:
        codigo_produto = safe_str(row.get("codigo_produto", row.get("codigo", "")))
        descricao = safe_str(row.get("descricao"))
        detected_tipo = _infer_fuel_type(codigo_produto, descricao)

        if detected_tipo != tipo_normalizado:
            continue

        preco_nota = _to_float(row.get("preco_xml", row.get("preco_nota", row.get("preco"))))
        if preco_nota is None:
            logger.warning("Registro ignorado por preço de nota inválido: %s", row)
            continue

        emitente_nome = safe_str(
            row.get("emitente_nome", row.get("posto", row.get("razao_social", "")))
        )
        normalized.append({
            "tipo": tipo_normalizado,
            "cnpj": _normalize_cnpj(row.get("cnpj_fornecedor", row.get("cnpj_emitente", row.get("cnpj")))),
            "cnpj_original": safe_str(row.get("cnpj_fornecedor", row.get("cnpj_emitente", row.get("cnpj", "")))),
            "posto": emitente_nome,
            "posto_normalizado": _normalize_text(emitente_nome),
            "cidade": _normalize_text(row.get("emitente_cidade", row.get("cidade"))),
            "uf": _normalize_text(row.get("emitente_uf", row.get("uf"))),
            "codigo_produto": codigo_produto,
            "descricao": descricao,
            "preco_nota": preco_nota,
            "nome_arquivo": safe_str(row.get("nome_arquivo")),
            "registro_original": row,
        })

    return normalized


def analyze_api_prices(
    api_payload,
    notas_processadas: list[dict],
    tipo: str,
    name_match_threshold: float = DEFAULT_NAME_MATCH_THRESHOLD,
) -> tuple[list[dict], list[str]]:
    """
    Cruza preços da API externa com notas fiscais já processadas pelo sistema.
    """
    api_items, errors = normalize_api_payload(api_payload, tipo)
    notas_normalizadas = normalize_processed_notes(notas_processadas, tipo)

    if not notas_normalizadas:
        errors.append(f"Nenhuma nota processada encontrada para o tipo '{tipo}'.")
        return [], errors

    notes_by_cnpj = _group_notes_by_cnpj(notas_normalizadas)
    results: list[dict] = []

    for api_item in api_items:
        nota_match, match_reason = _find_matching_note(
            api_item,
            notes_by_cnpj,
            notas_normalizadas,
            name_match_threshold=name_match_threshold,
        )

        if nota_match is None:
            results.append({
                "tipo": api_item["tipo"],
                "cnpj": api_item["cnpj"] or "",
                "posto": api_item["posto"],
                "preco_api": api_item["preco_api"],
                "preco_nota": None,
                "diferenca": None,
                "percentual": None,
                "status": "CRITICO",
                "motivo": "Nota fiscal correspondente não encontrada",
            })
            continue

        comparison = compare_price(
            cnpj=nota_match["cnpj"] or nota_match["cnpj_original"],
            codigo_produto=nota_match["codigo_produto"] or api_item["tipo"].upper(),
            preco_xml=nota_match["preco_nota"],
            preco_api=api_item["preco_api"],
        )

        results.append({
            "tipo": api_item["tipo"],
            "cnpj": api_item["cnpj"] or nota_match["cnpj_original"],
            "posto": api_item["posto"] or nota_match["posto"],
            "preco_api": api_item["preco_api"],
            "preco_nota": nota_match["preco_nota"],
            "diferenca": comparison["diff_abs"],
            "percentual": comparison["diff_pct"],
            "status": comparison["status"],
            "motivo": _build_reason(comparison["status"], match_reason, nota_match["preco_nota"], api_item["preco_api"]),
        })

    return results, errors


def _extract_payload_items(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "items", "produtos", "resultados"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _group_notes_by_cnpj(notas_normalizadas: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for note in notas_normalizadas:
        if not note["cnpj"]:
            continue
        grouped.setdefault(note["cnpj"], []).append(note)
    return grouped


def _find_matching_note(
    api_item: dict,
    notes_by_cnpj: dict[str, list[dict]],
    notas_normalizadas: list[dict],
    name_match_threshold: float,
) -> tuple[dict | None, str]:
    cnpj_candidates: list[dict] = []
    for cnpj in api_item["cnpjs_normalizados"]:
        cnpj_candidates.extend(notes_by_cnpj.get(cnpj, []))

    if cnpj_candidates:
        return _pick_best_note(api_item, cnpj_candidates), "Correspondência encontrada por CNPJ"

    posto_api = api_item["posto_normalizado"]
    if not posto_api:
        return None, "Sem CNPJ ou nome do posto para comparação"

    scored_candidates: list[tuple[float, dict]] = []
    for note in notas_normalizadas:
        ratio = SequenceMatcher(None, posto_api, note["posto_normalizado"]).ratio()
        if ratio < name_match_threshold:
            continue

        score = ratio
        if api_item["cidade"] and api_item["cidade"] == note["cidade"]:
            score += 0.10
        if api_item["uf"] and api_item["uf"] == note["uf"]:
            score += 0.05
        scored_candidates.append((score, note))

    if not scored_candidates:
        return None, "Nenhum posto compatível encontrado"

    scored_candidates.sort(
        key=lambda item: (
            item[0],
            -abs(item[1]["preco_nota"] - api_item["preco_api"]),
        ),
        reverse=True,
    )
    return scored_candidates[0][1], "Correspondência tolerante por nome do posto"


def _pick_best_note(api_item: dict, candidates: list[dict]) -> dict:
    return min(
        candidates,
        key=lambda note: (
            abs(note["preco_nota"] - api_item["preco_api"]),
            note["nome_arquivo"],
            note["codigo_produto"],
        ),
    )


def _build_reason(status: str, match_reason: str, preco_nota: float, preco_api: float) -> str:
    direction = "acima" if preco_nota > preco_api else "abaixo" if preco_nota < preco_api else "igual"
    if status == "OK":
        return f"{match_reason}; preço da nota dentro da tolerância configurada"
    if direction == "igual":
        return f"{match_reason}; preços coincidem, mas a tolerância configurada exige revisão"
    return f"{match_reason}; preço da nota {direction} da referência além da tolerância configurada"


def _normalize_code(value) -> str:
    return safe_str(value)


def _split_cnpjs(raw_value) -> list[str]:
    raw_text = safe_str(raw_value)
    if not raw_text:
        return []

    tokens = []
    for part in raw_text.split("///"):
        normalized = _normalize_cnpj(part)
        if normalized:
            tokens.append(normalized)
    return tokens


def _normalize_cnpj(value) -> str:
    digits = re.sub(r"\D+", "", safe_str(value))
    return digits if len(digits) == 14 else ""


def _normalize_text(value) -> str:
    text = safe_str(value).upper()
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_fuel_type(tipo: str) -> str:
    normalized = _normalize_text(tipo).lower()
    if normalized not in SUPPORTED_FUEL_TYPES:
        logger.warning("Tipo de combustível não mapeado explicitamente: %s", tipo)
    return normalized


def _infer_fuel_type(codigo_produto: str, descricao: str) -> str:
    haystack = _normalize_text(f"{codigo_produto} {descricao}")
    if "ARLA" in haystack:
        return "arla"
    if "DIESEL" in haystack or "S10" in haystack or "S500" in haystack:
        return "diesel"
    return ""


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        cleaned = value.strip().replace("R$", "").replace(" ", "")
        if cleaned.count(",") == 1 and cleaned.count(".") > 1:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif cleaned.count(",") == 1 and cleaned.count(".") == 0:
            cleaned = cleaned.replace(",", ".")
        value = cleaned

    try:
        return float(value)
    except (TypeError, ValueError):
        return None
