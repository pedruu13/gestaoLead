import re
import urllib.parse


BRAZIL_DDDS = {
    "11", "12", "13", "14", "15", "16", "17", "18", "19",
    "21", "22", "24", "27", "28", "31", "32", "33", "34", "35", "37", "38",
    "41", "42", "43", "44", "45", "46", "47", "48", "49", "51", "53", "54", "55",
    "61", "62", "63", "64", "65", "66", "67", "68", "69", "71", "73", "74", "75", "77",
    "79", "81", "82", "83", "84", "85", "86", "87", "88", "89", "91", "92", "93", "94",
    "95", "96", "97", "98", "99",
}


def digits_only(value):
    return re.sub(r"\D", "", str(value or ""))


def _looks_fake(digits):
    local = digits[-9:]
    if len(set(local)) < 3:
        return True
    return any(sequence in local for sequence in ("12345678", "23456789", "98765432", "87654321"))


def assess_phone(value, region="br"):
    digits = digits_only(value)
    result = {
        "digits": digits,
        "valid": False,
        "mobile": False,
        "whatsapp_candidate": False,
        "kind": "inválido",
        "confidence": 0,
        "reason": "Número ausente ou fora do formato esperado.",
    }
    if not digits or _looks_fake(digits):
        result["reason"] = "Número ausente, repetido ou com sequência artificial."
        return result

    if region == "br":
        national = digits[2:] if digits.startswith("55") else digits
        if len(national) not in {10, 11} or national[:2] not in BRAZIL_DDDS:
            result["reason"] = "DDD ou quantidade de dígitos inválida para o Brasil."
            return result
        mobile = len(national) == 11 and national[2] == "9"
        result.update({
            "digits": f"55{national}", "valid": True, "mobile": mobile,
            "whatsapp_candidate": mobile, "kind": "celular provável" if mobile else "telefone fixo",
            "confidence": 85 if mobile else 70,
            "reason": "Formato de celular brasileiro compatível com WhatsApp; a conta só é confirmada pela API oficial." if mobile else "Formato brasileiro válido, mas identificado como linha fixa.",
        })
        return result

    if region == "us":
        national = digits[1:] if len(digits) == 11 and digits.startswith("1") else digits
        if len(national) != 10 or national[0] in "01" or national[3] in "01":
            result["reason"] = "Número fora do padrão NANP dos Estados Unidos."
            return result
        result.update({
            "digits": f"1{national}", "valid": True, "mobile": True,
            "whatsapp_candidate": True, "kind": "telefone compatível",
            "confidence": 60,
            "reason": "Formato norte-americano plausível; não é possível distinguir móvel de fixo sem consulta externa.",
        })
        return result

    if 8 <= len(digits) <= 15:
        result.update({
            "valid": True, "mobile": True, "whatsapp_candidate": True,
            "kind": "telefone internacional compatível", "confidence": 50,
            "reason": "Formato internacional plausível; a existência da conta depende de confirmação pela API oficial.",
        })
    return result


def normalize_email(value):
    email = str(value or "").strip().casefold()
    return email if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) else ""


def website_domain(value):
    url = str(value or "").strip()
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
    domain = (parsed.hostname or "").casefold()
    return domain.removeprefix("www.")
