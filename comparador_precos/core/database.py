"""
core/database.py - Gerenciamento do banco SQLite local.
Contém schema, inicialização e funções CRUD para as 3 tabelas do sistema.
"""
import sqlite3
import os
from utils.helpers import get_logger

logger = get_logger(__name__)

DB_PATH = os.path.join(os.getcwd(), "comparador_precos.db")


def get_connection() -> sqlite3.Connection:
    """Abre e retorna uma conexão com o banco SQLite local."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """
    Cria as tabelas do banco de dados caso não existam.
    Seguro para chamadas repetidas (CREATE TABLE IF NOT EXISTS).
    """
    logger.info("Inicializando banco de dados: %s", DB_PATH)
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS config_fornecedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cnpj TEXT NOT NULL,
                codigo_produto TEXT NOT NULL,
                tipo_combustivel TEXT,
                tolerancia_tipo TEXT NOT NULL CHECK(tolerancia_tipo IN ('%', 'VALOR')),
                tolerancia_valor REAL NOT NULL,
                UNIQUE(cnpj, codigo_produto)
            );

            CREATE TABLE IF NOT EXISTS cache_precos_api (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo_produto TEXT NOT NULL UNIQUE,
                preco_referencia REAL NOT NULL,
                data_atualizacao TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS resultados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_arquivo TEXT NOT NULL,
                cnpj_fornecedor TEXT NOT NULL,
                emitente_nome TEXT,
                emitente_cidade TEXT,
                emitente_uf TEXT,
                codigo_produto TEXT NOT NULL,
                descricao TEXT,
                qtd REAL,
                valor_total REAL,
                preco_xml REAL,
                preco_api REAL,
                diff_abs REAL,
                diff_pct REAL,
                status TEXT NOT NULL CHECK(status IN ('OK', 'ALERTA', 'CRITICO')),
                data_processamento TEXT NOT NULL
            );
        """)
        _ensure_resultados_columns(conn)
    logger.info("Banco de dados inicializado com sucesso.")


def _ensure_resultados_columns(conn: sqlite3.Connection):
    """Aplica migrações leves em bancos já existentes sem destruir dados."""
    rows = conn.execute("PRAGMA table_info(resultados)").fetchall()
    existing_columns = {row["name"] for row in rows}

    for column_name, column_type in (
        ("emitente_nome", "TEXT"),
        ("emitente_cidade", "TEXT"),
        ("emitente_uf", "TEXT"),
    ):
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE resultados ADD COLUMN {column_name} {column_type}")
            logger.info("Coluna adicionada em resultados: %s", column_name)


# ─── config_fornecedores CRUD ────────────────────────────────────────────────

def upsert_config_fornecedor(cnpj: str, codigo_produto: str,
                              tipo_combustivel: str,
                              tolerancia_tipo: str,
                              tolerancia_valor: float) -> bool:
    """
    Insere ou atualiza uma configuração de tolerância para CNPJ + produto.
    Retorna True em caso de sucesso.
    """
    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT INTO config_fornecedores
                    (cnpj, codigo_produto, tipo_combustivel, tolerancia_tipo, tolerancia_valor)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cnpj, codigo_produto) DO UPDATE SET
                    tipo_combustivel = excluded.tipo_combustivel,
                    tolerancia_tipo = excluded.tolerancia_tipo,
                    tolerancia_valor = excluded.tolerancia_valor
            """, (cnpj, codigo_produto, tipo_combustivel, tolerancia_tipo, tolerancia_valor))
        return True
    except Exception as e:
        logger.error("Erro ao salvar config_fornecedor: %s", e)
        return False


def list_config_fornecedores() -> list:
    """Retorna todas as configurações de fornecedores como lista de dicts."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM config_fornecedores ORDER BY cnpj, codigo_produto"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("Erro ao listar config_fornecedores: %s", e)
        return []


def delete_config_fornecedor(record_id: int) -> bool:
    """Exclui uma configuração pelo ID. Retorna True em caso de sucesso."""
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM config_fornecedores WHERE id = ?", (record_id,))
        return True
    except Exception as e:
        logger.error("Erro ao excluir config_fornecedor id=%d: %s", record_id, e)
        return False


def get_tolerancia(cnpj: str, codigo_produto: str) -> dict | None:
    """
    Busca a configuração de tolerância para um CNPJ + código de produto.
    Retorna None se não encontrado.
    """
    try:
        with get_connection() as conn:
            row = conn.execute(
                """SELECT tolerancia_tipo, tolerancia_valor
                   FROM config_fornecedores
                   WHERE cnpj = ? AND codigo_produto = ?""",
                (cnpj, codigo_produto)
            ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error("Erro ao buscar tolerância CNPJ=%s prod=%s: %s", cnpj, codigo_produto, e)
        return None


# ─── cache_precos_api CRUD ───────────────────────────────────────────────────

def upsert_preco_api(codigo_produto: str, preco_referencia: float, data_atualizacao: str) -> bool:
    """Insere ou atualiza o preço de referência de um produto no cache."""
    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT INTO cache_precos_api (codigo_produto, preco_referencia, data_atualizacao)
                VALUES (?, ?, ?)
                ON CONFLICT(codigo_produto) DO UPDATE SET
                    preco_referencia = excluded.preco_referencia,
                    data_atualizacao = excluded.data_atualizacao
            """, (codigo_produto, preco_referencia, data_atualizacao))
        return True
    except Exception as e:
        logger.error("Erro ao salvar cache_precos_api produto=%s: %s", codigo_produto, e)
        return False


def get_preco_api(codigo_produto: str) -> dict | None:
    """Busca o preço de referência de um produto no cache local. Retorna None se ausente."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM cache_precos_api WHERE codigo_produto = ?",
                (codigo_produto,)
            ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error("Erro ao buscar cache produto=%s: %s", codigo_produto, e)
        return None


def list_cache_precos() -> list:
    """Lista todos os preços em cache."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM cache_precos_api ORDER BY codigo_produto"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("Erro ao listar cache_precos_api: %s", e)
        return []


# ─── resultados CRUD ─────────────────────────────────────────────────────────

def insert_resultado(data: dict) -> bool:
    """Insere um resultado de comparação no banco."""
    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT INTO resultados
                    (nome_arquivo, cnpj_fornecedor, emitente_nome, emitente_cidade, emitente_uf,
                     codigo_produto, descricao,
                     qtd, valor_total, preco_xml, preco_api,
                     diff_abs, diff_pct, status, data_processamento)
                VALUES
                    (:nome_arquivo, :cnpj_fornecedor, :emitente_nome, :emitente_cidade, :emitente_uf,
                     :codigo_produto, :descricao,
                     :qtd, :valor_total, :preco_xml, :preco_api,
                     :diff_abs, :diff_pct, :status, :data_processamento)
            """, data)
        return True
    except Exception as e:
        logger.error("Erro ao inserir resultado: %s", e)
        return False


def list_resultados() -> list:
    """Retorna todos os resultados ordenados pela data de processamento (mais recentes primeiro)."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM resultados ORDER BY data_processamento DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("Erro ao listar resultados: %s", e)
        return []


def clear_resultados() -> bool:
    """Remove todos os resultados do banco. Use com cuidado."""
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM resultados")
        return True
    except Exception as e:
        logger.error("Erro ao limpar resultados: %s", e)
        return False
