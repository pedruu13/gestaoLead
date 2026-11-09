import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from preview_studio import build_preview_config, generate_preview_assets, render_preview_html, validate_preview_html


def main():
    output = Path(__file__).resolve().parents[1] / "artifacts" / "preview-quality"
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for slug, category, name in (
        ("odontologia", "Dentista", "Clínica Exemplo — teste"),
        ("advocacia", "Advogado", "Escritório Exemplo — teste"),
        ("academia", "Academia", "Academia Exemplo — teste"),
    ):
        config = build_preview_config({"Nome": name, "Nicho": category, "Categoria Maps": category, "Bairro": "Campinas, SP"})
        html = render_preview_html(config)
        (output / f"{slug}.html").write_text(html, encoding="utf-8")
        paths, report = generate_preview_assets(html, str(output), slug, validate_preview_html(html, config))
        results.append({"segment": category, "test_fixture": True, "paths": paths, "report": report, "message": config["message"]})
    (output / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps([{"segment": item["segment"], "approved": item["report"]["approved"], "errors": item["report"]["errors"]} for item in results], ensure_ascii=False))
    if not all(item["report"]["approved"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
