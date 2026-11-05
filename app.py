import os
import json
import time
import random
import re
import urllib.parse
import urllib.error
import sqlite3
import multiprocessing
import hmac
import secrets
import uuid
import ipaddress
import socket
import zipfile
from datetime import datetime, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import psutil
import pandas as pd
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for, send_file
from markupsafe import escape
from ai_provider import MODEL_CANDIDATES, first_available_response, generate_text
from commercial_intelligence import PITCH_PIPELINE_VERSION, analyze_lead, build_generation_prompt, clean_text, evaluate_pitches, generate_fallback_pitches, recommend_contact_strategy
from preview_studio import build_preview_config, capture_preview_png, render_preview_html
from lead_scoring import DEFAULT_WEIGHTS, SCORE_VERSION, score_lead
from conversion_intelligence import VALID_OUTCOMES, calculate_conversion_metrics, performance_adjustment
from contact_quality import assess_phone, normalize_email, website_domain
from discovery_engine import DiscoveryEngine, init_discovery_schema
from geographic_campaigns import (campaign_detail, claim_batch, complete_location, create_campaign,
                                  finalize_campaign_if_done, init_geographic_schema, list_campaigns,
                                  list_location_sets, save_location_set, set_campaign_status)
from geographic_intelligence import (GEOGRAPHY_VERSION, load_catalog, municipality_label,
                                     rank_smart_locations, search_municipalities, select_municipalities)
from lead_validation import validate_candidate
from location_intelligence import expand_locations
from niche_intelligence import NICHE_ENGINE_VERSION, build_candidate_pool, rank_niche_opportunities
from niche_research import discover_public_niches, research_market_samples
from target_intelligence import MARKETS, TARGET_ENGINE_VERSION, build_research_plan, normalize, search_terms_for_niche
from whatsapp_cloud import cloud_configured, send_approved_template

# NOTA: sync_playwright é importado DENTRO de extrator_worker para evitar
# travamento quando o processo filho (spawn) reimporta este módulo.
import traceback
from bs4 import BeautifulSoup
from multiprocessing import Process
from dotenv import load_dotenv
from dotenv import set_key
from werkzeug.middleware.proxy_fix import ProxyFix

# Carrega ou cria .env para variáveis de ambiente seguras
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

app = Flask(__name__)
flask_secret_key = os.environ.get("FLASK_SECRET_KEY", "").strip()
if not flask_secret_key:
    raise RuntimeError("FLASK_SECRET_KEY não configurada. Defina uma chave estável no arquivo .env.")
app.secret_key = flask_secret_key
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=60)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get("SESSION_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024
if os.environ.get("TRUST_PROXY_HEADERS", "false").strip().lower() in {"1", "true", "yes", "on"}:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

DB_NAME = "gestao_leads.db"
CONFIG_FILE = "config.json"
PREVIEW_DIR = os.path.join(os.path.dirname(__file__), "generated_previews")
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "backups")
DEFAULT_AGENCY_NAME = "PH Digital"
PIPELINE_STATUS_MAP = {
    "": "Novo", "Novo": "Novo", "Analisado": "Novo", "Mensagem preparada": "Novo",
    "Contato Feito": "Contatado", "Contatado": "Contatado",
    "Respondeu": "Conversando", "Interessado": "Conversando", "Proposta enviada": "Conversando",
    "Negociação": "Conversando", "Em Negociação": "Conversando", "Conversando": "Conversando",
    "Fechado": "Fechado", "Perdido": "Não fechado", "Não fechado": "Não fechado",
    "Descartado": "Descartado",
}
LOGIN_ATTEMPTS = {}
LOGIN_ATTEMPT_LOCK = threading.Lock()
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 8


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = csrf_token


def persist_secret(name, value):
    cleaned = str(value or "").strip()
    if not cleaned:
        return False
    set_key(env_path, name, cleaned, quote_mode="always")
    os.environ[name] = cleaned
    return True


def login_rate_state(client_key, now=None):
    now = now or time.time()
    with LOGIN_ATTEMPT_LOCK:
        attempts = [stamp for stamp in LOGIN_ATTEMPTS.get(client_key, []) if now - stamp < LOGIN_WINDOW_SECONDS]
        LOGIN_ATTEMPTS[client_key] = attempts
        return attempts


def record_login_failure(client_key, now=None):
    now = now or time.time()
    with LOGIN_ATTEMPT_LOCK:
        attempts = [stamp for stamp in LOGIN_ATTEMPTS.get(client_key, []) if now - stamp < LOGIN_WINDOW_SECONDS]
        attempts.append(now)
        LOGIN_ATTEMPTS[client_key] = attempts
        return len(attempts)


def clear_login_failures(client_key):
    with LOGIN_ATTEMPT_LOCK:
        LOGIN_ATTEMPTS.pop(client_key, None)


def seller_profile(config):
    return {
        "name": clean_text(config.get("vendedor_nome", ""), 80),
        "agency": clean_text(config.get("agencia_nome", DEFAULT_AGENCY_NAME), 100),
        "positioning": clean_text(config.get("posicionamento_comercial", ""), 240),
        "proof": clean_text(config.get("prova_comercial", ""), 240),
        "portfolio_url": clean_text(config.get("portfolio_url", ""), 240),
        "signature": clean_text(config.get("assinatura_comercial", ""), 160),
    }

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"vendedor_nome": "", "agencia_nome": DEFAULT_AGENCY_NAME, "velocidade": "normal", "headless": True}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            config = json.load(f)
            legacy_api_key = str(config.pop("gemini_api_key", "") or "").strip()
            if legacy_api_key and not os.environ.get("GEMINI_API_KEY"):
                persist_secret("GEMINI_API_KEY", legacy_api_key)
                save_config(config)
            if not str(config.get("agencia_nome", "")).strip():
                config["agencia_nome"] = DEFAULT_AGENCY_NAME
            return config
        except Exception:
            return {"vendedor_nome": "", "agencia_nome": DEFAULT_AGENCY_NAME, "velocidade": "normal", "headless": True}

def save_config(data):
    data = dict(data)
    data.pop("gemini_api_key", None)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def config_publica(config):
    config_segura = dict(config)
    config_segura["gemini_configurada"] = bool(os.environ.get("GEMINI_API_KEY"))
    config_segura["whatsapp_configurado"] = cloud_configured()
    config_segura["google_places_configurado"] = bool(os.environ.get("GOOGLE_PLACES_API_KEY", "").strip())
    config_segura.pop("gemini_api_key", None)
    return config_segura

STATUS_FILE = "search_status.json"
SEARCH_LOCK = threading.Lock()
GEO_CAMPAIGN_LOCK = threading.Lock()
ACTIVE_GEO_CAMPAIGNS = set()
TARGET_RESEARCH_STATUS_FILE = "target_research_status.json"
TARGET_RESEARCH_LOCK = threading.Lock()
SITE_AUDIT_STATUS_FILE = "site_audit_status.json"
SITE_AUDIT_LOCK = threading.Lock()
REGEN_STATUS_FILE = "regeneration_status.json"
BACKUP_LOCK = threading.Lock()

COMMON_MOJIBAKE_REPLACEMENTS = {
    "Cl�nica": "Clínica",
    "cl�nica": "clínica",
    "S�o": "São",
    "s�o": "são",
    "Tatuap�": "Tatuapé",
    "Fl�or": "Flúor",
    "Odontol�gica": "Odontológica",
    "odontol�gica": "odontológica",
    "Est�tica": "Estética",
    "est�tica": "estética",
    "M�dica": "Médica",
    "m�dica": "médica",
    "Jo�o": "João",
    "Jos�": "José",
}


def repair_known_mojibake(value):
    repaired = str(value or "")
    for broken, correct in COMMON_MOJIBAKE_REPLACEMENTS.items():
        repaired = repaired.replace(broken, correct)
    return repaired


def lead_data_quality(lead):
    issues = []
    name = str(lead.get("nome") or lead.get("Nome") or "").strip()
    location = str(lead.get("bairro") or lead.get("Bairro") or "").strip()
    rating = str(lead.get("nota") or lead.get("Nota Maps") or "").strip()
    reviews = str(lead.get("avaliacoes") or lead.get("Qtd Avaliacoes") or "").strip()
    site_status = str(lead.get("site_opportunity_status") or lead.get("Oportunidade do Site") or "").strip()
    campaign = str(lead.get("search_run_id") or lead.get("Search Run ID") or "").strip()
    email = str(lead.get("email") or lead.get("E-mail Encontrado") or "").strip()
    phone = str(lead.get("telefone") or lead.get("Telefone") or "").strip()
    validation_status = str(lead.get("validation_status") or lead.get("Status Validação") or "NÃO VERIFICADO").upper()
    if "�" in name or "�" in location:
        issues.append("texto corrompido")
    if not rating or rating in {"0", "0.0", "0,0"}:
        issues.append("nota não confirmada")
    if not reviews or reviews == "0":
        issues.append("avaliações não confirmadas")
    if not site_status:
        issues.append("site não auditado")
    if not campaign:
        issues.append("origem da campanha desconhecida")
    if not email:
        issues.append("e-mail não localizado")
    if not phone:
        issues.append("telefone não localizado")
    if validation_status == "NÃO VERIFICADO":
        issues.append("empresa ainda não verificada")
    confidence = max(10, 100 - len(issues) * 14)
    if "texto corrompido" in issues or "site não auditado" in issues:
        status = "Revisar"
    elif len(issues) >= 3:
        status = "Incompleto"
    else:
        status = "Confiável"
    return {"status": status, "issues": issues, "confidence": confidence}


def save_regeneration_status(data):
    payload = dict(data)
    payload["pid"] = os.getpid()
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    temporary_path = f"{REGEN_STATUS_FILE}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as status_file:
        json.dump(payload, status_file, ensure_ascii=False)
    os.replace(temporary_path, REGEN_STATUS_FILE)


def load_regeneration_status():
    default = {"rodando": False, "total": 0, "processados": 0, "atualizados": 0, "falhas": 0, "mensagem": "", "concluido": False}
    if not os.path.exists(REGEN_STATUS_FILE):
        return default
    try:
        with open(REGEN_STATUS_FILE, "r", encoding="utf-8") as status_file:
            data = {**default, **json.load(status_file)}
        if data.get("rodando") and data.get("pid") and not psutil.pid_exists(int(data["pid"])):
            data.update({"rodando": False, "concluido": False, "mensagem": "A regeneração anterior foi interrompida pelo reinício do servidor."})
            save_regeneration_status(data)
        return data
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return default

def atualizar_status(dados):
    try:
        dados["pid"] = os.getpid()
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar status: {e}")

def ler_status():
    if not os.path.exists(STATUS_FILE):
        return {"rodando": False, "mensagem": "Nenhuma busca realizada ainda.", "leads_salvos": 0}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("rodando") and data.get("pid"):
                if not psutil.pid_exists(data["pid"]):
                    data["rodando"] = False
                    data["mensagem"] = "O processo foi interrompido inesperadamente (possivel limite de memoria do servidor)."
            return data
    except Exception:
        return {"rodando": False, "mensagem": "Status indisponivel.", "leads_salvos": 0}


def atualizar_status_investigacao(dados):
    dados["pid"] = os.getpid()
    with open(TARGET_RESEARCH_STATUS_FILE, "w", encoding="utf-8") as file:
        json.dump(dados, file, ensure_ascii=False)


