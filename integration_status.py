from contextlib import closing
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import sqlite3


def _schema(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS integration_checks (
        provider TEXT PRIMARY KEY, key_hash TEXT NOT NULL, status TEXT NOT NULL,
        model TEXT NOT NULL, message TEXT NOT NULL, checked_at TEXT NOT NULL
    )""")


def record_check(database, key, status, message, model=""):
    with closing(sqlite3.connect(database)) as connection, connection:
        _schema(connection)
        connection.execute(
            "INSERT OR REPLACE INTO integration_checks VALUES (?, ?, ?, ?, ?, ?)",
            ("gemini", sha256(key.encode()).hexdigest(), status, model, message,
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def gemini_status(database, key):
    result = {"status": "missing" if not key else "untested", "model": "", "checked_at": "",
              "label": "Não configurada" if not key else "Chave salva · ainda não testada",
              "message": "Salve sua chave e clique em Testar conexão."}
    if not key:
        return result
    with closing(sqlite3.connect(database)) as connection, connection:
        _schema(connection)
        row = connection.execute(
            "SELECT status, model, message, checked_at FROM integration_checks WHERE provider=? AND key_hash=?",
            ("gemini", sha256(key.encode()).hexdigest()),
        ).fetchone()
    if not row:
        return result
    status, model, message, checked_at = row
    stale = datetime.now(timezone.utc) - datetime.fromisoformat(checked_at) > timedelta(hours=24)
    labels = {"ok": "Funcionando no último teste", "error": "Falha no último teste"}
    result.update(status="stale" if stale else status, model=model, message=message,
                  checked_at=checked_at, label="Teste antigo · verificar novamente" if stale else labels[status])
    return result
