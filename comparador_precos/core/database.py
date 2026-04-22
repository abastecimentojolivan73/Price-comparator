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
            CREATE TABLE IF NOT EXISTS app_config (
                chave TEXT PRIMARY KEY,
                valor TEXT
            );

            CREATE TABLE IF NOT EXISTS ncm_sh_ignorados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ncm_sh TEXT NOT NULL UNIQUE
            );

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

            CREATE TABLE IF NOT EXISTS cache_precos_api_detalhes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo_combustivel TEXT NOT NULL,
                codigo TEXT,
                cnpj TEXT,
                estado TEXT,
                cidade TEXT,
                posto TEXT,
                preco REAL NOT NULL,
                uf TEXT,
                bandeira TEXT,
                data_atualizacao TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS resultados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_arquivo TEXT NOT NULL,
                numero_nota TEXT,
                cnpj_fornecedor TEXT NOT NULL,
                emitente_nome TEXT,
                emitente_cidade TEXT,
                emitente_uf TEXT,
                tipo_combustivel TEXT,
                posto_referencia TEXT,
                motivo TEXT,
                origem_comparacao TEXT,
                codigo_produto TEXT NOT NULL,
                descricao TEXT,
                qtd REAL,
                valor_total REAL,
                preco_xml REAL,
                preco_api REAL,
                diff_abs REAL,
                diff_pct REAL,
                status TEXT NOT NULL CHECK(status IN ('OK', 'ALERTA', 'CRITICO', 'REDUCAO')),
                data_processamento TEXT NOT NULL
            );
        """)
        _ensure_resultados_status_schema(conn)
        _ensure_resultados_columns(conn)
    logger.info("Banco de dados inicializado com sucesso.")


def set_app_config(chave: str, valor: str) -> bool:
    """Salva uma configuração simples da aplicação por chave."""
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO app_config (chave, valor)
                VALUES (?, ?)
                ON CONFLICT(chave) DO UPDATE SET
                    valor = excluded.valor
                """,
                (chave, valor),
            )
        return True
    except Exception as e:
        logger.error("Erro ao salvar app_config chave=%s: %s", chave, e)
        return False


def get_app_config(chave: str, default: str = "") -> str:
    """Busca uma configuração simples da aplicação por chave."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT valor FROM app_config WHERE chave = ?",
                (chave,),
            ).fetchone()
        if not row:
            return default
        return row["valor"] if row["valor"] is not None else default
    except Exception as e:
        logger.error("Erro ao buscar app_config chave=%s: %s", chave, e)
        return default


def add_ncm_sh_ignorado(ncm_sh: str) -> bool:
    """Adiciona um NCM/SH global na lista de ignorados."""
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO ncm_sh_ignorados (ncm_sh) VALUES (?)",
                (_normalize_ncm_sh(ncm_sh),),
            )
        return True
    except Exception as e:
        logger.error("Erro ao adicionar NCM/SH ignorado %s: %s", ncm_sh, e)
        return False


def list_ncm_sh_ignorados() -> list[dict]:
    """Lista todos os NCM/SH globais ignorados."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ncm_sh_ignorados ORDER BY ncm_sh"
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("Erro ao listar NCM/SH ignorados: %s", e)
        return []


def delete_ncm_sh_ignorado(record_id: int) -> bool:
    """Exclui um NCM/SH ignorado pelo ID."""
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM ncm_sh_ignorados WHERE id = ?", (record_id,))
        return True
    except Exception as e:
        logger.error("Erro ao excluir NCM/SH ignorado id=%s: %s", record_id, e)
        return False


def is_ncm_sh_ignorado(ncm_sh: str) -> bool:
    """Verifica se um NCM/SH está configurado para ignorar globalmente."""
    normalized = _normalize_ncm_sh(ncm_sh)
    if not normalized:
        return False
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM ncm_sh_ignorados WHERE ncm_sh = ?",
                (normalized,),
            ).fetchone()
        return row is not None
    except Exception as e:
        logger.error("Erro ao consultar NCM/SH ignorado %s: %s", ncm_sh, e)
        return False


def _normalize_ncm_sh(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip() if ch.isdigit())