def ler_status_investigacao():
    if not os.path.exists(TARGET_RESEARCH_STATUS_FILE):
        return {"rodando": False, "mensagem": "Nenhuma investigação iniciada."}
    try:
        with open(TARGET_RESEARCH_STATUS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        if data.get("rodando") and data.get("pid") and not psutil.pid_exists(data["pid"]):
            data.update({"rodando": False, "erro": "A investigação foi interrompida pelo servidor."})
        return data
    except Exception:
        return {"rodando": False, "mensagem": "Status da investigação indisponível."}


def atualizar_status_auditoria_sites(dados):
    dados["pid"] = os.getpid()
    with open(SITE_AUDIT_STATUS_FILE, "w", encoding="utf-8") as file:
        json.dump(dados, file, ensure_ascii=False)


def ler_status_auditoria_sites():
    if not os.path.exists(SITE_AUDIT_STATUS_FILE):
        return {"rodando": False, "mensagem": "Nenhuma auditoria de sites iniciada."}
    try:
        with open(SITE_AUDIT_STATUS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        if data.get("rodando") and data.get("pid") and not psutil.pid_exists(data["pid"]):
            data.update({"rodando": False, "mensagem": "A auditoria anterior foi interrompida."})
        return data
    except Exception:
        return {"rodando": False, "mensagem": "Status da auditoria indisponível."}


def _create_daily_backup(retention=14):
    if not os.path.isfile(DB_NAME) or os.path.getsize(DB_NAME) == 0:
        return ""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    date_label = datetime.now().strftime("%Y-%m-%d")
    archive_path = os.path.join(BACKUP_DIR, f"automatic-{date_label}.zip")
    if os.path.exists(archive_path):
        return archive_path
    snapshot_path = os.path.join(BACKUP_DIR, f"automatic-{date_label}.db")
    source = sqlite3.connect(DB_NAME)
    snapshot = sqlite3.connect(snapshot_path)
    try:
        source.backup(snapshot)
    finally:
        snapshot.close()
        source.close()
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot_path, "gestao_leads.db")
    finally:
        if os.path.exists(snapshot_path):
            os.remove(snapshot_path)
    automatic_backups = sorted(
        (
            os.path.join(BACKUP_DIR, name)
            for name in os.listdir(BACKUP_DIR)
            if name.startswith("automatic-") and name.endswith(".zip")
        ),
        key=os.path.getmtime,
        reverse=True,
    )
    for old_backup in automatic_backups[max(1, retention):]:
        os.remove(old_backup)
    return archive_path


def create_daily_backup(retention=14):
    with BACKUP_LOCK:
        return _create_daily_backup(retention)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    c = conn.cursor()
    configured_identity = load_config()
    c.execute("""CREATE TABLE IF NOT EXISTS leads
                 (place_id TEXT PRIMARY KEY, nome TEXT, nicho TEXT, bairro TEXT, nota TEXT,
                  avaliacoes TEXT, telefone TEXT, whatsapp_link TEXT, email TEXT,
                  instagram TEXT, facebook TEXT, linkedin TEXT, link_inicial TEXT,
                  google_maps TEXT, prompt_design TEXT, status TEXT, data_adicao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  copy_texto TEXT, analise_ia TEXT, estrategia_ia TEXT)""")
    # Fallback to alter table if columns are missing
    for col, tipo in [("copy_texto", "TEXT"), ("analise_ia", "TEXT"), ("estrategia_ia", "TEXT"), ("potencial", "INTEGER"), ("motivo_potencial", "TEXT"), ("faixa_potencial", "TEXT"), ("score_breakdown", "TEXT"), ("score_version", "TEXT"), ("copies_pitch", "TEXT"), ("inteligencia_comercial", "TEXT"), ("qualidade_pitch", "TEXT"), ("do_not_contact", "INTEGER DEFAULT 0"), ("do_not_contact_reason", "TEXT"), ("do_not_contact_at", "TIMESTAMP"), ("last_response", "TEXT"), ("next_action", "TEXT"), ("next_action_at", "TIMESTAMP"), ("last_contact_at", "TIMESTAMP"), ("last_contact_channel", "TEXT"), ("last_pitch_mode", "TEXT"), ("contact_count", "INTEGER DEFAULT 0"), ("search_run_id", "TEXT"), ("site_title", "TEXT"), ("site_description", "TEXT"), ("site_context", "TEXT"), ("site_opportunity_status", "TEXT"), ("site_opportunity_reasons", "TEXT"), ("data_quality_status", "TEXT"), ("data_quality_issues", "TEXT"), ("data_confidence", "INTEGER DEFAULT 0"), ("last_audited_at", "TIMESTAMP"), ("lead_source", "TEXT DEFAULT 'legacy_maps'"), ("source_record_id", "TEXT"), ("business_address", "TEXT"), ("validation_status", "TEXT DEFAULT 'NÃO VERIFICADO'"), ("validation_reason", "TEXT"), ("site_confidence", "TEXT DEFAULT 'NÃO VERIFICADO'"), ("evidence_json", "TEXT DEFAULT '[]'"), ("commercial_outcome", "TEXT"), ("last_verified_at", "TIMESTAMP")]:
        try: c.execute(f"ALTER TABLE leads ADD COLUMN {col} {tipo}")
        except: pass
    c.execute("""CREATE TABLE IF NOT EXISTS preview_versions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, place_id TEXT NOT NULL, version INTEGER NOT NULL,
                  config_json TEXT NOT NULL, html_content TEXT NOT NULL, screenshot_path TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(place_id, version))""")
    c.execute("""CREATE TABLE IF NOT EXISTS lead_interactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, place_id TEXT NOT NULL,
                  interaction_type TEXT NOT NULL, channel TEXT, content TEXT NOT NULL,
                  sentiment TEXT, next_action TEXT, next_action_at TIMESTAMP,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS target_research_observations
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, region TEXT NOT NULL,
                  niche TEXT NOT NULL, city TEXT NOT NULL, results_count INTEGER DEFAULT 0,
                  sample_size INTEGER DEFAULT 0, no_site_count INTEGER DEFAULT 0,
                  contactable_count INTEGER DEFAULT 0, mature_count INTEGER DEFAULT 0,
                  error TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    for col, tipo in [
        ("verified_count", "INTEGER DEFAULT 0"), ("own_site_count", "INTEGER DEFAULT 0"),
        ("confirmed_no_site_count", "INTEGER DEFAULT 0"), ("probable_no_site_count", "INTEGER DEFAULT 0"),
        ("weak_site_count", "INTEGER DEFAULT 0"),
        ("site_unknown_count", "INTEGER DEFAULT 0"), ("active_count", "INTEGER DEFAULT 0"),
        ("qualified_count", "INTEGER DEFAULT 0"), ("duplicate_count", "INTEGER DEFAULT 0"),
        ("discarded_count", "INTEGER DEFAULT 0"), ("sources_json", "TEXT DEFAULT '[]'"),
        ("examples_json", "TEXT DEFAULT '[]'"),
    ]:
        try:
            c.execute(f"ALTER TABLE target_research_observations ADD COLUMN {col} {tipo}")
        except sqlite3.OperationalError:
            pass
    c.execute("""CREATE TABLE IF NOT EXISTS target_research_runs
                 (run_id TEXT PRIMARY KEY, region TEXT NOT NULL, plan_json TEXT NOT NULL,
                  result_json TEXT, status TEXT NOT NULL, error TEXT, context_key TEXT DEFAULT '',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  finished_at TIMESTAMP)""")
    try:
        c.execute("ALTER TABLE target_research_runs ADD COLUMN context_key TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    c.execute("""CREATE TABLE IF NOT EXISTS dynamic_niche_catalog
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, region TEXT NOT NULL, niche_key TEXT NOT NULL,
                  niche_name TEXT NOT NULL, source TEXT NOT NULL, observed_businesses INTEGER DEFAULT 0,
                  first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(region, niche_key, source))""")
    c.execute("""CREATE TABLE IF NOT EXISTS niche_recommendation_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, region TEXT NOT NULL,
                  niche TEXT NOT NULL, niche_key TEXT NOT NULL, score REAL NOT NULL,
                  confidence TEXT NOT NULL, evidence_hash TEXT NOT NULL, metrics_json TEXT NOT NULL,
                  sources_json TEXT DEFAULT '[]', recommended_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS lead_discovery_history
                 (place_id TEXT PRIMARY KEY, first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, times_seen INTEGER DEFAULT 1,
                  last_niche TEXT, last_location TEXT, last_run_id TEXT, outcome TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS search_runs
                 (run_id TEXT PRIMARY KEY, name TEXT NOT NULL, market TEXT NOT NULL,
                  niches_json TEXT NOT NULL, locations_json TEXT NOT NULL, filters_json TEXT NOT NULL,
                  status TEXT NOT NULL, stats_json TEXT, started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  finished_at TIMESTAMP)""")
    for col, tipo in [("geo_campaign_id", "TEXT"), ("municipality_id", "INTEGER")]:
        try:
            c.execute(f"ALTER TABLE search_runs ADD COLUMN {col} {tipo}")
        except sqlite3.OperationalError:
            pass
    c.execute("""CREATE TABLE IF NOT EXISTS lead_evidence
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, place_id TEXT NOT NULL, source TEXT NOT NULL,
                  evidence_type TEXT NOT NULL, value TEXT NOT NULL, confidence TEXT NOT NULL,
                  source_url TEXT, observed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    init_discovery_schema(conn)
    init_geographic_schema(conn)
    c.execute(
        """UPDATE search_runs SET status = 'interrupted', finished_at = CURRENT_TIMESTAMP
           WHERE status = 'running'"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_leads_status_data ON leads(status, data_adicao DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_leads_next_action ON leads(next_action_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_preview_place_version ON preview_versions(place_id, version DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_interactions_place_created ON lead_interactions(place_id, created_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_discovery_last_seen ON lead_discovery_history(last_seen_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_target_research_context ON target_research_runs(region, context_key, finished_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_niche_history_region ON niche_recommendation_history(region, recommended_at DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_leads_source_validation ON leads(lead_source, validation_status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lead_evidence_place ON lead_evidence(place_id, observed_at DESC)")
    c.execute(
        """INSERT OR IGNORE INTO lead_discovery_history
           (place_id, first_seen_at, last_seen_at, last_niche, last_location, last_run_id, outcome)
           SELECT place_id, data_adicao, data_adicao, nicho, bairro, search_run_id, 'saved' FROM leads"""
    )
    c.execute(
        """UPDATE leads SET status = CASE
             WHEN status IN ('Analisado', 'Mensagem preparada') OR status IS NULL OR trim(status) = '' THEN 'Novo'
             WHEN status = 'Contato Feito' THEN 'Contatado'
             WHEN status IN ('Respondeu', 'Interessado', 'Proposta enviada', 'Negociação', 'Em Negociação') THEN 'Conversando'
             WHEN status = 'Perdido' THEN 'Não fechado'
             ELSE status END"""
    )
    for row in c.execute("SELECT place_id, nome, nicho, bairro FROM leads").fetchall():
        repaired_values = tuple(repair_known_mojibake(value) for value in row[1:])
        if repaired_values != tuple(value or "" for value in row[1:]):
            c.execute(
                "UPDATE leads SET nome = ?, nicho = ?, bairro = ? WHERE place_id = ?",
                (*repaired_values, row[0]),
            )
    c.execute(
        """UPDATE leads
           SET site_opportunity_status = CASE
               WHEN trim(coalesce(link_inicial, '')) = '' THEN 'Construção de site'
               WHEN lower(link_inicial) LIKE '%instagram.com%'
                 OR lower(link_inicial) LIKE '%facebook.com%'
                 OR lower(link_inicial) LIKE '%wa.me%'
                 OR lower(link_inicial) LIKE '%whatsapp.com%' THEN 'Construção de site'
               ELSE 'Revisão manual'
           END
           WHERE site_opportunity_status IS NULL OR trim(site_opportunity_status) = ''"""
    )
    quality_rows = c.execute("SELECT * FROM leads").fetchall()
    quality_columns = [description[0] for description in c.description]
    for quality_row in quality_rows:
        quality = lead_data_quality(dict(zip(quality_columns, quality_row)))
        c.execute(
            "UPDATE leads SET data_quality_status = ?, data_quality_issues = ?, data_confidence = ? WHERE place_id = ?",
            (quality["status"], json.dumps(quality["issues"], ensure_ascii=False), quality["confidence"], quality_row[0]),
        )
    legacy_rows = c.execute(
        """SELECT place_id, nome, nicho, bairro, nota, avaliacoes, telefone, email,
                  instagram, facebook, linkedin, link_inicial, google_maps, copies_pitch, copy_texto, qualidade_pitch
           FROM leads"""
    ).fetchall()
    for row in legacy_rows:
        stored_copies = row[13] or ""
        stored_primary = row[14] or ""
        try:
            stored_pipeline_version = json.loads(row[15] or "{}").get("pipeline_version")
        except (TypeError, json.JSONDecodeError):
            stored_pipeline_version = None
        legacy_phrases = (
            "responsável pelo comercial ou marketing",
            "perfil público consultado",
            "oportunidade mais clara",
            "estrutura que recomendaria",
            "pelas informações públicas disponíveis",
            "se fizer sentido",
            "três ideias práticas",
        )
        is_legacy = (
            not stored_copies
            or '"personalizada"' not in stored_copies
            or '"recepcao"' not in stored_copies
            or '"email"' not in stored_copies
            or stored_pipeline_version != PITCH_PIPELINE_VERSION
            or any(phrase in stored_primary.casefold() for phrase in legacy_phrases)
        )
        if not is_legacy:
            continue
        place_id = row[0]
        preview_available = bool(c.execute("SELECT 1 FROM preview_versions WHERE place_id = ? LIMIT 1", (place_id,)).fetchone())
        raw = {
            "Nome": row[1] or "", "Nicho": row[2] or "", "Categoria Maps": row[2] or "",
            "Bairro": row[3] or "", "Nota Maps": row[4] or "", "Qtd Avaliacoes": row[5] or "",
            "Telefone": row[6] or "", "E-mail Encontrado": row[7] or "", "Instagram": row[8] or "",
            "Facebook": row[9] or "", "LinkedIn": row[10] or "", "Link Inicial": row[11] or "",
            "Google Maps": row[12] or "",
        }
        intelligence = analyze_lead(raw, preview_available=preview_available)
        intelligence["seller"] = seller_profile(configured_identity)
        pitches = generate_fallback_pitches(intelligence)
        quality = evaluate_pitches(pitches, intelligence, require_preview=preview_available)
        diagnosis = f"Confiança da análise: {intelligence['confidence']}%. Oportunidade: {intelligence['opportunity']}."
        c.execute(
            """UPDATE leads SET copy_texto = ?, copies_pitch = ?, inteligencia_comercial = ?,
                      qualidade_pitch = ?, analise_ia = ?, estrategia_ia = ?
               WHERE place_id = ?""",
            (pitches["consultiva"], json.dumps(pitches, ensure_ascii=False),
             json.dumps(intelligence, ensure_ascii=False), json.dumps(quality, ensure_ascii=False),
             diagnosis, intelligence["main_argument"], place_id),
        )
    conn.commit()
    conn.close()

create_daily_backup()
init_db()

def build_crm_where(status_scope=None, filters=None):
    filters = filters or {}
    clauses = []
    params = []
    if status_scope == "inbox":
        clauses.append("leads.status = 'Novo'")
    elif status_scope == "contacted":
        clauses.append("leads.status IN ('Contatado', 'Conversando', 'Fechado', 'Não fechado')")
    elif status_scope == "active":
        clauses.append("leads.status != 'Descartado'")
    elif status_scope == "discarded":
        clauses.append("leads.status = 'Descartado'")
    if filters.get("nome"):
        clauses.append("lower(leads.nome) LIKE ?")
        params.append(f"%{filters['nome'].casefold()}%")
    if filters.get("status"):
        if filters["status"] == "Contatado":
            clauses.append("leads.status IN ('Contatado', 'Contato Feito')")
        else:
            clauses.append("leads.status = ?")
            params.append(filters["status"])
    for key, column in (
        ("nicho", "lower(trim(leads.nicho))"),
        ("potencial", "leads.faixa_potencial"),
        ("site", "leads.site_opportunity_status"),
        ("qualidade", "leads.data_quality_status"),
        ("validacao", "leads.validation_status"),
    ):
        if filters.get(key):
            clauses.append(f"{column} = ?")
            value = filters[key].casefold() if key == "nicho" else filters[key]
            params.append(value)
    if filters.get("origem"):
        clauses.append("lower(leads.lead_source) LIKE ?")
        params.append(f"%{filters['origem'].casefold()}%")
    if filters.get("min_score"):
        clauses.append("COALESCE(leads.potencial, 0) >= ?")
        params.append(int(filters["min_score"]))
    followup = filters.get("followup")
    if followup == "sem_acao":
        clauses.append("trim(coalesce(leads.next_action_at, '')) = ''")
    elif followup == "atrasado":
        clauses.append("date(leads.next_action_at) < date('now', 'localtime')")
    elif followup == "hoje":
        clauses.append("date(leads.next_action_at) = date('now', 'localtime')")
    elif followup == "proximo":
        clauses.append("date(leads.next_action_at) > date('now', 'localtime')")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def load_leads(status_scope=None, limit=None, offset=0, filters=None):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    where, params = build_crm_where(status_scope, filters)
    pagination = " LIMIT ? OFFSET ?" if limit else ""
    if limit:
        params.extend((int(limit), max(0, int(offset))))
    c.execute(f"""SELECT leads.*,
                 (SELECT id FROM preview_versions WHERE preview_versions.place_id = leads.place_id ORDER BY version DESC LIMIT 1) AS latest_preview_id
                 FROM leads{where}
                 ORDER BY COALESCE(potencial, 0) DESC, data_adicao DESC, nome COLLATE NOCASE ASC{pagination}""", params)
    rows = c.fetchall()
    conn.close()
    leads = [dict(ix) for ix in rows]
    configured_weights = load_config().get("lead_score_weights")
    for lead in leads:
        lead["nome"] = repair_known_mojibake(lead.get("nome"))
        lead["nicho"] = repair_known_mojibake(lead.get("nicho"))
        lead["bairro"] = repair_known_mojibake(lead.get("bairro"))
        site_assessment = assess_site_opportunity(
            lead.get("link_inicial"), lead.get("site_title"), lead.get("site_description"), lead.get("site_context")
        )
        lead["site_opportunity_status"] = lead.get("site_opportunity_status") or site_assessment["status"]
        try:
            lead["site_opportunity_reasons"] = json.loads(lead.get("site_opportunity_reasons") or "[]")
        except (TypeError, json.JSONDecodeError):
            lead["site_opportunity_reasons"] = site_assessment["reasons"]
        try:
            stored_scoring = json.loads(lead.get("score_breakdown") or "{}")
        except (TypeError, json.JSONDecodeError):
            stored_scoring = {}
        scoring = calcular_score_lead(
            lead, configured_weights=configured_weights,
            performance_adjustment=stored_scoring.get("performance_adjustment", 0),
        )
        lead["potencial"] = scoring["score"]
        lead["motivo_potencial"] = scoring["reason"]
        lead["faixa_potencial"] = scoring["range"]
        lead["score_breakdown"] = scoring
        lead["score_version"] = scoring["version"]
        data_quality = lead_data_quality(lead)
        lead["data_quality_status"] = data_quality["status"]
        lead["data_quality_issues"] = data_quality["issues"]
        lead["data_confidence"] = data_quality["confidence"]
    for lead in leads:
        try:
            lead["copies_pitch"] = json.loads(lead.get("copies_pitch") or "{}")
        except (TypeError, json.JSONDecodeError):
            lead["copies_pitch"] = {}
        for field_name in ("inteligencia_comercial", "qualidade_pitch"):
            try:
                lead[field_name] = json.loads(lead.get(field_name) or "{}")
            except (TypeError, json.JSONDecodeError):
                lead[field_name] = {}
        contact_strategy = lead["inteligencia_comercial"].get("contact_strategy")
        if not contact_strategy:
            contact_strategy = recommend_contact_strategy(lead_to_raw_data(lead), preview_available=bool(lead.get("latest_preview_id")))
        lead["contact_strategy"] = contact_strategy
        lead["recommended_pitch_mode"] = contact_strategy["recommended_mode"]
    return leads

def save_lead_db(lead, place_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("""INSERT INTO leads (place_id, nome, nicho, bairro, nota, avaliacoes, telefone, whatsapp_link, email, instagram, facebook, linkedin, link_inicial, google_maps, prompt_design, status, copy_texto, analise_ia, estrategia_ia, potencial, motivo_potencial, faixa_potencial, score_breakdown, score_version, search_run_id, site_title, site_description, site_context, site_opportunity_status, site_opportunity_reasons)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Novo', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (place_id, lead.get("Nome",""), lead.get("Nicho",""), lead.get("Bairro",""), lead.get("Nota Maps",""),
                   lead.get("Qtd Avaliacoes",""), lead.get("Telefone",""), lead.get("WhatsApp Link",""), lead.get("E-mail Encontrado",""),
                   lead.get("Instagram",""), lead.get("Facebook",""), lead.get("LinkedIn",""), lead.get("Link Inicial",""),
                   lead.get("Google Maps",""), lead.get("Prompt Prototipo",""), lead.get("Copy Texto", ""), lead.get("Analise IA", ""), lead.get("Estrategia IA", ""), lead.get("Potencial", 0), lead.get("Motivo Potencial", ""), lead.get("Faixa Potencial", "Oportunidade secundária"), json.dumps(lead.get("Score Breakdown", {}), ensure_ascii=False), lead.get("Score Version", SCORE_VERSION), lead.get("Search Run ID", ""), lead.get("Título do Site", ""), lead.get("Descrição do Site", ""), lead.get("Contexto do Site", ""), lead.get("Oportunidade do Site", ""), json.dumps(lead.get("Motivos da Oportunidade", []), ensure_ascii=False)))
        quality = lead_data_quality(lead)
        c.execute(
            """UPDATE leads SET data_quality_status = ?, data_quality_issues = ?, data_confidence = ?,
               lead_source = ?, source_record_id = ?, business_address = ?, validation_status = ?, validation_reason = ?,
               site_confidence = ?, evidence_json = ?, last_verified_at = CURRENT_TIMESTAMP
               WHERE place_id = ?""",
            (quality["status"], json.dumps(quality["issues"], ensure_ascii=False), quality["confidence"],
             lead.get("Origem", "legacy_maps"), lead.get("ID na Fonte", ""), lead.get("Endereço", lead.get("Bairro", "")),
             lead.get("Status Validação", "NÃO VERIFICADO"), lead.get("Motivo Validação", ""),
             lead.get("Confiança do Site", "NÃO VERIFICADO"),
             json.dumps(lead.get("Evidências", []), ensure_ascii=False), place_id),
        )
        for evidence in lead.get("Evidências", []):
            c.execute(
                """INSERT INTO lead_evidence
                   (place_id, source, evidence_type, value, confidence, source_url)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (place_id, evidence.get("source") or lead.get("Origem", "desconhecida"),
                 evidence.get("type", "geral"), evidence.get("value", ""),
                 evidence.get("confidence", "NÃO VERIFICADO"), evidence.get("source_url", "")),
            )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def update_lead_ai(place_id, copy_texto, analise_ia, estrategia_ia, whatsapp_link, copies_pitch=None, inteligencia=None, qualidade=None):
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            """UPDATE leads
               SET copy_texto = ?, analise_ia = ?, estrategia_ia = ?, whatsapp_link = ?, copies_pitch = ?,
                   inteligencia_comercial = ?, qualidade_pitch = ?
               WHERE place_id = ?""",
            (copy_texto, analise_ia, estrategia_ia, whatsapp_link, json.dumps(copies_pitch or {}, ensure_ascii=False),
             json.dumps(inteligencia or {}, ensure_ascii=False), json.dumps(qualidade or {}, ensure_ascii=False), place_id),
        )
        conn.commit()
    finally:
        conn.close()

def load_existing_place_ids():
    conn = sqlite3.connect(DB_NAME)
    try:
        return {
            row[0] for row in conn.execute(
                "SELECT place_id FROM lead_discovery_history WHERE outcome IN ('saved', 'duplicate_identity')"
            )
        }
    finally:
        conn.close()


def load_existing_lead_identities():
    conn = sqlite3.connect(DB_NAME)
    try:
        phones = set()
        names = set()
        emails = set()
        domains = set()
        for name, location, address, phone, email, website in conn.execute(
            "SELECT nome, bairro, business_address, telefone, email, link_inicial FROM leads"
        ):
            phone_key = re.sub(r"\D", "", phone or "")
            if len(phone_key) >= 10:
                phones.add(phone_key[-11:])
            name_key = normalize(name)
            location_key = normalize(address or location)
            if name_key:
                names.add((name_key, location_key))
            email_key = normalize_email(email)
            if email_key:
                emails.add(email_key)
            domain_key = website_domain(website)
            if domain_key and possui_site_proprio(website):
                domains.add(domain_key)
        return phones, names, emails, domains
    finally:
        conn.close()


def record_lead_discoveries(discoveries):
    rows = [item for item in discoveries if item[0]]
    if not rows:
        return
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.executemany(
            """INSERT INTO lead_discovery_history
               (place_id, last_niche, last_location, last_run_id, outcome)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(place_id) DO UPDATE SET
                 last_seen_at = CURRENT_TIMESTAMP,
                 times_seen = times_seen + 1,
                 last_niche = excluded.last_niche,
                 last_location = excluded.last_location,
                 last_run_id = excluded.last_run_id,
                 outcome = excluded.outcome""",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def record_lead_discovery(place_id, niche, location, run_id, outcome):
    record_lead_discoveries([(place_id, niche, location, run_id, outcome)])

def tratar_consentimento_cookies(page):
    try:
        seletores = [
            'button:has-text("Aceitar tudo")',
            'button:has-text("Accept all")',
            'button:has-text("I agree")',
            'form[action*="consent"] button',
        ]
        for seletor in seletores:
            botao = page.locator(seletor).first
            if botao.count() > 0 and botao.is_visible(timeout=2000):
                botao.click(timeout=3000)
                print("[WORKER] Tela de consentimento fechada.")
                time.sleep(1)
                return True
    except Exception as e:
        print(f"[WORKER] Sem tela de consentimento (ou falhou ao fechar): {e}")
    return False

def pausa(min_s=1.0, max_s=2.5, config=None):
    if config:
        if config.get("velocidade") == "rapido": min_s, max_s = min_s * 0.5, max_s * 0.5
        elif config.get("velocidade") == "lento": min_s, max_s = min_s * 1.5, max_s * 1.5
    time.sleep(random.uniform(min_s, max_s))

def extrair_apenas_numeros(telefone):
    if not telefone: return ""
    has_plus = telefone.startswith("+")
    numeros = re.sub(r"\D", "", telefone)
    
    if len(numeros) < 10:
        return ""
        
    if has_plus:
        return numeros
        
    if len(numeros) == 10 or len(numeros) == 11:
        return "55" + numeros
        
    return numeros

def eh_celular_valido(numeros, region=None):
    digits = re.sub(r"\D", "", str(numeros or ""))
    if region is None:
        region = "us" if len(digits) == 11 and digits.startswith("1") else "br"
    return assess_phone(numeros, region)["whatsapp_candidate"]

def formatar_whatsapp(numeros, copy_texto=""):
    if not numeros: return ""
    url = f"https://wa.me/{numeros}"
    if copy_texto: url += f"?text={urllib.parse.quote(copy_texto)}"
    return url

def normalizar_texto(texto, limite=900):
    return re.sub(r"\s+", " ", texto or "").strip()[:limite]


def normalizar_status_pipeline(status):
    return PIPELINE_STATUS_MAP.get(str(status or "").strip())

def extrair_numero_avaliacoes(valor):
    numeros = re.findall(r"\d+", str(valor or "").replace(".", "").replace(",", ""))
    return int("".join(numeros)) if numeros else 0

def calcular_score_lead(lead, tem_site=None, configured_weights=None, performance_adjustment=0):
    if tem_site is None:
        tem_site = possui_site_proprio(lead.get("Link Inicial") or lead.get("link_inicial"))
    return score_lead(lead, tem_site, configured_weights, performance_adjustment)


def calcular_potencial_lead(nota, avaliacoes, telefone, email, instagram, linkedin, tem_site, nicho="", bairro="", facebook="", configured_weights=None):
    scoring = calcular_score_lead({
        "Nota Maps": nota,
        "Qtd Avaliacoes": avaliacoes,
        "Telefone": telefone,
        "E-mail Encontrado": email,
        "Instagram": instagram,
        "Facebook": facebook,
        "LinkedIn": linkedin,
        "Nicho": nicho,
        "Bairro": bairro,
    }, tem_site=tem_site, configured_weights=configured_weights)
    return scoring["score"], scoring["reason"]

def classificar_potencial(potencial, minimo_prioridade=55):
    try:
        potencial = int(potencial or 0)
    except (TypeError, ValueError):
        potencial = 0
    if potencial >= minimo_prioridade:
        return "Prioridade"
    if potencial >= 35:
        return "Oportunidade secundária"
    return "Exploração"


def classificar_prazo_followup(value):
    if not value:
        return "sem_acao"
    try:
        due = datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return "sem_acao"
    today = datetime.now().date()
    if due.date() < today:
        return "atrasado"
    if due.date() == today:
        return "hoje"
    return "proximo"

def necessidade_digital_do_nicho(nicho):
    nicho = (nicho or "").casefold()
    if any(termo in nicho for termo in ["odont", "dentist", "clinic", "medic", "saud", "dermat", "estetic"]):
        return "não consegue entender tratamentos, transmitir confiança ou pedir uma avaliação de forma simples"
    if any(termo in nicho for termo in ["advoc", "jurid", "direito"]):
        return "não consegue identificar rapidamente as áreas atendidas nem encontrar um caminho claro para falar com o escritório"
    if any(termo in nicho for termo in ["imob", "corret", "imove"]):
        return "não consegue ver imóveis, diferenciais ou solicitar atendimento sem depender de várias mensagens"
    if any(termo in nicho for termo in ["move", "planejad", "marcen", "arquitet", "interiores", "decor"]):
        return "não consegue ver projetos, perceber o padrão do trabalho ou pedir orçamento com segurança"
    if any(termo in nicho for termo in ["restauran", "bar", "pizz", "hamburg", "caf", "padar", "gastronom"]):
        return "não consegue consultar cardápio, horários e reservas de forma rápida pelo celular"
    return "não encontra uma explicação clara dos serviços nem uma forma simples de iniciar o atendimento"

def normalizar_dados_pitch(dados_lead):
    nome = normalizar_texto(dados_lead.get("Nome", "").split(" - ")[0].split("|")[0], 90)
    categoria = normalizar_texto(dados_lead.get("Categoria Maps") or dados_lead.get("Nicho"), 120)
    site = extrair_destino_externo(dados_lead.get("Link Inicial", ""))
    tem_site = bool(site and not is_social_or_directory(site))
    instagram = extrair_destino_externo(dados_lead.get("Instagram", ""))
    evidencias = []
    if categoria:
        evidencias.append(f"atua em {categoria}")
    if dados_lead.get("Bairro"):
        evidencias.append(f"atende em {normalizar_texto(dados_lead.get('Bairro'), 90)}")
    if instagram:
        evidencias.append("tem Instagram identificado")
    if tem_site:
        evidencias.append("tem site próprio identificado")
    else:
        evidencias.append("não há site próprio identificado no perfil do Google")
    return {
        "nome": nome or "a empresa",
        "categoria": categoria or "o segmento",
        "bairro": normalizar_texto(dados_lead.get("Bairro"), 90),
        "tem_site": tem_site,
        "tem_instagram": bool(instagram),
        "evidencias": evidencias,
        "necessidade": necessidade_digital_do_nicho(categoria or dados_lead.get("Nicho", "")),
    }

def gerar_variacoes_contingencia(dados_lead, is_intl=False):
    dados = normalizar_dados_pitch(dados_lead)
    nome = dados["nome"]
    local = f" em {dados['bairro']}" if dados["bairro"] else ""
    if is_intl:
        base = f"I found {nome}{local} on Google. When someone looks for a {dados['categoria']}, they often need clear information before deciding to get in touch."
        if dados["tem_site"]:
            oportunidade = "There may be an opportunity to make the current website clearer on mobile and easier for visitors to take the next step."
        else:
            oportunidade = "I could not identify a standalone website on the Google profile, so visitors may have to piece together the information before contacting you."
        variacoes = {
            "consultiva": f"{base} {oportunidade} A focused website can organize the essentials and make the next step simpler. Would it be useful if I shared a quick idea?",
            "direta": f"Hi! For {nome}, a clear website can help visitors understand the service and contact the right person without relying only on social profiles. Would you like to see what that could look like?",
            "curiosidade": f"Hi! I noticed an opportunity in how {nome} is presented online{local}. What if a visitor could understand the service and take action in one place? Would you be open to a quick example?",
        }
    else:
        observacao = "não identifiquei um site próprio no perfil do Google" if not dados["tem_site"] else "identifiquei que vocês já possuem um site"
        complemento_instagram = " O Instagram ajuda na descoberta, mas não organiza toda a decisão do cliente." if dados["tem_instagram"] and not dados["tem_site"] else ""
        variacoes = {
            "consultiva": f"Oi! Encontrei a {nome}{local} no Google e {observacao}. Para quem procura {dados['categoria']}, muitas vezes é importante entender o serviço e o próximo passo antes de chamar. Hoje, sem um espaço próprio, a pessoa {dados['necessidade']}.{complemento_instagram} Um site bem organizado pode resolver isso. Posso te mostrar uma ideia?",
            "direta": f"Oi! Vi a {nome}{local} no Google. Quando alguém busca {dados['categoria']}, ter um site claro ajuda a apresentar o essencial e evita que o interesse esfrie antes do contato. {observacao.capitalize()}. Faz sentido eu te mostrar uma possibilidade?",
            "curiosidade": f"Oi! Uma dúvida sobre a {nome}: quando alguém encontra vocês no Google, consegue entender rapidamente o serviço e avançar para o contato? {observacao.capitalize()}. Um site pode concentrar isso em um só lugar. Posso te explicar a ideia em uma imagem?",
        }
    return {estilo: adicionar_triagem_responsavel(texto, is_intl) for estilo, texto in variacoes.items()}

def validar_variacoes_pitch(variacoes, nome_empresa, is_intl=False):
    estilos = ("consultiva", "direta", "curiosidade")
    proibidos = ("próximo nível", "potencialize", "alavanque", "solução personalizada", "desconto", "preço")
    if not isinstance(variacoes, dict) or any(not normalizar_texto(variacoes.get(estilo, "")) for estilo in estilos):
        return False
    textos = [normalizar_texto(variacoes[estilo], 1200) for estilo in estilos]
    if len({texto.casefold() for texto in textos}) != len(textos):
        return False
    marca = normalizar_texto(nome_empresa, 90).casefold()
    for texto in textos:
        palavras = len(texto.split())
        if palavras < 55 or palavras > 125 or ("site" not in texto.casefold() and "website" not in texto.casefold()):
            return False
        if any(termo in texto.casefold() for termo in proibidos):
            return False
        if marca and marca not in texto.casefold():
            return False
    return True

def mensagem_parece_personalizada(mensagem, nome_empresa):
    if len(mensagem.strip()) < 120:
        return False
    palavras_ignoradas = {
        "advocacia", "agencia", "clínica", "clinica", "comércio", "comercio",
        "empresa", "escritório", "escritorio", "ltda", "serviços", "servicos",
    }
    termos_da_marca = [
        termo for termo in re.findall(r"[\wÀ-ÿ]+", nome_empresa.casefold())
        if len(termo) >= 4 and termo not in palavras_ignoradas
    ]
    menciona_marca = not termos_da_marca or any(termo in mensagem.casefold() for termo in termos_da_marca)
    menciona_site = "site" in mensagem.casefold() or "website" in mensagem.casefold()
    return menciona_marca and menciona_site

def adicionar_triagem_responsavel(mensagem, is_intl=False):
    if is_intl:
        abertura = "Hi! Could you please confirm whether this is the contact for the person responsible for marketing or commercial decisions? If this number is used for appointments or reception, could you kindly forward this message to the right person?"
    else:
        abertura = "Olá! Este contato é da pessoa responsável pelo comercial ou marketing? Se este número for de agendamento ou recepção, poderia encaminhar esta mensagem para quem cuida dessa área, por favor?"
    return f"{abertura}\n\n{mensagem}"

def obter_copy_contingencia(dados_lead, vendedor, motivo="", is_intl=False):
    nome_curto = dados_lead.get('Nome', '').split(' - ')[0].split('|')[0].strip()
    nicho = " ".join([
        dados_lead.get('Categoria Maps', ''),
        dados_lead.get('Nicho', ''),
        dados_lead.get('Contexto do Site', ''),
    ]).lower()
    bairro = dados_lead.get('Bairro', '')
    site = dados_lead.get('Link Inicial')
    regiao = f" em {bairro}" if bairro else ""
    
    if any(k in nicho for k in ['advoc', 'jurid', 'direito']):
        if site:
            msg = f"Olá, tudo bem? Localizei o escritório da {nome_curto}{regiao} no Google. Preparei um comparativo visual mostrando como deixar a apresentação das áreas de atuação e o botão de atendimento consultivo mais objetivos para novos clientes. Posso te encaminhar essa sugestão para avaliar?"
        else:
            msg = f"Olá, tudo bem? Localizei o escritório da {nome_curto}{regiao} no Google e notei que vocês têm presença de destaque, mas quem busca atendimento online não encontra uma página institucional rápida com as áreas de atuação. Desenvolvi um modelo visual de apresentação institucional para o escritório. Posso te enviar para você ver?"
        estrategia = "Contingência Setorial: Advocacia (respeito a sobriedade e código de ética, foco em apresentação institucional das áreas e atendimento consultivo)."
    elif any(k in nicho for k in ['odont', 'dentist', 'clinic', 'medic', 'saud', 'dermat', 'estetic']):
        if site:
            msg = f"Olá, tudo bem? Vi a {nome_curto}{regiao} no Google. Estruturei uma proposta visual rápida para otimizar a experiência mobile e facilitar o agendamento de consultas/avaliações direto pelo WhatsApp. Posso te mandar uma prévia para dar uma olhada?"
        else:
            msg = f"Olá, tudo bem? Encontrei a {nome_curto}{regiao} no Google com ótimas avaliações. Notei que os pacientes que encontram a clínica online ainda não têm uma página exclusiva para conhecer os tratamentos e agendar com facilidade. Criei um layout demonstrativo de agendamento online focado nos serviços de vocês. Posso te enviar?"
        estrategia = "Contingência Setorial: Saúde/Estética (foco em confiança, apresentação dos procedimentos e facilidade de agendamento)."
    elif any(k in nicho for k in ['imob', 'corret', 'imove']):
        if site:
            msg = f"Olá, tudo bem? Vi a {nome_curto} atuando no mercado imobiliário{regiao}. Analisei o posicionamento online de vocês e desenhei uma melhoria visual focada em reter proprietários e compradores qualificados direto na página principal, antes que cliquem em concorrentes. Posso te enviar um print da ideia?"
        else:
            msg = f"Olá, tudo bem? Localizei a {nome_curto}{regiao} no Google Maps. Quem busca imóveis na região tem forte interesse visual e praticidade, e notei que vocês ainda não possuem uma página própria para destacar as oportunidades e captar contatos diretos. Desenvolvi um protótipo de landing page imobiliária para vocês. Posso te mostrar?"
        estrategia = "Contingência Setorial: Imobiliário (foco em captação de proprietários e compradores de alto valor)."
    elif any(k in nicho for k in ['move', 'planejad', 'marcen', 'arquitet', 'interiores', 'decor']):
        if site:
            msg = f"Olá, tudo bem? Acompanhei o trabalho da {nome_curto}{regiao} no Google. Montei um layout demonstrativo mostrando como organizar o portfólio de projetos para valorizar ainda mais o padrão de acabamento e estimular pedidos de orçamento qualificados. Posso te enviar uma imagem do projeto?"
        else:
            msg = f"Olá, tudo bem? Vi os projetos e avaliações da {nome_curto}{regiao} no Google Maps. Como o mercado de projetos exige forte apelo visual, preparei um protótipo de portfólio digital para apresentar os trabalhos e direcionar novos clientes para orçamento no WhatsApp. Posso te mostrar como ficou?"
        estrategia = "Contingência Setorial: Arquitetura/Móveis (foco em autoridade visual, acabamento e orçamento)."
    elif any(k in nicho for k in ['restauran', 'bar', 'pizz', 'hamburg', 'caf', 'padar', 'gastronom']):
        if site:
            msg = f"Olá! Encontrei a {nome_curto}{regiao} no Google. Analisei a presença digital de vocês e preparei um rascunho de página otimizada para carregar o cardápio rápido no celular e direcionar reservas sem fricção. Posso te mandar o print?"
        else:
            msg = f"Olá! Vi a {nome_curto}{regiao} no Google com excelente recomendação. Percebi que vocês ainda não contam com uma página rápida com o cardápio e botão de pedidos/reservas direto para quem pesquisa a casa no Google. Criei um modelo visual prático para o espaço de vocês. Quer que eu te envie para ver?"
        estrategia = "Contingência Setorial: Gastronomia (foco em cardápio rápido mobile e reserva/pedido)."
    else:
        if site:
            msg = f"Olá, tudo bem? Encontrei a {nome_curto}{regiao} no Google. Analisei o posicionamento online do segmento de vocês e preparei uma demonstração visual mostrando como simplificar o caminho do visitante até o contato comercial direto. Posso te enviar para dar uma olhada?"
        else:
            msg = f"Olá, tudo bem? Localizei a {nome_curto}{regiao} no Google Maps e vi que vocês já possuem boa visibilidade. Desenvolvi um protótipo visual demonstrando como uma página focada em conversão pode transformar quem já pesquisa pela empresa no Google em contatos reais no WhatsApp. Posso te mostrar como ficou?"
        estrategia = "Contingência Setorial Geral (proposta consultiva de melhoria de conversão/site)."

    if "site" not in msg.casefold() and "website" not in msg.casefold():
        msg = msg.replace(
            " Posso", " A sugestão é para um site pensado para esse atendimento. Posso", 1
        )
    if not site:
        necessidade = necessidade_digital_do_nicho(nicho)
        msg = (
            f"Olá, tudo bem? Encontrei a {nome_curto}{regiao} no Google. Hoje, quem procura vocês ali "
            f"{necessidade}. Sem um site que organize essas informações e conduza o próximo passo, parte desse interesse "
            f"acaba esfriando antes do contato. Posso te mostrar uma ideia simples de como resolver isso para a empresa?"
        )
    versoes = gerar_variacoes_contingencia(dados_lead, is_intl)
    msg = versoes["consultiva"]

    aviso_motivo = f" [Alerta: {motivo}]" if motivo else ""
    return {
        'analise': f"Contingência setorial aplicada com base em dados reais do lead.{aviso_motivo}",
        'estrategia': estrategia,
        'mensagem': msg,
        'versoes': versoes,
        'gerada_por_ia': False,
    }

def gerar_copy_inteligente(dados_lead, config, is_intl=False):
    import json
    import time
    
    nome_curto = dados_lead.get('Nome', '').split(' - ')[0].split('|')[0].strip()
    vendedor = config.get('vendedor_nome', '').strip() or 'aqui'
    api_key = os.environ.get("GEMINI_API_KEY", "").strip() or str(config.get("gemini_api_key", "")).strip()
    
    if not api_key:
        return obter_copy_contingencia(dados_lead, vendedor, motivo="Chave de API do Gemini não configurada", is_intl=is_intl)
        
    try:
        categoria = dados_lead.get('Categoria Maps') or dados_lead.get('Nicho', '')
        resumo = dados_lead.get('Resumo Maps', '')
        titulo_site = dados_lead.get('Título do Site', '')
        descricao_site = dados_lead.get('Descrição do Site', '')
        contexto_site = dados_lead.get('Contexto do Site', '')
        site_encontrado = dados_lead.get('Link Inicial', '')
        tem_site = bool(site_encontrado and not is_social_or_directory(site_encontrado))
        dados_normalizados = normalizar_dados_pitch(dados_lead)
        
        super_prompt = f"""Você é um especialista em prospecção consultiva B2B e criação de sites de alta conversão.
Sua missão é gerar uma mensagem curta e humana de primeiro contato para o WhatsApp do responsável por esta empresa local encontrada no Google Maps.

### DADOS REAIS DO NEGÓCIO:
- Nome da Empresa: {nome_curto}
- Nicho de Busca: {dados_lead.get('Nicho', '')}
- Categoria Real no Google Maps: {categoria}
- Resumo/Atuação: {resumo if resumo else 'Não informado'}
- Título do Site: {titulo_site if titulo_site else 'Não informado'}
- Descrição do Site: {descricao_site if descricao_site else 'Não informada'}
- Serviços/temas visíveis no Site: {contexto_site if contexto_site else 'Não informado'}
- Localização/Bairro: {dados_lead.get('Bairro', '')}
- Prova Social: Nota {dados_lead.get('Nota Maps', 'N/A')} ({dados_lead.get('Qtd Avaliacoes', '0')} avaliações no Google)
- Status de Site: {'SITE PRÓPRIO IDENTIFICADO (' + site_encontrado + ')' if tem_site else 'NENHUM SITE PRÓPRIO IDENTIFICADO NO PERFIL DO GOOGLE — não afirmar ausência absoluta'}
- Evidências verificadas: {"; ".join(dados_normalizados['evidencias'])}
- Meu Nome: {vendedor}

### DIRETRIZES DA ABORDAGEM:
1. FOCO DA PROPOSTA:
   - Se a empresa NÃO tem site: Comece pela necessidade percebida do cliente. Explique, sem alarmismo, o que uma pessoa que encontra a empresa no Google ainda não consegue fazer, entender ou decidir sem um site. Mostre a consequência prática: parte do interesse esfria, vira dúvida ou segue para outra opção antes do contato. Só depois apresente o site como o caminho natural para resolver esse problema.
   - Se a empresa JÁ tem site: Reconheça a presença atual e apresente uma oportunidade clara de otimização (conversão mobile, velocidade, apresentação de serviços ou retenção). Mostre que rascunhou uma sugestão visual sem compromisso.
2. ADAPTAÇÃO AO NICHO:
   - Advocacia: Sobriedade institucional, respeito ao código da OAB (sem promessas de causas/ganhos, foco em clareza das áreas e contato ético).
   - Saúde/Odonto/Clínicas: Credibilidade, apresentação dos tratamentos e facilidade de agendamento/tira-dúvidas.
   - Imobiliária/Corretores: Captação de proprietários, destaque visual dos imóveis e atendimento ágil.
   - Móveis/Arquitetura: Portfólio, projetos concluídos e solicitação de orçamento.
   - Gastronomia/Comércio: Praticidade mobile, cardápio rápido e pedidos/reservas.
3. ESTILO DE REDAÇÃO:
   - Tom natural, humano, direto e profissional.
   - Cada versão deve ter entre 45 e 90 palavras. Uma abertura de triagem será incluída pelo sistema depois.
   - NUNCA use clichês como: "próximo nível", "potencialize sua presença", "transforme sua presença", "solução personalizada", "alavanque resultados".
   - CTA (Chamada de Ação) de baixíssima fricção no final: uma pergunta simples para continuar a conversa, sem pedir reunião ou proposta.
   - Nunca pergunte "vamos marcar reunião" ou "posso enviar proposta comercial". O objetivo é apenas conseguir a permissão para mostrar a demonstração.
    - Diga explicitamente que a sugestão é de um SITE. A palavra "site" deve aparecer naturalmente na mensagem; não use apenas "página", "presença digital" ou "layout" de forma vaga.
    - Se o Nicho de Busca contrariar a Categoria Real ou o conteúdo do Site, use a Categoria Real e o conteúdo do Site. Nunca escreva uma abordagem de estética para uma empresa jurídica, por exemplo.
    - Cite apenas um detalhe que esteja nos dados reais acima. Se não houver detalhe confiável, use uma abordagem neutra do segmento, sem inventar serviços.
   - Não fale como um vendedor oferecendo um serviço, não comece com "preparei um site", "tenho uma proposta" ou "quero vender". A mensagem deve soar como uma observação útil sobre uma oportunidade que o próprio negócio está deixando passar.
4. CONTATO DE RECEPÇÃO/AGENDAMENTO:
   - O número do Google Maps pode ser de recepção, agendamento ou atendimento. Não assuma que a pessoa é dona da empresa.
   - Escreva apenas a parte comercial da mensagem. O sistema adicionará antes uma pergunta educada pedindo o responsável por marketing/comercial e solicitando encaminhamento caso seja recepção ou agendamento.

5. VARIAÇÕES:
   - Crie três abordagens realmente diferentes: consultiva (observação + contexto), direta (benefício específico) e curiosidade (pergunta que abre uma conversa).
   - Não invente serviços, problemas técnicos, números, site ausente ou conteúdo de rede social. Se os dados forem insuficientes, use uma observação exploratória.

### FORMATO DE SAÍDA OBRIGATÓRIO (JSON):
Retorne estritamente um objeto JSON com as chaves:
{{
  "diagnostico": "Resumo em 1-2 frases do diagnóstico da presença digital da empresa.",
  "estrategia": "Explicação do ângulo comercial adotado e o porquê.",
  "versoes": {{
    "consultiva": "Mensagem consultiva completa.",
    "direta": "Mensagem direta completa.",
    "curiosidade": "Mensagem de curiosidade completa."
  }}
}}
"""
        if is_intl:
            super_prompt += '\n\nIMPORTANTE: Escreva as três mensagens em INGLÊS natural.'
        
        modelos_candidatos = MODEL_CANDIDATES
        resposta_bruta = ""
        for m_name in modelos_candidatos:
            try:
                response_text = generate_text(api_key, m_name, super_prompt, json_mode=True)
                if response_text:
                    resposta_bruta = response_text
                    break
            except Exception as e:
                print(f"[WORKER] Modelo {m_name} indisponível: {str(e)[:100]}")
                continue

        if not resposta_bruta:
            return obter_copy_contingencia(dados_lead, vendedor, motivo="Modelos Gemini atingiram limite de quota diária (429)", is_intl=is_intl)

        resposta_bruta = re.sub(r"^```(?:json)?\s*|\s*```$", "", resposta_bruta.strip(), flags=re.IGNORECASE)
        parsed = json.loads(resposta_bruta)
        versoes_sem_triagem = parsed.get("versoes", {})
        diagnostico = parsed.get("diagnostico", "").strip()
        estrategia = parsed.get("estrategia", "").strip()
        versoes = {
            estilo: adicionar_triagem_responsavel(normalizar_texto(versoes_sem_triagem.get(estilo, ""), 900), is_intl)
            for estilo in ("consultiva", "direta", "curiosidade")
        }
        if not validar_variacoes_pitch(versoes, nome_curto, is_intl):
            return obter_copy_contingencia(dados_lead, vendedor, motivo="Resposta da IA sem variações personalizadas e verificáveis", is_intl=is_intl)
        mensagem = versoes["consultiva"]

        return {
            'analise': f"DIAGNÓSTICO:\n{diagnostico}" if diagnostico else "Análise concluída via IA.",
            'estrategia': estrategia or "Abordagem consultiva com proposta de melhoria/protótipo de site.",
            'mensagem': mensagem,
            'versoes': versoes,
            'gerada_por_ia': True,
        }
        
    except Exception as e:
        print(f'[WORKER] Erro AI: {e}')
        return obter_copy_contingencia(dados_lead, vendedor, motivo=f"Erro na execução da IA: {e}", is_intl=is_intl)


def gerar_copy_profissional(dados_lead, config, is_intl=False, preview_available=False, use_external_ai=True):
    inteligencia = analyze_lead(dados_lead, preview_available=preview_available)
    inteligencia["language"] = "en" if is_intl else "pt-BR"
    inteligencia["seller"] = seller_profile(config)
    fallback = generate_fallback_pitches(inteligencia, is_intl=is_intl)
    qualidade_fallback = evaluate_pitches(fallback, inteligencia, require_preview=preview_available)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip() or str(config.get("gemini_api_key", "")).strip()
    versoes = fallback
    gerada_por_ia = False
    motivo = "Modelo profissional local aplicado"

    if api_key and use_external_ai:
        modos = ["consultiva", "direta", "personalizada", "recepcao", "email"]
        if preview_available:
            modos.append("previa_visual")
        tentativas = 0
        feedback = None
        for model_name in MODEL_CANDIDATES:
            if tentativas >= 2:
                break
            tentativas += 1
            try:
                prompt = build_generation_prompt(inteligencia, modos, feedback=feedback, is_intl=is_intl)
                response_text = generate_text(api_key, model_name, prompt, json_mode=True)
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", response_text, flags=re.IGNORECASE)
                candidate = json.loads(raw).get("versoes", {})
                candidate = {mode: normalizar_texto(candidate.get(mode, ""), 1200) for mode in modos}
                candidate = {**fallback, **candidate}
                qualidade = evaluate_pitches(candidate, inteligencia, require_preview=preview_available)
                if qualidade["approved"]:
                    versoes = candidate
                    qualidade_fallback = qualidade
                    gerada_por_ia = True
                    motivo = f"Aprovada após {tentativas} tentativa(s) de IA"
                    break
                feedback = qualidade["reasons"]
                motivo = f"IA reprovada na tentativa {tentativas}: {qualidade['reasons']}"
            except Exception as error:
                motivo = f"IA indisponível na tentativa {tentativas}: {str(error)[:160]}"

    evidencias = inteligencia.get("verified", [])
    resumo = "\n".join(f"• {item['claim']} — Fonte: {item['source']}" for item in evidencias)
    analise = (
        f"Confiança da análise: {inteligencia['confidence']}%.\n"
        f"Oportunidade: {inteligencia['opportunity']}.\n"
        f"Evidências verificadas:\n{resumo}"
    )
    qualidade_fallback["processing_note"] = motivo
    return {
        "analise": analise,
        "estrategia": inteligencia["main_argument"],
        "mensagem": versoes["consultiva"],
        "versoes": versoes,
        "inteligencia": inteligencia,
        "qualidade": qualidade_fallback,
        "gerada_por_ia": gerada_por_ia,
    }


gerar_copy_inteligente = gerar_copy_profissional


def gerar_prompt_prototipo(nome, nicho):
    nome_curto = nome.split(" - ")[0].split("|")[0].strip()
    base = f"UI/UX web design of a modern, high-converting landing page for a {nicho} business named '{nome_curto}'. "
    design = "Clean layout, professional typography, hero section with a clear call-to-action button, services overview section, testimonials, WhatsApp floating button. Modern corporate colors, highly trustworthy."
    return base + design + " Dribbble style, Behance style, 8k resolution, photorealistic ui."

def extrair_id_unico(href):
    if not href: return str(random.random())
    match = re.search(r"1s(0x[^:]+:0x[a-f0-9]+)", href)
    return match.group(1) if match else href.split("?")[0]

def extrair_avaliacoes(page):
    nota = "0"
    qtd = "0"
    try:
        elementos = page.locator("[aria-label]")
        for i in range(min(elementos.count(), 300)):
            aria = elementos.nth(i).get_attribute("aria-label")
            if not aria: continue
            aria_normalizado = aria.lower()
            if nota == "0":
                match_nota = re.search(r"([\d,.]+)\s*(?:estrelas?|stars?)", aria_normalizado)
                if match_nota: nota = match_nota.group(1)
            if qtd == "0":
                match_qtd = re.search(r"([\d,.]+)\s*(?:avalia(?:cao|coes|ção|ções)|reviews?)", aria_normalizado)
                if match_qtd: qtd = match_qtd.group(1).replace(".", "").replace(",", "")
            if nota != "0" and qtd != "0":
                break
    except Exception as e: print("Aviso interno:", e)
    return nota, qtd

def check_auth(username, password):
    valid_user = os.environ.get("APP_USER", "")
    valid_pass = os.environ.get("APP_PASS", "")
    return bool(valid_user and valid_pass and username and password) and (
        hmac.compare_digest(username, valid_user) and hmac.compare_digest(password, valid_pass)
    )

@app.before_request
def require_login():
    if request.endpoint in ("static", "login", "health"):
        return
    
    # Suporte para requisições com Authorization Header (compatibilidade com automações/curl)
    auth = request.authorization
    if auth and check_auth(auth.username, auth.password):
        return

    # Autenticação via Sessão Web duradoura (cookie)
    if not session.get("authenticated"):
        if request.path.startswith("/api/") or request.path.startswith("/status_"):
            return jsonify({"success": False, "error": "Não autenticado"}), 401
        dest = request.full_path if request.query_string else request.path
        return redirect(url_for("login", next=dest))

    # Validação de origem em requisições de mutação
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not app.config.get("TESTING"):
        origin = request.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc != request.host:
            return jsonify({"success": False, "error": "Origem da requisição não permitida"}), 403
        expected_token = session.get("csrf_token", "")
        supplied_token = request.headers.get("X-CSRF-Token", "") or request.form.get("csrf_token", "")
        if not expected_token or not supplied_token or not hmac.compare_digest(expected_token, supplied_token):
            return jsonify({"success": False, "error": "Sessão de segurança expirada. Atualize a página e tente novamente."}), 403

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("index"))
    
    erro = None
    if request.method == "POST":
        client_key = request.remote_addr or "unknown"
        attempts = login_rate_state(client_key)
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            return render_template(
                "login.html",
                erro="Muitas tentativas incorretas. Aguarde alguns minutos antes de tentar novamente.",
            ), 429
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        
        if check_auth(username, password):
            clear_login_failures(client_key)
            session.clear()
            session.permanent = True
            session["authenticated"] = True
            session["user"] = username
            csrf_token()
            
            next_url = request.args.get("next")
            if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("index")
            return redirect(next_url)
        else:
            record_login_failure(client_key)
            erro = "Usuário ou senha incorretos. Verifique suas credenciais."
            
    return render_template("login.html", erro=erro)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.after_request
def aplicar_cabecalhos_seguranca(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN" if request.endpoint == "preview_document" else "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.endpoint == "preview_document":
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src 'none'; script-src 'none'; connect-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
            "img-src 'self' data: https:; connect-src 'self'; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if session.get("authenticated"):
        response.headers["Cache-Control"] = "no-store"
    return response

@app.route("/")
def index():
    return render_template("search.html")


@app.route("/health")
def health():
    try:
        create_daily_backup()
        conn = sqlite3.connect(DB_NAME)
        conn.execute("SELECT 1").fetchone()
        preview_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='preview_versions'").fetchone()
        interaction_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lead_interactions'").fetchone()
        conn.close()
        ready = bool(preview_table and interaction_table)
        return jsonify({
            "status": "ok" if ready else "degraded",
            "database": "ok",
            "studio": bool(preview_table),
            "follow_up": bool(interaction_table),
            "commercial_release": "2026.11.05-discovery-engine-v9",
            "target_engine_version": TARGET_ENGINE_VERSION,
            "niche_engine_version": NICHE_ENGINE_VERSION,
            "lead_score_version": SCORE_VERSION,
            "pitch_modes": 5,
            "whatsapp_cloud": cloud_configured(),
            "google_places": bool(os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()),
            "discovery_engine": "1.0",
            "pitch_pipeline_version": PITCH_PIPELINE_VERSION,
            "secure_cookie": bool(app.config.get("SESSION_COOKIE_SECURE")),
            "proxy_headers": isinstance(app.wsgi_app, ProxyFix),
        }), 200 if ready else 503
    except Exception:
        return jsonify({"status": "error", "database": "unavailable"}), 503

def render_crm_view(status_scope, crm_view):
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 20
    crm_filters = {
        "nome": normalizar_texto(request.args.get("nome", ""), 100),
        "status": normalizar_texto(request.args.get("status", ""), 40) if crm_view == "contacted" else "",
        "nicho": normalizar_texto(request.args.get("nicho", ""), 120),
        "potencial": normalizar_texto(request.args.get("potencial", ""), 40),
        "followup": normalizar_texto(request.args.get("followup", ""), 20),
        "site": normalizar_texto(request.args.get("site", ""), 80),
        "qualidade": normalizar_texto(request.args.get("qualidade", ""), 40),
        "validacao": normalizar_texto(request.args.get("validacao", ""), 40),
        "origem": normalizar_texto(request.args.get("origem", ""), 120),
        "min_score": max(0, min(100, request.args.get("min_score", 0, type=int))) if request.args.get("min_score") else 0,
    }
    active_filters = {key: value for key, value in crm_filters.items() if value}
    conn = sqlite3.connect(DB_NAME)
    where, params = build_crm_where(status_scope, crm_filters)
    total = conn.execute(f"SELECT COUNT(*) FROM leads{where}", params).fetchone()[0]
    scope_where, scope_params = build_crm_where(status_scope)
    niche_rows = [repair_known_mojibake(row[0]).strip() for row in conn.execute(
        f"SELECT DISTINCT nicho FROM leads{scope_where} AND trim(coalesce(nicho, '')) != '' ORDER BY lower(nicho)",
        scope_params,
    ).fetchall()]
    available_niches = []
    seen_niches = set()
    for niche in sorted(niche_rows, key=normalize):
        niche_key = normalize(niche)
        if niche_key and niche_key not in seen_niches:
            seen_niches.add(niche_key)
            available_niches.append(niche)
    if crm_view == "inbox":
        site_counts = conn.execute(
            """SELECT
                 SUM(CASE WHEN site_opportunity_status = 'Site encontrado — sem sinal claro' THEN 1 ELSE 0 END),
                 SUM(CASE WHEN site_opportunity_status = 'Revisão manual' OR
                               ((site_opportunity_status IS NULL OR site_opportunity_status = '') AND link_inicial != '')
                          THEN 1 ELSE 0 END)
               FROM leads WHERE status = 'Novo'"""
        ).fetchone()
    else:
        site_counts = (0, 0)
    follow_up_values = [row[0] for row in conn.execute(
        f"SELECT next_action_at FROM leads{scope_where}", scope_params,
    ).fetchall()]
    conn.close()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    leads = load_leads(status_scope, per_page, (page - 1) * per_page, crm_filters)
    for lead in leads:
        lead["follow_up_state"] = classificar_prazo_followup(lead.get("next_action_at"))
    contact_payloads = {
        lead["place_id"]: {
            "name": lead.get("nome") or "Lead",
            "whatsapp": lead.get("whatsapp_link") or "",
            "email": lead.get("email") or "",
            "copy": lead.get("copy_texto") or "",
            "copies": lead.get("copies_pitch") or {},
            "default_mode": lead.get("recommended_pitch_mode") or "consultiva",
            "contact_label": (lead.get("contact_strategy") or {}).get("label") or "Contato geral",
        }
        for lead in leads
    }
    leads_com_site = site_counts[0] or 0
    leads_site_para_auditar = site_counts[1] or 0
    follow_up_counts = {
        state: sum(1 for value in follow_up_values if classificar_prazo_followup(value) == state)
        for state in ("atrasado", "hoje", "proximo", "sem_acao")
    }
    return render_template(
        "crm.html", leads=leads, leads_com_site=leads_com_site,
        leads_site_para_auditar=leads_site_para_auditar,
        is_descartados=crm_view == "discarded", crm_view=crm_view, follow_up_counts=follow_up_counts,
        page=page, total_pages=total_pages, total_leads=total, contact_payloads=contact_payloads,
        crm_filters=crm_filters, active_filters=active_filters, available_niches=available_niches,
        whatsapp_cloud_enabled=cloud_configured(),
    )


@app.route("/crm")
def crm():
    return render_crm_view("inbox", "inbox")


@app.route("/crm/contatados")
def crm_contatados():
    return render_crm_view("contacted", "contacted")


@app.route("/crm/descartados")
def crm_descartados():
    return render_crm_view("discarded", "discarded")


def get_lead_by_id(place_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM leads WHERE place_id = ?", (place_id,)).fetchone()
    conn.close()
    if not row:
        return None
    lead = dict(row)
    lead["nome"] = repair_known_mojibake(lead.get("nome"))
    lead["nicho"] = repair_known_mojibake(lead.get("nicho"))
    lead["bairro"] = repair_known_mojibake(lead.get("bairro"))
    for field_name in ("copies_pitch", "inteligencia_comercial", "qualidade_pitch", "score_breakdown"):
        try:
            lead[field_name] = json.loads(lead.get(field_name) or "{}")
        except (TypeError, json.JSONDecodeError):
            lead[field_name] = {}
    try:
        lead["evidence"] = json.loads(lead.get("evidence_json") or "[]")
    except (TypeError, json.JSONDecodeError):
        lead["evidence"] = []
    site_assessment = assess_site_opportunity(
        lead.get("link_inicial"), lead.get("site_title"), lead.get("site_description"), lead.get("site_context")
    )
    lead["site_opportunity_status"] = lead.get("site_opportunity_status") or site_assessment["status"]
    try:
        lead["site_opportunity_reasons"] = json.loads(lead.get("site_opportunity_reasons") or "[]")
    except (TypeError, json.JSONDecodeError):
        lead["site_opportunity_reasons"] = site_assessment["reasons"]
    scoring = calcular_score_lead(
        lead, configured_weights=load_config().get("lead_score_weights"),
        performance_adjustment=lead.get("score_breakdown", {}).get("performance_adjustment", 0),
    )
    lead["potencial"] = scoring["score"]
    lead["motivo_potencial"] = scoring["reason"]
    lead["faixa_potencial"] = scoring["range"]
    lead["score_breakdown"] = scoring
    lead["score_version"] = scoring["version"]
    data_quality = lead_data_quality(lead)
    lead["data_quality_status"] = data_quality["status"]
    lead["data_quality_issues"] = data_quality["issues"]
    lead["data_confidence"] = data_quality["confidence"]
    contact_strategy = lead["inteligencia_comercial"].get("contact_strategy")
    if not contact_strategy:
        contact_strategy = recommend_contact_strategy(lead_to_raw_data(lead), preview_available=bool(get_preview_versions(place_id)))
    lead["contact_strategy"] = contact_strategy
    lead["recommended_pitch_mode"] = contact_strategy["recommended_mode"]
    return lead


def lead_to_raw_data(lead):
    return {
        "Nome": lead.get("nome", ""), "Nicho": lead.get("nicho", ""),
        "Categoria Maps": lead.get("nicho", ""), "Bairro": lead.get("bairro", ""),
        "Nota Maps": lead.get("nota", ""), "Qtd Avaliacoes": lead.get("avaliacoes", ""),
        "Telefone": lead.get("telefone", ""), "E-mail Encontrado": lead.get("email", ""),
        "Instagram": lead.get("instagram", ""), "Facebook": lead.get("facebook", ""),
        "LinkedIn": lead.get("linkedin", ""), "Link Inicial": lead.get("link_inicial", ""),
        "Google Maps": lead.get("google_maps", ""), "Título do Site": lead.get("site_title", ""),
        "Descrição do Site": lead.get("site_description", ""), "Contexto do Site": lead.get("site_context", ""),
    }


def lead_is_international(lead):
    phone = extrair_apenas_numeros(lead.get("telefone", ""))
    if phone and not phone.startswith("55"):
        return True
    location = (lead.get("bairro", "") or "").casefold()
    markers = ("usa", "united states", "portugal", "lisboa", "lisbon", "europe", "europa", "london", "madrid", "miami", "new york")
    return any(marker in location for marker in markers)


def get_preview_versions(place_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, place_id, version, config_json, screenshot_path, created_at FROM preview_versions WHERE place_id = ? ORDER BY version DESC",
        (place_id,),
    ).fetchall()
    conn.close()
    previews = []
    for row in rows:
        preview = dict(row)
        try:
            preview["config"] = json.loads(preview.pop("config_json"))
        except (TypeError, json.JSONDecodeError):
            preview["config"] = {}
        previews.append(preview)
    return previews


def get_lead_interactions(place_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM lead_interactions WHERE place_id = ? ORDER BY created_at DESC, id DESC",
        (place_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def suggest_next_action(response_text, sentiment, preview_available=False):
    response = (response_text or "").casefold()
    if sentiment == "não contatar" or any(term in response for term in ("não tenho interesse", "nao tenho interesse", "não chamar", "nao chamar", "remover contato")):
        return "Marcar como não contatar e encerrar a abordagem."
    if sentiment == "interessado" or any(term in response for term in ("tenho interesse", "pode enviar", "manda", "gostei", "quero ver")):
        return "Enviar a prévia visual e confirmar qual objetivo do site deve receber prioridade." if preview_available else "Gerar uma prévia visual e confirmar qual objetivo do site deve receber prioridade."
    if sentiment == "objeção" or any(term in response for term in ("preço", "valor", "caro", "orçamento", "orcamento")):
        return "Entender o escopo necessário antes de falar em investimento e responder sem pressionar."
    if sentiment == "sem momento" or any(term in response for term in ("agora não", "agora nao", "depois", "outro momento")):
        return "Registrar o prazo indicado pelo lead e fazer apenas um retorno na data combinada."
    if response_text:
        return "Revisar a resposta, esclarecer a dúvida apresentada e definir um único próximo passo."
    return "Fazer um acompanhamento curto em três dias úteis, sem repetir a mensagem inicial."


def add_business_days(start, days):
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


@app.route("/api/leads/<path:place_id>/contacted", methods=["POST"])
def register_lead_contact(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    if lead.get("do_not_contact"):
        return jsonify({"success": False, "error": "Este lead está marcado como não contatar"}), 409

    payload = request.get_json(silent=True) or {}
    channel = normalizar_texto(payload.get("channel", "WhatsApp"), 40)
    if channel not in {"WhatsApp", "E-mail", "Telefone", "Outro"}:
        return jsonify({"success": False, "error": "Canal de contato inválido"}), 400
    pitch_mode = normalizar_texto(payload.get("pitch_mode", "consultiva"), 40)
    message = normalizar_texto(payload.get("message", ""), 3000)
    if not message:
        return jsonify({"success": False, "error": "A mensagem enviada não pode ficar vazia"}), 400

    now = datetime.now()
    next_action_at = add_business_days(now, 3).replace(hour=10, minute=0, second=0, microsecond=0)
    next_action = "Confirmar se a mensagem foi recebida e fazer um retorno curto, sem repetir a abordagem inicial."
    advanced_statuses = {"Conversando", "Fechado", "Não fechado"}
    next_status = lead.get("status") if lead.get("status") in advanced_statuses else "Contatado"

    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            """INSERT INTO lead_interactions
               (place_id, interaction_type, channel, content, sentiment, next_action, next_action_at)
               VALUES (?, 'abordagem', ?, ?, 'aguardando resposta', ?, ?)""",
            (place_id, channel, message, next_action, next_action_at.isoformat(timespec="minutes")),
        )
        conn.execute(
            """UPDATE leads SET status = ?, last_contact_at = ?, last_contact_channel = ?,
               last_pitch_mode = ?, contact_count = COALESCE(contact_count, 0) + 1,
               next_action = ?, next_action_at = ? WHERE place_id = ?""",
            (next_status, now.isoformat(timespec="seconds"), channel, pitch_mode, next_action,
             next_action_at.isoformat(timespec="minutes"), place_id),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({
        "success": True,
        "status": next_status,
        "next_action": next_action,
        "next_action_at": next_action_at.isoformat(timespec="minutes"),
    })


@app.route("/api/leads/<path:place_id>/whatsapp", methods=["POST"])
def send_lead_whatsapp(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    if lead.get("do_not_contact"):
        return jsonify({"success": False, "error": "Este lead está marcado como não contatar"}), 409
    payload = request.get_json(silent=True) or {}
    message = normalizar_texto(payload.get("message", ""), 1024)
    assessment = assess_phone(lead.get("telefone"), "europa" if lead_is_international(lead) else "br")
    if not assessment["valid"]:
        return jsonify({"success": False, "error": assessment["reason"]}), 400
    try:
        delivery = send_approved_template(assessment["digits"], message)
    except (ValueError, RuntimeError) as error:
        return jsonify({"success": False, "error": str(error)}), 502

    now = datetime.now()
    next_action_at = add_business_days(now, 3).replace(hour=10, minute=0, second=0, microsecond=0)
    next_action = "Confirmar se a mensagem foi recebida e fazer um retorno curto, sem repetir a abordagem inicial."
    advanced_statuses = {"Conversando", "Fechado", "Não fechado"}
    next_status = lead.get("status") if lead.get("status") in advanced_statuses else "Contatado"
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            """INSERT INTO lead_interactions
               (place_id, interaction_type, channel, content, sentiment, next_action, next_action_at)
               VALUES (?, 'abordagem', 'WhatsApp Cloud API', ?, 'aguardando resposta', ?, ?)""",
            (place_id, message, next_action, next_action_at.isoformat(timespec="minutes")),
        )
        conn.execute(
            """UPDATE leads SET status = ?, last_contact_at = ?, last_contact_channel = 'WhatsApp Cloud API',
               contact_count = COALESCE(contact_count, 0) + 1, next_action = ?, next_action_at = ? WHERE place_id = ?""",
            (next_status, now.isoformat(timespec="seconds"), next_action, next_action_at.isoformat(timespec="minutes"), place_id),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"success": True, "message_id": delivery["message_id"], "next_action_at": next_action_at.isoformat(timespec="minutes")})


@app.route("/leads/<path:place_id>")
def lead_detail(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return "Lead não encontrado", 404
    previews = get_preview_versions(place_id)
    intelligence = lead.get("inteligencia_comercial") or analyze_lead(lead_to_raw_data(lead), preview_available=bool(previews))
    interactions = get_lead_interactions(place_id)
    return render_template("lead_detail.html", lead=lead, intelligence=intelligence, previews=previews, interactions=interactions)


@app.route("/leads/<path:place_id>/studio")
def preview_studio(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return "Lead não encontrado", 404
    previews = get_preview_versions(place_id)
    initial_config = previews[0]["config"] if previews else build_preview_config(lead_to_raw_data(lead))
    return render_template("studio.html", lead=lead, previews=previews, initial_config=initial_config)


@app.route("/api/leads/<path:place_id>/previews", methods=["POST"])
def create_preview(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    payload = request.get_json(silent=True) or request.form.to_dict()
    config = build_preview_config(lead_to_raw_data(lead), payload)
    html = render_preview_html(config)
    conn = sqlite3.connect(DB_NAME)
    try:
        version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM preview_versions WHERE place_id = ?", (place_id,)).fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO preview_versions (place_id, version, config_json, html_content) VALUES (?, ?, ?, ?)",
            (place_id, version, json.dumps(config, ensure_ascii=False), html),
        )
        preview_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    def refresh_pitch_with_preview():
        current_lead = get_lead_by_id(place_id)
        if not current_lead:
            return
        raw = lead_to_raw_data(current_lead)
        result = gerar_copy_inteligente(raw, load_config(), is_intl=lead_is_international(current_lead), preview_available=True)
        phone = extrair_apenas_numeros(current_lead.get("telefone", ""))
        whatsapp = formatar_whatsapp(phone, result["mensagem"]) if eh_celular_valido(phone) else ""
        update_lead_ai(place_id, result["mensagem"], result["analise"], result["estrategia"], whatsapp,
                       result["versoes"], result["inteligencia"], result["qualidade"])

    threading.Thread(target=refresh_pitch_with_preview, daemon=True).start()
    return jsonify({
        "success": True, "preview_id": preview_id, "version": version,
        "preview_url": url_for("preview_document", preview_id=preview_id),
        "png_url": url_for("preview_png", preview_id=preview_id),
        "screenshot_ready": False, "png_deferred": True,
    })


@app.route("/preview/<int:preview_id>")
def preview_document(preview_id):
    conn = sqlite3.connect(DB_NAME)
    row = conn.execute("SELECT html_content FROM preview_versions WHERE id = ?", (preview_id,)).fetchone()
    conn.close()
    if not row:
        return "Prévia não encontrada", 404
    return Response(row[0], mimetype="text/html")


@app.route("/preview/<int:preview_id>/png")
def preview_png(preview_id):
    conn = sqlite3.connect(DB_NAME)
    row = conn.execute("SELECT html_content, screenshot_path FROM preview_versions WHERE id = ?", (preview_id,)).fetchone()
    conn.close()
    if not row:
        return "Prévia não encontrada", 404
    screenshot_path = row[1] or os.path.join(PREVIEW_DIR, f"preview_{preview_id}.png")
    if not os.path.exists(screenshot_path):
        try:
            capture_preview_png(row[0], screenshot_path)
            conn = sqlite3.connect(DB_NAME)
            conn.execute("UPDATE preview_versions SET screenshot_path = ? WHERE id = ?", (screenshot_path, preview_id))
            conn.commit()
            conn.close()
        except Exception as error:
            return jsonify({"success": False, "error": f"Não foi possível gerar o PNG: {error}"}), 503
    return send_file(screenshot_path, mimetype="image/png", as_attachment=True, download_name=f"previa-site-{preview_id}.png")


@app.route("/api/leads/<path:place_id>/regenerate-pitches", methods=["POST"])
def regenerate_lead_pitches(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    previews = get_preview_versions(place_id)
    result = gerar_copy_inteligente(lead_to_raw_data(lead), load_config(), is_intl=lead_is_international(lead), preview_available=bool(previews))
    phone = extrair_apenas_numeros(lead.get("telefone", ""))
    whatsapp = formatar_whatsapp(phone, result["mensagem"]) if eh_celular_valido(phone) else ""
    update_lead_ai(place_id, result["mensagem"], result["analise"], result["estrategia"], whatsapp,
                   result["versoes"], result["inteligencia"], result["qualidade"])
    return jsonify({"success": True, "versoes": result["versoes"], "qualidade": result["qualidade"]})


@app.route("/api/leads/<path:place_id>/pitch", methods=["PATCH"])
def save_lead_pitch(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    payload = request.get_json(silent=True) or {}
    mode = payload.get("mode", "")
    text = normalizar_texto(payload.get("text", ""), 1400)
    allowed = {"consultiva", "direta", "personalizada", "recepcao", "email", "previa_visual"}
    if mode not in allowed or not text:
        return jsonify({"success": False, "error": "Modalidade ou texto inválido"}), 400
    copies = dict(lead.get("copies_pitch") or {})
    copies[mode] = text
    intelligence = lead.get("inteligencia_comercial") or analyze_lead(lead_to_raw_data(lead), bool(get_preview_versions(place_id)))
    quality = evaluate_pitches(copies, intelligence, require_preview=bool(get_preview_versions(place_id)))
    primary = copies.get("consultiva") or text
    phone = extrair_apenas_numeros(lead.get("telefone", ""))
    whatsapp = formatar_whatsapp(phone, primary) if eh_celular_valido(phone) else ""
    update_lead_ai(place_id, primary, lead.get("analise_ia", ""), lead.get("estrategia_ia", ""), whatsapp,
                   copies, intelligence, quality)
    return jsonify({"success": True, "qualidade": quality})


@app.route("/api/leads/<path:place_id>/follow-up", methods=["POST"])
def save_lead_follow_up(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    payload = request.get_json(silent=True) or {}
    response_text = normalizar_texto(payload.get("response", ""), 1800)
    channel = normalizar_texto(payload.get("channel", "WhatsApp"), 40)
    sentiment = normalizar_texto(payload.get("sentiment", "neutro"), 40).casefold()
    allowed_sentiments = {"neutro", "interessado", "objeção", "sem momento", "não contatar"}
    if sentiment not in allowed_sentiments:
        return jsonify({"success": False, "error": "Classificação da resposta inválida"}), 400
    next_action = normalizar_texto(payload.get("next_action", ""), 700)
    if not next_action:
        next_action = suggest_next_action(response_text, sentiment, bool(get_preview_versions(place_id)))
    next_action_at = normalizar_texto(payload.get("next_action_at", ""), 30) or None
    if next_action_at and not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?", next_action_at):
        return jsonify({"success": False, "error": "Data da próxima ação inválida"}), 400
    if not response_text and not next_action:
        return jsonify({"success": False, "error": "Informe uma resposta ou próxima ação"}), 400

    status = "Conversando" if response_text else normalizar_status_pipeline(lead.get("status")) or "Novo"
    do_not_contact = sentiment == "não contatar"
    if do_not_contact:
        status = "Não fechado"
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            """INSERT INTO lead_interactions
               (place_id, interaction_type, channel, content, sentiment, next_action, next_action_at)
               VALUES (?, 'resposta', ?, ?, ?, ?, ?)""",
            (place_id, channel, response_text or "Próxima ação registrada", sentiment, next_action, next_action_at),
        )
        conn.execute(
            """UPDATE leads SET last_response = ?, next_action = ?, next_action_at = ?, status = ?,
               do_not_contact = CASE WHEN ? THEN 1 ELSE do_not_contact END,
               do_not_contact_reason = CASE WHEN ? THEN ? ELSE do_not_contact_reason END,
               do_not_contact_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE do_not_contact_at END
               WHERE place_id = ?""",
            (response_text, next_action, next_action_at, status, do_not_contact, do_not_contact,
             response_text or "Preferência registrada", do_not_contact, place_id),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"success": True, "next_action": next_action, "status": status, "do_not_contact": do_not_contact})


@app.route("/api/leads/<path:place_id>/do-not-contact", methods=["POST"])
def update_do_not_contact(place_id):
    lead = get_lead_by_id(place_id)
    if not lead:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    payload = request.get_json(silent=True) or {}
    blocked = bool(payload.get("blocked", True))
    reason = normalizar_texto(payload.get("reason", "Preferência de não contato registrada"), 500)
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            """UPDATE leads SET do_not_contact = ?, do_not_contact_reason = ?,
               do_not_contact_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
               status = CASE WHEN ? THEN 'Não fechado' ELSE 'Conversando' END WHERE place_id = ?""",
            (int(blocked), reason if blocked else "", blocked, blocked, place_id),
        )
        conn.execute(
            "INSERT INTO lead_interactions (place_id, interaction_type, channel, content, sentiment) VALUES (?, 'preferencia', 'Sistema', ?, ?)",
            (place_id, reason if blocked else "Permissão de contato reaberta manualmente", "não contatar" if blocked else "neutro"),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"success": True, "blocked": blocked})

@app.route("/estatisticas")
def estatisticas():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        leads = [dict(row) for row in conn.execute(
            """SELECT nicho, bairro, status, whatsapp_link, email, link_inicial, faixa_potencial,
                      lead_source, validation_status, site_confidence, commercial_outcome
               FROM leads"""
        ).fetchall()]
        source_usage = [dict(row) for row in conn.execute(
            """SELECT usage_date, source, requests, candidates, estimated_cost_micros, errors
               FROM source_usage ORDER BY usage_date DESC, source LIMIT 30"""
        ).fetchall()]
        discovery_jobs = [dict(row) for row in conn.execute(
            """SELECT job_id, status, stats_json, error, created_at, finished_at
               FROM discovery_jobs ORDER BY created_at DESC LIMIT 12"""
        ).fetchall()]
    finally:
        conn.close()
    total_leads = len(leads)
    com_whats = sum(1 for l in leads if l.get("whatsapp_link"))
    fechados = sum(1 for l in leads if l.get("status") == "Fechado")
    em_negociacao = sum(1 for l in leads if l.get("status") == "Conversando")
    commercial_outcomes = {"Contatado", "Respondeu", "Demonstrou interesse", "Reunião agendada", "Proposta enviada", "Contrato fechado", "Sem interesse"}
    positive_outcomes = {"Respondeu", "Demonstrou interesse", "Reunião agendada", "Proposta enviada", "Contrato fechado"}
    contato_feito = sum(1 for lead in leads if lead.get("commercial_outcome") in commercial_outcomes)
    responderam = sum(1 for lead in leads if lead.get("commercial_outcome") in positive_outcomes)
    interessados = sum(1 for lead in leads if lead.get("commercial_outcome") in {"Demonstrou interesse", "Reunião agendada", "Proposta enviada", "Contrato fechado"})
    propostas = sum(1 for lead in leads if lead.get("commercial_outcome") in {"Proposta enviada", "Contrato fechado"})
    qualificados = sum(1 for l in leads if l.get("faixa_potencial") == "Prioridade")
    descartados = sum(1 for l in leads if l.get("status") == "Descartado")
    novos = sum(1 for l in leads if l.get("status") in ("Novo", None, ""))
    sem_site = sum(
        1 for lead in leads
        if not possui_site_proprio(lead.get("link_inicial"))
        and str(lead.get("site_confidence") or "").upper() in {"CONFIRMADO", "PROVÁVEL"}
    )
    com_site = sum(1 for lead in leads if possui_site_proprio(lead.get("link_inicial")))
    com_email = sum(1 for l in leads if l.get("email"))
    validation_counts = {
        status: sum(1 for lead in leads if str(lead.get("validation_status") or "NÃO VERIFICADO").upper() == status)
        for status in ("CONFIRMADO", "PROVÁVEL", "NÃO VERIFICADO")
    }
    conversion_metrics = calculate_conversion_metrics(leads)
    conversion_rows = []
    dimension_labels = {"niche": "Nicho", "city": "Local", "source": "Origem"}
    for (dimension, value), metrics in conversion_metrics.items():
        conversion_rows.append({
            "dimension": dimension_labels.get(dimension, dimension),
            "value": value,
            **metrics,
        })
    conversion_rows.sort(key=lambda item: (not item["sufficient_sample"], -item["contacted"], item["dimension"], item["value"]))
    for job in discovery_jobs:
        try:
            job["stats"] = json.loads(job.pop("stats_json") or "{}")
        except json.JSONDecodeError:
            job["stats"] = {}

    taxa_sem_site = round((sem_site / total_leads * 100), 1) if total_leads > 0 else 0
    taxa_whats = round((com_whats / total_leads * 100), 1) if total_leads > 0 else 0
    taxa_fechamento = round((fechados / total_leads * 100), 1) if total_leads > 0 else 0
    taxa_resposta = round((responderam / contato_feito * 100), 1) if contato_feito else 0
    taxa_interesse = round((interessados / responderam * 100), 1) if responderam else 0
    taxa_proposta = round((propostas / interessados * 100), 1) if interessados else 0
    taxa_conversao_contato = round((fechados / contato_feito * 100), 1) if contato_feito else 0

    dashboard_data = {
        "total": total_leads,
        "sem_site": sem_site,
        "whatsapp": com_whats,
        "email": com_email,
        "nichos": {},
        "nichos_sem_site": {},
        "nichos_whatsapp": {},
        "regioes": {},
        "status": {"Preparação": 0, "Contato": 0, "Negociação": 0, "Fechado": 0, "Encerrado": 0},
    }
    for lead in leads:
        niche = str(lead.get("nicho") or "Geral").strip().capitalize()
        dashboard_data["nichos"][niche] = dashboard_data["nichos"].get(niche, 0) + 1
        if not possui_site_proprio(lead.get("link_inicial")) and str(lead.get("site_confidence") or "").upper() in {"CONFIRMADO", "PROVÁVEL"}:
            dashboard_data["nichos_sem_site"][niche] = dashboard_data["nichos_sem_site"].get(niche, 0) + 1
        if lead.get("whatsapp_link"):
            dashboard_data["nichos_whatsapp"][niche] = dashboard_data["nichos_whatsapp"].get(niche, 0) + 1
        region = re.split(r"[,\-]", str(lead.get("bairro") or "Não informado"), maxsplit=1)[0].strip()
        if len(region) > 2:
            dashboard_data["regioes"][region] = dashboard_data["regioes"].get(region, 0) + 1
        lead_status = lead.get("status") or "Novo"
        if lead_status == "Novo":
            stage = "Preparação"
        elif lead_status == "Contatado":
            stage = "Contato"
        elif lead_status == "Conversando":
            stage = "Negociação"
        elif lead_status == "Fechado":
            stage = "Fechado"
        else:
            stage = "Encerrado"
        dashboard_data["status"][stage] += 1

    return render_template(
        "estatisticas.html",
        total=total_leads,
        whats=com_whats,
        fechados=fechados,
        em_negociacao=em_negociacao,
        contato_feito=contato_feito,
        responderam=responderam,
        interessados=interessados,
        propostas=propostas,
        qualificados=qualificados,
        descartados=descartados,
        novos=novos,
        sem_site=sem_site,
        com_site=com_site,
        com_email=com_email,
        taxa_sem_site=taxa_sem_site,
        taxa_whats=taxa_whats,
        taxa_fechamento=taxa_fechamento,
        taxa_resposta=taxa_resposta,
        taxa_interesse=taxa_interesse,
        taxa_proposta=taxa_proposta,
        taxa_conversao_contato=taxa_conversao_contato,
        search_runs=load_search_runs(),
        dashboard_data=dashboard_data,
        source_usage=source_usage,
        discovery_jobs=discovery_jobs,
        validation_counts=validation_counts,
        conversion_rows=conversion_rows[:30],
    )

@app.route("/configuracoes", methods=["GET", "POST"])
def configuracoes():
    if request.method == "POST":
        data = load_config()
        nova_configuracao = request.form.to_dict()
        api_key = nova_configuracao.pop("gemini_api_key", "").strip()
        whatsapp_token = nova_configuracao.pop("whatsapp_access_token", "").strip()
        whatsapp_phone_id = nova_configuracao.pop("whatsapp_phone_number_id", "").strip()
        whatsapp_template = nova_configuracao.pop("whatsapp_template_name", "").strip()
        whatsapp_language = nova_configuracao.pop("whatsapp_template_language", "").strip()
        google_places_key = nova_configuracao.pop("google_places_api_key", "").strip()
        score_weights = {}
        for key, default in DEFAULT_WEIGHTS.items():
            raw_value = nova_configuracao.pop(f"score_{key}", str(default))
            try:
                score_weights[key] = max(0, int(raw_value))
            except (TypeError, ValueError):
                score_weights[key] = default
        if sum(score_weights.values()) == 100:
            data["lead_score_weights"] = score_weights
        data.update(nova_configuracao)
        if api_key:
            persist_secret("GEMINI_API_KEY", api_key)
        if google_places_key:
            persist_secret("GOOGLE_PLACES_API_KEY", google_places_key)
        for secret_name, secret_value in (
            ("WHATSAPP_ACCESS_TOKEN", whatsapp_token),
            ("WHATSAPP_PHONE_NUMBER_ID", whatsapp_phone_id),
            ("WHATSAPP_TEMPLATE_NAME", whatsapp_template),
            ("WHATSAPP_TEMPLATE_LANGUAGE", whatsapp_language),
        ):
            if secret_value:
                persist_secret(secret_name, secret_value)
        data["headless"] = "headless" in nova_configuracao
        data["enable_modular_discovery"] = "enable_modular_discovery" in nova_configuracao
        data["enable_openstreetmap"] = "enable_openstreetmap" in nova_configuracao
        save_config(data)
        return render_template("configuracoes.html", config=config_publica(data), success=True)
    return render_template("configuracoes.html", config=config_publica(load_config()), success=False)

@app.route("/api/update_status", methods=["POST"])
def update_status():
    data = request.get_json(silent=True) or {}
    place_id = data.get("place_id", "")
    status = normalizar_status_pipeline(data.get("status", ""))
    if not place_id or status not in {"Novo", "Contatado", "Conversando", "Fechado", "Não fechado", "Descartado"}:
        return jsonify({"success": False, "error": "Status ou lead inválido"}), 400
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE leads SET status = ? WHERE place_id = ?", (status, place_id))
    if c.rowcount > 0:
        c.execute(
            "INSERT INTO lead_interactions (place_id, interaction_type, channel, content, sentiment) VALUES (?, 'mudanca_etapa', 'Sistema', ?, 'neutro')",
            (place_id, f"Etapa alterada para {status}"),
        )
    conn.commit()
    atualizado = c.rowcount > 0
    conn.close()
    if not atualizado:
        return jsonify({"success": False, "error": "Lead não encontrado"}), 404
    return jsonify({"success": True, "status": status, "removed_from_pipeline": status == "Descartado"})


@app.route("/api/leads/<path:place_id>/outcome", methods=["POST"])
def update_commercial_outcome(place_id):
    payload = request.get_json(silent=True) or {}
    outcome = normalizar_texto(payload.get("outcome", ""), 60)
    if outcome not in VALID_OUTCOMES:
        return jsonify({"success": False, "error": "Resultado comercial inválido."}), 400
    status_map = {
        "Contatado": "Contatado", "Respondeu": "Conversando", "Demonstrou interesse": "Conversando",
        "Reunião agendada": "Conversando", "Proposta enviada": "Conversando",
        "Contrato fechado": "Fechado", "Sem interesse": "Não fechado",
    }
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.execute(
            "UPDATE leads SET commercial_outcome = ?, status = ? WHERE place_id = ?",
            (outcome, status_map[outcome], place_id),
        )
        if not cursor.rowcount:
            return jsonify({"success": False, "error": "Lead não encontrado."}), 404
        conn.execute(
            """INSERT INTO lead_interactions
               (place_id, interaction_type, channel, content, sentiment)
               VALUES (?, 'resultado_comercial', 'Sistema', ?, 'neutro')""",
            (place_id, f"Resultado comercial registrado: {outcome}"),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"success": True, "outcome": outcome, "status": status_map[outcome]})

@app.route("/export/csv")
def export_csv():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM leads", conn)
    conn.close()
    csv_data = df.to_csv(index=False)
    return Response(csv_data, mimetype="text/csv", headers={"Content-disposition": "attachment; filename=meu_crm_completo.csv"})

@app.route("/dossie/<place_id>")
def dossie(place_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM leads WHERE place_id = ?", (place_id,))
    lead = c.fetchone()
    conn.close()
    if not lead: return "Lead nao encontrado", 404
    lead_original = dict(lead)
    instagram_url = extrair_destino_externo(lead_original.get("instagram"))
    linkedin_url = extrair_destino_externo(lead_original.get("linkedin"))
    site_url = extrair_destino_externo(lead_original.get("link_inicial"))
    lead = {campo: texto_html_seguro(valor) for campo, valor in lead_original.items()}
    instagram_link = f"<a href='{texto_html_seguro(instagram_url)}' class='text-blue-500 underline' target='_blank' rel='noopener noreferrer'>Acessar Perfil</a>" if instagram_url else "<span class='text-orange-500'>Nao localizado</span>"
    linkedin_link = f"<a href='{texto_html_seguro(linkedin_url)}' class='text-blue-500 underline' target='_blank' rel='noopener noreferrer'>Acessar Perfil</a>" if linkedin_url else "Nao localizado"
    site_link = f"<a href='{texto_html_seguro(site_url)}' class='text-blue-500 underline' target='_blank' rel='noopener noreferrer'>Visualizar</a>" if site_url else "<span class='text-red-500 font-bold'>Nenhum link cadastrado no Google!</span>"
    email_info = lead["email"] or "<span class='text-red-500 font-bold'>Vazamento: Nenhum e-mail de contato encontrado.</span>"
    
    analise_ia = lead['analise_ia'] if 'analise_ia' in lead.keys() and lead['analise_ia'] else 'N/A'
    estrategia_ia = lead['estrategia_ia'] if 'estrategia_ia' in lead.keys() and lead['estrategia_ia'] else 'N/A'
    copy_texto = lead['copy_texto'] if 'copy_texto' in lead.keys() and lead['copy_texto'] else 'N/A'
    
    diagnostico_site = (
        "A empresa já possui um site cadastrado no Google. A oportunidade é melhorar como ele apresenta serviços e converte visitas em contatos."
        if possui_site_proprio(lead_original.get("link_inicial"))
        else "A empresa ainda não possui um site institucional próprio cadastrado no Google, o que pode dificultar a conversão de pessoas que já a encontram online."
    )
    html = f"""<!DOCTYPE html><html lang="pt-BR" class="dark"><head><meta charset="UTF-8"><title>Auditoria Digital - {lead['nome']}</title><script src="https://cdn.tailwindcss.com"></script><link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800;900&display=swap" rel="stylesheet"><style>body{{font-family:'Plus Jakarta Sans',sans-serif;}}</style></head>
    <body class="bg-[#090a0f] text-[#f0f6fc] p-6 md:p-10 antialiased">
    <div class="max-w-3xl mx-auto bg-[#12151c] p-8 md:p-10 rounded-2xl shadow-2xl border border-[#222733]">
    <div class="flex justify-between items-start mb-6 pb-6 border-b border-[#222733]"><div><h1 class="text-2xl md:text-3xl font-black mb-1 text-white">Auditoria de Presença Digital</h1><h2 class="text-lg text-slate-300 font-semibold">{lead['nome']}</h2></div><div class="text-right"><span class="inline-block bg-[#161b26] border border-[#262c3a] text-slate-300 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider">{lead['nicho']}</span></div></div>
    <p class="text-slate-400 text-sm mb-8">Análise de presença comercial e captação na região de <strong class="text-white">{lead['bairro']}</strong>.</p>
    <div class="grid grid-cols-2 gap-4 mb-8"><div class="bg-[#090d14] border border-[#222733] p-5 rounded-xl text-center"><span class="block text-3xl font-black text-white mb-1">{lead['nota']} ★</span><span class="text-[11px] font-bold text-slate-500 uppercase tracking-widest">Nota no Google Maps</span></div><div class="bg-[#090d14] border border-[#222733] p-5 rounded-xl text-center"><span class="block text-3xl font-black text-white mb-1">{lead['avaliacoes']}</span><span class="text-[11px] font-bold text-slate-500 uppercase tracking-widest">Avaliações Públicas</span></div></div>
    <div class="mb-8"><h3 class="text-sm font-bold text-white uppercase tracking-wider mb-4 border-b border-[#222733] pb-2">Canais de Contato Detectados</h3><ul class="space-y-2.5 text-xs text-slate-300"><li><strong class="text-slate-400">Telefone / WhatsApp:</strong> {lead['telefone'] or 'Não disponível'}</li><li><strong class="text-slate-400">E-mail:</strong> {email_info}</li><li><strong class="text-slate-400">Instagram:</strong> {instagram_link}</li><li><strong class="text-slate-400">LinkedIn:</strong> {linkedin_link}</li><li><strong class="text-slate-400">Website Oficial:</strong> {site_link}</li></ul></div>
    
    <div class="mb-8 bg-[#090d14] rounded-xl p-5 border border-[#222733]">
        <h3 class="text-sm font-black text-white uppercase tracking-wider mb-4 border-b border-[#222733] pb-2">Diagnóstico Comercial & Abordagem</h3>
        <div class="mb-4">
            <h4 class="font-bold text-slate-400 text-xs uppercase mb-1">1. Diagnóstico do Negócio</h4>
            <p class="text-slate-200 text-xs bg-[#12151c] p-3 rounded-lg border border-[#222733]">{analise_ia}</p>
        </div>
        <div class="mb-4">
            <h4 class="font-bold text-slate-400 text-xs uppercase mb-1">2. Ângulo de Venda Recomendado</h4>
            <p class="text-slate-200 text-xs bg-[#12151c] p-3 rounded-lg border border-[#222733]">{estrategia_ia}</p>
        </div>
        <div>
            <h4 class="font-bold text-slate-400 text-xs uppercase mb-1">3. Abordagem WhatsApp</h4>
            <div class="text-slate-200 bg-[#12151c] p-4 rounded-lg border border-[#222733] text-xs shadow-inner whitespace-pre-wrap">{copy_texto}</div>
        </div>
    </div>
    
    <div class="bg-[#161b26] border border-[#262c3a] p-5 rounded-xl mb-4"><h3 class="text-sm font-bold text-white mb-2">Diagnóstico de Presença</h3><p class="text-xs text-slate-300 leading-relaxed mb-2">{texto_html_seguro(diagnostico_site)}</p><p class="text-xs text-slate-400">Oportunidade para aumentar a taxa de conversão entre quem pesquisa no Google e quem chama no WhatsApp.</p></div>
    <div class="bg-[#12151c] border border-[#222733] p-5 rounded-xl"><h3 class="text-sm font-bold text-white mb-2">Recomendação Comercial</h3><p class="text-xs text-slate-300 leading-relaxed">Desenvolvimento de uma <strong>Landing Page de Alta Conversão</strong> focada em velocidade mobile e contato direto via WhatsApp.</p></div>
    <p class="text-center text-[11px] text-slate-500 mt-8">Relatório emitido via GestãoLead PRO &bull; Antigravity Architecture</p></div></body></html>"""
    return html

import urllib.request
import urllib.parse

def buscar_email_web(nome, bairro):
    busca = f'"{nome}" {bairro} email'
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(busca)
    try:
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            content = resp.read().decode("utf-8", "ignore")
        emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", content)
        emails = [e for e in emails if not e.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4")) and "sentry" not in e and "example" not in e and "wix" not in e and "sitedobem" not in e]
        return emails[0] if emails else ""
    except Exception as e:
        return ""

def is_social_or_directory(url):
    if not url: return False
    url = url.lower()
    domains = ["facebook.com", "instagram.com", "linkedin.com", "linktr.ee", "wa.me", "api.whatsapp", "yelp.", "tripadvisor.", "yellowpages.", "foursquare."]
    return any(d in url for d in domains)

def extrair_destino_externo(url):
    if not url:
        return ""
    url = str(url).strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("google.com"):
        params = urllib.parse.parse_qs(parsed.query)
        url = params.get("url", params.get("q", [url]))[0]
    return url if url.startswith(("http://", "https://")) else ""

def possui_site_proprio(url):
    destino = extrair_destino_externo(url)
    return bool(destino and not is_social_or_directory(destino))


def validar_url_publica(url):
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Endereço de site inválido para auditoria")
    hostname = parsed.hostname.casefold().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise ValueError("Endereço interno bloqueado na auditoria")
    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        }
    except socket.gaierror as error:
        raise ValueError("Não foi possível localizar o domínio do site") from error
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Endereço interno ou reservado bloqueado na auditoria")
    return parsed.geturl()


class _SemRedirecionamentoAutomatico(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def baixar_html_publico(url, timeout=6, max_bytes=400_000):
    current_url = validar_url_publica(url)
    opener = urllib.request.build_opener(_SemRedirecionamentoAutomatico)
    for _ in range(4):
        request_site = urllib.request.Request(
            current_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        try:
            response = opener.open(request_site, timeout=timeout)
        except urllib.error.HTTPError as error:
            if error.code not in {301, 302, 303, 307, 308} or not error.headers.get("Location"):
                raise
            current_url = validar_url_publica(urllib.parse.urljoin(current_url, error.headers["Location"]))
            continue
        with response:
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                raise ValueError("O endereço não retornou uma página HTML")
            return response.read(max_bytes + 1)[:max_bytes].decode("utf-8", "replace")
    raise ValueError("O site excedeu o limite de redirecionamentos")


def assess_site_opportunity(url, title="", description="", context=""):
    destination = extrair_destino_externo(url)
    if not possui_site_proprio(destination):
        return {"status": "Construção de site", "score": 100, "reasons": ["Nenhum site próprio identificado no campo verificado"]}
    if not any((title, description, context)):
        return {"status": "Revisão manual", "score": 35, "reasons": ["Site encontrado, mas sem conteúdo suficiente para auditoria automática"]}
    reasons = []
    if destination.startswith("http://"):
        reasons.append("endereço sem HTTPS")
    if not clean_text(title, 180):
        reasons.append("título da página não identificado")
    if not clean_text(description, 400):
        reasons.append("descrição para mecanismos de busca não identificada")
    page_text = f"{title} {description} {context}".casefold()
    if not any(term in page_text for term in ("contato", "agend", "orçamento", "orcamento", "fale", "contact", "book", "quote")):
        reasons.append("caminho de contato não identificado no conteúdo coletado")
    if len(clean_text(context, 700)) < 40:
        reasons.append("pouca estrutura de conteúdo identificada")
    score = min(90, 25 + len(reasons) * 15)
    return {
        "status": "Site com oportunidade de melhoria" if len(reasons) >= 2 else "Site encontrado — sem sinal claro",
        "score": score,
        "reasons": reasons or ["Nenhuma fragilidade objetiva identificada na coleta automática"],
    }

def texto_html_seguro(valor):
    return str(escape(valor or ""))

def cacar_dados_profundos(context, url, nome="", bairro="", buscar_email_externo=True):
    dados = {
        "email": "", "instagram": "", "facebook": "", "linkedin": "",
        "titulo_site": "", "descricao_site": "", "contexto_site": "",
    }
    
    # Se tem URL, tenta extrair da URL
    if url and not is_social_or_directory(url):
        try:
            req_url = url if url.startswith(("http://", "https://")) else "http://" + url
            content = baixar_html_publico(req_url)
            soup = BeautifulSoup(content, "html.parser")
            dados["titulo_site"] = normalizar_texto(
                soup.title.get_text(" ", strip=True) if soup.title else "", 180
            )
            meta_descricao = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
            dados["descricao_site"] = normalizar_texto(
                meta_descricao.get("content", "") if meta_descricao else "", 400
            )
            titulos = [
                normalizar_texto(tag.get_text(" ", strip=True), 160)
                for tag in soup.find_all(["h1", "h2"])[:8]
            ]
            dados["contexto_site"] = normalizar_texto(
                " | ".join(titulo for titulo in titulos if titulo), 700
            )
                
            emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", content)
            emails = [e for e in emails if not e.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4")) and "sentry" not in e and "example" not in e]
            if emails: dados["email"] = emails[0]
            
            ig = re.search(r"https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_.-]+", content)
            if ig: dados["instagram"] = ig.group(0)
            
            fb = re.search(r"https?://(?:www\.)?facebook\.com/[a-zA-Z0-9_.-]+", content)
            if fb: dados["facebook"] = fb.group(0)
            
            li = re.search(r"https?://(?:www\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_.-]+", content)
            if li: dados["linkedin"] = li.group(0)
            
        except Exception as e:
            print(f"[WORKER] Erro ao buscar HTML de {url}: {e}")
            pass

    if url:
        url_lower = url.lower()
        if "instagram.com" in url_lower: dados["instagram"] = url
        if "facebook.com" in url_lower: dados["facebook"] = url
        if "linkedin.com" in url_lower: dados["linkedin"] = url

    # Se ainda nao tem email (ex: empresa sem site), faz busca web profunda!
    if buscar_email_externo and not dados["email"] and nome:
        print(f"[WORKER] Sem email no site/sem site para {nome}. Buscando na web...")
        dados["email"] = buscar_email_web(nome, bairro)
        
    return dados


def create_search_run(data):
    run_id = uuid.uuid4().hex
    niches = [item.strip() for item in str(data.get("nichos", "")).split(",") if item.strip()]
    locations = [item.strip() for item in str(data.get("bairros", "")).split(",") if item.strip()]
    label_niche = niches[0] if niches else "Pesquisa"
    label_location = locations[0] if locations else "mercado selecionado"
    name = normalizar_texto(data.get("campaign_name", ""), 120) or f"{label_niche} em {label_location}"
    filters = {key: value for key, value in data.items() if key not in {"nichos", "bairros", "campaign_name"}}
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            """INSERT INTO search_runs
               (run_id, name, market, niches_json, locations_json, filters_json, status, stats_json,
                geo_campaign_id, municipality_id)
               VALUES (?, ?, ?, ?, ?, ?, 'running', '{}', ?, ?)""",
            (run_id, name, normalizar_texto(data.get("mercado", "br"), 20),
             json.dumps(niches, ensure_ascii=False), json.dumps(locations, ensure_ascii=False),
             json.dumps(filters, ensure_ascii=False), data.get("geo_campaign_id"), data.get("municipality_id")),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def finish_search_run(run_id, status, stats=None):
    if not run_id:
        return
    conn = sqlite3.connect(DB_NAME)
    try:
        conn.execute(
            "UPDATE search_runs SET status = ?, stats_json = ?, finished_at = CURRENT_TIMESTAMP WHERE run_id = ?",
            (status, json.dumps(stats or {}, ensure_ascii=False), run_id),
        )
        conn.commit()
    finally:
        conn.close()


def load_search_runs(limit=8):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT *, (SELECT COUNT(*) FROM leads WHERE leads.search_run_id = search_runs.run_id) AS lead_count FROM search_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    runs = []
    for row in rows:
        item = dict(row)
        for field_name in ("niches_json", "locations_json", "filters_json", "stats_json"):
            try:
                item[field_name.removesuffix("_json")] = json.loads(item.pop(field_name) or "{}")
            except (TypeError, json.JSONDecodeError):
                item[field_name.removesuffix("_json")] = {}
        runs.append(item)
    return runs


def load_conversion_rows():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(
            """SELECT nicho, bairro, lead_source, commercial_outcome
               FROM leads WHERE trim(coalesce(commercial_outcome, '')) != ''"""
        ).fetchall()]
    finally:
        conn.close()


def modular_discovery_worker(data, config, publish_global=True, cancelled_callback=None):
    job_id = data.get("discovery_job_id", "")
    search_run_id = data.get("search_run_id", "")
    engine = DiscoveryEngine(DB_NAME, config)
    started_at = time.monotonic()
    stats = {
        "encontrados": 0, "novos_resultados": 0, "analisados": 0, "salvos": 0,
        "duplicados": 0, "com_site": 0, "site_sem_oportunidade": 0,
        "telefone_invalido": 0, "sem_whatsapp": 0, "sem_email": 0,
        "nota_baixa": 0, "prioridade": 0, "oportunidade_secundaria": 0,
        "exploracao": 0, "erros": 0, "fontes": {}, "cache_hits": 0,
        "consultas_planejadas": len(data.get("nichos_lista", [])) * len(data.get("bairros_lista", [])),
        "consultas_concluidas": 0, "tentativas_busca": 0,
    }

    def publish(message, running=True):
        stats["tempo_segundos"] = round(time.monotonic() - started_at, 1)
        stats["ignorados"] = sum(stats[key] for key in (
            "duplicados", "com_site", "site_sem_oportunidade", "telefone_invalido",
            "sem_whatsapp", "sem_email", "nota_baixa",
        ))
        stats["taxa_adicao"] = round(stats["salvos"] * 100 / stats["novos_resultados"]) if stats["novos_resultados"] else 0
        if publish_global:
            atualizar_status({
                "rodando": running, "mensagem": message, "leads_salvos": stats["salvos"],
                "metricas": stats.copy(), "search_run_id": search_run_id,
                "discovery_job_id": job_id,
                "cancelamento_solicitado": cancelled(),
            })
        if not running:
            finish_search_run(search_run_id, "cancelled" if cancelled() else "completed", stats)

    def cancelled():
        if cancelled_callback:
            return bool(cancelled_callback())
        return bool(ler_status().get("cancelamento_solicitado"))

    def discovery_progress(engine_stats, message):
        stats["encontrados"] = int(engine_stats.get("candidates") or 0)
        stats["novos_resultados"] = stats["encontrados"]
        stats["cache_hits"] = int(engine_stats.get("cache_hits") or 0)
        stats["tentativas_busca"] = int(engine_stats.get("requests") or 0)
        stats["consultas_concluidas"] = int(engine_stats.get("tasks_completed") or 0)
        publish(message)

    try:
        publish("Iniciando descoberta em múltiplas fontes...")
        candidates = engine.run(job_id, progress=discovery_progress, cancelled=cancelled)
        if cancelled():
            publish("Busca cancelada. Os leads já salvos foram mantidos.", running=False)
            return
        stats["encontrados"] = len(candidates)
        stats["novos_resultados"] = len(candidates)
        existing_phones, existing_names, existing_emails, existing_domains = load_existing_lead_identities()
        conversion_metrics = calculate_conversion_metrics(load_conversion_rows())
        max_leads = max(5, min(100, int(data.get("max_leads", 30))))
        minimum_score = max(0, min(100, int(data.get("min_potencial", 55))))
        region = data.get("mercado", "br")
        for index, candidate in enumerate(candidates):
            if cancelled() or stats["salvos"] >= max_leads:
                break
            stats["analisados"] += 1
            publish(f"Validando empresa {index + 1}/{len(candidates)}: {candidate.get('name', 'sem nome')}...")
            try:
                validation = validate_candidate(
                    candidate, region=region,
                    corroborating_sources=len(set(candidate.get("sources") or [candidate.get("source")])),
                    inspect_site=True,
                )
                if not validation["valid_business"]:
                    engine.update_candidate_validation(job_id, candidate, "rejected", validation)
                    continue
                name = candidate.get("name", "")
                business_address = candidate.get("address") or candidate.get("location") or ""
                location = candidate.get("location") or business_address
                phone_key = re.sub(r"\D", "", validation["phone"]["digits"] or "")[-11:]
                name_key = (normalize(name), normalize(business_address))
                email_key = validation["email"]
                domain_key = website_domain(candidate.get("website"))
                if ((len(phone_key) >= 10 and phone_key in existing_phones) or name_key in existing_names
                        or (email_key and email_key in existing_emails) or (domain_key and domain_key in existing_domains)):
                    stats["duplicados"] += 1
                    engine.update_candidate_validation(job_id, candidate, "duplicate", validation)
                    continue
                site = validation["site"]
                mode = data.get("site_filter_mode", "only_without_site")
                if mode == "only_without_site" and site["present"]:
                    stats["com_site"] += 1
                    engine.update_candidate_validation(job_id, candidate, "site_filtered", validation)
                    continue
                if mode == "without_and_weak" and site["present"] and site["working"] and site["belongs"]:
                    stats["site_sem_oportunidade"] += 1
                    engine.update_candidate_validation(job_id, candidate, "site_filtered", validation)
                    continue
                rating = float(candidate.get("rating") or 0)
                if rating and rating < float(data.get("min_nota", 0) or 0):
                    stats["nota_baixa"] += 1
                    engine.update_candidate_validation(job_id, candidate, "rating_filtered", validation)
                    continue
                if data.get("strict_mobile") and not validation["phone"]["mobile"]:
                    stats["telefone_invalido"] += 1
                    engine.update_candidate_validation(job_id, candidate, "phone_filtered", validation)
                    continue
                if data.get("req_whatsapp") and not validation["phone"]["whatsapp_candidate"]:
                    stats["sem_whatsapp"] += 1
                    engine.update_candidate_validation(job_id, candidate, "whatsapp_filtered", validation)
                    continue
                if data.get("req_email") and not email_key:
                    stats["sem_email"] += 1
                    engine.update_candidate_validation(job_id, candidate, "email_filtered", validation)
                    continue
                source_label = ", ".join(sorted(set(candidate.get("sources") or [candidate.get("source", "desconhecida")])))
                adjustment = performance_adjustment(
                    conversion_metrics, candidate.get("niche"), candidate.get("location"), candidate.get("source")
                )
                scoring_input = {
                    "Nome": name, "Nicho": candidate.get("niche", ""), "Categoria Maps": candidate.get("category", ""),
                    "Bairro": location, "Nota Maps": rating, "Qtd Avaliacoes": candidate.get("reviews", 0),
                    "Telefone": validation["phone"]["digits"], "E-mail Encontrado": email_key,
                    "Link Inicial": candidate.get("website", ""), "Oportunidade do Site": validation["site_opportunity_status"],
                    "Status Validação": validation["validation_status"], "Confiança do Site": validation["site_confidence"],
                    "Quantidade de Fontes": len(set(candidate.get("sources") or [])), "Mercado": region,
                }
                scoring = score_lead(scoring_input, site["present"], config.get("lead_score_weights"), adjustment)
                lead_data = {
                    **scoring_input,
                    "WhatsApp Link": formatar_whatsapp(validation["phone"]["digits"], "") if validation["phone"]["whatsapp_candidate"] else "",
                    "Google Maps": candidate.get("source_url", ""), "Prompt Prototipo": gerar_prompt_prototipo(name, candidate.get("niche", "")),
                    "Potencial": scoring["score"], "Motivo Potencial": scoring["reason"],
                    "Faixa Potencial": classificar_potencial(scoring["score"], minimum_score),
                    "Score Breakdown": scoring, "Score Version": scoring["version"], "Search Run ID": search_run_id,
                    "Origem": source_label, "ID na Fonte": candidate.get("source_id", ""),
                    "Endereço": business_address,
                    "Status Validação": validation["validation_status"], "Motivo Validação": validation["validation_reason"],
                    "Confiança do Site": validation["site_confidence"], "Evidências": validation["evidence"],
                    "Motivos da Oportunidade": [validation["site"]["reason"]],
                }
                place_id = f"{candidate.get('source', 'source')}:{candidate.get('source_id', uuid.uuid4().hex)}"
                if save_lead_db(lead_data, place_id):
                    stats["salvos"] += 1
                    stats["fontes"][source_label] = stats["fontes"].get(source_label, 0) + 1
                    range_key = {"Prioridade": "prioridade", "Oportunidade secundária": "oportunidade_secundaria", "Exploração": "exploracao"}[lead_data["Faixa Potencial"]]
                    stats[range_key] += 1
                    if len(phone_key) >= 10:
                        existing_phones.add(phone_key)
                    existing_names.add(name_key)
                    if email_key:
                        existing_emails.add(email_key)
                    if domain_key:
                        existing_domains.add(domain_key)
                    engine.update_candidate_validation(job_id, candidate, "saved", validation)
                    if data.get("ai_copy"):
                        result = gerar_copy_inteligente(scoring_input, config, region != "br", use_external_ai=False)
                        update_lead_ai(
                            place_id, result.get("mensagem", ""), result.get("analise", ""), result.get("estrategia", ""),
                            formatar_whatsapp(validation["phone"]["digits"], result.get("mensagem", "")) if validation["phone"]["whatsapp_candidate"] else "",
                            result.get("versoes", {}), result.get("inteligencia", {}), result.get("qualidade", {}),
                        )
                else:
                    stats["duplicados"] += 1
                    engine.update_candidate_validation(job_id, candidate, "duplicate", validation)
            except Exception as error:
                stats["erros"] += 1
                engine.update_candidate_validation(job_id, candidate, "error", error=str(error))
        stats["search_run_id"] = search_run_id
        publish(f"{stats['salvos']} lead(s) validados e adicionados por fontes configuradas.", running=False)
        return stats
    except Exception as error:
        stats["erros"] += 1
        stats["search_run_id"] = search_run_id
        stats["error"] = str(error)[:500]
        finish_search_run(search_run_id, "interrupted", {**stats, "error": str(error)[:500]})
        if publish_global:
            atualizar_status({"rodando": False, "mensagem": f"Descoberta interrompida: {str(error)[:180]}", "metricas": stats, "search_run_id": search_run_id, "discovery_job_id": job_id})
        return stats

def extrator_worker(data, config, queue):
    try:
        from playwright.sync_api import sync_playwright  # Import aqui para spawn funcionar
        process = psutil.Process(os.getpid())
        mem_inicial = process.memory_info().rss / (1024 * 1024)
        print(f"[WORKER] Iniciando. Memoria RAM uso atual: {mem_inicial:.2f} MB")
        stats = {
            "encontrados": 0,
            "novos_resultados": 0,
            "consultas_esgotadas": 0,
            "analisados": 0,
            "salvos": 0,
            "duplicados": 0,
            "com_site": 0,
            "site_sem_oportunidade": 0,
            "franquias": 0,
            "fora_regiao": 0,
            "telefone_invalido": 0,
            "nota_baixa": 0,
            "sem_whatsapp": 0,
            "sem_email": 0,
            "prioridade": 0,
            "oportunidade_secundaria": 0,
            "exploracao": 0,
            "erros": 0,
            "tentativas_busca": 0,
        }
        existing_place_ids = load_existing_place_ids()
        existing_phones, existing_names, existing_emails, existing_domains = load_existing_lead_identities()
        search_run_id = data.get("search_run_id", "")
        started_at = time.monotonic()
        max_leads = max(5, min(100, int(data.get("max_leads", 30))))
        analysis_multiplier = 6 if data.get("strict_no_socials") else 4
        max_analyzed = max(80, max_leads * analysis_multiplier)
        max_duration_seconds = 15 * 60
        max_results_per_query = 60

        def search_limit_reason():
            if stats["salvos"] >= max_leads:
                return f"Meta de {max_leads} leads alcançada."
            if stats["analisados"] >= max_analyzed:
                return f"Limite de {max_analyzed} empresas analisadas alcançado."
            if time.monotonic() - started_at >= max_duration_seconds:
                return "Limite de 15 minutos da campanha alcançado."
            return ""

        def publicar_status(mensagem, rodando=True):
            cancelamento_solicitado = ler_status().get("cancelamento_solicitado", False)
            elapsed = round(time.monotonic() - started_at, 1)
            average = elapsed / stats["analisados"] if stats["analisados"] else 0
            remaining = max(0, min(max_analyzed - stats["analisados"], max_leads - stats["salvos"]))
            eta = round(min(max_duration_seconds - elapsed, average * remaining)) if average else None
            stats["tempo_segundos"] = elapsed
            stats["estimativa_segundos"] = max(0, eta) if eta is not None else None
            sites_ignored = stats["com_site"] if data.get("strict_no_socials") and not data.get("include_site_opportunities") else stats["site_sem_oportunidade"]
            stats["ignorados"] = sites_ignored + sum(stats[key] for key in (
                "duplicados", "franquias", "fora_regiao", "telefone_invalido",
                "nota_baixa", "sem_whatsapp", "sem_email",
            ))
            stats["taxa_adicao"] = round(stats["salvos"] * 100 / stats["novos_resultados"]) if stats["novos_resultados"] else 0
            atualizar_status({
                "rodando": rodando,
                "mensagem": mensagem,
                "leads_salvos": stats["salvos"],
                "metricas": stats.copy(),
                "cancelamento_solicitado": cancelamento_solicitado,
                "search_run_id": search_run_id,
            })
            if not rodando:
                finish_search_run(search_run_id, "cancelled" if cancelamento_solicitado else "completed", stats)

        def busca_cancelada():
            if not ler_status().get("cancelamento_solicitado", False):
                return False
            publicar_status("Busca cancelada. Os leads já salvos foram mantidos.", rodando=False)
            return True

        publicar_status("Abrindo navegador...")
        nichos = [n.strip() for n in data["nichos"].split(",") if n.strip()]
        bairros = [b.strip() for b in data["bairros"].split(",") if b.strip()]
        stats["consultas_planejadas"] = len(nichos) * len(bairros)
        stats["consultas_concluidas"] = 0
        print(f"[WORKER] nichos={nichos}, bairros={bairros}")
        is_headless = config.get("headless", True)
        GRANDES_REDES = ["odontocompany","smart fit","smartfit","mcdonalds","boticario","cacau show","subway","sorridents","amorasaude","bluefit","pague menos","raia","drogasil","localiza","unidas","movida"]
        with sync_playwright() as p:
            args = [
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-setuid-sandbox",
                "--disable-software-rasterizer"
            ]
            browser = p.chromium.launch(headless=is_headless, args=args)
            print("[WORKER] Browser aberto.")
            context = browser.new_context(locale="pt-BR", viewport={"width": 1280, "height": 800})
            page = context.new_page()
            if is_headless:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            consent_ok = False

            def coletar_hrefs_maps(termo, local):
                nonlocal consent_ok
                busca = f"{termo} {local}"
                stats["tentativas_busca"] += 1
                publicar_status(f"Buscando '{nicho}' em '{local}' com o termo '{termo}'...")
                try:
                    page.goto(
                        f"https://www.google.com/maps/search/{urllib.parse.quote(busca)}",
                        wait_until="domcontentloaded", timeout=22000,
                    )
                    if not consent_ok:
                        tratar_consentimento_cookies(page)
                        consent_ok = True
                    page.wait_for_timeout(700)
                    try:
                        page.wait_for_selector("a.hfpxzc, a[href*='/maps/place/']", state="attached", timeout=6500)
                    except Exception:
                        pass
                except Exception as error:
                    print(f"[WORKER] Falha na consulta '{busca}': {error}")
                    return []
                painel = page.locator("div[role='feed']").first
                collected = []
                try:
                    for scroll_index in range(14):
                        links = page.locator("a.hfpxzc")
                        if links.count() == 0:
                            links = page.locator("a[href*='/maps/place/']")
                        for link_index in range(min(links.count(), max_results_per_query)):
                            href = links.nth(link_index).get_attribute("href")
                            if href and href not in collected:
                                collected.append(href)
                        unseen_count = sum(
                            1 for href in collected
                            if extrair_id_unico(href) and extrair_id_unico(href) not in existing_place_ids
                        )
                        remaining_target = max_leads - stats["salvos"]
                        if unseen_count >= min(20, max(8, remaining_target * 2)) or len(collected) >= max_results_per_query:
                            break
                        if painel.count() == 0:
                            break
                        previous_count = len(collected)
                        painel.evaluate("node => node.scrollTop = node.scrollHeight")
                        page.wait_for_timeout(random.randint(550, 850))
                        if scroll_index >= 2 and len(collected) == previous_count:
                            page.keyboard.press("End")
                            page.wait_for_timeout(500)
                except Exception as error:
                    print(f"[WORKER] Falha ao rolar resultados: {error}")
                return collected

            for bairro in bairros:
                if search_limit_reason():
                    break
                if busca_cancelada():
                    browser.close()
                    return
                for nicho in nichos:
                    if search_limit_reason():
                        break
                    if busca_cancelada():
                        browser.close()
                        return
                    hrefs = []
                    for termo_busca in search_terms_for_niche(data.get("mercado", "br"), nicho):
                        for href in coletar_hrefs_maps(termo_busca, bairro):
                            if href not in hrefs:
                                hrefs.append(href)
                        unseen = sum(
                            1 for href in hrefs
                            if extrair_id_unico(href) and extrair_id_unico(href) not in existing_place_ids
                        )
                        if unseen >= 5:
                            break

                    if not hrefs:
                        print("[WORKER] Definitivamente nenhum lead encontrado.")
                        stats["consultas_concluidas"] += 1
                        continue
                    stats["encontrados"] += len(hrefs)
                    new_hrefs = []
                    new_discoveries = []
                    for href in hrefs:
                        place_id = extrair_id_unico(href)
                        if not place_id or place_id in existing_place_ids:
                            stats["duplicados"] += 1
                            continue
                        existing_place_ids.add(place_id)
                        new_hrefs.append(href)
                        new_discoveries.append((place_id, nicho, bairro, search_run_id, "discovered"))
                    record_lead_discoveries(new_discoveries)
                    stats["novos_resultados"] += len(new_hrefs)
                    if not new_hrefs:
                        stats["consultas_esgotadas"] += 1
                        stats["consultas_concluidas"] += 1
                        publicar_status(f"'{nicho}' em '{bairro}' já foi explorado. Avançando...")
                        continue
                    for index, href in enumerate(new_hrefs):
                        if search_limit_reason():
                            break
                        if busca_cancelada():
                            browser.close()
                            return
                        place_id = extrair_id_unico(href)
                        try:
                            stats["analisados"] += 1
                            publicar_status(f"Analisando lead novo {index+1}/{len(new_hrefs)}...")
                            page.goto(href, wait_until="domcontentloaded", timeout=12000)
                            try: page.wait_for_selector("h1", timeout=3500)
                            except Exception as e: print("Aviso interno:", e)
                            
                            page.wait_for_timeout(350)
                            
                            # Tenta esperar explicitamente pelo elemento do site caso ele demore mais que o h1
                            try: page.wait_for_selector("a[data-item-id='authority']", timeout=1200)
                            except: pass
                            
                            nome_el = page.locator("h1").first
                            nome = nome_el.inner_text() if nome_el.count() > 0 else page.title().split(" - Google")[0]
                            if not nome or "Google Maps" in nome:
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "invalid_profile")
                                continue
                            if data.get("anti_franchise") and any(rede in nome.lower() for rede in GRANDES_REDES):
                                stats["franquias"] += 1
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "franchise_filtered")
                                continue
                            
                            link_el = page.locator("a[data-item-id='authority'], a[data-tooltip='Abrir website'], a[data-tooltip='Open website']")
                            link_encontrado = link_el.first.get_attribute("href") if link_el.count() > 0 else ""
                            link_encontrado = extrair_destino_externo(link_encontrado)
                            if not link_encontrado:
                                # Fallback robusto via regex de atributo aria-label e links externos
                                fallback = page.locator("a[aria-label*='ebsite'], a[aria-label*='site'], a[href^='http']").all()
                                for f in fallback:
                                    hf = extrair_destino_externo(f.get_attribute("href"))
                                    if hf:
                                        link_encontrado = hf
                                        break
                                        
                            is_real_website = possui_site_proprio(link_encontrado)
                            if data.get("strict_no_socials") and is_real_website and not data.get("include_site_opportunities"):
                                stats["com_site"] += 1
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "site_filtered")
                                print(f"[WORKER] Ignorando {nome} - Possui SITE REAL ({link_encontrado}) e o filtro de EXCLUIR COM SITE esta ativo.")
                                continue

                            tel_el = page.locator("button[data-item-id^='phone']")
                            telefone_raw = tel_el.first.get_attribute("aria-label").replace("Telefone: ", "").strip() if tel_el.count() > 0 else ""
                            numeros_whats = extrair_apenas_numeros(telefone_raw)
                            phone_assessment = assess_phone(numeros_whats, data.get("mercado", "br"))
                            numeros_whats = phone_assessment["digits"] or numeros_whats
                            whatsapp_provavel = phone_assessment["whatsapp_candidate"]
                            phone_key = re.sub(r"\D", "", telefone_raw or "")[-11:]
                            name_key = (normalize(nome), normalize(bairro))
                            if (len(phone_key) >= 10 and phone_key in existing_phones) or name_key in existing_names:
                                stats["duplicados"] += 1
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "duplicate_identity")
                                publicar_status(f"Empresa já existente ignorada: {nome}")
                                continue
                            if data.get("strict_mobile") and not whatsapp_provavel:
                                stats["telefone_invalido"] += 1
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "phone_filtered")
                                continue
                            end_el = page.locator("button[data-item-id='address']")
                            endereco = end_el.first.get_attribute("aria-label").replace("Endereco: ", "").strip() if end_el.count() > 0 else ""
                            if data.get("strict_bairro") and bairro.split("-")[0].strip().lower() not in endereco.lower():
                                stats["fora_regiao"] += 1
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "location_filtered")
                                continue
                            nota_str, avaliacoes_str = extrair_avaliacoes(page)
                            try: nota_float = float(nota_str.replace(",", "."))
                            except ValueError: nota_float = 0.0
                            if nota_float < float(data.get("min_nota", 0)):
                                stats["nota_baixa"] += 1
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "rating_filtered")
                                print(f"[WORKER] Ignorando {nome} - Nota {nota_float} muito baixa")
                                continue
                            if data.get("req_whatsapp") and not whatsapp_provavel:
                                stats["sem_whatsapp"] += 1
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "whatsapp_filtered")
                                print(f"[WORKER] Ignorando {nome} - Sem WhatsApp")
                                continue
                            categoria_el = page.locator("button[jsaction*='pane.rating.category'], span[jsaction*='pane.rating.category'], button[data-item-id='address'] + div button, div.fontBodyMedium button").first
                            categoria_maps = ""
                            try:
                                if categoria_el.count() > 0:
                                    categoria_maps = categoria_el.inner_text().strip()
                            except Exception:
                                pass

                            resumo_el = page.locator("div[aria-label*='Sobre'], div.PYvSYb, div[jslog*='metadata']").first
                            resumo_maps = ""
                            try:
                                if resumo_el.count() > 0:
                                    resumo_maps = resumo_el.inner_text().strip()[:200]
                            except Exception:
                                pass

                            print(f"[WORKER] Iniciando cacador profundo para {nome}...")
                            buscar_email_externo = bool(data.get("req_email") or data.get("mercado", "br") != "br")
                            dados_profundos = cacar_dados_profundos(
                                context, link_encontrado, nome=nome, bairro=bairro,
                                buscar_email_externo=buscar_email_externo,
                            )
                            email_key = normalize_email(dados_profundos["email"])
                            domain_key = website_domain(link_encontrado) if is_real_website else ""
                            if (email_key and email_key in existing_emails) or (domain_key and domain_key in existing_domains):
                                stats["duplicados"] += 1
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "duplicate_identity")
                                publicar_status(f"Empresa já existente por e-mail ou domínio: {nome}")
                                continue
                            if data.get("req_email") and not dados_profundos["email"]:
                                stats["sem_email"] += 1
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "email_filtered")
                                print(f"[WORKER] Ignorando {nome} - Sem e-mail encontrado")
                                continue

                            try:
                                minimo_potencial = max(0, min(100, int(data.get("min_potencial", 55))))
                            except (TypeError, ValueError):
                                minimo_potencial = 55
                            
                            dados_raw = {
                                "Nome": nome, "Nicho": nicho, "Bairro": bairro,
                                "Categoria Maps": categoria_maps or nicho,
                                "Resumo Maps": resumo_maps,
                                "Nota Maps": nota_str, "Qtd Avaliacoes": avaliacoes_str,
                                "Telefone": telefone_raw, "E-mail Encontrado": dados_profundos["email"],
                                "Instagram": dados_profundos["instagram"],
                                "Facebook": dados_profundos["facebook"],
                                "LinkedIn": dados_profundos["linkedin"],
                                "Link Inicial": link_encontrado,
                                "Título do Site": dados_profundos["titulo_site"],
                                "Descrição do Site": dados_profundos["descricao_site"],
                                "Contexto do Site": dados_profundos["contexto_site"],
                            }
                            
                            is_intl = data.get("mercado", "br") != "br"
                            whats_link_final = formatar_whatsapp(numeros_whats, "") if whatsapp_provavel else ""
                            lead_data = {
                                "Nome": nome, "Nicho": nicho, "Bairro": bairro,
                                "Nota Maps": nota_str, "Qtd Avaliacoes": avaliacoes_str,
                                "Telefone": telefone_raw, "WhatsApp Link": whats_link_final,
                                "E-mail Encontrado": dados_profundos["email"],
                                "Instagram": dados_profundos["instagram"],
                                "Facebook": dados_profundos["facebook"],
                                "LinkedIn": dados_profundos["linkedin"],
                                "Link Inicial": link_encontrado,
                                "Google Maps": href,
                                "Prompt Prototipo": gerar_prompt_prototipo(nome, nicho),
                                "Copy Texto": "",
                                "Analise IA": "",
                                "Estrategia IA": "",
                                "Search Run ID": search_run_id,
                                "Título do Site": dados_profundos["titulo_site"],
                                "Descrição do Site": dados_profundos["descricao_site"],
                                "Contexto do Site": dados_profundos["contexto_site"],
                            }
                            site_assessment = assess_site_opportunity(
                                link_encontrado, dados_profundos["titulo_site"],
                                dados_profundos["descricao_site"], dados_profundos["contexto_site"]
                            )
                            if is_real_website:
                                stats["com_site"] += 1
                            if (
                                is_real_website
                                and data.get("strict_no_socials")
                                and data.get("include_site_opportunities")
                                and site_assessment["status"] == "Site encontrado — sem sinal claro"
                            ):
                                stats["site_sem_oportunidade"] += 1
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "site_quality_filtered")
                                publicar_status(f"Site sem oportunidade objetiva ignorado: {nome}")
                                continue
                            lead_data["Oportunidade do Site"] = site_assessment["status"]
                            lead_data["Motivos da Oportunidade"] = site_assessment["reasons"]
                            scoring_input = dict(dados_raw)
                            scoring_input["Oportunidade do Site"] = site_assessment["status"]
                            scoring = calcular_score_lead(
                                scoring_input,
                                tem_site=is_real_website,
                                configured_weights=config.get("lead_score_weights"),
                            )
                            potencial = scoring["score"]
                            motivo_potencial = scoring["reason"]
                            faixa_potencial = classificar_potencial(
                                potencial, minimo_prioridade=minimo_potencial
                            )
                            lead_data.update({
                                "Potencial": potencial,
                                "Motivo Potencial": motivo_potencial,
                                "Faixa Potencial": faixa_potencial,
                                "Score Breakdown": scoring,
                                "Score Version": scoring["version"],
                            })
                            if faixa_potencial == "Prioridade":
                                stats["prioridade"] += 1
                            elif faixa_potencial == "Oportunidade secundária":
                                stats["oportunidade_secundaria"] += 1
                            else:
                                stats["exploracao"] += 1
                            salvo = save_lead_db(lead_data, place_id)
                            if salvo:
                                print(f"[WORKER] Salvo com sucesso: {nome}")
                                if len(phone_key) >= 10:
                                    existing_phones.add(phone_key)
                                existing_names.add(name_key)
                                if email_key:
                                    existing_emails.add(email_key)
                                if domain_key:
                                    existing_domains.add(domain_key)
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "saved")
                                stats["salvos"] += 1
                                publicar_status(f"Lead salvo: {nome}")

                                if data.get("ai_copy"):
                                    publicar_status(f"Gerando mensagem para: {nome}")
                                    resultado_ia = gerar_copy_inteligente(
                                        dados_raw, config, is_intl, use_external_ai=False
                                    )
                                    copy_texto = resultado_ia.get("mensagem", "")
                                    analise_ia = resultado_ia.get("analise", "")
                                    estrategia_ia = resultado_ia.get("estrategia", "")
                                    publicar_status(f"Pitch profissional pronto: {nome}")
                                    whats_link_final = formatar_whatsapp(numeros_whats, copy_texto) if whatsapp_provavel else ""
                                    update_lead_ai(
                                        place_id,
                                        copy_texto,
                                        analise_ia,
                                        estrategia_ia,
                                        whats_link_final,
                                        resultado_ia.get("versoes", {}),
                                        resultado_ia.get("inteligencia", {}),
                                        resultado_ia.get("qualidade", {}),
                                    )
                            else:
                                record_lead_discovery(place_id, nicho, bairro, search_run_id, "duplicate_identity")
                        except Exception as e:
                            stats["erros"] += 1
                            record_lead_discovery(place_id, nicho, bairro, search_run_id, "analysis_error")
                            print(f"[WORKER] Erro no lead {href}: {e}")
                    stats["consultas_concluidas"] += 1
            limit_reason = search_limit_reason()
            stats["tempo_segundos"] = round(time.monotonic() - started_at, 1)
            stats["limite"] = limit_reason
            print("[WORKER] Fechando navegador.")
            mem_final = process.memory_info().rss / (1024 * 1024)
            print(f"[WORKER] Finalizando. Memoria RAM uso final: {mem_final:.2f} MB")
            summary = (
                f"{stats['salvos']} lead(s) adicionado(s) ao CRM, {stats['novos_resultados']} resultado(s) novo(s), "
                f"{stats['duplicados']} já conhecido(s) e {stats['ignorados']} ignorado(s) pelos filtros."
            )
            publicar_status(f"{limit_reason + ' ' if limit_reason else ''}{summary}", rodando=False)
            browser.close()
        print("[WORKER] Finalizado com sucesso.")
    except Exception as e:
        print(f"[WORKER] ERRO FATAL: {e}")
        finish_search_run((data or {}).get("search_run_id", ""), "failed", {"error": str(e)})
        atualizar_status({"rodando": False, "mensagem": "A busca foi interrompida por uma falha interna. Tente novamente.", "leads_salvos": 0})

def _geographic_campaign_status(campaign_id):
    conn = sqlite3.connect(DB_NAME)
    try:
        row = conn.execute("SELECT status FROM geographic_campaigns WHERE campaign_id = ?", (campaign_id,)).fetchone()
        return row[0] if row else "missing"
    finally:
        conn.close()


def _process_geographic_location(campaign, location, config):
    campaign_id = campaign["campaign_id"]
    if _geographic_campaign_status(campaign_id) == "cancelled":
        complete_location(DB_NAME, location["id"], error="Campanha cancelada antes do processamento.")
        return
    label = f"{location['municipality_name']} - {location['uf']}"
    filters = dict(campaign.get("filters") or {})
    data = normalizar_modo_filtro_site({
        **filters, "mercado": "br", "nichos": ", ".join(campaign["niches"]), "bairros": label,
        "nichos_lista": campaign["niches"], "bairros_lista": [label],
        "campaign_name": f"{campaign['name']} · {label}", "geo_campaign_id": campaign_id,
        "municipality_id": location["municipality_id"],
    })
    data["search_run_id"] = create_search_run(data)
    engine = DiscoveryEngine(DB_NAME, config)
    data["discovery_job_id"] = engine.create_job({
        "region": "br", "niches": data["nichos_lista"], "locations": [label],
        "filters": filters, "municipality_id": location["municipality_id"],
    }, data["search_run_id"])
    stats = modular_discovery_worker(
        data, config, publish_global=False,
        cancelled_callback=lambda: _geographic_campaign_status(campaign_id) == "cancelled",
    ) or {}
    complete_location(DB_NAME, location["id"], stats, stats.get("error", ""))


def geographic_campaign_worker(campaign_id):
    try:
        current = campaign_detail(DB_NAME, campaign_id)
        if current["status"] in {"pending", "interrupted"}:
            set_campaign_status(DB_NAME, campaign_id, "running")
        config = load_config()
        while _geographic_campaign_status(campaign_id) == "running":
            campaign = campaign_detail(DB_NAME, campaign_id)
            batch = claim_batch(DB_NAME, campaign_id)
            if not batch:
                finalize_campaign_if_done(DB_NAME, campaign_id)
                break
            with ThreadPoolExecutor(max_workers=campaign["concurrency"]) as executor:
                futures = {executor.submit(_process_geographic_location, campaign, location, config): location for location in batch}
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as error:
                        complete_location(DB_NAME, futures[future]["id"], error=str(error))
                        print("[CAMPANHA GEOGRÁFICA] Falha em município:", error)
            finalize_campaign_if_done(DB_NAME, campaign_id)
    finally:
        with GEO_CAMPAIGN_LOCK:
            ACTIVE_GEO_CAMPAIGNS.discard(campaign_id)


def start_geographic_campaign(campaign_id):
    with GEO_CAMPAIGN_LOCK:
        if campaign_id in ACTIVE_GEO_CAMPAIGNS:
            return False
        ACTIVE_GEO_CAMPAIGNS.add(campaign_id)
    threading.Thread(target=geographic_campaign_worker, args=(campaign_id,), daemon=True).start()
    return True


def _geographic_evidence():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        evidence = [dict(row) for row in conn.execute("""SELECT city, sample_size, verified_count,
            qualified_count, contactable_count FROM target_research_observations""").fetchall()]
        conversions = [dict(row) for row in conn.execute("""SELECT bairro, commercial_outcome FROM leads
            WHERE trim(coalesce(commercial_outcome, '')) != ''""").fetchall()]
        coverage = [dict(row) for row in conn.execute("""SELECT municipality_id,
            CASE WHEN SUM(queries_planned) > 0 THEN SUM(queries_completed) * 100.0 / SUM(queries_planned) ELSE 0 END AS coverage_percent
            FROM geographic_campaign_locations GROUP BY municipality_id""").fetchall()]
        return evidence, conversions, coverage
    finally:
        conn.close()


def _resolve_geographic_payload(payload):
    catalog = load_catalog()
    mode = str(payload.get("mode") or "custom").strip().lower()
    if mode == "smart":
        evidence, conversions, coverage = _geographic_evidence()
        ranked = rank_smart_locations(catalog, evidence, conversions, coverage, payload.get("limit", 20))
        locations = [item for item in ranked]
    else:
        locations = select_municipalities(
            catalog, mode=mode, state_codes=payload.get("states"), regions=payload.get("regions"),
            municipality_ids=payload.get("municipality_ids"), excluded_ids=payload.get("excluded_ids"),
            center_id=payload.get("center_id"), radius_km=payload.get("radius_km"),
        )
        ranked = []
    if payload.get("exclude_researched"):
        conn = sqlite3.connect(DB_NAME)
        try:
            researched = {row[0] for row in conn.execute("""SELECT municipality_id FROM geographic_campaign_locations
                GROUP BY municipality_id HAVING SUM(queries_planned) > 0
                AND SUM(queries_completed) >= SUM(queries_planned)""").fetchall()}
        finally:
            conn.close()
        locations = [item for item in locations if item["id"] not in researched]
    return catalog, locations, ranked


@app.route("/api/geography/catalog")
def geography_catalog():
    catalog = load_catalog()
    municipalities = search_municipalities(
        catalog, request.args.get("q", ""), request.args.get("uf", ""),
        request.args.get("region", ""), request.args.get("limit", 50),
    )
    return jsonify({
        "version": GEOGRAPHY_VERSION, "fetched_at": catalog["fetched_at"],
        "source": catalog["official_source"], "states": catalog["states"], "regions": catalog["regions"],
        "municipalities": municipalities, "total_municipalities": len(catalog["municipalities"]),
    })


@app.route("/api/geography/selection", methods=["POST"])
def geography_selection():
    try:
        _, locations, ranked = _resolve_geographic_payload(request.get_json(silent=True) or {})
        return jsonify({
            "success": True, "count": len(locations), "municipality_ids": [item["id"] for item in locations],
            "preview": [{**item, "label": municipality_label(item)} for item in locations[:200]],
            "ranking": ranked[:50], "truncated": len(locations) > 200,
        })
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400


@app.route("/api/geography/sets", methods=["GET", "POST"])
def geography_sets():
    if request.method == "GET":
        return jsonify({"sets": list_location_sets(DB_NAME)})
    payload = request.get_json(silent=True) or {}
    name = normalizar_texto(payload.get("name"), 100)
    if not name:
        return jsonify({"success": False, "error": "Informe um nome para o conjunto."}), 400
    save_location_set(DB_NAME, name, payload.get("selection") or {})
    return jsonify({"success": True, "sets": list_location_sets(DB_NAME)})


@app.route("/api/geographic-campaigns", methods=["GET", "POST"])
def geographic_campaigns_api():
    if request.method == "GET":
        return jsonify({"campaigns": list_campaigns(DB_NAME)})
    payload = request.get_json(silent=True) or {}
    niches = normalizar_foco_alvos(payload.get("niches"), 12)
    if not niches:
        return jsonify({"success": False, "error": "Selecione pelo menos um nicho."}), 400
    try:
        _, locations, ranked = _resolve_geographic_payload(payload)
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    if not locations:
        message = "Não existem evidências geográficas suficientes para o modo inteligente." if payload.get("mode") == "smart" else "Nenhum município foi selecionado."
        return jsonify({"success": False, "error": message}), 400
    name = normalizar_texto(payload.get("name"), 120) or f"Campanha {niches[0]} · {len(locations)} municípios"
    campaign_id = create_campaign(
        DB_NAME, name, payload.get("mode", "custom"), niches, locations,
        {key: payload.get(key) for key in ("states", "regions", "municipality_ids", "excluded_ids", "center_id", "radius_km", "exclude_researched")},
        payload.get("filters") or {}, payload.get("batch_size", 10), payload.get("concurrency", 1),
    )
    start_geographic_campaign(campaign_id)
    return jsonify({"success": True, "campaign": campaign_detail(DB_NAME, campaign_id), "smart_ranking": ranked}), 202


@app.route("/api/geographic-campaigns/<campaign_id>")
def geographic_campaign_detail_api(campaign_id):
    try:
        return jsonify(campaign_detail(DB_NAME, campaign_id))
    except ValueError as error:
        return jsonify({"error": str(error)}), 404


@app.route("/api/geographic-campaigns/<campaign_id>/<action>", methods=["POST"])
def geographic_campaign_action(campaign_id, action):
    status_by_action = {"pause": "paused", "resume": "running", "cancel": "cancelled"}
    if action not in status_by_action:
        return jsonify({"success": False, "error": "Ação inválida."}), 400
    try:
        set_campaign_status(DB_NAME, campaign_id, status_by_action[action])
        if action == "resume":
            start_geographic_campaign(campaign_id)
        return jsonify({"success": True, "campaign": campaign_detail(DB_NAME, campaign_id)})
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 404


@app.route("/api/status")
def api_status():
    return jsonify(ler_status())


def normalizar_modo_filtro_site(data):
    mode = str(data.get("site_filter_mode") or "").strip()
    if mode not in {"only_without_site", "without_and_weak", "all"}:
        if "strict_no_socials" in data or "include_site_opportunities" in data:
            strict = bool(data.get("strict_no_socials"))
            include_weak = bool(data.get("include_site_opportunities"))
            mode = "without_and_weak" if strict and include_weak else "only_without_site" if strict else "all"
        else:
            mode = "only_without_site"
    data["site_filter_mode"] = mode
    data["strict_no_socials"] = mode != "all"
    data["include_site_opportunities"] = mode == "without_and_weak"
    return data


@app.route("/api/search", methods=["POST"])
def api_search():
    data = normalizar_modo_filtro_site(request.get_json(silent=True) or {})
    if not data.get("nichos") or not data.get("bairros"):
        return jsonify({"success": False, "error": "Nichos ou Bairros vazios"})
    region = str(data.get("mercado") or "br").strip().lower()
    location_resolution = expand_locations(region, data.get("bairros"), per_group=5, max_total=24)
    if not location_resolution["locations"]:
        return jsonify({"success": False, "error": "Nenhuma cidade válida foi informada."}), 400
    data["bairros"] = ", ".join(location_resolution["locations"])
    data["location_expansions"] = location_resolution["expansions"]
    if ler_status_investigacao().get("rodando"):
        return jsonify({"success": False, "error": "Aguarde a investigação de mercado terminar antes de iniciar a busca de leads."}), 409
    try:
        data["max_leads"] = max(5, min(100, int(data.get("max_leads", 30))))
    except (TypeError, ValueError):
        data["max_leads"] = 30
    with SEARCH_LOCK:
        if ler_status().get("rodando"):
            return jsonify({"success": False, "error": "Já existe uma busca em andamento."}), 409
        config = load_config()
        data["search_run_id"] = create_search_run(data)
        data["nichos_lista"] = [item.strip() for item in str(data["nichos"]).split(",") if item.strip()]
        data["bairros_lista"] = [item.strip() for item in str(data["bairros"]).split(",") if item.strip()]
        modular_enabled = bool(os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()) and str(config.get("enable_modular_discovery", "true")).lower() not in {"0", "false", "off", "no"}
        if modular_enabled:
            engine = DiscoveryEngine(DB_NAME, config)
            data["discovery_job_id"] = engine.create_job({
                "region": region,
                "niches": data["nichos_lista"],
                "locations": data["bairros_lista"],
                "filters": {key: value for key, value in data.items() if key not in {"nichos", "bairros"}},
            }, data["search_run_id"])
        engine_label = "fontes oficiais e públicas" if modular_enabled else "Google Maps legado"
        atualizar_status({"rodando": True, "mensagem": f"Busca iniciada com {engine_label}...", "leads_salvos": 0, "cancelamento_solicitado": False, "search_run_id": data["search_run_id"], "discovery_job_id": data.get("discovery_job_id", "")})
        target = modular_discovery_worker if modular_enabled else extrator_worker
        args = (data, config) if modular_enabled else (data, config, None)
        t = threading.Thread(target=target, args=args, daemon=True)
        t.start()
    return jsonify({
        "success": True, "salvos": "Em andamento", "run_id": data["search_run_id"],
        "message": "Busca iniciada em segundo plano.",
        "locations": location_resolution["locations"],
        "location_expansions": location_resolution["expansions"],
        "discovery_engine": "modular" if modular_enabled else "legacy_maps",
        "discovery_job_id": data.get("discovery_job_id", ""),
    })


@app.route("/api/discovery/jobs/<job_id>/resume", methods=["POST"])
def resume_discovery_job(job_id):
    if ler_status().get("rodando"):
        return jsonify({"success": False, "error": "Já existe uma busca em andamento."}), 409
    engine = DiscoveryEngine(DB_NAME, load_config())
    try:
        job = engine.job_status(job_id)
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 404
    if job["status"] not in {"interrupted", "pending"}:
        return jsonify({"success": False, "error": "Esta tarefa não está disponível para retomada."}), 409
    payload = job["payload"]
    data = {
        **(payload.get("filters") or {}),
        "mercado": payload.get("region", "br"),
        "nichos_lista": payload.get("niches", []), "bairros_lista": payload.get("locations", []),
        "nichos": ", ".join(payload.get("niches", [])), "bairros": ", ".join(payload.get("locations", [])),
        "search_run_id": job.get("search_run_id", ""), "discovery_job_id": job_id,
    }
    atualizar_status({"rodando": True, "mensagem": "Retomando a descoberta do último ponto salvo...", "leads_salvos": 0, "cancelamento_solicitado": False, "search_run_id": data["search_run_id"], "discovery_job_id": job_id})
    threading.Thread(target=modular_discovery_worker, args=(data, load_config()), daemon=True).start()
    return jsonify({"success": True, "job_id": job_id, "message": "Tarefa retomada."})

@app.route("/api/cancelar_busca", methods=["POST"])
def cancelar_busca():
    with SEARCH_LOCK:
        status = ler_status()
        if not status.get("rodando"):
            return jsonify({"success": False, "error": "Não há uma busca em andamento."}), 409
        status["cancelamento_solicitado"] = True
        status["mensagem"] = "Cancelamento solicitado. Finalizando o lead atual..."
        atualizar_status(status)
    return jsonify({"success": True, "message": "Cancelamento solicitado."})

def carregar_dados_investigacao(regiao=None):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    where = " WHERE region = ?" if regiao else ""
    params = (regiao,) if regiao else ()
    observations = [dict(row) for row in conn.execute(
        f"""SELECT run_id, region, niche, city, results_count, sample_size, no_site_count,
                   verified_count, own_site_count, confirmed_no_site_count, probable_no_site_count, weak_site_count,
                   site_unknown_count, contactable_count, active_count, mature_count,
                   qualified_count, duplicate_count, discarded_count, sources_json,
                   examples_json, error, created_at
            FROM target_research_observations{where}
            ORDER BY created_at DESC""",
        params,
    ).fetchall()]
    conn.close()
    return observations


def carregar_leads_para_investigacao():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    rows = [dict(row) for row in conn.execute(
        """SELECT nicho, bairro, link_inicial, telefone, whatsapp_link, email, avaliacoes, status,
                  commercial_outcome, lead_source
           FROM leads"""
    ).fetchall()]
    conn.close()
    return rows


def carregar_nichos_recentes(regiao, limite=2):
    conn = sqlite3.connect(DB_NAME)
    rows = conn.execute(
        """SELECT result_json FROM target_research_runs
           WHERE region = ? AND status = 'concluido' AND result_json IS NOT NULL
             AND COALESCE(context_key, '') = ''
           ORDER BY finished_at DESC LIMIT ?""",
        (regiao, limite),
    ).fetchall()
    conn.close()
    niches = []
    for row in rows:
        try:
            niches.extend(json.loads(row[0]).get("nichos", []))
        except (TypeError, json.JSONDecodeError):
            continue
    return niches


def carregar_historico_recomendacoes(regiao, limite=100):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(
            """SELECT run_id, region, niche, niche_key, score, confidence, evidence_hash,
                      metrics_json, sources_json, recommended_at
               FROM niche_recommendation_history
               WHERE region = ? ORDER BY recommended_at DESC LIMIT ?""",
            (regiao, limite),
        ).fetchall()]
    finally:
        conn.close()


def normalizar_foco_alvos(values, limit):
    if isinstance(values, str):
        values = values.split(",")
    result = []
    seen = set()
    for value in values or []:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
        key = normalize(cleaned)
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def chave_contexto_alvos(nichos, cidades):
    if not nichos and not cidades:
        return ""
    return json.dumps({
        "nichos": sorted(normalize(value) for value in nichos),
        "cidades": sorted(normalize(value) for value in cidades),
    }, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def carregar_resultado_investigacao_recente(regiao, context_key="", max_age_days=2, min_sample=12):
    conn = sqlite3.connect(DB_NAME)
    row = conn.execute(
        """SELECT result_json, finished_at FROM target_research_runs
           WHERE region = ? AND status = 'concluido' AND result_json IS NOT NULL
             AND COALESCE(context_key, '') = ?
             AND finished_at >= datetime('now', ?)
           ORDER BY finished_at DESC LIMIT 1""",
        (regiao, context_key, f"-{int(max_age_days)} days"),
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        result = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return None
    if result.get("engine_version") != TARGET_ENGINE_VERSION:
        return None
    investigation = result.setdefault("investigacao", {})
    if int(investigation.get("amostra_nova") or 0) < min_sample:
        return None
    investigation["reutilizado"] = True
    investigation["atualizado_em"] = row[1]
    return result


def worker_investigar_alvos(regiao, run_id, config, focus_niches=None, focus_locations=None, context_key="", sample_target=50, refresh_catalog=False):
    try:
        try:
            max_research_seconds = max(60, min(600, int(config.get("niche_research_max_seconds", 180) or 180)))
        except (TypeError, ValueError):
            max_research_seconds = 180
        observations = carregar_dados_investigacao(regiao)
        catalog_names = [item["name"] for item in MARKETS[regiao]["niches"]]
        discovery_locations = focus_locations or [item["name"] for item in MARKETS[regiao]["cities"][:4]]
        discovery = discover_public_niches(
            DB_NAME, regiao, discovery_locations, catalog_names,
            refresh=refresh_catalog, limit=12, config=config,
        )
        history = carregar_historico_recomendacoes(regiao)
        candidate_pool = build_candidate_pool(
            regiao, discovery["catalog_names"], discovery["crm_names"], discovery["discovered"],
            history=history, limit=8,
        )
        candidate_names = focus_niches or [item["name"] for item in candidate_pool]
        plan = build_research_plan(
            regiao, observations, pair_limit=8,
            focus_niches=focus_niches, focus_locations=focus_locations,
            candidate_niches=candidate_names,
        )
        conn = sqlite3.connect(DB_NAME)
        conn.execute(
            """INSERT INTO target_research_runs (run_id, region, plan_json, status, context_key)
               VALUES (?, ?, ?, 'executando', ?)""",
            (run_id, regiao, json.dumps(plan, ensure_ascii=False), context_key),
        )
        conn.commit()
        conn.close()

        def progress(index, total, message):
            atualizar_status_investigacao({
                "rodando": True, "run_id": run_id, "regiao": regiao,
                "mensagem": message, "etapa_atual": min(int(index) + 1, total), "total_etapas": total,
                "progresso": round(min(index, total) * 100 / max(total, 1)),
            })

        results = research_market_samples(
            DB_NAME, config, plan,
            sample_target=sample_target,
            progress=progress,
            max_seconds=max_research_seconds,
        )
        successful_samples = sum(item.get("verified_count", item.get("sample_size", 0)) for item in results)
        if not successful_samples:
            raise RuntimeError("As fontes consultadas não retornaram empresas verificáveis nesta rodada.")

        conn = sqlite3.connect(DB_NAME)
        for item in results:
            conn.execute(
                """INSERT INTO target_research_observations
                   (run_id, region, niche, city, results_count, sample_size, no_site_count,
                    verified_count, own_site_count, confirmed_no_site_count, probable_no_site_count, weak_site_count,
                    site_unknown_count, contactable_count, active_count, mature_count,
                    qualified_count, duplicate_count, discarded_count, sources_json,
                    examples_json, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, item["region"], item["niche"], item["city"], item["results_count"],
                 item["sample_size"], item["no_site_count"],
                 item.get("verified_count", item["sample_size"]), item.get("own_site_count", 0),
                 item.get("confirmed_no_site_count", 0), item.get("probable_no_site_count", 0), item.get("weak_site_count", 0),
                 item.get("site_unknown_count", item["no_site_count"]), item["contactable_count"],
                 item.get("active_count", item["mature_count"]), item["mature_count"],
                 item.get("qualified_count", 0), item.get("duplicate_count", 0),
                 item.get("discarded_count", 0), json.dumps(item.get("sources", []), ensure_ascii=False),
                 json.dumps(item.get("examples", []), ensure_ascii=False), item.get("error")),
            )
        conn.commit()
        conn.close()
        current_observations = [item for item in carregar_dados_investigacao(regiao) if item.get("run_id") == run_id]
        recommendations = rank_niche_opportunities(
            regiao, current_observations, carregar_leads_para_investigacao(), history,
            sample_target=sample_target, limit=4,
        )
        if not recommendations:
            raise RuntimeError("A pesquisa terminou, mas a amostra foi inconclusiva para recomendar um nicho.")
        cities = []
        for item in recommendations:
            for city in item["cities"]:
                if city not in cities:
                    cities.append(city)
        result = {
            "engine_version": TARGET_ENGINE_VERSION, "niche_engine_version": NICHE_ENGINE_VERSION,
            "run_id": run_id, "mercado": MARKETS[regiao]["label"],
            "nichos": [item["niche"] for item in recommendations], "cidades": cities[:6],
            "recomendacoes_detalhadas": recommendations,
            "pracas": [{
                "nome": city, "regiao": regiao, "nicho_principal": item["niche"],
                "score": round(item["score"]), "confianca": item["confidence"],
                "amostra": item["companies_verified"], "evidencia": item["justification"],
                "necessidade_site": item["site_return_reason"],
            } for item in recommendations for city in item["cities"][:1]],
            "quantidade_nichos": len(recommendations), "quantidade_locais": len(cities[:6]),
            "total_combinacoes": len(plan),
            "contexto": {"nichos_informados": focus_niches or [], "locais_informados": focus_locations or []},
            "investigacao": {
                "amostra_nova": successful_samples, "amostra_alvo_por_nicho": sample_target,
                "combinacoes_estudadas": len(results),
                "fontes": sorted({source for item in results for source in item.get("sources", [])}),
                "candidatos": candidate_pool,
                "catalogo_dinamico": bool(discovery["discovered"]),
                "reutilizado": False,
            },
            "metodologia": "Pesquisa empresas reais, valida presença digital e contatos, mede confiança da amostra e aplica histórico comercial somente quando há volume suficiente.",
        }
        conn = sqlite3.connect(DB_NAME)
        for item in recommendations:
            conn.execute(
                """INSERT INTO niche_recommendation_history
                   (run_id, region, niche, niche_key, score, confidence, evidence_hash, metrics_json, sources_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, regiao, item["niche"], item["niche_key"], item["score"], item["confidence"],
                 item["evidence_hash"], json.dumps(item["metrics"], ensure_ascii=False),
                 json.dumps(item["sources"], ensure_ascii=False)),
            )
        conn.execute(
            """UPDATE target_research_runs
               SET result_json = ?, status = 'concluido', finished_at = CURRENT_TIMESTAMP
               WHERE run_id = ?""",
            (json.dumps(result, ensure_ascii=False), run_id),
        )
        conn.commit()
        conn.close()
        atualizar_status_investigacao({
            "rodando": False, "concluido": True, "run_id": run_id, "regiao": regiao,
            "mensagem": f"Pesquisa concluída com {successful_samples} empresas verificadas.",
            "progresso": 100, "resultado": result,
        })
    except Exception as error:
        print("[ERRO INVESTIGACAO DE ALVOS]:", error)
        conn = sqlite3.connect(DB_NAME)
        conn.execute(
            """UPDATE target_research_runs SET status = 'erro', error = ?, finished_at = CURRENT_TIMESTAMP
               WHERE run_id = ?""",
            (str(error)[:500], run_id),
        )
        conn.commit()
        conn.close()
        atualizar_status_investigacao({
            "rodando": False, "concluido": False, "run_id": run_id, "regiao": regiao,
            "erro": str(error), "mensagem": "A investigação não conseguiu concluir esta rodada.",
        })


@app.route("/api/sugerir_alvos", methods=["GET", "POST"])
def sugerir_alvos():
    try:
        payload = request.get_json(silent=True) or {}
        regiao = (payload.get("regiao") or request.args.get("regiao") or "br").lower()
        focus_niches = normalizar_foco_alvos(payload.get("nichos") or request.args.get("nichos"), 4)
        raw_locations = payload.get("cidades") or request.args.get("cidades")
        location_resolution = expand_locations(regiao, raw_locations, per_group=6, max_total=6)
        focus_locations = normalizar_foco_alvos(location_resolution["locations"], 6)
        context_key = chave_contexto_alvos(focus_niches, focus_locations)
        if request.method == "GET":
            cached_result = carregar_resultado_investigacao_recente(regiao, context_key, max_age_days=30, min_sample=1)
            if cached_result:
                return jsonify(cached_result)
            return jsonify({
                "success": False, "research_required": True, "engine_version": TARGET_ENGINE_VERSION,
                "nichos": [], "cidades": [], "recomendacoes_detalhadas": [],
                "mensagem": "Ainda não existe pesquisa real para este contexto. Inicie uma investigação.",
            })
        config = load_config()
        try:
            sample_target = max(10, min(100, int(payload.get("amostra_alvo") or config.get("niche_sample_target", 50) or 50)))
        except (TypeError, ValueError):
            sample_target = 50
        if not payload.get("atualizar"):
            cached_result = carregar_resultado_investigacao_recente(regiao, context_key)
            if cached_result:
                return jsonify({
                    "success": True, "cached": True, "resultado": cached_result,
                    "mensagem": "Sugestão carregada da investigação recente.",
                })
        if ler_status().get("rodando"):
            return jsonify({"erro": "Aguarde a busca de leads terminar antes de investigar novos mercados."}), 409
        with TARGET_RESEARCH_LOCK:
            current = ler_status_investigacao()
            if current.get("rodando"):
                return jsonify({"erro": "Já existe uma investigação em andamento.", "status": current}), 409
            if regiao not in MARKETS:
                raise ValueError("Mercado inválido.")
            run_id = uuid.uuid4().hex
            atualizar_status_investigacao({
                "rodando": True, "run_id": run_id, "regiao": regiao,
                "context_key": context_key,
                "mensagem": "Montando o plano de investigação...", "progresso": 0,
            })
            thread = threading.Thread(
                target=worker_investigar_alvos,
                args=(regiao, run_id, config, focus_niches, focus_locations, context_key, sample_target, bool(payload.get("atualizar"))),
                daemon=True,
            )
            thread.start()
        return jsonify({
            "success": True, "run_id": run_id, "amostra_alvo": sample_target,
            "mensagem": "Pesquisa real de mercado iniciada.",
        }), 202
    except ValueError as error:
        return jsonify({"erro": str(error)}), 400
    except Exception as error:
        print("[ERRO SUGESTAO DE ALVOS]:", error)
        return jsonify({"erro": "Não foi possível iniciar a investigação agora."}), 500


@app.route("/api/sugerir_alvos/status", methods=["GET"])
def status_sugerir_alvos():
    return jsonify(ler_status_investigacao())

@app.route("/api/limpar_crm", methods=["POST"])
def limpar_crm():
    try:
        backup_path = criar_backup_crm()
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        screenshot_paths = [row[0] for row in c.execute("SELECT screenshot_path FROM preview_versions WHERE screenshot_path IS NOT NULL").fetchall()]
        c.execute("DELETE FROM lead_interactions")
        c.execute("DELETE FROM preview_versions")
        c.execute("DELETE FROM leads")
        conn.commit()
        conn.close()
        preview_root = os.path.abspath(PREVIEW_DIR)
        for screenshot_path in screenshot_paths:
            absolute_path = os.path.abspath(screenshot_path)
            if os.path.commonpath((preview_root, absolute_path)) == preview_root and os.path.isfile(absolute_path):
                os.remove(absolute_path)
        return jsonify({
            "success": True,
            "backup": os.path.basename(backup_path),
            "backup_url": url_for("baixar_backup_crm", filename=os.path.basename(backup_path)),
        })
    except Exception as e:
        return jsonify({"success": False, "error": "Não foi possível criar o backup e limpar a base."}), 500


def criar_backup_crm():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    snapshot_path = os.path.join(BACKUP_DIR, f"crm-{timestamp}.db")
    archive_path = os.path.join(BACKUP_DIR, f"crm-{timestamp}.zip")
    source = sqlite3.connect(DB_NAME)
    snapshot = sqlite3.connect(snapshot_path)
    try:
        source.backup(snapshot)
    finally:
        snapshot.close()
        source.close()
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot_path, "gestao_leads.db")
            if os.path.isdir(PREVIEW_DIR):
                for root, _, filenames in os.walk(PREVIEW_DIR):
                    for filename in filenames:
                        source_path = os.path.join(root, filename)
                        archive_name = os.path.join("generated_previews", os.path.relpath(source_path, PREVIEW_DIR))
                        archive.write(source_path, archive_name)
    finally:
        if os.path.exists(snapshot_path):
            os.remove(snapshot_path)
    archives = sorted(
        (os.path.join(BACKUP_DIR, name) for name in os.listdir(BACKUP_DIR) if name.endswith(".zip")),
        key=os.path.getmtime,
        reverse=True,
    )
    for expired_path in archives[10:]:
        os.remove(expired_path)
    return archive_path


@app.route("/api/backups/<filename>")
def baixar_backup_crm(filename):
    safe_name = os.path.basename(filename)
    if safe_name != filename or not safe_name.endswith(".zip"):
        return "Backup inválido", 400
    backup_path = os.path.abspath(os.path.join(BACKUP_DIR, safe_name))
    backup_root = os.path.abspath(BACKUP_DIR)
    if os.path.commonpath((backup_root, backup_path)) != backup_root or not os.path.isfile(backup_path):
        return "Backup não encontrado", 404
    return send_file(backup_path, as_attachment=True, download_name=safe_name)

@app.route("/api/descartar_com_site", methods=["POST"])
def descartar_com_site():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT place_id, link_inicial, site_title, site_description, site_context,
                      site_opportunity_status
               FROM leads WHERE status != 'Descartado'"""
        ).fetchall()
        place_ids = []
        for row in rows:
            if not possui_site_proprio(row["link_inicial"]):
                continue
            assessment = assess_site_opportunity(
                row["link_inicial"], row["site_title"], row["site_description"], row["site_context"]
            )
            status = row["site_opportunity_status"] or assessment["status"]
            if status == "Site encontrado — sem sinal claro":
                place_ids.append(row["place_id"])
        if place_ids:
            conn.executemany(
                "UPDATE leads SET status = 'Descartado' WHERE place_id = ?",
                [(place_id,) for place_id in place_ids],
            )
            conn.commit()
        return jsonify({"success": True, "descartados": len(place_ids)})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": "Não foi possível classificar os leads"}), 500
    finally:
        conn.close()


def worker_auditar_sites_existentes():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT place_id, nome, link_inicial FROM leads
               WHERE status != 'Descartado' AND link_inicial IS NOT NULL AND link_inicial != ''"""
        ).fetchall()
        rows = [row for row in rows if possui_site_proprio(row["link_inicial"])]
        stats = {"total": len(rows), "analisados": 0, "melhoria": 0, "sem_sinal": 0, "revisao": 0}
        atualizar_status_auditoria_sites({
            "rodando": True, "mensagem": f"Preparando auditoria de {len(rows)} site(s)...", **stats,
        })
        for row in rows:
            dados = cacar_dados_profundos(None, row["link_inicial"])
            assessment = assess_site_opportunity(
                row["link_inicial"], dados["titulo_site"],
                dados["descricao_site"], dados["contexto_site"],
            )
            conn.execute(
                """UPDATE leads SET site_title = ?, site_description = ?, site_context = ?,
                          site_opportunity_status = ?, site_opportunity_reasons = ?
                   WHERE place_id = ?""",
                (dados["titulo_site"], dados["descricao_site"], dados["contexto_site"],
                 assessment["status"], json.dumps(assessment["reasons"], ensure_ascii=False),
                 row["place_id"]),
            )
            conn.commit()
            stats["analisados"] += 1
            if assessment["status"] == "Site com oportunidade de melhoria":
                stats["melhoria"] += 1
            elif assessment["status"] == "Site encontrado — sem sinal claro":
                stats["sem_sinal"] += 1
            else:
                stats["revisao"] += 1
            atualizar_status_auditoria_sites({
                "rodando": True,
                "mensagem": f"Auditando {row['nome']} ({stats['analisados']}/{stats['total']})",
                **stats,
            })
        atualizar_status_auditoria_sites({
            "rodando": False,
            "mensagem": "Auditoria concluída. A fila foi reorganizada.",
            **stats,
        })
    except Exception as error:
        atualizar_status_auditoria_sites({
            "rodando": False, "mensagem": "A auditoria encontrou um erro e foi encerrada.",
            "erro": str(error),
        })
    finally:
        conn.close()


@app.route("/api/auditar_sites", methods=["POST"])
def iniciar_auditoria_sites():
    with SITE_AUDIT_LOCK:
        status = ler_status_auditoria_sites()
        if status.get("rodando"):
            return jsonify({"success": False, "error": "A auditoria de sites já está em andamento."}), 409
        atualizar_status_auditoria_sites({"rodando": True, "mensagem": "Iniciando auditoria dos sites..."})
        thread = threading.Thread(target=worker_auditar_sites_existentes, daemon=True)
        thread.start()
    return jsonify({"success": True})


@app.route("/api/auditar_sites/status")
def status_auditoria_sites():
    return jsonify(ler_status_auditoria_sites())

@app.route("/api/test_gemini", methods=["POST"])
def test_gemini():
    data = request.json or {}
    api_key = data.get("key", "").strip()
    chave_enviada = bool(api_key)
    
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        
    if not api_key:
        return jsonify({"success": False, "error": "Informe uma API Key para testar."})
        
    try:
        _, model_name = first_available_response(api_key, "Diga apenas 'ok'", attempt_limit=2)
        if chave_enviada:
            persist_secret("GEMINI_API_KEY", api_key)
        return jsonify({"success": True, "message": f"Conexão bem-sucedida! Modelo ativo: {model_name}"})
    except Exception as error:
        print(f"[GEMINI] Falha no teste da API: {type(error).__name__}: {str(error)[:240]}")
        return jsonify({"success": False, "error": "A chave não pôde ser validada. Confira a chave, a cota e a conexão do servidor."}), 502

STATUS_REGEN = load_regeneration_status()
REGEN_LOCK = threading.Lock()

def worker_regenerar_copys():
    global STATUS_REGEN
    try:
        config = load_config()
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM leads ORDER BY data_adicao DESC")
        leads = [dict(ix) for ix in c.fetchall()]
        conn.close()

        total = len(leads)
        atualizados = 0
        falhas = 0
        with REGEN_LOCK:
            STATUS_REGEN["rodando"] = True
            STATUS_REGEN["total"] = total
            STATUS_REGEN["processados"] = 0
            STATUS_REGEN["atualizados"] = 0
            STATUS_REGEN["falhas"] = 0
            STATUS_REGEN["concluido"] = False
            STATUS_REGEN["mensagem"] = f"Iniciando regeneração de {total} copys..."
            save_regeneration_status(STATUS_REGEN)

        for idx, lead in enumerate(leads, 1):
            place_id = lead.get("place_id")
            nome = lead.get("nome", "Lead")
            with REGEN_LOCK:
                STATUS_REGEN["processados"] = idx
                STATUS_REGEN["mensagem"] = f"Atualizando ({idx}/{total}): {nome[:30]}"
                save_regeneration_status(STATUS_REGEN)

            dados_raw = {
                "Nome": lead.get("nome", "") or "",
                "Nicho": lead.get("nicho", "") or "",
                "Categoria Maps": lead.get("nicho", "") or "",
                "Bairro": lead.get("bairro", "") or "",
                "Nota Maps": lead.get("nota", "") or "",
                "Qtd Avaliacoes": lead.get("avaliacoes", "0") or "0",
                "Telefone": lead.get("telefone", "") or "",
                "E-mail Encontrado": lead.get("email", "") or "",
                "Instagram": lead.get("instagram", "") or "",
                "Facebook": lead.get("facebook", "") or "",
                "LinkedIn": lead.get("linkedin", "") or "",
                "Link Inicial": lead.get("link_inicial", "") or "",
                "Google Maps": lead.get("google_maps", "") or "",
                "Prompt Prototipo": lead.get("prompt_design", "") or "",
            }

            tel = extrair_apenas_numeros(lead.get("telefone", ""))
            is_intl = bool(tel and not tel.startswith("55"))
            if not is_intl:
                local = (lead.get("bairro", "") or "").lower()
                intl_kws = ["usa", "fl", "ny", "tx", "ca", "london", "uk", "portugal", "lisbon", "spain", "madrid", "united states"]
                is_intl = any(k in local for k in intl_kws)

            try:
                res_ia = gerar_copy_inteligente(dados_raw, config, is_intl=is_intl)
                c_texto = res_ia.get("mensagem", "")
                a_ia = res_ia.get("analise", "")
                e_ia = res_ia.get("estrategia", "")
                v_pitch = res_ia.get("versoes", {})

                w_link = formatar_whatsapp(tel, c_texto) if eh_celular_valido(tel) else ""

                update_lead_ai(
                    place_id,
                    c_texto,
                    a_ia,
                    e_ia,
                    w_link,
                    v_pitch,
                    res_ia.get("inteligencia", {}),
                    res_ia.get("qualidade", {}),
                )
                atualizados += 1
            except Exception as e:
                falhas += 1
                print(f"[REGEN] Erro no lead {nome}: {e}")
            with REGEN_LOCK:
                STATUS_REGEN["atualizados"] = atualizados
                STATUS_REGEN["falhas"] = falhas
                save_regeneration_status(STATUS_REGEN)

            time.sleep(0.8)

        with REGEN_LOCK:
            STATUS_REGEN["rodando"] = False
            STATUS_REGEN["concluido"] = True
            STATUS_REGEN["atualizados"] = atualizados
            STATUS_REGEN["falhas"] = falhas
            if falhas:
                STATUS_REGEN["mensagem"] = f"Regeneração concluída: {atualizados} atualizadas e {falhas} com falha."
            else:
                STATUS_REGEN["mensagem"] = f"Todas as {atualizados} copys foram atualizadas com sucesso."
            save_regeneration_status(STATUS_REGEN)
    except Exception as e:
        with REGEN_LOCK:
            STATUS_REGEN["rodando"] = False
            STATUS_REGEN["mensagem"] = f"Erro na regeneração: {e}"
            STATUS_REGEN["concluido"] = False
            save_regeneration_status(STATUS_REGEN)

@app.route("/api/regenerar_copys", methods=["POST"])
def api_regenerar_copys():
    global STATUS_REGEN
    with REGEN_LOCK:
        STATUS_REGEN = load_regeneration_status()
        if STATUS_REGEN["rodando"]:
            return jsonify({"success": False, "error": "Já existe uma regeneração em andamento."}), 409
        t = threading.Thread(target=worker_regenerar_copys, daemon=True)
        t.start()
    return jsonify({"success": True, "message": "Regeneração de copys iniciada em segundo plano."})

@app.route("/api/status_regenerar_copys", methods=["GET"])
def api_status_regenerar_copys():
    global STATUS_REGEN
    with REGEN_LOCK:
        STATUS_REGEN = load_regeneration_status()
        return jsonify(dict(STATUS_REGEN))


def remover_whatsapps_invalidos_existentes():
    conn = sqlite3.connect(DB_NAME)
    try:
        rows = conn.execute(
            "SELECT place_id, telefone FROM leads WHERE trim(coalesce(whatsapp_link, '')) != ''"
        ).fetchall()
        invalid_ids = [
            place_id for place_id, phone in rows
            if not eh_celular_valido(extrair_apenas_numeros(phone))
        ]
        if invalid_ids:
            conn.executemany("UPDATE leads SET whatsapp_link = '' WHERE place_id = ?", [(place_id,) for place_id in invalid_ids])
            conn.commit()
        return len(invalid_ids)
    finally:
        conn.close()


remover_whatsapps_invalidos_existentes()


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)










