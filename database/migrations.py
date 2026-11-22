"""Database migrations for gestaoLead AI Workforce."""

import sqlite3
import logging
from typing import Dict, Any

logger = logging.getLogger("ai_workforce.database.migrations")

MIGRATION_VERSION = "20261120_001_ai_workforce_init"

UP_QUERIES = [
    # 1. Tabela de Tarefas dos Agentes (Fila e Rastreabilidade)
    """
    CREATE TABLE IF NOT EXISTS agent_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT UNIQUE NOT NULL,
        campaign_id TEXT,
        agent_name TEXT NOT NULL,
        task_type TEXT NOT NULL,
        payload_json TEXT DEFAULT '{}',
        result_json TEXT DEFAULT '{}',
        priority INTEGER DEFAULT 5,
        status TEXT NOT NULL DEFAULT 'queued',
        retries INTEGER DEFAULT 0,
        max_retries INTEGER DEFAULT 3,
        error_message TEXT,
        queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP,
        completed_at TIMESTAMP
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks (status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_tasks_agent ON agent_tasks (agent_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_tasks_campaign ON agent_tasks (campaign_id);
    """,

    # 2. Tabela de Execuções dos Agentes (Telemetria)
    """
    CREATE TABLE IF NOT EXISTS agent_executions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id TEXT UNIQUE NOT NULL,
        task_id TEXT,
        campaign_id TEXT,
        agent_name TEXT NOT NULL,
        model_used TEXT,
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        cost_usd REAL DEFAULT 0.0,
        cost_brl REAL DEFAULT 0.0,
        execution_time_ms INTEGER DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'running',
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_executions_task ON agent_executions (task_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_executions_agent ON agent_executions (agent_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_executions_status ON agent_executions (status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_executions_campaign ON agent_executions (campaign_id);
    """,

    # 3. Tabela de Logs Granulares dos Agentes
    """
    CREATE TABLE IF NOT EXISTS agent_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT,
        execution_id TEXT,
        agent_name TEXT NOT NULL,
        level TEXT NOT NULL DEFAULT 'INFO',
        message TEXT NOT NULL,
        details_json TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_logs_task ON agent_logs (task_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_logs_execution ON agent_logs (execution_id);
    """,

    # 4. Tabela de Custos Financeiros Consolidados
    """
    CREATE TABLE IF NOT EXISTS agent_costs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id TEXT NOT NULL,
        campaign_id TEXT,
        agent_name TEXT NOT NULL,
        model_name TEXT NOT NULL,
        prompt_tokens INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL NOT NULL DEFAULT 0.0,
        cost_brl REAL NOT NULL DEFAULT 0.0,
        calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_costs_execution ON agent_costs (execution_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_costs_campaign ON agent_costs (campaign_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_costs_agent ON agent_costs (agent_name);
    """,

    # 5. Tabela de Controle de Versões de Migrações
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
]

DOWN_QUERIES = [
    "DROP TABLE IF EXISTS agent_costs;",
    "DROP TABLE IF EXISTS agent_logs;",
    "DROP TABLE IF EXISTS agent_executions;",
    "DROP TABLE IF EXISTS agent_tasks;",
    "DELETE FROM schema_migrations WHERE version = '20261120_001_ai_workforce_init';"
]


def run_ai_workforce_migrations(db_path: str = "gestao_leads.db") -> Dict[str, Any]:
    """Aplica as migrações da Fase 1 de forma segura e idempotente."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        
        # Verificar se migração já foi aplicada
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
        if cur.fetchone():
            cur.execute("SELECT version FROM schema_migrations WHERE version = ?", (MIGRATION_VERSION,))
            if cur.fetchone():
                return {"success": True, "applied": False, "message": f"Migração {MIGRATION_VERSION} já aplicada."}

        for query in UP_QUERIES:
            conn.execute(query)

        conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)", (MIGRATION_VERSION,))
        conn.commit()
        logger.info(f"Migração {MIGRATION_VERSION} aplicada com sucesso em {db_path}.")
        return {"success": True, "applied": True, "message": f"Migração {MIGRATION_VERSION} aplicada com sucesso."}
    except Exception as error:
        conn.rollback()
        logger.error(f"Erro ao aplicar migração {MIGRATION_VERSION}: {error}")
        raise error
    finally:
        conn.close()


def rollback_ai_workforce_migrations(db_path: str = "gestao_leads.db") -> Dict[str, Any]:
    """Reverte as migrações da Fase 1 (operações não destrutivas para outras tabelas)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        for query in DOWN_QUERIES:
            conn.execute(query)
        conn.commit()
        logger.info(f"Rollback de {MIGRATION_VERSION} concluído em {db_path}.")
        return {"success": True, "message": f"Rollback de {MIGRATION_VERSION} concluído com sucesso."}
    except Exception as error:
        conn.rollback()
        logger.error(f"Erro no rollback da migração {MIGRATION_VERSION}: {error}")
        raise error
    finally:
        conn.close()
