import json
import sqlite3
import time
import uuid
from datetime import datetime, timedelta

from contact_quality import digits_only, normalize_email, website_domain
from discovery_sources import source_registry, stable_cache_key
from target_intelligence import normalize


ENGINE_VERSION = "1.0"


def init_discovery_schema(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS discovery_jobs
        (job_id TEXT PRIMARY KEY, search_run_id TEXT, engine_version TEXT NOT NULL,
         status TEXT NOT NULL, payload_json TEXT NOT NULL, checkpoint_json TEXT DEFAULT '{}',
         stats_json TEXT DEFAULT '{}', error TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, finished_at TIMESTAMP)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS discovery_candidates
        (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, source TEXT NOT NULL,
         source_id TEXT NOT NULL, identity_key TEXT NOT NULL, payload_json TEXT NOT NULL,
         status TEXT DEFAULT 'discovered', validation_json TEXT DEFAULT '{}', attempts INTEGER DEFAULT 0,
         error TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         UNIQUE(job_id, source, source_id))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS discovery_cache
        (cache_key TEXT PRIMARY KEY, source TEXT NOT NULL, payload_json TEXT NOT NULL,
         expires_at TIMESTAMP NOT NULL, hit_count INTEGER DEFAULT 0,
         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS source_usage
        (usage_date TEXT NOT NULL, source TEXT NOT NULL, requests INTEGER DEFAULT 0,
         candidates INTEGER DEFAULT 0, estimated_cost_micros INTEGER DEFAULT 0, errors INTEGER DEFAULT 0,
         PRIMARY KEY(usage_date, source))""")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_discovery_jobs_status ON discovery_jobs(status, updated_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_discovery_candidates_job ON discovery_candidates(job_id, status)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_discovery_candidates_identity ON discovery_candidates(identity_key)")
    connection.execute("UPDATE discovery_jobs SET status = 'interrupted', updated_at = CURRENT_TIMESTAMP WHERE status = 'running'")


def candidate_identity_keys(candidate):
    domain = website_domain(candidate.get("website"))
    phone = digits_only(candidate.get("phone"))[-11:]
    email = normalize_email(candidate.get("email"))
    name = normalize(candidate.get("name"))
    location = normalize(candidate.get("address") or candidate.get("location"))
    keys = set()
    if domain:
        keys.add(f"domain:{domain}")
    if len(phone) >= 10:
        keys.add(f"phone:{phone}")
    if email:
        keys.add(f"email:{email}")
    if name and location:
        keys.add(f"name:{name}|location:{location}")
    return keys or {f"source:{candidate.get('source')}:{candidate.get('source_id')}"}


def candidate_identity(candidate):
    keys = candidate_identity_keys(candidate)
    for prefix in ("domain:", "phone:", "email:", "name:", "source:"):
        matching = sorted(key for key in keys if key.startswith(prefix))
        if matching:
            return matching[0]
    return sorted(keys)[0]


class DiscoveryEngine:
    def __init__(self, db_name, config=None):
        self.db_name = db_name
        self.config = config or {}

    def _connect(self):
        connection = sqlite3.connect(self.db_name, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def create_job(self, payload, search_run_id=""):
        job_id = uuid.uuid4().hex
        connection = self._connect()
        try:
            connection.execute(
                """INSERT INTO discovery_jobs
                   (job_id, search_run_id, engine_version, status, payload_json, checkpoint_json, stats_json)
                   VALUES (?, ?, ?, 'pending', ?, '{}', '{}')""",
                (job_id, search_run_id, ENGINE_VERSION, json.dumps(payload, ensure_ascii=False)),
            )
            connection.commit()
        finally:
            connection.close()
        return job_id

    def _cache_get(self, source, request_payload):
        key = stable_cache_key(source, request_payload)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT payload_json FROM discovery_cache WHERE cache_key = ? AND expires_at > CURRENT_TIMESTAMP",
                (key,),
            ).fetchone()
            if not row:
                return key, None
            connection.execute("UPDATE discovery_cache SET hit_count = hit_count + 1, updated_at = CURRENT_TIMESTAMP WHERE cache_key = ?", (key,))
            connection.commit()
            return key, json.loads(row[0])
        finally:
            connection.close()

    def _cache_put(self, key, source, result, ttl_hours):
        expires_at = datetime.now() + timedelta(hours=ttl_hours)
        connection = self._connect()
        try:
            connection.execute(
                """INSERT INTO discovery_cache (cache_key, source, payload_json, expires_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(cache_key) DO UPDATE SET payload_json = excluded.payload_json,
                   expires_at = excluded.expires_at, updated_at = CURRENT_TIMESTAMP""",
                (key, source, json.dumps(result, ensure_ascii=False), expires_at.strftime("%Y-%m-%d %H:%M:%S")),
            )
            connection.commit()
        finally:
            connection.close()

    def _record_usage(self, source, requests=0, candidates=0, cost=0, errors=0):
        connection = self._connect()
        try:
            connection.execute(
                """INSERT INTO source_usage (usage_date, source, requests, candidates, estimated_cost_micros, errors)
                   VALUES (date('now'), ?, ?, ?, ?, ?)
                   ON CONFLICT(usage_date, source) DO UPDATE SET
                   requests = requests + excluded.requests,
                   candidates = candidates + excluded.candidates,
                   estimated_cost_micros = estimated_cost_micros + excluded.estimated_cost_micros,
                   errors = errors + excluded.errors""",
                (source, requests, candidates, cost, errors),
            )
            connection.commit()
        finally:
            connection.close()

    def _usage_today(self, source):
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT requests FROM source_usage WHERE usage_date = date('now') AND source = ?", (source,)
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            connection.close()

    def _store_candidates(self, job_id, candidates):
        connection = self._connect()
        stored = 0
        try:
            for candidate in candidates:
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO discovery_candidates
                       (job_id, source, source_id, identity_key, payload_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (job_id, candidate["source"], candidate["source_id"], candidate_identity(candidate), json.dumps(candidate, ensure_ascii=False)),
                )
                stored += cursor.rowcount
            connection.commit()
        finally:
            connection.close()
        return stored

    def _update_job(self, job_id, status=None, checkpoint=None, stats=None, error=None, finished=False):
        fields = ["updated_at = CURRENT_TIMESTAMP"]
        values = []
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if checkpoint is not None:
            fields.append("checkpoint_json = ?")
            values.append(json.dumps(checkpoint, ensure_ascii=False))
        if stats is not None:
            fields.append("stats_json = ?")
            values.append(json.dumps(stats, ensure_ascii=False))
        if error is not None:
            fields.append("error = ?")
            values.append(str(error)[:1000])
        if finished:
            fields.append("finished_at = CURRENT_TIMESTAMP")
        values.append(job_id)
        connection = self._connect()
        try:
            connection.execute(f"UPDATE discovery_jobs SET {', '.join(fields)} WHERE job_id = ?", values)
            connection.commit()
        finally:
            connection.close()

    def _load_job(self, job_id):
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM discovery_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                raise ValueError("Tarefa de descoberta não encontrada.")
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            item["checkpoint"] = json.loads(item.pop("checkpoint_json") or "{}")
            item["stats"] = json.loads(item.pop("stats_json") or "{}")
            return item
        finally:
            connection.close()

    def run(self, job_id, progress=None, cancelled=None):
        progress = progress or (lambda *_: None)
        cancelled = cancelled or (lambda: False)
        job = self._load_job(job_id)
        payload = job["payload"]
        niches = payload.get("niches") or []
        locations = payload.get("locations") or []
        tasks = [(niche, location) for location in locations for niche in niches]
        checkpoint = job["checkpoint"] or {"task_index": 0, "source_index": 0, "page_token": "", "page_number": 0}
        stats = {"tasks": len(tasks), "tasks_completed": 0, "requests": 0, "cache_hits": 0, "candidates": 0, "errors": 0, **job["stats"]}
        sources = [source for source in source_registry(self.config) if source.configured()]
        if not sources:
            self._update_job(job_id, status="failed", stats=stats, error="Nenhuma fonte configurada.", finished=True)
            raise RuntimeError("Nenhuma fonte de descoberta configurada.")
        self._update_job(job_id, status="running", checkpoint=checkpoint, stats=stats)
        def configured_integer(key, default, minimum=1):
            try:
                return max(minimum, int(self.config.get(key, default) or default))
            except (TypeError, ValueError):
                return default
        daily_limits = {
            "google_places": configured_integer("google_places_daily_limit", 40),
            "google_maps": configured_integer("google_maps_daily_limit", 500),
            "openstreetmap": configured_integer("openstreetmap_daily_limit", 500),
        }
        ttl_hours = configured_integer("discovery_cache_hours", 168)
        try:
            for task_index in range(int(checkpoint.get("task_index", 0)), len(tasks)):
                niche, location = tasks[task_index]
                source_start = int(checkpoint.get("source_index", 0)) if task_index == int(checkpoint.get("task_index", 0)) else 0
                for source_index in range(source_start, len(sources)):
                    source = sources[source_index]
                    if cancelled():
                        self._update_job(job_id, status="cancelled", checkpoint={"task_index": task_index, "source_index": source_index}, stats=stats, finished=True)
                        return self.load_candidates(job_id)
                    source_limit = daily_limits.get(source.name, 500)
                    if self._usage_today(source.name) >= source_limit:
                        progress(stats, f"Cota diária da fonte {source.name} atingida; avançando.")
                        continue
                    page_token = ""
                    max_pages = 2 if source.name == "google_places" else 1
                    for page_number in range(max_pages):
                        remaining_requests = source_limit - self._usage_today(source.name)
                        if remaining_requests <= 0:
                            progress(stats, f"Cota diária da fonte {source.name} atingida durante a paginação.")
                            break
                        expected_requests = 1 if page_token else int(getattr(source, "query_variants", 3 if source.name == "openstreetmap" else 1))
                        request_budget = min(remaining_requests, expected_requests)
                        request_payload = {
                            "extractor_version": 2,
                            "niche": niche, "location": location, "region": payload.get("region", "br"),
                            "page_token": page_token, "request_budget": request_budget,
                        }
                        key, result = self._cache_get(source.name, request_payload)
                        if result is None:
                            last_error = None
                            for attempt in range(2):
                                try:
                                    result = source.search(
                                        niche, location, payload.get("region", "br"),
                                        page_token=page_token, request_budget=request_budget,
                                    )
                                    break
                                except Exception as error:
                                    last_error = error
                                    if attempt == 0:
                                        time.sleep(0.5)
                            if result is None:
                                stats["errors"] += 1
                                self._record_usage(source.name, errors=1)
                                checkpoint = {
                                    "task_index": task_index,
                                    "source_index": source_index + 1,
                                    "page_token": "",
                                    "page_number": 0,
                                }
                                self._update_job(
                                    job_id,
                                    checkpoint=checkpoint,
                                    stats=stats,
                                    error=f"{source.name}: {last_error}",
                                )
                                progress(stats, f"{source.name} falhou após 2 tentativas; seguindo para a próxima fonte.")
                                break
                            if result.get("candidates") and not result.get("warnings"):
                                self._cache_put(key, source.name, result, ttl_hours)
                            requests = int(result.get("requests") or 1)
                            stats["requests"] += requests
                            self._record_usage(source.name, requests=requests, candidates=len(result.get("candidates", [])), cost=requests * source.estimated_cost_micros)
                        else:
                            stats["cache_hits"] += 1
                        stored = self._store_candidates(job_id, result.get("candidates", []))
                        stats["candidates"] += stored
                        page_token = str(result.get("next_page_token") or "")
                        checkpoint = {"task_index": task_index, "source_index": source_index, "page_token": page_token, "page_number": page_number}
                        self._update_job(job_id, checkpoint=checkpoint, stats=stats)
                        progress(stats, f"{source.name}: {niche} em {location} — {stored} novo(s).")
                        if not page_token:
                            break
                        time.sleep(0.2)
                stats["tasks_completed"] = task_index + 1
                checkpoint = {"task_index": task_index + 1, "source_index": 0, "page_token": "", "page_number": 0}
                self._update_job(job_id, checkpoint=checkpoint, stats=stats)
            failed_without_results = stats["errors"] > 0 and stats["candidates"] == 0
            self._update_job(job_id, status="failed" if failed_without_results else "completed", checkpoint=checkpoint, stats=stats, finished=True)
        except Exception as error:
            stats["errors"] += 1
            source_name = locals().get("source").name if locals().get("source") else "unknown"
            self._record_usage(source_name, errors=1)
            self._update_job(job_id, status="interrupted", checkpoint=checkpoint, stats=stats, error=error)
            raise
        return self.load_candidates(job_id)

    def load_candidates(self, job_id):
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT payload_json FROM discovery_candidates WHERE job_id = ? ORDER BY id", (job_id,)
            ).fetchall()
        finally:
            connection.close()
        candidates = [json.loads(row[0]) for row in rows]
        groups = []
        for candidate in candidates:
            keys = candidate_identity_keys(candidate)
            matching_group = next((group for group in groups if group["identity_keys"] & keys), None)
            if matching_group is None:
                merged = dict(candidate)
                merged["sources"] = [candidate["source"]]
                merged["source_records"] = [candidate]
                groups.append({"identity_keys": set(keys), "candidate": merged})
                continue
            merged = matching_group["candidate"]
            matching_group["identity_keys"].update(keys)
            merged["sources"].append(candidate["source"])
            merged["source_records"].append(candidate)
            for field in ("phone", "email", "website", "address", "source_url", "rating", "reviews"):
                if not merged.get(field) and candidate.get(field):
                    merged[field] = candidate[field]
        return [group["candidate"] for group in groups]

    def update_candidate_validation(self, job_id, candidate, status, validation=None, error=""):
        records = candidate.get("source_records") or [candidate]
        connection = self._connect()
        try:
            connection.executemany(
                """UPDATE discovery_candidates SET status = ?, validation_json = ?, error = ?,
                   attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP
                   WHERE job_id = ? AND source = ? AND source_id = ?""",
                [
                    (status, json.dumps(validation or {}, ensure_ascii=False), str(error or "")[:500],
                     job_id, record.get("source"), record.get("source_id"))
                    for record in records
                ],
            )
            connection.commit()
        finally:
            connection.close()

    def job_status(self, job_id):
        return self._load_job(job_id)
