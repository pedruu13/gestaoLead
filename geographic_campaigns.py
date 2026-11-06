import json
import sqlite3
import uuid


ACTIVE_STATUSES = {"pending", "running", "paused", "interrupted"}
TERMINAL_LOCATION_STATUSES = {"completed", "failed", "cancelled", "skipped"}


def init_geographic_schema(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS geographic_saved_sets
        (set_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, selection_json TEXT NOT NULL,
         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS geographic_campaigns
        (campaign_id TEXT PRIMARY KEY, name TEXT NOT NULL, mode TEXT NOT NULL,
         niches_json TEXT NOT NULL, selection_json TEXT NOT NULL, filters_json TEXT NOT NULL,
         status TEXT NOT NULL DEFAULT 'pending', batch_size INTEGER NOT NULL DEFAULT 10,
         concurrency INTEGER NOT NULL DEFAULT 1, total_municipalities INTEGER NOT NULL DEFAULT 0,
         completed_municipalities INTEGER NOT NULL DEFAULT 0, failed_municipalities INTEGER NOT NULL DEFAULT 0,
         businesses_found INTEGER NOT NULL DEFAULT 0, qualified_leads INTEGER NOT NULL DEFAULT 0,
         error TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, started_at TIMESTAMP,
         updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, finished_at TIMESTAMP)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS geographic_campaign_locations
        (id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL, municipality_id INTEGER NOT NULL,
         municipality_name TEXT NOT NULL, uf TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
         attempts INTEGER NOT NULL DEFAULT 0, queries_planned INTEGER NOT NULL DEFAULT 0,
         queries_completed INTEGER NOT NULL DEFAULT 0, businesses_found INTEGER NOT NULL DEFAULT 0,
         qualified_leads INTEGER NOT NULL DEFAULT 0, last_search_run_id TEXT, error TEXT,
         started_at TIMESTAMP, finished_at TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         UNIQUE(campaign_id, municipality_id))""")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_geo_campaign_status ON geographic_campaigns(status, updated_at DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_geo_location_queue ON geographic_campaign_locations(campaign_id, status, id)")
    existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(geographic_campaigns)").fetchall()}
    for column, definition in {
        "worker_id": "TEXT",
        "worker_heartbeat_at": "TIMESTAMP",
    }.items():
        if column not in existing_columns:
            connection.execute(f"ALTER TABLE geographic_campaigns ADD COLUMN {column} {definition}")


def _connect(db_name):
    connection = sqlite3.connect(db_name, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def create_campaign(db_name, name, mode, niches, locations, selection, filters=None, batch_size=10, concurrency=1):
    campaign_id = uuid.uuid4().hex
    batch_size = max(1, min(int(batch_size), 100))
    concurrency = max(1, min(int(concurrency), 3))
    queries_planned = max(3, len(niches) * 3)
    connection = _connect(db_name)
    try:
        connection.execute("""INSERT INTO geographic_campaigns
            (campaign_id, name, mode, niches_json, selection_json, filters_json, status,
             batch_size, concurrency, total_municipalities)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (campaign_id, name, mode, json.dumps(niches, ensure_ascii=False),
             json.dumps(selection, ensure_ascii=False), json.dumps(filters or {}, ensure_ascii=False),
             batch_size, concurrency, len(locations)))
        connection.executemany("""INSERT INTO geographic_campaign_locations
            (campaign_id, municipality_id, municipality_name, uf, queries_planned)
            VALUES (?, ?, ?, ?, ?)""",
            [(campaign_id, item["id"], item["name"], item["uf"], queries_planned) for item in locations])
        connection.commit()
    finally:
        connection.close()
    return campaign_id


def campaign_detail(db_name, campaign_id):
    connection = _connect(db_name)
    try:
        row = connection.execute("SELECT * FROM geographic_campaigns WHERE campaign_id = ?", (campaign_id,)).fetchone()
        if not row:
            raise ValueError("Campanha geográfica não encontrada.")
        campaign = dict(row)
        for field in ("niches_json", "selection_json", "filters_json"):
            campaign[field.removesuffix("_json")] = json.loads(campaign.pop(field) or "{}")
        counts = connection.execute("""SELECT status, COUNT(*) AS total FROM geographic_campaign_locations
            WHERE campaign_id = ? GROUP BY status""", (campaign_id,)).fetchall()
        campaign["location_statuses"] = {item["status"]: item["total"] for item in counts}
        totals = connection.execute("""SELECT COALESCE(SUM(queries_planned), 0), COALESCE(SUM(queries_completed), 0),
            COALESCE(SUM(businesses_found), 0), COALESCE(SUM(qualified_leads), 0)
            FROM geographic_campaign_locations WHERE campaign_id = ?""", (campaign_id,)).fetchone()
        planned, completed, found, qualified = map(int, totals)
        campaign["queries_planned"] = planned
        campaign["queries_completed"] = completed
        campaign["estimated_queries_remaining"] = max(0, planned - completed)
        campaign["businesses_found"] = found
        campaign["qualified_leads"] = qualified
        campaign["coverage_percent"] = round(completed * 100 / planned, 1) if planned else 0
        campaign["locations"] = [dict(item) for item in connection.execute(
            """SELECT municipality_id, municipality_name, uf, status, attempts, queries_planned,
                      queries_completed, businesses_found, qualified_leads, error, updated_at
               FROM geographic_campaign_locations WHERE campaign_id = ? ORDER BY id LIMIT 500""", (campaign_id,)).fetchall()]
        return campaign
    finally:
        connection.close()


def list_campaigns(db_name, limit=20):
    connection = _connect(db_name)
    try:
        ids = [row[0] for row in connection.execute(
            "SELECT campaign_id FROM geographic_campaigns ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 100)),)
        ).fetchall()]
    finally:
        connection.close()
    return [campaign_detail(db_name, campaign_id) for campaign_id in ids]


def set_campaign_status(db_name, campaign_id, status):
    allowed = {"pending", "running", "paused", "cancelled", "interrupted"}
    if status not in allowed:
        raise ValueError("Status de campanha inválido.")
    connection = _connect(db_name)
    try:
        cursor = connection.execute(
            "UPDATE geographic_campaigns SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE campaign_id = ?",
            (status, campaign_id),
        )
        if not cursor.rowcount:
            raise ValueError("Campanha geográfica não encontrada.")
        if status == "cancelled":
            connection.execute("""UPDATE geographic_campaign_locations SET status = 'cancelled',
                finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE campaign_id = ? AND status IN ('pending', 'running')""", (campaign_id,))
        connection.commit()
    finally:
        connection.close()


def claim_campaign_worker(db_name, campaign_id, worker_id, stale_minutes=15):
    connection = _connect(db_name)
    try:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            """SELECT status, worker_id, worker_heartbeat_at
               FROM geographic_campaigns WHERE campaign_id = ?""",
            (campaign_id,),
        ).fetchone()
        if not campaign or campaign["status"] not in {"pending", "interrupted", "running"}:
            connection.rollback()
            return False
        if campaign["status"] == "running":
            active = connection.execute(
                """SELECT 1 WHERE COALESCE(?, '') != ''
                   AND ? >= datetime('now', ?)""",
                (campaign["worker_id"], campaign["worker_heartbeat_at"], f"-{int(stale_minutes)} minutes"),
            ).fetchone()
            if active:
                connection.rollback()
                return False
        connection.execute(
            """UPDATE geographic_campaign_locations
               SET status = 'pending', updated_at = CURRENT_TIMESTAMP
               WHERE campaign_id = ? AND status = 'running'""",
            (campaign_id,),
        )
        connection.execute(
            """UPDATE geographic_campaigns
               SET status = 'running', worker_id = ?, worker_heartbeat_at = CURRENT_TIMESTAMP,
                   started_at = COALESCE(started_at, CURRENT_TIMESTAMP), updated_at = CURRENT_TIMESTAMP,
                   finished_at = NULL, error = NULL
               WHERE campaign_id = ?""",
            (worker_id, campaign_id),
        )
        connection.commit()
        return True
    finally:
        connection.close()


