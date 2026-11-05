import json
import sqlite3
import uuid
from datetime import datetime

import geographic_campaigns
import geographic_intelligence
from niche_intelligence import canonical_niche_key


# Status detalhados exigidos pela interface
STATUS_MAP = {
    "preparando": "Preparando",
    "pesquisando_nichos": "Pesquisando nichos",
    "selecionando_regioes": "Selecionando regiões",
    "buscando_empresas": "Buscando empresas",
    "validando_leads": "Validando leads",
    "concluida": "Concluída",
    "pausada": "Pausada",
    "cancelada": "Cancelada",
    "falha": "Falha",
}

DEFAULT_AUTO_NICHES = [
    "Clínica de Estética",
    "Odontologia",
    "Advocacia",
    "Energia Solar",
    "Arquitetura",
    "Móveis Planejados",
]


def init_smart_campaigns_schema(connection):
    """Garante a inicialização do esquema geográfico e a migração segura das novas colunas."""
    geographic_campaigns.init_geographic_schema(connection)
    cursor = connection.cursor()
    cursor.execute("PRAGMA table_info(geographic_campaigns)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    new_columns = {
        "target_qualified_leads": "INTEGER NOT NULL DEFAULT 100",
        "min_qualification_score": "INTEGER NOT NULL DEFAULT 70",
        "detailed_status": "TEXT NOT NULL DEFAULT 'preparando'",
        "location_mode": "TEXT NOT NULL DEFAULT 'auto'",
        "niche_mode": "TEXT NOT NULL DEFAULT 'auto'",
        "is_exploratory": "INTEGER NOT NULL DEFAULT 0",
        "companies_searched": "INTEGER NOT NULL DEFAULT 0",
        "companies_analyzed": "INTEGER NOT NULL DEFAULT 0",
        "companies_discarded": "INTEGER NOT NULL DEFAULT 0",
        "niches_count": "INTEGER NOT NULL DEFAULT 1",
        "meta_metodologia": "TEXT DEFAULT ''",
    }

    for col_name, col_def in new_columns.items():
        if col_name not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE geographic_campaigns ADD COLUMN {col_name} {col_def}")
            except Exception:
                pass
    connection.commit()


