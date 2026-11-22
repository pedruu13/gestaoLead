import re
import unicodedata
import urllib.parse


BRAZIL_DDDS = {
    "11", "12", "13", "14", "15", "16", "17", "18", "19",
    "21", "22", "24", "27", "28", "31", "32", "33", "34", "35", "37", "38",
    "41", "42", "43", "44", "45", "46", "47", "48", "49", "51", "53", "54", "55",
    "61", "62", "63", "64", "65", "66", "67", "68", "69", "71", "73", "74", "75", "77",
    "79", "81", "82", "83", "84", "85", "86", "87", "88", "89", "91", "92", "93", "94",
    "95", "96", "97", "98", "99",
}

BRAZIL_STATE_DDDS = {
    "SP": {"11", "12", "13", "14", "15", "16", "17", "18", "19"},
    "RJ": {"21", "22", "24"},
    "ES": {"27", "28"},
    "MG": {"31", "32", "33", "34", "35", "37", "38"},
    "PR": {"41", "42", "43", "44", "45", "46"},
    "SC": {"47", "48", "49"},
    "RS": {"51", "53", "54", "55"},
    "DF": {"61"},
    "GO": {"62", "64"},
    "TO": {"63"},
    "MT": {"65", "66"},
    "MS": {"67"},
    "AC": {"68"},
    "RO": {"69"},
    "BA": {"71", "73", "74", "75", "77"},
    "SE": {"79"},
    "PE": {"81", "87"},
    "AL": {"82"},
    "PB": {"83"},
    "RN": {"84"},
    "CE": {"85", "88"},
    "PI": {"86", "89"},
    "MA": {"98", "99"},
    "PA": {"91", "93", "94"},
    "AP": {"96"},
    "AM": {"92", "97"},
    "RR": {"95"},
}

