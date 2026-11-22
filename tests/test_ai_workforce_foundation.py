"""Unit tests for gestaoLead AI Workforce Phase 1 Foundation."""

import os
import time
import tempfile
import unittest

from database.migrations import run_ai_workforce_migrations, rollback_ai_workforce_migrations
from database.repositories import AgentRepository
from telemetry.cost_calculator import calculate_model_cost
from telemetry.tracker import ExecutionTracker
from tools.base_tool import BaseAgentTool, ToolResult
from agents.registry import list_available_agents, get_agent_metadata
from integrations.model_provider import ModelGateway
from workers.task_queue import TaskQueueManager
from workers.agent_worker import process_agent_task
from orchestrator.coordinator import WorkforceCoordinator
from app import app


class TestDummyTool(BaseAgentTool):
    name = "dummy_tool"
    description = "Ferramenta de teste para validação de tools."

    def execute(self, text: str = "") -> str:
        return f"Echo: {text}"


class AIWorkforceFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_workforce.db")
        run_ai_workforce_migrations(self.db_path)
        self.repo = AgentRepository(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    # 1. Testes de Migrações
    def test_migrations_and_idempotency(self):
        # Segunda execução deve ser idempotente
        res = run_ai_workforce_migrations(self.db_path)
        self.assertTrue(res["success"])
        self.assertFalse(res["applied"])

        # Rollback seguro
        rollback_res = rollback_ai_workforce_migrations(self.db_path)
        self.assertTrue(rollback_res["success"])

        # Re-aplicar com sucesso
        re_res = run_ai_workforce_migrations(self.db_path)
        self.assertTrue(re_res["success"])
        self.assertTrue(re_res["applied"])

    # 2. Testes de Repositório
    def test_repository_task_lifecycle(self):
        task = self.repo.create_task(
            task_id="task_001",
            agent_name="lead_discovery_agent",
            task_type="discover_leads",
            payload={"niche": "clinica", "city": "Campinas"},
            campaign_id="camp_test",
        )
        self.assertEqual(task["task_id"], "task_001")
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["payload"]["niche"], "clinica")

        # Atualizar para running e completed
        self.assertTrue(self.repo.update_task_status("task_001", status="running"))
        task_running = self.repo.get_task("task_001")
        self.assertEqual(task_running["status"], "running")

        self.assertTrue(self.repo.update_task_status(
            "task_001",
            status="completed",
            result={"leads_found": 15},
        ))
        task_done = self.repo.get_task("task_001")
        self.assertEqual(task_done["status"], "completed")
        self.assertEqual(task_done["result"]["leads_found"], 15)

    def test_repository_execution_and_telemetry(self):
        with ExecutionTracker(
            agent_name="market_intelligence_agent",
            task_id="task_002",
            campaign_id="camp_002",
            model_used="gemini-2.0-flash",
            repository=self.repo,
        ) as tracker:
            tracker.add_tokens(prompt=500, completion=200)
            tracker.log("Análise de mercado concluída", level="INFO")

        executions = self.repo.list_executions(agent_name="market_intelligence_agent")
        self.assertEqual(len(executions), 1)
        exec_item = executions[0]
        self.assertEqual(exec_item["status"], "success")
        self.assertEqual(exec_item["prompt_tokens"], 500)
        self.assertEqual(exec_item["completion_tokens"], 200)
        self.assertGreater(exec_item["cost_usd"], 0)
        self.assertGreater(exec_item["cost_brl"], 0)

        logs = self.repo.list_logs(agent_name="market_intelligence_agent")
        self.assertGreaterEqual(len(logs), 2)

    # 3. Testes de Cálculo de Custos
    def test_cost_calculator(self):
        # 1M prompt ($0.10) + 1M completion ($0.40) no gemini-2.0-flash = $0.50 USD
        cost_usd, cost_brl = calculate_model_cost("gemini-2.0-flash", 1_000_000, 1_000_000, usd_brl_rate=5.80)
        self.assertAlmostEqual(cost_usd, 0.50, places=4)
        self.assertAlmostEqual(cost_brl, 2.90, places=2)

        # Modelo local/ollama deve ser gratuito
        local_usd, local_brl = calculate_model_cost("local", 500_000, 500_000)
        self.assertEqual(local_usd, 0.0)
        self.assertEqual(local_brl, 0.0)

    # 4. Testes de Ferramenta Base
    def test_base_tool_execution(self):
        tool = TestDummyTool()
        result = tool.run(text="GestaoLead")
        self.assertTrue(result.success)
        self.assertEqual(result.data, "Echo: GestaoLead")
        self.assertEqual(result.error, "")

    # 5. Testes de Roster de Agentes
    def test_agent_roster(self):
        agents = list_available_agents()
        self.assertEqual(len(agents), 9)
        agent_ids = {a["id"] for a in agents}
        self.assertIn("manager_agent", agent_ids)
        self.assertIn("lead_discovery_agent", agent_ids)
        self.assertIn("sales_agent", agent_ids)
        self.assertIn("system_auditor_agent", agent_ids)

    # 6. Testes do Gateway de Modelos
    def test_model_gateway(self):
        self.assertEqual(ModelGateway.resolve_model_name("flash"), "gemini-2.0-flash")
        self.assertEqual(ModelGateway.resolve_model_name("gpt-mini"), "gpt-4o-mini")
        self.assertGreater(ModelGateway.estimate_tokens("Olá mundo, este é um teste"), 0)
        providers = ModelGateway.provider_status()
        self.assertIn("gemini", providers)
        self.assertIn("local", providers)

    # 7. Testes da Fila Assíncrona e Worker
    def test_async_task_processing(self):
        queue_mgr = TaskQueueManager(db_path=self.db_path)
        task_record = queue_mgr.enqueue_task(
            task_id="task_async_01",
            agent_name="system_auditor_agent",
            task_type="diagnostic",
            payload={"check": "connectivity"},
        )
        self.assertEqual(task_record["status"], "queued")

        # Aguardar processamento pelo SingleWorkerThreadQueue
        for _ in range(30):
            time.sleep(0.1)
            t = self.repo.get_task("task_async_01")
            if t and t["status"] == "completed":
                break

        final_task = self.repo.get_task("task_async_01")
        self.assertEqual(final_task["status"], "completed")
        self.assertEqual(final_task["result"]["status"], "healthy")

    # 8. Testes do Coordenador
    def test_workforce_coordinator(self):
        coordinator = WorkforceCoordinator(db_path=self.db_path)
        status = coordinator.get_operational_status()
        self.assertEqual(status["workforce_status"], "operational")
        self.assertEqual(status["phase"], "fase_1_fundacao_tecnica")
        self.assertEqual(status["agents_registered"], 9)
        self.assertTrue(status["queue"]["memory_safe_mode"])

    # 9. Testes de Endpoints da API via Flask Test Client
    def test_api_authentication_protection(self):
        with app.test_client() as client:
            # Sem autenticação deve retornar 401
            res_status = client.get("/api/ai-workforce/status")
            self.assertEqual(res_status.status_code, 401)
            data = res_status.get_json()
            self.assertFalse(data["success"])
            self.assertEqual(data["error"], "Não autenticado")

    def test_api_authenticated_access(self):
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["authenticated"] = True
                sess["csrf_token"] = "csrf_test_token"

            # 1. Status
            res = client.get("/api/ai-workforce/status")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["data"]["phase"], "fase_1_fundacao_tecnica")

            # 2. Agentes
            res_agents = client.get("/api/ai-workforce/agents")
            self.assertEqual(res_agents.status_code, 200)
            data_agents = res_agents.get_json()
            self.assertEqual(data_agents["count"], 9)

            # 3. Submissão de Tarefa
            res_submit = client.post(
                "/api/ai-workforce/tasks",
                json={
                    "agent_name": "market_intelligence_agent",
                    "task_type": "diagnostic",
                    "payload": {"niche": "energia_solar"},
                },
                headers={"X-CSRF-Token": "csrf_test_token"},
            )
            self.assertEqual(res_submit.status_code, 202)
            task_info = res_submit.get_json()
            self.assertTrue(task_info["success"])
            task_id = task_info["task_id"]

            # 4. Consulta de Tarefa
            res_get = client.get(f"/api/ai-workforce/tasks/{task_id}")
            self.assertEqual(res_get.status_code, 200)

            # 5. Custos
            res_costs = client.get("/api/ai-workforce/costs")
            self.assertEqual(res_costs.status_code, 200)


if __name__ == "__main__":
    unittest.main()