def touch_campaign_worker(db_name, campaign_id, worker_id):
    connection = _connect(db_name)
    try:
        connection.execute(
            """UPDATE geographic_campaigns
               SET worker_heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE campaign_id = ? AND worker_id = ? AND status = 'running'""",
            (campaign_id, worker_id),
        )
        connection.commit()
    finally:
        connection.close()


def interrupt_stale_campaign(db_name, campaign_id, stale_minutes=15):
    connection = _connect(db_name)
    try:
        cursor = connection.execute(
            """UPDATE geographic_campaigns
               SET status = 'interrupted', error = 'O processo de busca foi interrompido. Clique em continuar para retomar.',
                   worker_id = NULL, updated_at = CURRENT_TIMESTAMP
               WHERE campaign_id = ? AND status = 'running'
                 AND COALESCE(worker_heartbeat_at, updated_at) < datetime('now', ?)""",
            (campaign_id, f"-{int(stale_minutes)} minutes"),
        )
        if cursor.rowcount:
            connection.execute(
                """UPDATE geographic_campaign_locations
                   SET status = 'pending', updated_at = CURRENT_TIMESTAMP
                   WHERE campaign_id = ? AND status = 'running'""",
                (campaign_id,),
            )
        connection.commit()
        return bool(cursor.rowcount)
    finally:
        connection.close()