BRAZIL_CITY_SPECIFIC_DDDS = {
    "sao paulo": {"11"}, "guarulhos": {"11"}, "osasco": {"11"}, "santo andre": {"11"},
    "sao bernardo": {"11"}, "sao caetano": {"11"}, "diadema": {"11"}, "barueri": {"11"},
    "alphaville": {"11"}, "moema": {"11"}, "tatuape": {"11"}, "pinheiros": {"11"}, "santana": {"11"},
    "vila mariana": {"11"}, "itaquera": {"11"}, "sao miguel": {"11"},
    "campinas": {"19"}, "americana": {"19"}, "indaiatuba": {"19"}, "limeira": {"19"},
    "piracicaba": {"19"}, "santa barbara": {"19"}, "sumare": {"19"}, "hortolandia": {"19"},
    "paulinia": {"19"}, "valinhos": {"19"}, "vinhedo": {"19"}, "rio claro": {"19"},
    "sao jose dos campos": {"12"}, "taubate": {"12"}, "jacarei": {"12"},
    "santos": {"13"}, "sao vicente": {"13"}, "praia grande": {"13"}, "guaruja": {"13"},
    "bauru": {"14"}, "marilia": {"14"}, "jau": {"14"}, "botucatu": {"14"},
    "sorocaba": {"15"}, "itu": {"15"}, "salto": {"15"}, "votorantim": {"15"},
    "ribeirao preto": {"16"}, "franca": {"16"}, "araraquara": {"16"}, "sao carlos": {"16"},
    "sao jose do rio preto": {"17"}, "barretos": {"17"}, "catanduva": {"17"},
    "presidente prudente": {"18"}, "aracatuba": {"18"},
    "belo horizonte": {"31"}, "barreiro": {"31"}, "venda nova": {"31"}, "savassi": {"31"},
    "contagem": {"31"}, "betim": {"31"}, "nova lima": {"31"}, "santa luzia": {"31"},
    "sabara": {"31"}, "ibirite": {"31"}, "ribeirao das neves": {"31"},
    "juiz de fora": {"32"}, "governador valadares": {"33"},
    "uberlandia": {"34"}, "uberaba": {"34"},
    "pocos de caldas": {"35"}, "pouso alegre": {"35"}, "varginha": {"35"},
    "divinopolis": {"37"}, "montes claros": {"38"},
    "curitiba": {"41"}, "batel": {"41"}, "agua verde": {"41"}, "sitio cercado": {"41"},
    "boqueirao": {"41"}, "santa felicidade": {"41"}, "colombo": {"41"},
    "sao jose dos pinhais": {"41"}, "pinhais": {"41"}, "araucaria": {"41"},
    "fazenda rio grande": {"41"}, "campo largo": {"41"},
    "ponta grossa": {"42"}, "guarapuava": {"42"},
    "londrina": {"43"}, "apucarana": {"43"},
    "maringa": {"44"}, "campo mourao": {"44"},
    "cascavel": {"45"}, "foz do iguacu": {"45"},
    "francisco beltrao": {"46"}, "pato branco": {"46"},
    "florianopolis": {"48"}, "palhoca": {"48"}, "sao jose": {"48"}, "biguacu": {"48"},
    "criciuma": {"48"}, "tubarao": {"48"},
    "joinville": {"47"}, "blumenau": {"47"}, "itajai": {"47"}, "balneario camboriu": {"47"},
    "brusque": {"47"}, "jaragua do sul": {"47"},
    "chapeco": {"49"}, "lages": {"49"},
    "porto alegre": {"51"}, "canoas": {"51"}, "novo hamburgo": {"51"}, "sao leopoldo": {"51"},
    "pelotas": {"53"}, "caxias do sul": {"54"}, "bento goncalves": {"54"}, "passo fundo": {"54"},
    "santa maria": {"55"},
    "brasilia": {"61"}, "taguatinga": {"61"}, "aguas claras": {"61"}, "lago sul": {"61"},
    "goiania": {"62"}, "anapolis": {"62"}, "aparecida de goiania": {"62"}, "rio verde": {"64"},
    "cuiaba": {"65"}, "rondonopolis": {"66"}, "sinop": {"66"},
    "campo grande": {"67"}, "dourados": {"67"},
    "salvador": {"71"}, "lauro de freitas": {"71"}, "camacari": {"71"}, "feira de santana": {"75"},
    "vitoria da conquista": {"77"}, "ilheus": {"73"}, "itabuna": {"73"},
    "aracaju": {"79"},
    "recife": {"81"}, "boa viagem": {"81"}, "olinda": {"81"}, "jaboatao": {"81"}, "petrolina": {"87"},
    "maceio": {"82"}, "joao pessoa": {"83"}, "campina grande": {"83"},
    "natal": {"84"}, "mossoro": {"84"},
    "fortaleza": {"85"}, "meireles": {"85"}, "caucaia": {"85"}, "juazeiro do norte": {"88"}, "sobral": {"88"},
    "teresina": {"86"}, "sao luis": {"98"}, "imperatriz": {"99"},
    "belem": {"91"}, "santarem": {"93"}, "maraba": {"94"},
    "manaus": {"92"}, "macapa": {"96"}, "boa vista": {"95"},
    "rio de janeiro": {"21"}, "barra da tijuca": {"21"}, "niteroi": {"21"}, "sao goncalo": {"21"},
    "duque de caxias": {"21"}, "nova iguacu": {"21"},
    "petropolis": {"24"}, "volta redonda": {"24"}, "campos dos goytacazes": {"22"}, "cabo frio": {"22"},
    "vitoria": {"27"}, "vila velha": {"27"}, "serra": {"27"}, "cariacica": {"27"},
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
            "whatsapp_candidate": bool(mobile), "kind": "celular provável" if mobile else "telefone fixo",
            "confidence": 85 if mobile else 50,
            "reason": "Formato de celular brasileiro compatível com WhatsApp; a conta só é confirmada pela API oficial." if mobile else "Formato brasileiro válido, mas identificado como linha fixa (sem garantia de WhatsApp).",
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


def normalize_location_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def validate_phone_city_compatibility(phone, location, region="br"):
    """
    Verifica se o DDD do telefone é compatível com a cidade/localização informada.
    Sinaliza divergências sem descartar automaticamente números legítimos.
    """
    if region != "br":
        return {
            "compatible": True, "actual_ddd": "", "expected_ddds": [],
            "warning": "", "level": "ok",
        }
    assessment = assess_phone(phone, region="br")
    if not assessment["valid"]:
        return {
            "compatible": True, "actual_ddd": "", "expected_ddds": [],
            "warning": "", "level": "unknown",
        }
    actual_digits = assessment["digits"].removeprefix("55")
    actual_ddd = actual_digits[:2]

    norm_loc = normalize_location_text(location)
    if not norm_loc:
        return {
            "compatible": True, "actual_ddd": actual_ddd, "expected_ddds": [],
            "warning": "", "level": "ok",
        }

    # 1. Procurar cidades específicas
    expected_ddds = None
    for city_key, ddds in BRAZIL_CITY_SPECIFIC_DDDS.items():
        if city_key in norm_loc:
            expected_ddds = ddds
            break

    # 2. Se não achou por cidade, procurar por estado (UF)
    if not expected_ddds:
        for uf, ddds in BRAZIL_STATE_DDDS.items():
            uf_pattern = rf"\b{uf.lower()}\b"
            if re.search(uf_pattern, norm_loc):
                expected_ddds = ddds
                break

    if not expected_ddds:
        return {
            "compatible": True, "actual_ddd": actual_ddd, "expected_ddds": [],
            "warning": "", "level": "ok",
        }

    if actual_ddd in expected_ddds:
        return {
            "compatible": True, "actual_ddd": actual_ddd, "expected_ddds": sorted(expected_ddds),
            "warning": "", "level": "ok",
        }

    expected_str = "/".join(sorted(expected_ddds))
    return {
        "compatible": False,
        "actual_ddd": actual_ddd,
        "expected_ddds": sorted(expected_ddds),
        "warning": f"DDD {actual_ddd} divergente da localidade informada ({location}, esperado DDD {expected_str})",
        "level": "warning",
    }
