"""Worker task execution logic for AI Workforce."""

import logging
from typing import Dict, Any

from database.repositories import AgentRepository
from telemetry.tracker import ExecutionTracker

logger = logging.getLogger("ai_workforce.workers.agent_worker")


def process_agent_task(task_id: str, db_path: str = "gestao_leads.db") -> Dict[str, Any]:
    """
    Função executora padrão chamada tanto pelo RQ quanto pelo worker em thread assíncrona.
    - Busca a tarefa em agent_tasks
    - Marca como 'running'
    - Despacha para o manipulador
    - Registra telemetria e atualiza para 'completed' ou 'failed'
    """
    repo = AgentRepository(db_path=db_path)
    task = repo.get_task(task_id)
    if not task:
        logger.error(f"Tarefa {task_id} não encontrada para processamento.")
        return {"success": False, "error": f"Tarefa {task_id} não encontrada."}

    logger.info(f"Iniciando processamento da tarefa {task_id} para o agente {task['agent_name']}.")
    repo.update_task_status(task_id, status="running")

    try:
        with ExecutionTracker(
            agent_name=task["agent_name"],
            task_id=task_id,
            campaign_id=task.get("campaign_id"),
            model_used=task.get("payload", {}).get("model", "gemini-2.0-flash"),
            repository=repo,
        ) as tracker:
            tracker.log(f"Worker processando tarefa {task['task_type']} com prioridade {task.get('priority', 5)}")

            # Na Fase 1, executamos o pipeline de despacho técnico base
            result_data = _dispatch_task(task, tracker)

            repo.update_task_status(task_id, status="completed", result=result_data)
            tracker.log(f"Tarefa {task_id} finalizada com sucesso.")
            return {"success": True, "task_id": task_id, "result": result_data}

    except Exception as error:
        logger.error(f"Falha ao executar tarefa {task_id}: {error}", exc_info=True)
        repo.update_task_status(task_id, status="failed", error_message=str(error))
        repo.log_event(
            agent_name=task["agent_name"],
            message=f"Falha na tarefa {task_id}: {str(error)}",
            level="ERROR",
            task_id=task_id,
        )
        return {"success": False, "task_id": task_id, "error": str(error)}


def _dispatch_task(task: Dict[str, Any], tracker: ExecutionTracker) -> Dict[str, Any]:
    """
    Roteador de tarefas da fundação técnica.
    (Nas fases seguintes, conectará os 9 agentes CrewAI definitivos).
    """
    task_type = task.get("task_type", "diagnostic")
    payload = task.get("payload", {})

    if task_type in ("diagnostic", "healthcheck", "ping"):
        tracker.add_tokens(prompt=25, completion=20)
        return {
            "status": "healthy",
            "agent": task["agent_name"],
            "task_type": task_type,
            "message": "Tarefa de diagnóstico da fundação técnica executada com sucesso.",
            "echo_payload": payload,
        }

    # Tarefas futuras são reconhecidas e registradas
    return {
        "status": "acknowledged",
        "agent": task["agent_name"],
        "task_type": task_type,
        "message": f"Tarefa {task_type} recebida e enfileirada para o AI Workforce.",
        "input_keys": list(payload.keys()),
    }
