"""Repository for gestaoLead AI Workforce data access."""

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional


class AgentRepository:
    def __init__(self, db_path: str = "gestao_leads.db"):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    # ==========================================
    # TAREFAS (agent_tasks)
    # ==========================================
    def create_task(
        self,
        task_id: str,
        agent_name: str,
        task_type: str,
        payload: Optional[Dict[str, Any]] = None,
        campaign_id: Optional[str] = None,
        priority: int = 5,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        payload_str = json.dumps(payload or {}, ensure_ascii=False)
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO agent_tasks (
                    task_id, campaign_id, agent_name, task_type,
                    payload_json, priority, status, max_retries, queued_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, CURRENT_TIMESTAMP)
                """,
                (task_id, campaign_id, agent_name, task_type, payload_str, priority, max_retries),
            )
            conn.commit()
            return self.get_task(task_id) or {}
        finally:
            conn.close()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            try:
                data["payload"] = json.loads(data.pop("payload_json") or "{}")
            except (ValueError, TypeError):
                data["payload"] = {}
            try:
                data["result"] = json.loads(data.pop("result_json") or "{}")
            except (ValueError, TypeError):
                data["result"] = {}
            return data
        finally:
            conn.close()

    def list_tasks(
        self,
        status: Optional[str] = None,
        agent_name: Optional[str] = None,
        campaign_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            query = "SELECT * FROM agent_tasks WHERE 1=1"
            params: List[Any] = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if agent_name:
                query += " AND agent_name = ?"
                params.append(agent_name)
            if campaign_id:
                query += " AND campaign_id = ?"
                params.append(campaign_id)
            query += " ORDER BY queued_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            tasks = []
            for row in rows:
                item = dict(row)
                try:
                    item["payload"] = json.loads(item.pop("payload_json") or "{}")
                except Exception:
                    item["payload"] = {}
                try:
                    item["result"] = json.loads(item.pop("result_json") or "{}")
                except Exception:
                    item["result"] = {}
                tasks.append(item)
            return tasks
        finally:
            conn.close()

    def update_task_status(
        self,
        task_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        conn = self._get_connection()
        try:
            updates = ["status = ?"]
            params: List[Any] = [status]
            if status == "running":
                updates.append("started_at = CURRENT_TIMESTAMP")
            elif status in ("completed", "failed", "cancelled"):
                updates.append("completed_at = CURRENT_TIMESTAMP")

            if result is not None:
                updates.append("result_json = ?")
                params.append(json.dumps(result, ensure_ascii=False))
            if error_message is not None:
                updates.append("error_message = ?")
                params.append(error_message)

            params.append(task_id)
            cur = conn.execute(
                f"UPDATE agent_tasks SET {', '.join(updates)} WHERE task_id = ?",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # ==========================================
    # EXECUÇÕES (agent_executions)
    # ==========================================
    def create_execution(
        self,
        execution_id: str,
        agent_name: str,
        task_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        model_used: Optional[str] = None,
    ) -> Dict[str, Any]:
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO agent_executions (
                    execution_id, task_id, campaign_id, agent_name,
                    model_used, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'running', CURRENT_TIMESTAMP)
                """,
                (execution_id, task_id, campaign_id, agent_name, model_used),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM agent_executions WHERE execution_id = ?", (execution_id,)).fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    def finish_execution(
        self,
        execution_id: str,
        status: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
        cost_brl: float = 0.0,
        execution_time_ms: int = 0,
        error_message: Optional[str] = None,
    ) -> bool:
        conn = self._get_connection()
        try:
            total_tokens = prompt_tokens + completion_tokens
            cur = conn.execute(
                """
                UPDATE agent_executions SET
                    status = ?,
                    prompt_tokens = ?,
                    completion_tokens = ?,
                    total_tokens = ?,
                    cost_usd = ?,
                    cost_brl = ?,
                    execution_time_ms = ?,
                    error_message = ?,
                    finished_at = CURRENT_TIMESTAMP
                WHERE execution_id = ?
                """,
                (
                    status, prompt_tokens, completion_tokens, total_tokens,
                    cost_usd, cost_brl, execution_time_ms, error_message, execution_id
                ),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def list_executions(
        self,
        agent_name: Optional[str] = None,
        campaign_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            query = "SELECT * FROM agent_executions WHERE 1=1"
            params: List[Any] = []
            if agent_name:
                query += " AND agent_name = ?"
                params.append(agent_name)
            if campaign_id:
                query += " AND campaign_id = ?"
                params.append(campaign_id)
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ==========================================
    # LOGS (agent_logs)
    # ==========================================
    def log_event(
        self,
        agent_name: str,
        message: str,
        level: str = "INFO",
        task_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> int:
        conn = self._get_connection()
        try:
            details_str = json.dumps(details or {}, ensure_ascii=False)
            cur = conn.execute(
                """
                INSERT INTO agent_logs (
                    task_id, execution_id, agent_name, level, message, details_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, execution_id, agent_name, level.upper(), message, details_str),
            )
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()

    def list_logs(
        self,
        task_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        level: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            query = "SELECT * FROM agent_logs WHERE 1=1"
            params: List[Any] = []
            if task_id:
                query += " AND task_id = ?"
                params.append(task_id)
            if execution_id:
                query += " AND execution_id = ?"
                params.append(execution_id)
            if agent_name:
                query += " AND agent_name = ?"
                params.append(agent_name)
            if level:
                query += " AND level = ?"
                params.append(level.upper())
            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            logs = []
            for r in rows:
                item = dict(r)
                try:
                    item["details"] = json.loads(item.pop("details_json") or "{}")
                except Exception:
                    item["details"] = {}
                logs.append(item)
            return logs
        finally:
            conn.close()

    # ==========================================
    # CUSTOS (agent_costs)
    # ==========================================
    def record_cost(
        self,
        execution_id: str,
        agent_name: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        cost_brl: float,
        campaign_id: Optional[str] = None,
    ) -> int:
        conn = self._get_connection()
        try:
            cur = conn.execute(
                """
                INSERT INTO agent_costs (
                    execution_id, campaign_id, agent_name, model_name,
                    prompt_tokens, completion_tokens, cost_usd, cost_brl
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (execution_id, campaign_id, agent_name, model_name, prompt_tokens, completion_tokens, cost_usd, cost_brl),
            )
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()

    def get_cost_summary(self, campaign_id: Optional[str] = None) -> Dict[str, Any]:
        conn = self._get_connection()
        try:
            where_clause = "WHERE campaign_id = ?" if campaign_id else ""
            params = [campaign_id] if campaign_id else []
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) as total_entries,
                    COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                    COALESCE(SUM(cost_usd), 0.0) as total_cost_usd,
                    COALESCE(SUM(cost_brl), 0.0) as total_cost_brl
                FROM agent_costs {where_clause}
                """,
                params,
            ).fetchone()
            summary = dict(row) if row else {
                "total_entries": 0, "total_prompt_tokens": 0,
                "total_completion_tokens": 0, "total_cost_usd": 0.0, "total_cost_brl": 0.0,
            }

            # Breakdown por agente
            by_agent = conn.execute(
                f"""
                SELECT
                    agent_name,
                    COUNT(*) as executions,
                    SUM(prompt_tokens + completion_tokens) as total_tokens,
                    SUM(cost_usd) as cost_usd,
                    SUM(cost_brl) as cost_brl
                FROM agent_costs {where_clause}
                GROUP BY agent_name ORDER BY cost_usd DESC
                """,
                params,
            ).fetchall()
            summary["by_agent"] = [dict(r) for r in by_agent]
            return summary
        finally:
            conn.close()
