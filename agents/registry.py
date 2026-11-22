"""Registry and metadata of AI Workforce agents."""

from typing import Dict, Any, List

AGENT_ROSTER: Dict[str, Dict[str, Any]] = {
    "manager_agent": {
        "id": "manager_agent",
        "name": "Manager Agent",
        "role": "Coordenador Geral e Guardião da Meta",
        "goal": "Orquestrar a equipe de agentes para entregar a meta de 100 leads qualificados (score >= 70) por campanha com custo e tempo mínimos.",
        "status": "planned",
        "capabilities": ["task_delegation", "campaign_monitoring", "budget_governance", "goal_tracking"],
        "default_model": "gemini-2.0-flash",
    },
    "market_intelligence_agent": {
        "id": "market_intelligence_agent",
        "name": "Market Intelligence Agent",
        "role": "Estrategista de Mercado e Nichos",
        "goal": "Identificar oportunidades de alta demanda, dores comerciais do nicho e ângulos estratégicos de abordagem.",
        "status": "planned",
        "capabilities": ["niche_analysis", "commercial_pain_extraction", "market_density"],
        "default_model": "gemini-2.0-flash",
    },
    "geographic_research_agent": {
        "id": "geographic_research_agent",
        "name": "Geographic Research Agent",
        "role": "Pesquisador Regional e Cartógrafo Comercial",
        "goal": "Mapear cidades e micro-regiões viáveis, garantindo que locais já pesquisados nunca sejam repetidos.",
        "status": "planned",
        "capabilities": ["location_mapping", "deduplication_by_city", "route_planning"],
        "default_model": "gemini-2.0-flash",
    },
    "lead_discovery_agent": {
        "id": "lead_discovery_agent",
        "name": "Lead Discovery Agent",
        "role": "Minerador de Dados Reais",
        "goal": "Extrair empresas reais diretamente do Google Maps via Playwright sem alucinações de dados ou contatos.",
        "status": "planned",
        "capabilities": ["maps_scraping", "html_evidence_extraction", "raw_data_collection"],
        "default_model": "local",
    },
    "lead_qualification_agent": {
        "id": "lead_qualification_agent",
        "name": "Lead Qualification Agent",
        "role": "Auditor de Potencial Comercial",
        "goal": "Avaliar a presença digital e aplicar a matriz de corte de 70/100 para qualificar ou descartar candidatos.",
        "status": "planned",
        "capabilities": ["score_calculation", "digital_presence_audit", "fit_analysis"],
        "default_model": "gemini-2.0-flash",
    },
    "data_validation_agent": {
        "id": "data_validation_agent",
        "name": "Data Validation Agent",
        "role": "Guardião da Integridade e Deduplicação",
        "goal": "Validar sintaxe de telefones no padrão brasileiro, verificar canais ativos e impedir leads duplicados no banco.",
        "status": "planned",
        "capabilities": ["phone_sanitization", "domain_check", "hash_deduplication"],
        "default_model": "local",
    },
    "sales_agent": {
        "id": "sales_agent",
        "name": "Sales Agent",
        "role": "Copywriter Comercial de Alta Conversão",
        "goal": "Criar abordagens de vendas personalizadas (Direta, Consultiva, Curiosidade) baseadas em evidências reais do lead.",
        "status": "planned",
        "capabilities": ["pitch_crafting", "copywriting_variants", "personalized_messaging"],
        "default_model": "gemini-2.0-flash",
    },
    "website_preview_agent": {
        "id": "website_preview_agent",
        "name": "Website Preview Agent",
        "role": "Diretor de Arte e Sites Demonstrativos",
        "goal": "Estruturar conceitos visuais de sites e gerar imagens de prévias em alta resolução para envio pelo WhatsApp.",
        "status": "planned",
        "capabilities": ["visual_direction", "canvas_rendering", "preview_validation"],
        "default_model": "gemini-2.0-flash",
    },
    "system_auditor_agent": {
        "id": "system_auditor_agent",
        "name": "System Auditor Agent",
        "role": "Controlador Interno e Otimizador do Sistema",
        "goal": "Auditar execuções, monitorar erros, consumo de tokens, custos operacionais e propor melhorias contínuas no sistema.",
        "status": "planned",
        "capabilities": ["cost_auditing", "error_telemetry", "self_diagnosis", "performance_monitoring"],
        "default_model": "gemini-2.0-flash",
    },
}


def list_available_agents() -> List[Dict[str, Any]]:
    """Retorna lista com todos os agentes registrados e seus metadados."""
    return list(AGENT_ROSTER.values())


def get_agent_metadata(agent_id: str) -> Dict[str, Any]:
    """Retorna os metadados de um agente específico."""
    return AGENT_ROSTER.get(agent_id, {
        "id": agent_id,
        "name": agent_id,
        "role": "Agente desconhecido",
        "goal": "",
        "status": "unknown",
        "capabilities": [],
        "default_model": "gemini-2.0-flash",
    })
