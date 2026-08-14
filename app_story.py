
from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import requests, uuid, os, io

story_bp = Blueprint("story_bp", __name__)

W, H = 1080, 1920

RED = (232, 22, 32)
WHITE = (247, 247, 247)
BLACK = (6, 6, 7)
GRAY = (170, 170, 170)
DARK = (12, 12, 14)

FONT_BOLD = next((p for p in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
] if os.path.exists(p)), None)

FONT_REG = next((p for p in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
] if os.path.exists(p)), None)

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL",
    "https://kbmryoeevdxvugcelflp.supabase.co"
).rstrip("/")

SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "veiculos")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_STORIES_FOLDER = os.environ.get("SUPABASE_STORIES_FOLDER", "stories")

DEFAULT_LOGO_URL = os.environ.get(
    "PREMIUM_LOGO_URL",
    "https://kbmryoeevdxvugcelflp.supabase.co/storage/v1/object/public/veiculos/Musicas/Logo%20minimalista%20de%20carro%20esportivo.png"
)

def F(size, bold=False):
    p = FONT_BOLD if bold else FONT_REG
    return ImageFont.truetype(p, size) if p else ImageFont.load_default()

def download_image(url):
    r = requests.get(
        url,
        timeout=40,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGBA")

def fit_contain(im, maxw, maxh):
    scale = min(maxw / im.width, maxh / im.height)
    return im.resize(
        (max(1, int(im.width * scale)), max(1, int(im.height * scale))),
        Image.Resampling.LANCZOS
    )

def fit_cover(im, w, h):
    scale = max(w / im.width, h / im.height)
    r = im.resize(
        (int(im.width * scale), int(im.height * scale)),
        Image.Resampling.LANCZOS
    )
    x = max(0, (r.width - w) // 2)
    y = max(0, (r.height - h) // 2)
    return r.crop((x, y, x + w, y + h))

def clean_logo(logo):
    logo = logo.convert("RGBA")
    px = logo.load()

    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b, a = px[x, y]
            if max(r, g, b) < 18:
                px[x, y] = (r, g, b, 0)

    bb = logo.getbbox()
    return logo.crop(bb) if bb else logo

def feather(im, edge=58):
    im = im.convert("RGBA")

    mask = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(mask)

    inset = min(edge, max(24, min(im.size) // 8))
    d.rounded_rectangle(
        (inset, inset, im.width - inset, im.height - inset),
        radius=max(22, inset // 2),
        fill=255
    )

    mask = mask.filter(ImageFilter.GaussianBlur(max(14, inset // 3)))
    im.putalpha(mask)
    return im

def txt(d, xy, value, size, fill=WHITE, bold=False, anchor=None):
    d.text(
        xy,
        str(value),
        font=F(size, bold),
        fill=fill,
        anchor=anchor
    )

def fmt_price(v):
    try:
        n = float(str(v).replace("R$", "").strip().replace(".", "").replace(",", "."))
        return f"{n:,.0f}".replace(",", ".")
    except:
        return str(v or "")

def fmt_km(v):
    try:
        return f"{int(float(v)):,}".replace(",", ".")
    except:
        return str(v or "")

def fit_text_size(draw, text_value, max_width, start_size, min_size=34, bold=True):
    size = start_size
    while size > min_size:
        font = F(size, bold)
        bb = draw.textbbox((0, 0), text_value, font=font)
        if bb[2] - bb[0] <= max_width:
            return size
        size -= 2
    return min_size

def upload_png_to_supabase(img, job):
    if not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_KEY não configurada no Render.")

    bio = io.BytesIO()
    img.convert("RGB").save(
        bio,
        format="PNG",
        optimize=True
    )

    object_name = f"{SUPABASE_STORIES_FOLDER}/{job}.png"
    upload_url = (
        f"{SUPABASE_URL}/storage/v1/object/"
        f"{SUPABASE_BUCKET}/{object_name}"
    )

    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": "image/png",
        "x-upsert": "true",
        "cache-control": "3600"
    }

    r = requests.post(
        upload_url,
        headers=headers,
        data=bio.getvalue(),
        timeout=180
    )

    if r.status_code not in (200, 201):
        raise RuntimeError(
            f"Falha upload Story no Supabase HTTP {r.status_code}: "
            f"{r.text[:800]}"
        )

    return (
        f"{SUPABASE_URL}/storage/v1/object/public/"
        f"{SUPABASE_BUCKET}/{object_name}"
    )

def render_story(data):
    marca = str(data.get("marca", "")).upper()
    modelo = str(data.get("modelo", "")).upper()

    ano = (
        data.get("ano_modelo")
        or data.get("ano")
        or ""
    )

    km = fmt_km(data.get("km", ""))
    cambio = str(data.get("cambio", "")).upper()
    combustivel = str(data.get("combustivel", "")).upper()
    preco = fmt_price(data.get("preco", ""))
    cor = str(data.get("cor", "")).upper()
    portas = str(data.get("portas", ""))

    fotos = data.get("fotos") or []
    foto_capa = data.get("foto_capa")

    if foto_capa and foto_capa not in fotos:
        fotos = [foto_capa] + fotos

    fotos = [x for x in fotos if x]

    if not fotos:
        raise ValueError("Nenhuma foto recebida.")

    hero = download_image(fotos[0])
    interior = download_image(fotos[min(5, len(fotos) - 1)])
    traseira = download_image(fotos[min(10, len(fotos) - 1)])
    lateral = download_image(fotos[min(3, len(fotos) - 1)])

    logo = clean_logo(
        download_image(
            data.get("logo_url") or DEFAULT_LOGO_URL
        )
    )

    canvas = Image.new(
        "RGBA",
        (W, H),
        BLACK + (255,)
    )

    # =========================================================
    # BLOCO SUPERIOR
    # =========================================================
    bg = fit_cover(hero, W, 1210)
    bg = bg.filter(ImageFilter.GaussianBlur(28))
    bg = ImageEnhance.Brightness(bg).enhance(0.24)
    canvas.alpha_composite(bg, (0, 0))

    top_overlay = Image.new(
        "RGBA",
        (W, 1210),
        (0, 0, 0, 0)
    )

    od = ImageDraw.Draw(top_overlay)

    for y in range(1210):
        alpha = int(115 + (y / 1210) * 55)
        od.line(
            (0, y, W, y),
            fill=(0, 0, 0, alpha)
        )

    canvas.alpha_composite(top_overlay, (0, 0))
    d = ImageDraw.Draw(canvas)

    # Logo
    lg = fit_contain(logo, 430, 180)
    canvas.alpha_composite(lg, (40, 34))

    # Selo
    txt(
        d,
        (1030, 55),
        "SEMINOVOS",
        26,
        WHITE,
        False,
        anchor="ra"
    )

    txt(
        d,
        (1030, 89),
        "DE QUALIDADE",
        22,
        WHITE,
        False,
        anchor="ra"
    )

    d.polygon(
        [(998, 114), (1030, 114), (1017, 148), (985, 148)],
        fill=RED
    )

    # Marca e modelo
    txt(
        d,
        (48, 205),
        marca,
        40,
        RED,
        True
    )

    model_size = 104 if len(modelo) <= 12 else 84

    txt(
        d,
        (42, 245),
        modelo,
        model_size,
        WHITE,
        True
    )

    # Ano / câmbio / combustível
    d.rounded_rectangle(
        (42, 382, 225, 456),
        radius=8,
        fill=RED
    )

    txt(
        d,
        (133, 419),
        ano,
        46,
        WHITE,
        True,
        anchor="mm"
    )

    txt(
        d,
        (255, 417),
        f"{cambio}  |  {combustivel}",
        36,
        WHITE,
        True,
        anchor="lm"
    )

    txt(
        d,
        (48, 490),
        "ESPAÇO, CONFORTO",
        32,
        WHITE,
        True
    )

    txt(
        d,
        (48, 530),
        "E VERSATILIDADE",
        32,
        RED,
        True
    )

    # =========================================================
    # FOTO PRINCIPAL
    # =========================================================
    hp = fit_contain(hero, 1035, 790)
    hp = ImageEnhance.Contrast(hp).enhance(1.04)
    hp = ImageEnhance.Brightness(hp).enhance(1.03)
    hp = feather(hp, 55)

    hero_x = (W - hp.width) // 2
    hero_y = 545

    # sombra
    shadow = Image.new(
        "RGBA",
        (hp.width + 80, hp.height + 80),
        (0, 0, 0, 0)
    )

    sd = ImageDraw.Draw(shadow)

    sd.rounded_rectangle(
        (40, 40, hp.width + 40, hp.height + 40),
        radius=42,
        fill=(0, 0, 0, 120)
    )

    shadow = shadow.filter(
        ImageFilter.GaussianBlur(26)
    )

    canvas.alpha_composite(
        shadow,
        (hero_x - 40, hero_y - 40)
    )

    canvas.alpha_composite(
        hp,
        (hero_x, hero_y)
    )

    d = ImageDraw.Draw(canvas)

    # =========================================================
    # BENEFÍCIOS + PREÇO
    # =========================================================
    d.rectangle(
        (0, 1195, W, 1495),
        fill=(8, 8, 9, 248)
    )

    d.line(
        (0, 1195, W, 1195),
        fill=RED,
        width=4
    )

    benefits = [
        "CONFORTO",
        "ESPAÇO",
        "TECNOLOGIA",
        "SEGURANÇA"
    ]

    benefit_centers = [85, 250, 420, 590]

    for i, (label, cx) in enumerate(
        zip(benefits, benefit_centers)
    ):
        d.rounded_rectangle(
            (cx - 28, 1245, cx + 28, 1301),
            radius=11,
            outline=RED,
            width=3
        )

        txt(
            d,
            (cx, 1325),
            label,
            19,
            WHITE,
            True,
            anchor="ma"
        )

        if i < 3:
            d.line(
                (cx + 78, 1238, cx + 78, 1355),
                fill=(125, 0, 0),
                width=2
            )

    # preço
    d.polygon(
        [(655, 1195), (W, 1195), (W, 1495), (610, 1495)],
        fill=(4, 4, 5, 255)
    )

    d.line(
        (655, 1195, 610, 1495),
        fill=RED,
        width=7
    )

    txt(
        d,
        (835, 1232),
        "POR APENAS",
        25,
        WHITE,
        True,
        anchor="ma"
    )

    price_string = f"R$ {preco}"
    psize = fit_text_size(
        d,
        price_string,
        390,
        78,
        54,
        True
    )

    txt(
        d,
        (835, 1297),
        price_string,
        psize,
        WHITE,
        True,
        anchor="mm"
    )

    d.rectangle(
        (690, 1380, 1035, 1458),
        fill=RED
    )

    txt(
        d,
        (862, 1419),
        "FALE CONOSCO",
        29,
        WHITE,
        True,
        anchor="mm"
    )

    # =========================================================
    # BLOCO INFERIOR
    # =========================================================
    lower_top = 1510

    d.rectangle(
        (0, lower_top, W, H),
        fill=(5, 5, 6, 255)
    )

    # divisória central
    d.polygon(
        [(530, lower_top), (W, lower_top), (W, H), (610, H)],
        fill=(10, 10, 11, 255)
    )

    d.line(
        (605, lower_top, 550, H),
        fill=RED,
        width=4
    )

    # Cabeçalho destaques
    txt(
        d,
        (42, 1545),
        "DESTAQUES",
        35,
        WHITE,
        True
    )

    txt(
        d,
        (42, 1586),
        "DO VEÍCULO",
        35,
        RED,
        True
    )

    # opções
    opts = data.get("opcionais") or []

    preferred = [
        "Ar condicionado",
        "Computador de bordo",
        "Entrada USB",
        "Rodas de liga leve",
        "Vidros elétricos",
        "Travas elétricas",
        "Freio ABS",
        "Airbags frontais"
    ]

    lower_opts = [str(x).lower() for x in opts]

    shown = []

    for p in preferred:
        if any(
            p.lower() in o
            for o in lower_opts
        ):
            shown.append(p)

    if not shown:
        shown = [
            "Ar condicionado",
            "Rodas de liga leve",
            "Vidros elétricos",
            "Freio ABS"
        ]

    shown = shown[:4]

    yy = 1645

    for item in shown:
        d.rounded_rectangle(
            (42, yy, 76, yy + 34),
            radius=7,
            outline=RED,
            width=2
        )

        txt(
            d,
            (95, yy + 17),
            item,
            19,
            WHITE,
            False,
            anchor="lm"
        )

        yy += 47

    # mini fotos
    thumb_y = 1815
    thumb_w = 150
    thumb_h = 88

    thumbs = [
        fit_cover(interior, thumb_w, thumb_h),
        fit_cover(traseira, thumb_w, thumb_h),
        fit_cover(lateral, thumb_w, thumb_h)
    ]

    thumb_xs = [42, 202, 362]

    for th, tx in zip(thumbs, thumb_xs):
        canvas.alpha_composite(
            th,
            (tx, thumb_y)
        )

        d.rectangle(
            (tx, thumb_y, tx + thumb_w, thumb_y + thumb_h),
            outline=(110, 110, 110),
            width=1
        )

    # ficha técnica
    txt(
        d,
        (650, 1545),
        "FICHA",
        35,
        WHITE,
        True
    )

    txt(
        d,
        (650, 1586),
        "TÉCNICA",
        35,
        RED,
        True
    )

    specs = [
        ("ANO/MODELO", str(ano)),
        ("QUILOMETRAGEM", f"{km} KM" if km else ""),
        ("COMBUSTÍVEL", combustivel),
        ("CÂMBIO", cambio),
        ("COR", cor),
        ("PORTAS", f"{portas} PORTAS" if portas else "")
    ]

    sy = 1645

    for key, value in specs:
        if not value:
            continue

        txt(
            d,
            (650, sy),
            key,
            15,
            GRAY,
            True
        )

        txt(
            d,
            (650, sy + 20),
            value,
            22,
            WHITE,
            True
        )

        sy += 45

    # rodapé
    d.rectangle(
        (0, 1905, W, H),
        fill=(0, 0, 0, 255)
    )

    txt(
        d,
        (35, 1912),
        data.get(
            "whatsapp",
            "(51) 99573-4555"
        ),
        19,
        WHITE,
        True
    )

    txt(
        d,
        (1045, 1912),
        data.get(
            "instagram",
            "@premiumautomarcas"
        ),
        19,
        WHITE,
        True,
        anchor="ra"
    )

    return canvas

@story_bp.get("/story-health")
def story_health():
    return {
        "ok": True,
        "service": "premium-story-renderer",
        "supabase": {
            "configured": bool(SUPABASE_SERVICE_KEY),
            "bucket": SUPABASE_BUCKET,
            "folder": SUPABASE_STORIES_FOLDER
        }
    }

@story_bp.post("/story")
def story():
    try:
        data = request.get_json(force=True)
        img = render_story(data)

        job = uuid.uuid4().hex

        public_url = upload_png_to_supabase(
            img,
            job
        )

        return jsonify({
            "status": "done",
            "id": job,
            "url": public_url,
            "story_url": public_url,
            "template": "story_01_v2"
        })

    except Exception as e:
        import traceback
        traceback.print_exc()

        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500
