"""Execution tracking and telemetry for AI Workforce."""

import time
import uuid
import logging
from typing import Optional, Dict, Any

from database.repositories import AgentRepository
from .cost_calculator import calculate_model_cost

logger = logging.getLogger("ai_workforce.telemetry.tracker")


class ExecutionTracker:
    """
    Context manager para rastrear a execução de um agente:
    - Inicia registro em agent_executions
    - Mede duração em milissegundos
    - Registra tokens e custo
    - Grava status final e erros
    """

    def __init__(
        self,
        agent_name: str,
        task_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        model_used: Optional[str] = None,
        repository: Optional[AgentRepository] = None,
    ):
        self.agent_name = agent_name
        self.task_id = task_id
        self.campaign_id = campaign_id
        self.model_used = model_used or "gemini-2.0-flash"
        self.repository = repository or AgentRepository()
        self.execution_id = f"exec_{uuid.uuid4().hex[:12]}"

        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.status: str = "running"
        self.error_message: Optional[str] = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        try:
            self.repository.create_execution(
                execution_id=self.execution_id,
                agent_name=self.agent_name,
                task_id=self.task_id,
                campaign_id=self.campaign_id,
                model_used=self.model_used,
            )
            self.repository.log_event(
                agent_name=self.agent_name,
                message=f"Iniciando execução {self.execution_id}",
                level="INFO",
                task_id=self.task_id,
                execution_id=self.execution_id,
            )
        except Exception as err:
            logger.warning(f"Erro ao criar execution record: {err}")
        return self

    def add_tokens(self, prompt: int, completion: int):
        self.prompt_tokens += max(0, prompt)
        self.completion_tokens += max(0, completion)

    def log(self, message: str, level: str = "INFO", details: Optional[Dict[str, Any]] = None):
        try:
            self.repository.log_event(
                agent_name=self.agent_name,
                message=message,
                level=level,
                task_id=self.task_id,
                execution_id=self.execution_id,
                details=details,
            )
        except Exception as err:
            logger.warning(f"Erro ao registrar log de agente: {err}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.perf_counter()
        duration_ms = int((self.end_time - self.start_time) * 1000)

        if exc_type is not None:
            self.status = "failed"
            self.error_message = str(exc_val)
        else:
            self.status = "success"

        cost_usd, cost_brl = calculate_model_cost(
            self.model_used,
            self.prompt_tokens,
            self.completion_tokens,
        )

        try:
            self.repository.finish_execution(
                execution_id=self.execution_id,
                status=self.status,
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                cost_usd=cost_usd,
                cost_brl=cost_brl,
                execution_time_ms=duration_ms,
                error_message=self.error_message,
            )

            # Gravar também na tabela de custos se houver tokens
            if self.prompt_tokens > 0 or self.completion_tokens > 0:
                self.repository.record_cost(
                    execution_id=self.execution_id,
                    agent_name=self.agent_name,
                    model_name=self.model_used,
                    prompt_tokens=self.prompt_tokens,
                    completion_tokens=self.completion_tokens,
                    cost_usd=cost_usd,
                    cost_brl=cost_brl,
                    campaign_id=self.campaign_id,
                )
        except Exception as err:
            logger.warning(f"Erro ao finalizar execution record: {err}")

        # Retorna False para permitir que a exceção seja propagada se houver
        return False
