"""Asynchronous task queue manager for gestaoLead AI Workforce."""

import os
import queue
import logging
import threading
from typing import Dict, Any, Optional

from database.repositories import AgentRepository
from .agent_worker import process_agent_task

logger = logging.getLogger("ai_workforce.workers.task_queue")


class SingleWorkerThreadQueue:
    """
    Fila assíncrona baseada em thread única local.
    Garante:
    - Execução desacoplada da requisição HTTP
    - Exatamente 1 worker concorrente para poupar memória da VM (máximo 15-20 MB de overhead)
    - Fallback resiliente automático quando Redis não estiver instalado ou conectado
    """

    def __init__(self, db_path: str = "gestao_leads.db"):
        self.db_path = db_path
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._lock = threading.Lock()
        self.start()

    def start(self):
        with self._lock:
            if not self._running:
                self._running = True
                self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="AIWorkforceSingleWorker")
                self._thread.start()
                logger.info("SingleWorkerThreadQueue iniciado (1 worker assíncrono).")

    def _worker_loop(self):
        while self._running:
            try:
                task_id = self._queue.get(timeout=1.0)
                try:
                    process_agent_task(task_id, db_path=self.db_path)
                except Exception as err:
                    logger.error(f"Erro no processamento da tarefa {task_id}: {err}", exc_info=True)
                finally:
                    self._queue.task_done()
            except queue.Empty:
                continue

    def enqueue(self, task_id: str):
        self._queue.put(task_id)

    def qsize(self) -> int:
        return self._queue.qsize()

    def stop(self):
        with self._lock:
            self._running = False


class TaskQueueManager:
    """
    Gerenciador unificado de filas do AI Workforce:
    - Avalia Redis + RQ como primeira opção
    - Fallback automático para SingleWorkerThreadQueue se Redis estiver ausente
    - Garante concorrência limitada (1 worker) para proteger a memória do servidor
    """

    def __init__(self, db_path: str = "gestao_leads.db", redis_url: Optional[str] = None):
        self.db_path = db_path
        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.repository = AgentRepository(db_path=self.db_path)

        self._backend: str = "internal_single_worker"
        self._rq_queue = None
        self._internal_worker: Optional[SingleWorkerThreadQueue] = None

        self._initialize_backend()

    def _initialize_backend(self):
        """Tenta conectar ao Redis + RQ; se falhar, utiliza o SingleWorkerThreadQueue."""
        try:
            import redis
            from rq import Queue

            client = redis.from_url(self.redis_url, socket_connect_timeout=1.5)
            client.ping()
            self._rq_queue = Queue("ai_workforce", connection=client)
            self._backend = "redis_rq"
            logger.info("TaskQueueManager conectado com sucesso ao Redis + RQ.")
        except Exception as err:
            logger.info(f"Redis não disponível ({err}). Utilizando SingleWorkerThreadQueue (1 worker leve).")
            self._internal_worker = SingleWorkerThreadQueue(db_path=self.db_path)
            self._backend = "internal_single_worker"

    def enqueue_task(
        self,
        task_id: str,
        agent_name: str,
        task_type: str,
        payload: Optional[Dict[str, Any]] = None,
        campaign_id: Optional[str] = None,
        priority: int = 5,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """
        Cria o registro persistente em agent_tasks e enfileira para execução assíncrona.
        Retorna imediatamente sem bloquear a requisição HTTP.
        """
        # 1. Registrar no banco com status 'queued'
        task_record = self.repository.create_task(
            task_id=task_id,
            agent_name=agent_name,
            task_type=task_type,
            payload=payload,
            campaign_id=campaign_id,
            priority=priority,
            max_retries=max_retries,
        )

        # 2. Despachar para a fila assíncrona
        if self._backend == "redis_rq" and self._rq_queue is not None:
            self._rq_queue.enqueue(process_agent_task, task_id, self.db_path)
        else:
            if not self._internal_worker:
                self._internal_worker = SingleWorkerThreadQueue(db_path=self.db_path)
            self._internal_worker.enqueue(task_id)

        return task_record

    def get_status(self) -> Dict[str, Any]:
        """Retorna o status operacional da fila e dos workers."""
        pending_count = len(self.repository.list_tasks(status="queued", limit=1000))
        running_count = len(self.repository.list_tasks(status="running", limit=1000))

        queue_size = 0
        if self._backend == "redis_rq" and self._rq_queue is not None:
            queue_size = len(self._rq_queue)
        elif self._internal_worker:
            queue_size = self._internal_worker.qsize()

        return {
            "backend": self._backend,
            "worker_concurrency": 1,
            "queue_name": "ai_workforce",
            "redis_connected": self._backend == "redis_rq",
            "memory_safe_mode": True,
            "queue_size": queue_size,
            "tasks_queued_in_db": pending_count,
            "tasks_running_in_db": running_count,
        }


# Instância singleton global
_global_queue_manager: Optional[TaskQueueManager] = None
_global_lock = threading.Lock()


def get_task_queue(db_path: str = "gestao_leads.db") -> TaskQueueManager:
    global _global_queue_manager
    with _global_lock:
        if _global_queue_manager is None:
            _global_queue_manager = TaskQueueManager(db_path=db_path)
        return _global_queue_manager
