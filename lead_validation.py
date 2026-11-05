import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from contact_quality import assess_phone, normalize_email, website_domain
from target_intelligence import normalize


SOCIAL_OR_DIRECTORY = ("instagram.com", "facebook.com", "linkedin.com", "linktr.ee", "wa.me", "yelp.", "tripadvisor.")


def _safe_public_url(url):
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror:
        return False
    blocked = ("127.", "10.", "192.168.", "169.254.", "::1", "fc", "fd")
    return bool(addresses) and not any(address.startswith(blocked) or address.startswith("172.") and 16 <= int(address.split(".")[1]) <= 31 for address in addresses)


def inspect_website(url, business_name, timeout=8):
    url = str(url or "").strip()
    if not url:
        return {"present": False, "status": "ausente", "working": False, "belongs": False, "reason": "Nenhum site informado pelas fontes consultadas."}
    if any(domain in url.casefold() for domain in SOCIAL_OR_DIRECTORY):
        return {"present": False, "status": "rede_social_ou_diretorio", "working": True, "belongs": False, "reason": "O endereço encontrado é rede social ou diretório, não site próprio."}
    if not _safe_public_url(url):
        return {"present": True, "status": "nao_verificado", "working": False, "belongs": False, "reason": "O endereço não pôde ser validado com segurança."}
    request = urllib.request.Request(url, headers={"User-Agent": "GestaoLead/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
            body = response.read(160000).decode("utf-8", errors="ignore") if "text/html" in content_type else ""
            title_match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.I | re.S)
            title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    except (urllib.error.URLError, TimeoutError, ValueError):
        return {"present": True, "status": "inacessivel", "working": False, "belongs": False, "reason": "O domínio foi informado, mas não respondeu durante a verificação."}
    business_tokens = {token for token in normalize(business_name).split() if len(token) >= 4}
    site_tokens = set(normalize(f"{website_domain(final_url)} {title}").split())
    belongs = bool(business_tokens & site_tokens)
    return {
        "present": True, "status": "funcionando" if belongs else "pertencimento_incerto",
        "working": True, "belongs": belongs, "final_url": final_url, "title": title,
        "reason": "Site ativo com sinais de pertencimento à empresa." if belongs else "Site ativo, mas o pertencimento precisa de revisão manual.",
    }


def validate_candidate(candidate, region="br", corroborating_sources=1, inspect_site=True):
    name = str(candidate.get("name") or "").strip()
    address = str(candidate.get("address") or candidate.get("location") or "").strip()
    status = str(candidate.get("business_status") or "").upper()
    phone = assess_phone(candidate.get("phone"), region)
    email = normalize_email(candidate.get("email"))
    website = inspect_website(candidate.get("website"), name) if inspect_site else {"present": bool(candidate.get("website")), "status": "nao_verificado", "working": False, "belongs": False, "reason": "Site ainda não verificado."}
    activity_signals = []
    if int(candidate.get("reviews") or 0) > 0:
        activity_signals.append(f"{int(candidate.get('reviews') or 0)} avaliações públicas")
    if float(candidate.get("rating") or 0) > 0:
        activity_signals.append(f"nota {float(candidate.get('rating')):.1f}")
    if phone["valid"] or email:
        activity_signals.append("canal comercial público")
    if status in {"CLOSED_PERMANENTLY", "CLOSED"} or not name:
        validation_status = "NÃO VERIFICADO"
        valid_business = False
        reason = "Empresa sem nome válido ou marcada como encerrada na fonte."
    elif address and activity_signals and corroborating_sources >= 2:
        validation_status = "CONFIRMADO"
        valid_business = True
        reason = "Empresa encontrada em mais de uma fonte, com endereço e evidência pública de atividade."
    elif address and (activity_signals or corroborating_sources >= 2):
        validation_status = "PROVÁVEL"
        valid_business = True
        reason = "Empresa possui localização e pelo menos um sinal público de atividade."
    else:
        validation_status = "NÃO VERIFICADO"
        valid_business = bool(name and address)
        reason = "A fonte retornou a empresa, mas faltam sinais suficientes de atividade atual."
    if not website["present"]:
        site_confidence = "PROVÁVEL" if corroborating_sources >= 2 else "NÃO VERIFICADO"
        opportunity = "Construção de site"
    elif website["working"] and website["belongs"]:
        site_confidence = "CONFIRMADO"
        opportunity = "Site encontrado — sem sinal claro"
    else:
        site_confidence = "PROVÁVEL"
        opportunity = "Site com oportunidade de melhoria"
    evidence = [
        {"type": "existencia", "value": reason, "source": candidate.get("source"), "confidence": validation_status, "source_url": candidate.get("source_url", "")},
        {"type": "site", "value": website["reason"], "source": candidate.get("source"), "confidence": site_confidence, "source_url": candidate.get("source_url", "")},
    ]
    if activity_signals:
        evidence.append({"type": "atividade", "value": ", ".join(activity_signals), "source": candidate.get("source"), "confidence": "CONFIRMADO", "source_url": candidate.get("source_url", "")})
    for record in candidate.get("source_records") or []:
        evidence.append({
            "type": "origem",
            "value": f"Registro localizado na fonte {record.get('source')}.",
            "source": record.get("source"),
            "confidence": "CONFIRMADO",
            "source_url": record.get("source_url", ""),
        })
    return {
        "valid_business": valid_business, "validation_status": validation_status,
        "validation_reason": reason, "site_confidence": site_confidence,
        "site": website, "site_opportunity_status": opportunity,
        "phone": phone, "email": email, "activity_signals": activity_signals,
        "evidence": evidence,
    }