def _connect(db_name):
    connection = sqlite3.connect(db_name, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def resolve_auto_niches(db_name, limit=4):
    """
    Identifica os nichos mais promissores e com menor saturação.
    Se a base estiver fria, recorre aos nichos de alta demanda comprovada.
    """
    connection = _connect(db_name)
    try:
        try:
            rows = connection.execute(
                """SELECT nicho, COUNT(*) as total,
                          SUM(CASE WHEN trim(coalesce(commercial_outcome, '')) != '' THEN 1 ELSE 0 END) as converts
                   FROM leads
                   WHERE trim(coalesce(nicho, '')) != ''
                   GROUP BY nicho
                   ORDER BY converts DESC, total ASC"""
            ).fetchall()

            if rows and len(rows) >= 2:
                niches = [row["nicho"] for row in rows if row["nicho"]][:limit]
                if len(niches) < limit:
                    for default_niche in DEFAULT_AUTO_NICHES:
                        if default_niche not in niches:
                            niches.append(default_niche)
                        if len(niches) >= limit:
                            break
                return niches, False
        except sqlite3.OperationalError:
            pass

        return DEFAULT_AUTO_NICHES[:limit], True
    finally:
        connection.close()


def resolve_auto_locations(db_name, limit=30):
    """
    Seleciona municípios promissores e balanceados do Brasil.
    Evita municípios que já foram completamente varridos.
    """
    catalog = geographic_intelligence.load_catalog()
    connection = _connect(db_name)
    try:
        # Cidades que já foram totalmente pesquisadas
        researched_ids = {
            row[0]
            for row in connection.execute(
                """SELECT municipality_id FROM geographic_campaign_locations
                   GROUP BY municipality_id
                   HAVING SUM(queries_planned) > 0 AND SUM(queries_completed) >= SUM(queries_planned)"""
            ).fetchall()
        }

        evidence = []
        conversions = []
        coverage = []
        try:
            evidence = [
                dict(row)
                for row in connection.execute(
                    """SELECT city, sample_size, verified_count, qualified_count, contactable_count
                       FROM target_research_observations"""
                ).fetchall()
            ]
        except sqlite3.OperationalError:
            pass
        try:
            conversions = [
                dict(row)
                for row in connection.execute(
                    """SELECT bairro, commercial_outcome FROM leads
                       WHERE trim(coalesce(commercial_outcome, '')) != ''"""
                ).fetchall()
            ]
        except sqlite3.OperationalError:
            pass
        try:
            coverage = [
                dict(row)
                for row in connection.execute(
                    """SELECT municipality_id,
                              CASE WHEN SUM(queries_planned) > 0 THEN SUM(queries_completed) * 100.0 / SUM(queries_planned) ELSE 0 END AS coverage_percent
                       FROM geographic_campaign_locations GROUP BY municipality_id"""
                ).fetchall()
            ]
        except sqlite3.OperationalError:
            pass

        if evidence or conversions:
            ranked = geographic_intelligence.rank_smart_locations(catalog, evidence, conversions, coverage, limit * 2)
            filtered = [item for item in ranked if item["id"] not in researched_ids]
            if len(filtered) >= limit:
                return filtered[:limit], False

        # Fallback inteligente: capitais e cidades pólo estratégicas distribuídas por regiões
        strategic_ufs = ["SP", "MG", "RJ", "PR", "SC", "RS", "GO", "DF", "BA", "PE", "CE"]
        candidates = []
        for mun in catalog["municipalities"]:
            if mun["id"] in researched_ids:
                continue
            if mun["uf"] in strategic_ufs and mun.get("population", 0) >= 80000:
                candidates.append(mun)

        # Ordena priorizando equilíbrio entre população e oportunidade comercial
        candidates.sort(key=lambda m: m.get("population", 0), reverse=True)

        selected = candidates[:limit] if candidates else catalog["municipalities"][:limit]
        is_exploratory = not (evidence or conversions)
        return selected, is_exploratory
    finally:
        connection.close()


def create_smart_campaign(db_name, payload):
    """
    Cria uma nova Campanha Inteligente validando localização, nicho e meta.
    """
    payload = payload or {}

    # 1. Localização
    location_mode = str(payload.get("location_mode") or "auto").strip().lower()
    if location_mode not in {"auto", "states", "cities", "brazil"}:
        location_mode = "auto"

    catalog = geographic_intelligence.load_catalog()
    is_exploratory = False
    locations = []

    if location_mode == "auto":
        locations, is_exploratory = resolve_auto_locations(db_name, limit=int(payload.get("locations_limit", 25)))
    elif location_mode == "states":
        state_codes = payload.get("states") or []
        if isinstance(state_codes, str):
            state_codes = [s.strip().upper() for s in state_codes.split(",") if s.strip()]
        if not state_codes:
            raise ValueError("Selecione pelo menos um estado para a campanha.")
        locations = geographic_intelligence.select_municipalities(catalog, mode="state", state_codes=state_codes)
    elif location_mode == "cities":
        municipality_ids = payload.get("municipality_ids") or []
        if not municipality_ids:
            raise ValueError("Selecione pelo menos um município para a campanha.")
        locations = geographic_intelligence.select_municipalities(catalog, mode="custom", municipality_ids=municipality_ids)
    elif location_mode == "brazil":
        locations = geographic_intelligence.select_municipalities(catalog, mode="brazil")

    if not locations:
        raise ValueError("Nenhum município foi encontrado com os critérios fornecidos.")

    # 2. Nicho
    niche_mode = str(payload.get("niche_mode") or "auto").strip().lower()
    if niche_mode not in {"auto", "manual"}:
        niche_mode = "auto"

    niches = []
    if niche_mode == "auto":
        auto_niches, niche_exploratory = resolve_auto_niches(db_name, limit=3)
        niches = auto_niches
        if niche_exploratory:
            is_exploratory = True
    else:
        raw_niches = payload.get("niches") or []
        if isinstance(raw_niches, str):
            raw_niches = [n.strip() for n in raw_niches.split(",") if n.strip()]
        niches = [n for n in raw_niches if n]
        if not niches:
            raise ValueError("Informe pelo menos um nicho específico para a campanha.")

    # 3. Meta de Leads Qualificados
    try:
        target_leads = int(payload.get("target_qualified_leads", payload.get("target_leads", 100)))
    except (TypeError, ValueError):
        target_leads = 100
    target_leads = max(5, min(target_leads, 2000))

    # Score mínimo de qualificação (padrão 70/100)
    try:
        min_score = int(payload.get("min_qualification_score", 70))
    except (TypeError, ValueError):
        min_score = 70
    min_score = max(30, min(min_score, 95))

    # Filtros avançados e defaults seguros
    filters = payload.get("filters") or {}
    batch_size = max(1, min(int(payload.get("batch_size", 10)), 50))
    concurrency = max(1, min(int(payload.get("concurrency", 2)), 3))

    name = str(payload.get("name") or "").strip()
    if not name:
        niche_summary = " & ".join(niches[:2]) if niches else "Multi-nicho"
        if len(niches) > 2:
            niche_summary += f" (+{len(niches) - 2})"
        loc_summary = "Brasil Inteligente" if location_mode == "auto" else f"{len(locations)} praças"
        name = f"Campanha Inteligente · {niche_summary} · {loc_summary}"

    campaign_id = uuid.uuid4().hex
    queries_planned = max(3, len(niches) * 3)

    connection = _connect(db_name)
    try:
        connection.execute(
            """INSERT INTO geographic_campaigns
            (campaign_id, name, mode, niches_json, selection_json, filters_json, status,
             batch_size, concurrency, total_municipalities, target_qualified_leads,
             min_qualification_score, detailed_status, location_mode, niche_mode,
             is_exploratory, niches_count)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, 'preparando', ?, ?, ?, ?)""",
            (
                campaign_id,
                name,
                "smart",
                json.dumps(niches, ensure_ascii=False),
                json.dumps({"location_mode": location_mode, "count": len(locations)}, ensure_ascii=False),
                json.dumps(filters, ensure_ascii=False),
                batch_size,
                concurrency,
                len(locations),
                target_leads,
                min_score,
                location_mode,
                niche_mode,
                1 if is_exploratory else 0,
                len(niches),
            ),
        )

        connection.executemany(
            """INSERT INTO geographic_campaign_locations
            (campaign_id, municipality_id, municipality_name, uf, queries_planned)
            VALUES (?, ?, ?, ?, ?)""",
            [(campaign_id, loc["id"], loc["name"], loc["uf"], queries_planned) for loc in locations],
        )
        connection.commit()
    finally:
        connection.close()

    return smart_campaign_detail(db_name, campaign_id)


def update_smart_campaign_status(db_name, campaign_id, status=None, detailed_status=None, error=None):
    """Atualiza o status principal e/ou detalhado da campanha."""
    connection = _connect(db_name)
    try:
        updates = ["updated_at = CURRENT_TIMESTAMP"]
        params = []
        if status:
            updates.append("status = ?")
            params.append(status)
            if status == "running":
                updates.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
            elif status in {"completed", "cancelled", "failed"}:
                updates.append("finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP)")
        if detailed_status:
            updates.append("detailed_status = ?")
            params.append(detailed_status)
        if error is not None:
            updates.append("error = ?")
            params.append(str(error)[:500])

        params.append(campaign_id)
        connection.execute(f"UPDATE geographic_campaigns SET {', '.join(updates)} WHERE campaign_id = ?", params)
        if status == "cancelled":
            connection.execute(
                """UPDATE geographic_campaign_locations SET status = 'cancelled',
                   finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE campaign_id = ? AND status IN ('pending', 'running')""",
                (campaign_id,),
            )
        connection.commit()
    finally:
        connection.close()


def smart_campaign_detail(db_name, campaign_id):
    """
    Retorna o estado completo da Campanha Inteligente com métricas auditáveis.
    """
    connection = _connect(db_name)
    try:
        row = connection.execute("SELECT * FROM geographic_campaigns WHERE campaign_id = ?", (campaign_id,)).fetchone()
        if not row:
            raise ValueError("Campanha inteligente não encontrada.")

        campaign = dict(row)
        for field in ("niches_json", "selection_json", "filters_json"):
            campaign[field.removesuffix("_json")] = json.loads(campaign.pop(field) or "{}")

        # Contagens de status por localização
        loc_rows = connection.execute(
            """SELECT status, COUNT(*) as total FROM geographic_campaign_locations
               WHERE campaign_id = ? GROUP BY status""",
            (campaign_id,),
        ).fetchall()
        loc_status = {item["status"]: item["total"] for item in loc_rows}
        campaign["location_statuses"] = loc_status

        # Agregações de progresso das buscas
        totals = connection.execute(
            """SELECT COALESCE(SUM(queries_planned), 0),
                      COALESCE(SUM(queries_completed), 0),
                      COALESCE(SUM(businesses_found), 0),
                      COALESCE(SUM(qualified_leads), 0)
               FROM geographic_campaign_locations WHERE campaign_id = ?""",
            (campaign_id,),
        ).fetchone()

        planned, completed, found, qualified = map(int, totals)
        campaign["queries_planned"] = planned
        campaign["queries_completed"] = completed
        campaign["estimated_queries_remaining"] = max(0, planned - completed)

        target_leads = int(campaign.get("target_qualified_leads") or 100)
        qualified_leads = int(campaign.get("qualified_leads") or qualified or 0)
        businesses_found = int(campaign.get("businesses_found") or found or 0)

        # Contagem de municípios pesquisados
        completed_municipalities = int(campaign.get("completed_municipalities") or loc_status.get("completed", 0))
        total_municipalities = int(campaign.get("total_municipalities") or 0)

        # Leads qualificados vs Meta
        campaign["qualified_leads"] = qualified_leads
        campaign["target_qualified_leads"] = target_leads
        progress_pct = round((qualified_leads * 100.0) / target_leads, 1) if target_leads > 0 else 0
        campaign["progress_percent"] = min(100.0, progress_pct)
        campaign["progress_text"] = f"{qualified_leads} de {target_leads} leads qualificados"

        # Métricas do Painel exigidas
        campaign["companies_found"] = businesses_found
        campaign["companies_analyzed"] = int(campaign.get("companies_analyzed") or max(businesses_found, qualified_leads))
        campaign["companies_discarded"] = max(0, campaign["companies_analyzed"] - qualified_leads)
        campaign["niches_count"] = len(campaign.get("niches") or [])
        campaign["municipalities_count"] = total_municipalities
        campaign["completed_municipalities"] = completed_municipalities
        campaign["queries_executed"] = completed

        # Status legível
        detailed = campaign.get("detailed_status") or "preparando"
        if campaign["status"] == "paused":
            detailed = "pausada"
        elif campaign["status"] == "cancelled":
            detailed = "cancelada"
        elif campaign["status"] == "completed":
            detailed = "concluida"

        campaign["detailed_status"] = detailed
        campaign["detailed_status_label"] = STATUS_MAP.get(detailed, detailed.title())

        # Amostra de localidades para o painel
        sample_locs = connection.execute(
            """SELECT municipality_id, municipality_name, uf, status,
                      queries_planned, queries_completed, businesses_found, qualified_leads
               FROM geographic_campaign_locations
               WHERE campaign_id = ? ORDER BY id LIMIT 30""",
            (campaign_id,),
        ).fetchall()
        campaign["locations_preview"] = [dict(loc) for loc in sample_locs]

        return campaign
    finally:
        connection.close()


def list_smart_campaigns(db_name, limit=10):
    """Lista as campanhas inteligentes mais recentes."""
    connection = _connect(db_name)
    try:
        rows = connection.execute(
            """SELECT campaign_id FROM geographic_campaigns
               ORDER BY created_at DESC LIMIT ?""",
            (max(1, min(limit, 50)),),
        ).fetchall()
    finally:
        connection.close()
    return [smart_campaign_detail(db_name, row["campaign_id"]) for row in rows]


def get_latest_active_smart_campaign(db_name):
    """Retorna a campanha inteligente ativa mais recente, ou a última criada se não houver ativa."""
    connection = _connect(db_name)
    try:
        # Busca ativa primeiro
        row = connection.execute(
            """SELECT campaign_id FROM geographic_campaigns
               WHERE status IN ('running', 'pending', 'paused')
               ORDER BY updated_at DESC LIMIT 1"""
        ).fetchone()

        if not row:
            # Fallback para a mais recente geral
            row = connection.execute(
                """SELECT campaign_id FROM geographic_campaigns
                   ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()

        if not row:
            return None
        return smart_campaign_detail(db_name, row["campaign_id"])
    finally:
        connection.close()


def check_and_finalize_smart_goal(db_name, campaign_id):
    """
    Verifica se a campanha atingiu a meta de leads qualificados.
    Se atingiu, finaliza com sucesso imediatamente e cancela o restante da fila.
    """
    connection = _connect(db_name)
    try:
        row = connection.execute(
            """SELECT status, target_qualified_leads, qualified_leads
               FROM geographic_campaigns WHERE campaign_id = ?""",
            (campaign_id,),
        ).fetchone()
        if not row:
            return False

        status, target_leads, qualified_leads = row[0], int(row[1] or 100), int(row[2] or 0)
        if status in {"completed", "cancelled"}:
            return True

        if qualified_leads >= target_leads:
            # Meta alcançada com sucesso!
            connection.execute(
                """UPDATE geographic_campaigns
                   SET status = 'completed', detailed_status = 'concluida',
                       finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE campaign_id = ?""",
                (campaign_id,),
            )
            # Cancela os restantes pendentes sem erro
            connection.execute(
                """UPDATE geographic_campaign_locations
                   SET status = 'skipped', finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE campaign_id = ? AND status IN ('pending', 'running')""",
                (campaign_id,),
            )
            connection.commit()
            return True
        return False
    finally:
        connection.close()