def claim_batch(db_name, campaign_id):
    connection = _connect(db_name)
    try:
        connection.execute("BEGIN IMMEDIATE")
        campaign = connection.execute(
            "SELECT status, batch_size FROM geographic_campaigns WHERE campaign_id = ?", (campaign_id,)
        ).fetchone()
        if not campaign or campaign["status"] != "running":
            connection.rollback()
            return []
        rows = connection.execute("""SELECT * FROM geographic_campaign_locations
            WHERE campaign_id = ? AND status = 'pending' ORDER BY id LIMIT ?""",
            (campaign_id, campaign["batch_size"])).fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            connection.execute(f"""UPDATE geographic_campaign_locations SET status = 'running', attempts = attempts + 1,
                started_at = COALESCE(started_at, CURRENT_TIMESTAMP), updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})""", ids)
        connection.commit()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def complete_location(db_name, location_id, stats=None, error=""):
    stats = stats or {}
    queries_completed = int(stats.get("tentativas_busca") or stats.get("consultas_concluidas") or 0)
    connection = _connect(db_name)
    try:
        row = connection.execute("SELECT campaign_id, queries_planned, status FROM geographic_campaign_locations WHERE id = ?", (location_id,)).fetchone()
        if not row:
            return
        if row["status"] == "cancelled":
            return
        if not error and queries_completed <= 0 and not int(stats.get("encontrados") or 0):
            error = "Nenhuma consulta real foi executada para esta localidade."
        status = "failed" if error else "completed"
        connection.execute("""UPDATE geographic_campaign_locations SET status = ?, queries_completed = ?,
            businesses_found = ?, qualified_leads = ?, last_search_run_id = ?, error = ?,
            finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (status, min(int(row["queries_planned"]), queries_completed), int(stats.get("encontrados") or 0),
             int(stats.get("salvos") or 0), stats.get("search_run_id"), str(error)[:500], location_id))
        connection.commit()
    finally:
        connection.close()


def finalize_campaign_if_done(db_name, campaign_id):
    connection = _connect(db_name)
    try:
        campaign = connection.execute("SELECT status FROM geographic_campaigns WHERE campaign_id = ?", (campaign_id,)).fetchone()
        if not campaign or campaign["status"] in {"paused", "cancelled"}:
            return False
        remaining = connection.execute("""SELECT COUNT(*) FROM geographic_campaign_locations
            WHERE campaign_id = ? AND status IN ('pending', 'running')""", (campaign_id,)).fetchone()[0]
        if remaining:
            return False
        aggregates = connection.execute("""SELECT
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END),
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END),
            COALESCE(SUM(businesses_found), 0), COALESCE(SUM(qualified_leads), 0),
            COALESCE(SUM(queries_completed), 0)
            FROM geographic_campaign_locations WHERE campaign_id = ?""", (campaign_id,)).fetchone()
        completed, failed, businesses, qualified, queries = [int(value or 0) for value in aggregates]
        successful = completed > 0 and queries > 0
        status = "completed" if successful else "failed"
        error = None if successful else "A campanha terminou sem executar consultas válidas. Verifique as fontes e tente novamente."
        connection.execute("""UPDATE geographic_campaigns SET status = ?, completed_municipalities = ?,
            failed_municipalities = ?, businesses_found = ?, qualified_leads = ?, error = ?,
            worker_id = NULL, worker_heartbeat_at = CURRENT_TIMESTAMP,
            finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE campaign_id = ?""",
            (status, completed, failed, businesses, qualified, error, campaign_id))
        connection.commit()
        return True
    finally:
        connection.close()


def save_location_set(db_name, name, selection):
    set_id = uuid.uuid4().hex
    connection = _connect(db_name)
    try:
        connection.execute("""INSERT INTO geographic_saved_sets (set_id, name, selection_json)
            VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET selection_json = excluded.selection_json,
            updated_at = CURRENT_TIMESTAMP""", (set_id, name, json.dumps(selection, ensure_ascii=False)))
        connection.commit()
    finally:
        connection.close()


def list_location_sets(db_name):
    connection = _connect(db_name)
    try:
        return [{**dict(row), "selection": json.loads(row["selection_json"])} for row in connection.execute(
            "SELECT * FROM geographic_saved_sets ORDER BY updated_at DESC"
        ).fetchall()]
    finally:
        connection.close()
