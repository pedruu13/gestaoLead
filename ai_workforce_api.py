"""Flask API Blueprint for gestaoLead AI Workforce."""

from flask import Blueprint, jsonify, request

from orchestrator.coordinator import get_coordinator

ai_workforce_bp = Blueprint("ai_workforce", __name__, url_prefix="/api/ai-workforce")


def _get_db_name():
    from app import DB_NAME
    return DB_NAME


@ai_workforce_bp.route("/status", methods=["GET"])
def get_workforce_status():
    """Retorna o status operacional do AI Workforce, filas e provedores."""
    coordinator = get_coordinator(db_path=_get_db_name())
    status = coordinator.get_operational_status()
    return jsonify({"success": True, "data": status})


@ai_workforce_bp.route("/agents", methods=["GET"])
def get_agents():
    """Retorna a lista dos 9 agentes planejados com suas capacidades e metadados."""
    coordinator = get_coordinator(db_path=_get_db_name())
    agents = coordinator.get_agents()
    return jsonify({"success": True, "count": len(agents), "agents": agents})


@ai_workforce_bp.route("/tasks", methods=["GET"])
def list_tasks():
    """Lista tarefas enfileiradas ou executadas com filtros opcionais."""
    coordinator = get_coordinator(db_path=_get_db_name())
    status = request.args.get("status")
    agent_name = request.args.get("agent_name")
    campaign_id = request.args.get("campaign_id")
    limit = min(100, max(1, int(request.args.get("limit", 50))))
    offset = max(0, int(request.args.get("offset", 0)))

    tasks = coordinator.list_tasks(
        status=status,
        agent_name=agent_name,
        campaign_id=campaign_id,
        limit=limit,
        offset=offset,
    )
    return jsonify({"success": True, "count": len(tasks), "tasks": tasks})


@ai_workforce_bp.route("/tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    """Consulta detalhes de uma tarefa específica."""
    coordinator = get_coordinator(db_path=_get_db_name())
    task = coordinator.get_task(task_id)
    if not task:
        return jsonify({"success": False, "error": f"Tarefa {task_id} não encontrada."}), 404
    return jsonify({"success": True, "task": task})


@ai_workforce_bp.route("/tasks", methods=["POST"])
def submit_task():
    """Submete uma nova tarefa para ser executada assincronamente pelo agente."""
    payload = request.get_json(silent=True) or {}
    agent_name = payload.get("agent_name", "").strip()
    task_type = payload.get("task_type", "").strip()

    if not agent_name:
        return jsonify({"success": False, "error": "Campo 'agent_name' é obrigatório."}), 400
    if not task_type:
        return jsonify({"success": False, "error": "Campo 'task_type' é obrigatório."}), 400

    coordinator = get_coordinator(db_path=_get_db_name())
    result = coordinator.submit_task(
        agent_name=agent_name,
        task_type=task_type,
        payload=payload.get("payload", {}),
        campaign_id=payload.get("campaign_id"),
        priority=int(payload.get("priority", 5)),
    )
    return jsonify(result), 202


@ai_workforce_bp.route("/executions", methods=["GET"])
def list_executions():
    """Consulta o histórico de execuções dos agentes com telemetria e tempos."""
    coordinator = get_coordinator(db_path=_get_db_name())
    agent_name = request.args.get("agent_name")
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    limit = min(100, max(1, int(request.args.get("limit", 50))))
    offset = max(0, int(request.args.get("offset", 0)))

    executions = coordinator.list_executions(
        agent_name=agent_name,
        campaign_id=campaign_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return jsonify({"success": True, "count": len(executions), "executions": executions})


@ai_workforce_bp.route("/costs", methods=["GET"])
def get_costs():
    """Consulta relatório consolidado e detalhado de consumo de tokens e custos em USD/BRL."""
    coordinator = get_coordinator(db_path=_get_db_name())
    campaign_id = request.args.get("campaign_id")
    costs = coordinator.get_costs(campaign_id=campaign_id)
    return jsonify({"success": True, "data": costs})