def _ensure_resultados_status_schema(conn: sqlite3.Connection):
    """
    Recria a tabela de resultados quando o CHECK de status ainda não suporta REDUCAO.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'resultados'"
    ).fetchone()
    create_sql = (row["sql"] or "") if row else ""
    if "REDUCAO" in create_sql:
        return

    conn.executescript("""
        ALTER TABLE resultados RENAME TO resultados_old;

        CREATE TABLE resultados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_arquivo TEXT NOT NULL,
            numero_nota TEXT,
            cnpj_fornecedor TEXT NOT NULL,
            emitente_nome TEXT,
            emitente_cidade TEXT,
            emitente_uf TEXT,
            tipo_combustivel TEXT,
            posto_referencia TEXT,
            motivo TEXT,
            origem_comparacao TEXT,
            codigo_produto TEXT NOT NULL,
            descricao TEXT,
            qtd REAL,
            valor_total REAL,
            preco_xml REAL,
            preco_api REAL,
            diff_abs REAL,
            diff_pct REAL,
            status TEXT NOT NULL CHECK(status IN ('OK', 'ALERTA', 'CRITICO', 'REDUCAO')),
            data_processamento TEXT NOT NULL
        );

        INSERT INTO resultados (
            id, nome_arquivo, cnpj_fornecedor, codigo_produto, descricao,
            qtd, valor_total, preco_xml, preco_api, diff_abs, diff_pct, status, data_processamento
        )
        SELECT
            id, nome_arquivo, cnpj_fornecedor, codigo_produto, descricao,
            qtd, valor_total, preco_xml, preco_api, diff_abs, diff_pct, status, data_processamento
        FROM resultados_old;

        DROP TABLE resultados_old;
    """)
    logger.info("Tabela resultados migrada para suportar status REDUCAO.")


def _ensure_resultados_columns(conn: sqlite3.Connection):
    """Aplica migrações leves em bancos já existentes sem destruir dados."""
    rows = conn.execute("PRAGMA table_info(resultados)").fetchall()
    existing_columns = {row["name"] for row in rows}

    for column_name, column_type in (
        ("numero_nota", "TEXT"),
        ("emitente_nome", "TEXT"),
        ("emitente_cidade", "TEXT"),
        ("emitente_uf", "TEXT"),
        ("tipo_combustivel", "TEXT"),
        ("posto_referencia", "TEXT"),
        ("motivo", "TEXT"),
        ("origem_comparacao", "TEXT"),
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
            normalized_code = (codigo_produto or "").strip()
            normalized_tipo = (tipo_combustivel or "").strip().lower()

            if normalized_tipo:
                existing = conn.execute(
                    """
                    SELECT id FROM config_fornecedores
                    WHERE cnpj = ? AND lower(coalesce(tipo_combustivel, '')) = ?
                    """,
                    (cnpj, normalized_tipo),
                ).fetchone()
                if existing:
                    conn.execute(
                        """
                        UPDATE config_fornecedores
                        SET codigo_produto = ?, tipo_combustivel = ?, tolerancia_tipo = ?, tolerancia_valor = ?
                        WHERE id = ?
                        """,
                        (normalized_code, normalized_tipo, tolerancia_tipo, tolerancia_valor, existing["id"]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO config_fornecedores
                            (cnpj, codigo_produto, tipo_combustivel, tolerancia_tipo, tolerancia_valor)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (cnpj, normalized_code, normalized_tipo, tolerancia_tipo, tolerancia_valor),
                    )
            else:
                conn.execute("""
                    INSERT INTO config_fornecedores
                        (cnpj, codigo_produto, tipo_combustivel, tolerancia_tipo, tolerancia_valor)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(cnpj, codigo_produto) DO UPDATE SET
                        tipo_combustivel = excluded.tipo_combustivel,
                        tolerancia_tipo = excluded.tolerancia_tipo,
                        tolerancia_valor = excluded.tolerancia_valor
                """, (cnpj, normalized_code, normalized_tipo, tolerancia_tipo, tolerancia_valor))
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


def get_tolerancia(cnpj: str, codigo_produto: str = "", tipo_combustivel: str = "") -> dict | None:
    """
    Busca a configuração de tolerância para um CNPJ + tipo de combustível.
    Faz fallback para o modelo legado por código de produto.
    Retorna None se não encontrado.
    """
    try:
        with get_connection() as conn:
            row = None
            if tipo_combustivel:
                row = conn.execute(
                    """
                    SELECT tolerancia_tipo, tolerancia_valor
                    FROM config_fornecedores
                    WHERE cnpj = ? AND lower(coalesce(tipo_combustivel, '')) = lower(?)
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (cnpj, tipo_combustivel),
                ).fetchone()
            if row is None and codigo_produto:
                row = conn.execute(
                    """SELECT tolerancia_tipo, tolerancia_valor
                       FROM config_fornecedores
                       WHERE cnpj = ? AND codigo_produto = ?""",
                    (cnpj, codigo_produto)
                ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(
            "Erro ao buscar tolerância CNPJ=%s prod=%s tipo=%s: %s",
            cnpj, codigo_produto, tipo_combustivel, e
        )
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


def replace_cache_precos_detalhes(tipo_combustivel: str, items: list[dict], data_atualizacao: str) -> int:
    """
    Substitui o cache detalhado local de um tipo de combustível pelo payload mais recente.
    """
    try:
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM cache_precos_api_detalhes WHERE tipo_combustivel = ?",
                (tipo_combustivel,),
            )
            conn.executemany(
                """
                INSERT INTO cache_precos_api_detalhes
                    (tipo_combustivel, codigo, cnpj, estado, cidade, posto, preco, uf, bandeira, data_atualizacao)
                VALUES
                    (:tipo_combustivel, :codigo, :cnpj, :estado, :cidade, :posto, :preco, :uf, :bandeira, :data_atualizacao)
                """,
                [
                    {
                        "tipo_combustivel": tipo_combustivel,
                        "codigo": item.get("codigo", ""),
                        "cnpj": item.get("cnpj", ""),
                        "estado": item.get("estado", ""),
                        "cidade": item.get("cidade", ""),
                        "posto": item.get("posto", ""),
                        "preco": item.get("preco_api", 0.0),
                        "uf": item.get("uf", ""),
                        "bandeira": item.get("bandeira", ""),
                        "data_atualizacao": data_atualizacao,
                    }
                    for item in items
                ],
            )
        return len(items)
    except Exception as e:
        logger.error("Erro ao substituir cache detalhado de %s: %s", tipo_combustivel, e)
        return 0


