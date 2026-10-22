from google import genai
from google.genai import types


MODEL_CANDIDATES = (
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-latest",
)


def generate_text(api_key, model, prompt, json_mode=False):
    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        response_mime_type="application/json" if json_mode else "text/plain",
        temperature=0.45,
    )
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    return (response.text or "").strip()


def first_available_response(api_key, prompt, json_mode=False, attempt_limit=None):
    last_error = None
    models = MODEL_CANDIDATES[:attempt_limit] if attempt_limit else MODEL_CANDIDATES
    for model in models:
        try:
            text = generate_text(api_key, model, prompt, json_mode=json_mode)
            if text:
                return text, model
        except Exception as error:
            last_error = error
    if last_error:
        raise last_error
    raise RuntimeError("Nenhum modelo Gemini retornou conteúdo")
