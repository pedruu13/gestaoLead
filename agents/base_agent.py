"""Base agent class for AI Workforce."""

import abc
from typing import Any, Dict, List, Optional

from database.repositories import AgentRepository
from telemetry.tracker import ExecutionTracker
from tools.base_tool import BaseAgentTool


class BaseAgent(abc.ABC):
    """
    Classe base para todos os agentes autônomos do gestaoLead.
    Encapsula:
    - Identidade e atribuições
    - Ferramentas acopladas
    - Rastreamento e telemetria automáticos
    """

    agent_id: str = "base_agent"
    role: str = "Agente Base"
    goal: str = "Executar tarefas designadas."
    backstory: str = "Especialista em automação comercial."
    default_model: str = "gemini-2.0-flash"

    def __init__(
        self,
        tools: Optional[List[BaseAgentTool]] = None,
        model_name: Optional[str] = None,
        repository: Optional[AgentRepository] = None,
    ):
        self.tools: Dict[str, BaseAgentTool] = {tool.name: tool for tool in (tools or [])}
        self.model_name = model_name or self.default_model
        self.repository = repository or AgentRepository()

    def get_tool(self, name: str) -> Optional[BaseAgentTool]:
        return self.tools.get(name)

    @abc.abstractmethod
    def run_task(self, task: Dict[str, Any], tracker: ExecutionTracker) -> Dict[str, Any]:
        """Lógica de negócio executada pelo agente."""
        raise NotImplementedError

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ponto de entrada de execução com telemetria, medição de custos e tratamento de exceções.
        """
        task_id = task.get("task_id")
        campaign_id = task.get("campaign_id")

        with ExecutionTracker(
            agent_name=self.agent_id,
            task_id=task_id,
            campaign_id=campaign_id,
            model_used=self.model_name,
            repository=self.repository,
        ) as tracker:
            tracker.log(f"Agente {self.agent_id} iniciou a tarefa {task_id or 'ad-hoc'}")
            result = self.run_task(task, tracker)
            tracker.log(f"Agente {self.agent_id} concluiu a tarefa {task_id or 'ad-hoc'}")
            return result
