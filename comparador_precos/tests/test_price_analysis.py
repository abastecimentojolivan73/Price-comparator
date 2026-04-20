import os
import sys
import unittest
from unittest.mock import patch


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.price_analysis import (
    analyze_api_prices,
    compare_note_with_api_cache,
    normalize_api_payload,
)
from core.xml_processor import parse_nfe_file


class PriceAnalysisTests(unittest.TestCase):
    def test_normalize_api_payload_supports_multiple_cnpjs(self):
        payload = [
            {
                "codigo": "915/1223",
                "cnpj": "20.940.512/0001-45///42.354.394/0001-26",
                "estado": "GO",
                "cidade": "HIDROLANDIA-GO",
                "posto": "POSTO MARAJO HIDROLANDIA 1 e 2",
                "preço": 7,
                "uf": "GOIÁS",
            }
        ]

        normalized, errors = normalize_api_payload(payload, "diesel")

        self.assertEqual(errors, [])
        self.assertEqual(normalized[0]["codigo"], "915/1223")
        self.assertEqual(
            normalized[0]["cnpjs_normalizados"],
            ["20940512000145", "42354394000126"],
        )
        self.assertEqual(normalized[0]["preco_api"], 7.0)

    @patch(
        "core.comparator.get_tolerancia",
        return_value={"tolerancia_tipo": "VALOR", "tolerancia_valor": 0.08},
    )
    def test_compare_prefers_cnpj_match(self, _mock_tolerancia):
        api_payload = [
            {
                "codigo": 22,
                "cnpj": "05.443.159/0001-02",
                "estado": "GO",
                "cidade": "APARECIDA DE GOIANIA - GO",
                "posto": "POSTO MARAJO APARECIDA DE GOIANIA",
                "preço": 7.0,
                "uf": "GOIÁS",
            }
        ]
        notas_processadas = [
            {
                "cnpj_fornecedor": "05.443.159/0001-02",
                "emitente_nome": "POSTO MARAJO APARECIDA DE GOIANIA",
                "emitente_cidade": "Aparecida de Goiania",
                "emitente_uf": "GO",
                "codigo_produto": "DIESEL-S10",
                "descricao": "OLEO DIESEL S10",
                "preco_xml": 6.89,
                "nome_arquivo": "NF_001.xml",
            }
        ]

        results, errors = analyze_api_prices(api_payload, notas_processadas, "diesel")

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "ALERTA")
        self.assertEqual(results[0]["preco_nota"], 6.89)
        self.assertAlmostEqual(results[0]["diferenca"], 0.11, places=2)
        self.assertIn("CNPJ", results[0]["motivo"])

    @patch("core.comparator.get_tolerancia", return_value=None)
    def test_compare_falls_back_to_station_name(self, _mock_tolerancia):
        api_payload = [
            {
                "codigo": 22,
                "cnpj": "",
                "estado": "GO",
                "cidade": "APARECIDA DE GOIANIA - GO",
                "posto": "POSTO MARAJO APARECIDA DE GOIANIA",
                "preço": 7.0,
                "uf": "GO",
            }
        ]
        notas_processadas = [
            {
                "cnpj_fornecedor": "99999999000199",
                "emitente_nome": "Posto Marajo Aparecida de Goiania Ltda",
                "emitente_cidade": "Aparecida de Goiania",
                "emitente_uf": "GO",
                "codigo_produto": "DIESEL-S10",
                "descricao": "DIESEL S10",
                "preco_xml": 7.05,
                "nome_arquivo": "NF_002.xml",
            }
        ]

        results, errors = analyze_api_prices(api_payload, notas_processadas, "diesel")

        self.assertEqual(errors, [])
        self.assertEqual(results[0]["status"], "OK")
        self.assertIn("nome do posto", results[0]["motivo"])

    def test_parse_nfe_file_extracts_emitente_metadata(self):
        xml_path = os.path.join(BASE_DIR, "xmls_exemplo", "NF_001_04_2026.xml")

        parsed, errors = parse_nfe_file(xml_path)

        self.assertEqual(errors, [])
        self.assertEqual(parsed["cnpj_emitente"], "12345678000195")
        self.assertEqual(parsed["emitente_nome"], "Distribuidora Alpha Combustiveis Ltda")
        self.assertEqual(parsed["emitente_cidade"], "São Paulo")
        self.assertEqual(parsed["emitente_uf"], "SP")

    @patch("core.comparator.get_tolerancia", return_value=None)
    def test_compare_note_with_api_cache_uses_local_payload(self, _mock_tolerancia):
        nota = {
            "nome_arquivo": "NF_003.xml",
            "cnpj_fornecedor": "05.443.159/0001-02",
            "emitente_nome": "POSTO MARAJO APARECIDA DE GOIANIA",
            "emitente_cidade": "Aparecida de Goiania",
            "emitente_uf": "GO",
            "codigo_produto": "DIESEL-S10",
            "descricao": "OLEO DIESEL S10",
            "preco_xml": 6.89,
        }
        api_cache_local = [
            {
                "codigo": 22,
                "cnpj": "05.443.159/0001-02",
                "estado": "GO",
                "cidade": "APARECIDA DE GOIANIA - GO",
                "posto": "POSTO MARAJO APARECIDA DE GOIANIA",
                "preço": 7.0,
                "uf": "GOIÁS",
            }
        ]

        comparison, errors = compare_note_with_api_cache(nota, api_cache_local, "diesel")

        self.assertEqual(errors, [])
        self.assertIsNotNone(comparison)
        self.assertEqual(comparison["status"], "OK")
        self.assertEqual(comparison["posto"], "POSTO MARAJO APARECIDA DE GOIANIA")
        self.assertAlmostEqual(comparison["preco_api"], 7.0, places=2)


if __name__ == "__main__":
    unittest.main()
