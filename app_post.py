from flask import Blueprint, request, jsonify
from PIL import Image
from pathlib import Path
import requests, uuid, os, io, json, base64

post_bp = Blueprint("post_bp", __name__)
BASE = Path(__file__).parent
TEMPLATE_HTML_PATH = BASE / "post_template.html"
REFERENCE_PNG_PATH = BASE / "post_reference.png"

W, H = 1536, 1024

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://kbmryoeevdxvugcelflp.supabase.co").rstrip("/")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "veiculos")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_POSTS_FOLDER = os.environ.get("SUPABASE_POSTS_FOLDER", "posts")

# --- Load template + inline the reference PNG (used only for the static logo/seal crop) as base64 ---
# This avoids ever needing a separate "blank" template file or any relative-path/base-url resolution:
# the HTML is fully self-contained at render time.
def _load_html_template():
    html = TEMPLATE_HTML_PATH.read_text(encoding="utf-8")
    if REFERENCE_PNG_PATH.exists():
        b64 = base64.b64encode(REFERENCE_PNG_PATH.read_bytes()).decode("ascii")
        html = html.replace('url("post_reference.png")', f'url("data:image/png;base64,{b64}")')
    return html

HTML_TEMPLATE = _load_html_template() if TEMPLATE_HTML_PATH.exists() else None


def normalize(raw):
    if isinstance(raw, dict) and isinstance(raw.get("body"), dict):
        d = dict(raw["body"])
        for k, v in raw.items():
            if k != "body" and k not in d:
                d[k] = v
        return d
    return raw or {}


def fmt_price(v):
    if v is None or str(v).strip() == "":
        raise ValueError("Campo 'preco' não recebido do Supabase.")
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if "," in s:
        n = float(s.replace(".", "").replace(",", "."))
    elif s.count(".") == 1 and len(s.split(".")[1]) == 3:
        n = float(s.replace(".", ""))
    else:
        n = float(s)
    return f"{int(round(n)):,}".replace(",", ".")


def fmt_km(v):
    try:
        return f"{int(float(v)):,}".replace(",", ".")
    except Exception:
        return str(v or "")


def upload(img, job):
    if not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_KEY não configurada.")
    bio = io.BytesIO()
    img.convert("RGB").save(bio, format="PNG", optimize=True)
    name = f"{SUPABASE_POSTS_FOLDER}/{job}.png"
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{name}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": "image/png",
        "x-upsert": "true",
        "cache-control": "3600",
    }
    r = requests.post(url, headers=headers, data=bio.getvalue(), timeout=180)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Upload HTTP {r.status_code}: {r.text[:500]}")
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{name}"


def build_render_data(raw):
    """Turn the incoming Supabase/n8n payload into the flat dict the HTML template's JS expects."""
    data = normalize(raw)

    marca = str(data.get("marca", "")).upper()
    modelo = str(data.get("modelo", "")).upper()
    ano = str(data.get("ano_modelo") or data.get("ano") or "")
    km = fmt_km(data.get("km"))
    cambio = str(data.get("cambio", "")).upper()
    combustivel = str(data.get("combustivel", "")).upper()
    cor = str(data.get("cor", "")).upper()
    portas = str(data.get("portas", "") or "")
    preco = fmt_price(data.get("preco"))

    fotos = data.get("fotos") or []
    capa = data.get("foto_capa")
    if capa and capa not in fotos:
        fotos = [capa] + fotos
    fotos = [x for x in fotos if x]
    if not fotos:
        raise ValueError("Nenhuma foto recebida.")

    hero = fotos[0]
    interior = fotos[min(5, len(fotos) - 1)]
    traseira = fotos[min(10, len(fotos) - 1)]
    lateral = fotos[min(3, len(fotos) - 1)]

    opts = data.get("opcionais") or []
    if isinstance(opts, str):
        opts = [x.strip() for x in opts.split(",") if x.strip()]
    if not opts:
        opts = ["Motor 1.6 Flex", f"Câmbio {cambio.title()}", "Direção Elétrica", "Ar Condicionado",
                 "Vidros e Travas Elétricas", "Rodas de Liga Leve", "Central Multimídia", "Airbags + ABS"]

    # Same breakpoints the old PIL renderer used for shrinking oversized text, now applied as
    # explicit font-size overrides passed to the HTML/CSS layer instead of raster point sizes.
    marca_display = " ".join(list(marca)) if len(marca) <= 10 else marca
    modelo_size = 112 if len(modelo) <= 10 else 94 if len(modelo) <= 13 else 76
    preco_size = 70 if len(preco) <= 6 else 56

    return {
        "marca": marca, "marca_display": marca_display,
        "modelo": modelo, "modelo_size": modelo_size,
        "ano": ano, "km": km, "cambio": cambio, "combustivel": combustivel, "cor": cor, "portas": portas,
        "preco": preco, "preco_size": preco_size,
        "hero": hero, "interior": interior, "rear": traseira, "side": lateral,
        "opcionais": opts[:8],
        "whatsapp": data.get("whatsapp") or "(51) 99575-1376",
        "instagram": data.get("instagram") or "@premiumautomarcas",
    }


def render_png(raw):
    if not HTML_TEMPLATE:
        raise RuntimeError("post_template.html não encontrado.")
    render_data = build_render_data(raw)
    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(render_data, ensure_ascii=False))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        try:
            page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            page.set_content(html, wait_until="load")
            # Wait for every <img> (hero/interior/rear/side, fetched from external CDNs) to finish
            # loading, plus web fonts, before taking the screenshot. This is what the old PIL
            # approach couldn't guarantee — it composited photos synchronously with no concept of
            # "did the image actually finish downloading and decoding".
            page.wait_for_function("window.__READY === true", timeout=25000)
            png_bytes = page.screenshot(type="png")
        finally:
            browser.close()

    return Image.open(io.BytesIO(png_bytes)).convert("RGB"), render_data.get("preco")


@post_bp.get("/post-health")
def health():
    return {
        "ok": True,
        "service": "premium-post-final",
        "engine": "html-playwright-compositor",
        "size": f"{W}x{H}",
        "template_found": TEMPLATE_HTML_PATH.exists(),
        "reference_found": REFERENCE_PNG_PATH.exists(),
    }


@post_bp.post("/post")
def post():
    try:
        raw = request.get_json(force=True)
        img, preco = render_png(raw)
        job = uuid.uuid4().hex
        url = upload(img, job)
        return jsonify({
            "status": "done", "id": job, "url": url, "post_url": url,
            "engine": "html-playwright-compositor", "template": "post_template.html",
            "source_price": preco,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "error": str(e)}), 500