def list_cache_precos_detalhes(tipo_combustivel: str | None = None) -> list[dict]:
    """Lista o cache detalhado local de preços da API."""
    try:
        with get_connection() as conn:
            if tipo_combustivel:
                rows = conn.execute(
                    """
                    SELECT * FROM cache_precos_api_detalhes
                    WHERE tipo_combustivel = ?
                    ORDER BY posto, cnpj
                    """,
                    (tipo_combustivel,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM cache_precos_api_detalhes ORDER BY tipo_combustivel, posto, cnpj"
                ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("Erro ao listar cache_precos_api_detalhes: %s", e)
        return []


# ─── resultados CRUD ─────────────────────────────────────────────────────────

def insert_resultado(data: dict) -> bool:
    """Insere um resultado de comparação no banco."""
    try:
        payload = {
            "emitente_nome": "",
            "emitente_cidade": "",
            "emitente_uf": "",
            "numero_nota": "",
            "tipo_combustivel": "",
            "posto_referencia": "",
            "motivo": "",
            "origem_comparacao": "cache_codigo",
        }
        payload.update(data)
        with get_connection() as conn:
            conn.execute("""
                INSERT INTO resultados
                    (nome_arquivo, numero_nota, cnpj_fornecedor, emitente_nome, emitente_cidade, emitente_uf,
                     tipo_combustivel, posto_referencia, motivo, origem_comparacao,
                     codigo_produto, descricao,
                     qtd, valor_total, preco_xml, preco_api,
                     diff_abs, diff_pct, status, data_processamento)
                VALUES
                    (:nome_arquivo, :numero_nota, :cnpj_fornecedor, :emitente_nome, :emitente_cidade, :emitente_uf,
                     :tipo_combustivel, :posto_referencia, :motivo, :origem_comparacao,
                     :codigo_produto, :descricao,
                     :qtd, :valor_total, :preco_xml, :preco_api,
                     :diff_abs, :diff_pct, :status, :data_processamento)
            """, payload)
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
