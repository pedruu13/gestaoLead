"""Central coordinator for AI Workforce orchestration."""

import uuid
from typing import Dict, Any, Optional, List

from agents.registry import list_available_agents, get_agent_metadata
from database.repositories import AgentRepository
from integrations.model_provider import ModelGateway
from workers.task_queue import get_task_queue, TaskQueueManager


class WorkforceCoordinator:
    """
    Coordenador central da orquestração multiagente.
    Ponto de contato entre o Flask / APIs e o AI Workforce.
    """

    def __init__(self, db_path: str = "gestao_leads.db"):
        self.db_path = db_path
        self.repository = AgentRepository(db_path=self.db_path)
        self.queue_manager: TaskQueueManager = get_task_queue(db_path=self.db_path)

    def submit_task(
        self,
        agent_name: str,
        task_type: str,
        payload: Optional[Dict[str, Any]] = None,
        campaign_id: Optional[str] = None,
        priority: int = 5,
    ) -> Dict[str, Any]:
        """
        Submete uma nova tarefa para ser executada assincronamente pelo agente.
        Gera um task_id único e enfileira imediatamente.
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        task = self.queue_manager.enqueue_task(
            task_id=task_id,
            agent_name=agent_name,
            task_type=task_type,
            payload=payload or {},
            campaign_id=campaign_id,
            priority=priority,
        )
        return {
            "success": True,
            "task_id": task_id,
            "status": task.get("status", "queued"),
            "agent_name": agent_name,
            "queued_at": task.get("queued_at"),
        }

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.repository.get_task(task_id)

    def list_tasks(
        self,
        status: Optional[str] = None,
        agent_name: Optional[str] = None,
        campaign_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        return self.repository.list_tasks(
            status=status,
            agent_name=agent_name,
            campaign_id=campaign_id,
            limit=limit,
            offset=offset,
        )

    def list_executions(
        self,
        agent_name: Optional[str] = None,
        campaign_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        return self.repository.list_executions(
            agent_name=agent_name,
            campaign_id=campaign_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    def get_costs(self, campaign_id: Optional[str] = None) -> Dict[str, Any]:
        return self.repository.get_cost_summary(campaign_id=campaign_id)

    def get_agents(self) -> List[Dict[str, Any]]:
        return list_available_agents()

    def get_operational_status(self) -> Dict[str, Any]:
        """Consolida o status completo do AI Workforce."""
        queue_status = self.queue_manager.get_status()
        providers = ModelGateway.provider_status()
        costs = self.get_costs()
        agents = self.get_agents()

        return {
            "workforce_status": "operational",
            "phase": "fase_1_fundacao_tecnica",
            "agents_registered": len(agents),
            "queue": queue_status,
            "providers": providers,
            "cost_summary": {
                "total_cost_usd": costs.get("total_cost_usd", 0.0),
                "total_cost_brl": costs.get("total_cost_brl", 0.0),
                "total_tokens": costs.get("total_prompt_tokens", 0) + costs.get("total_completion_tokens", 0),
            },
        }


_global_coordinator: Optional[WorkforceCoordinator] = None


def get_coordinator(db_path: str = "gestao_leads.db") -> WorkforceCoordinator:
    global _global_coordinator
    if _global_coordinator is None:
        _global_coordinator = WorkforceCoordinator(db_path=db_path)
    return _global_coordinator
