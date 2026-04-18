"""
mock_data.py - Popula o banco com dados de exemplo para testes.
Execute: python mock_data.py
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.helpers import setup_logging
from core.database import (
    init_db, upsert_config_fornecedor, upsert_preco_api,
    insert_resultado, clear_resultados
)

setup_logging()
init_db()

print("Limpando resultados anteriores...")
clear_resultados()

# ─── Preços de referência (cache_precos_api) ──────────────────────────────────
# Agora associamos a um CNPJ (ex: Distribuidora Alpha 12345678000195)
MOCK_CNPJ = "12345678000195"
precos_api = [
    ("GASOLINA-C",  5.79),
    ("GASOLINA-A",  5.49),
    ("ETANOL",      3.99),
    ("DIESEL-S10",  6.29),
    ("DIESEL-S500", 5.99),
    ("GNV",         4.15),
    ("ARLA32",      3.50),
]

print("Inserindo preços de referência...")
for cod, preco in precos_api:
    upsert_preco_api(MOCK_CNPJ, cod, preco, "16/04/2026 10:00:00")
    print(f"  CNPJ {MOCK_CNPJ} | {cod}: R$ {preco:.4f}")

# ─── Configurações de fornecedores (config_fornecedores) ──────────────────────
configs = [
    # (cnpj, codigo_produto, tipo_combustivel, tolerancia_tipo, tolerancia_valor)
    ("12345678000195", "GASOLINA-C",  "Gasolina Comum",   "%",     2.0),
    ("12345678000195", "GASOLINA-A",  "Gasolina Aditivada","%",    2.5),
    ("12345678000195", "ETANOL",      "Etanol Hidratado", "%",     3.0),
    ("12345678000195", "DIESEL-S10",  "Diesel S10",       "%",     1.5),
    ("98765432000100", "DIESEL-S10",  "Diesel S10",       "VALOR", 0.10),
    ("98765432000100", "DIESEL-S500", "Diesel S500",      "VALOR", 0.15),
    ("98765432000100", "GNV",         "GNV",              "%",     5.0),
    ("11222333000181", "ARLA32",      "ARLA 32",          "%",     4.0),
]

print("\nInserindo configurações de fornecedores...")
for cnpj, cod, tipo_comb, tol_tipo, tol_val in configs:
    upsert_config_fornecedor(cnpj, cod, tipo_comb, tol_tipo, tol_val)
    print(f"  CNPJ {cnpj} | {cod} | tolerância {tol_tipo} {tol_val}")

# ─── Resultados de comparação (resultados) ────────────────────────────────────
resultados = [
    # (arquivo, cnpj, codigo, descricao, qtd, valor_total, preco_xml, preco_api, diff_abs, diff_pct, status, data)
    ("NF_001_04_2026.xml", "12345678000195", "GASOLINA-C",  "GASOLINA COMUM",    500.0,  2895.00, 5.7900, 5.79, 0.0000, 0.00,  "OK",     "16/04/2026 08:15:00"),
    ("NF_001_04_2026.xml", "12345678000195", "ETANOL",      "ETANOL HIDRATADO",  300.0,  1215.00, 4.0500, 3.99, 0.0600, 1.50,  "ALERTA", "16/04/2026 08:15:00"),
    ("NF_001_04_2026.xml", "12345678000195", "DIESEL-S10",  "DIESEL S10",        800.0,  5040.00, 6.3000, 6.29, 0.0100, 0.16,  "OK",     "16/04/2026 08:15:00"),
    ("NF_002_04_2026.xml", "12345678000195", "GASOLINA-A",  "GASOLINA ADITIVADA",200.0,  1140.00, 5.7000, 5.49, 0.2100, 3.83,  "CRITICO","16/04/2026 08:30:00"),
    ("NF_002_04_2026.xml", "12345678000195", "GASOLINA-C",  "GASOLINA COMUM",    400.0,  2312.00, 5.7800, 5.79, 0.0100, 0.17,  "OK",     "16/04/2026 08:30:00"),
    ("NF_003_04_2026.xml", "98765432000100", "DIESEL-S10",  "DIESEL S10",       1000.0,  6310.00, 6.3100, 6.29, 0.0200, 0.32,  "ALERTA", "16/04/2026 09:00:00"),
    ("NF_003_04_2026.xml", "98765432000100", "DIESEL-S500", "DIESEL S500",       600.0,  3618.00, 6.0300, 5.99, 0.0400, 0.67,  "ALERTA", "16/04/2026 09:00:00"),
    ("NF_003_04_2026.xml", "98765432000100", "GNV",         "GNV COMPRIMIDO",    900.0,  3744.00, 4.1600, 4.15, 0.0100, 0.24,  "OK",     "16/04/2026 09:00:00"),
    ("NF_004_04_2026.xml", "98765432000100", "DIESEL-S10",  "DIESEL S10",        500.0,  3250.00, 6.5000, 6.29, 0.2100, 3.34,  "CRITICO","16/04/2026 09:45:00"),
    ("NF_004_04_2026.xml", "11222333000181", "ARLA32",      "ARLA 32 20L",       150.0,   525.00, 3.5000, 3.50, 0.0000, 0.00,  "OK",     "16/04/2026 09:45:00"),
    ("NF_005_04_2026.xml", "11222333000181", "ARLA32",      "ARLA 32 20L",       200.0,   730.00, 3.6500, 3.50, 0.1500, 4.29,  "ALERTA", "16/04/2026 10:00:00"),
    ("NF_005_04_2026.xml", "12345678000195", "GASOLINA-C",  "GASOLINA COMUM",    750.0,  4425.00, 5.9000, 5.79, 0.1100, 1.90,  "ALERTA", "16/04/2026 10:00:00"),
    ("NF_006_04_2026.xml", "98765432000100", "DIESEL-S500", "DIESEL S500",       400.0,  2452.00, 6.1300, 5.99, 0.1400, 2.34,  "ALERTA", "16/04/2026 10:30:00"),
    ("NF_006_04_2026.xml", "12345678000195", "ETANOL",      "ETANOL HIDRATADO",  500.0,  2200.00, 4.4000, 3.99, 0.4100, 10.28, "CRITICO","16/04/2026 10:30:00"),
    ("NF_007_04_2026.xml", "11222333000181", "GNV",         "GNV COMPRIMIDO",    300.0,  1248.00, 4.1600, 4.15, 0.0100, 0.24,  "OK",     "16/04/2026 11:00:00"),
]

print("\nInserindo resultados de comparação...")
for r in resultados:
    insert_resultado({
        "nome_arquivo":      r[0],
        "cnpj_fornecedor":   r[1],
        "codigo_produto":    r[2],
        "descricao":         r[3],
        "qtd":               r[4],
        "valor_total":       r[5],
        "preco_xml":         r[6],
        "preco_api":         r[7],
        "diff_abs":          r[8],
        "diff_pct":          r[9],
        "status":            r[10],
        "data_processamento":r[11],
    })
    print(f"  {r[0]} | {r[2]} | {r[10]}")

print(f"\nMock data inserido com sucesso!")
print(f"  {len(precos_api)} preços de referência")
print(f"  {len(configs)} configurações de fornecedores")
print(f"  {len(resultados)} resultados de comparação")
print(f"\nExecute 'python main.py' para ver os dados na interface.")
