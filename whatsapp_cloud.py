import json
import os
import urllib.error
import urllib.request

from contact_quality import digits_only


def cloud_configuration():
    return {
        "token": os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip(),
        "phone_number_id": os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip(),
        "template_name": os.environ.get("WHATSAPP_TEMPLATE_NAME", "").strip(),
        "template_language": os.environ.get("WHATSAPP_TEMPLATE_LANGUAGE", "pt_BR").strip() or "pt_BR",
        "api_version": os.environ.get("WHATSAPP_API_VERSION", "v22.0").strip() or "v22.0",
    }


def cloud_configured():
    config = cloud_configuration()
    return all(config[key] for key in ("token", "phone_number_id", "template_name"))


def send_approved_template(recipient, message, timeout=20):
    config = cloud_configuration()
    if not cloud_configured():
        raise RuntimeError("WhatsApp Cloud API ainda não foi configurada.")
    phone = digits_only(recipient)
    if not phone:
        raise ValueError("O lead não possui um telefone utilizável.")
    content = str(message or "").strip()
    if not content:
        raise ValueError("A mensagem não pode ficar vazia.")
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": config["template_name"],
            "language": {"code": config["template_language"]},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": content[:1024]}],
            }],
        },
    }
    request = urllib.request.Request(
        f"https://graph.facebook.com/{config['api_version']}/{config['phone_number_id']}/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['token']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            details = json.loads(error.read().decode("utf-8")).get("error", {}).get("message", "")
        except (ValueError, UnicodeDecodeError):
            details = ""
        raise RuntimeError(details or f"A API do WhatsApp recusou o envio ({error.code}).") from error
    message_id = ((result.get("messages") or [{}])[0]).get("id", "")
    if not message_id:
        raise RuntimeError("A API não confirmou o identificador da mensagem.")
    return {"message_id": message_id, "recipient": phone}
