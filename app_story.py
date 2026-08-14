
from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import requests, uuid, os, io

story_bp = Blueprint("story_bp", __name__)

W, H = 1080, 1920

RED = (235, 25, 34)
WHITE = (248, 248, 248)
BLACK = (4, 4, 5)
GRAY = (170, 170, 170)

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
    path = FONT_BOLD if bold else FONT_REG
    return ImageFont.truetype(path, size) if path else ImageFont.load_default()

def txt(d, xy, value, size, fill=WHITE, bold=False, anchor=None):
    d.text(xy, str(value), font=F(size, bold), fill=fill, anchor=anchor)

def download_image(url):
    r = requests.get(url, timeout=40, headers={"User-Agent":"Mozilla/5.0"})
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGBA")

def fit_cover(im, w, h):
    s = max(w / im.width, h / im.height)
    r = im.resize((int(im.width*s), int(im.height*s)), Image.Resampling.LANCZOS)
    x = max(0, (r.width-w)//2)
    y = max(0, (r.height-h)//2)
    return r.crop((x, y, x+w, y+h))

def fit_contain(im, maxw, maxh):
    s = min(maxw / im.width, maxh / im.height)
    return im.resize(
        (max(1, int(im.width*s)), max(1, int(im.height*s))),
        Image.Resampling.LANCZOS
    )

def clean_logo(logo):
    logo = logo.convert("RGBA")
    px = logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r,g,b,a = px[x,y]
            if max(r,g,b) < 18:
                px[x,y] = (r,g,b,0)
    bb = logo.getbbox()
    return logo.crop(bb) if bb else logo

def soft_edges(im, edge=42):
    im = im.convert("RGBA")
    mask = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(mask)
    inset = min(edge, max(20, min(im.size)//10))
    d.rounded_rectangle(
        (inset, inset, im.width-inset, im.height-inset),
        radius=max(18, inset//2),
        fill=255
    )
    mask = mask.filter(ImageFilter.GaussianBlur(max(12, inset//3)))
    im.putalpha(mask)
    return im

def normalize_payload(raw):
    # Aceita tanto payload direto quanto { body: {...} } vindo do n8n.
    if isinstance(raw, dict) and isinstance(raw.get("body"), dict):
        merged = dict(raw["body"])
        for k,v in raw.items():
            if k != "body" and k not in merged:
                merged[k] = v
        return merged
    return raw or {}

def fmt_price_from_supabase(v):
    # NÃO CHUTA PREÇO.
    # Usa exclusivamente o valor recebido do Supabase/n8n.
    if v is None or str(v).strip() == "":
        raise ValueError("Campo 'preco' não recebido do Supabase.")

    s = str(v).strip().replace("R$", "").replace(" ", "")

    # formatos aceitos:
    # 58990
    # 58990.00
    # 58.990
    # 58.990,00
    # 58990,00
    try:
        if "," in s:
            normalized = s.replace(".", "").replace(",", ".")
            n = float(normalized)
        else:
            # se houver ponto e exatamente 3 dígitos depois, tratamos como separador milhar.
            if s.count(".") == 1 and len(s.split(".")[1]) == 3:
                n = float(s.replace(".", ""))
            else:
                n = float(s)

        return f"{int(round(n)):,}".replace(",", ".")
    except Exception:
        raise ValueError(f"Preço inválido recebido do Supabase: {v}")

def fmt_km(v):
    if v is None or str(v).strip() == "":
        return ""
    try:
        return f"{int(float(v)):,}".replace(",", ".")
    except:
        return str(v)

def upload_png_to_supabase(img, job):
    if not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_KEY não configurada no Render.")

    bio = io.BytesIO()
    img.convert("RGB").save(bio, format="PNG", optimize=True)

    object_name = f"{SUPABASE_STORIES_FOLDER}/{job}.png"
    upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_name}"

    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": "image/png",
        "x-upsert": "true",
        "cache-control": "3600"
    }

    r = requests.post(upload_url, headers=headers, data=bio.getvalue(), timeout=180)

    if r.status_code not in (200, 201):
        raise RuntimeError(
            f"Falha upload Story HTTP {r.status_code}: {r.text[:800]}"
        )

    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{object_name}"

def icon_box(d, x, y):
    d.rounded_rectangle((x,y,x+46,y+46), radius=8, outline=RED, width=3)

def render_story(raw):
    data = normalize_payload(raw)

    marca = str(data.get("marca","")).upper()
    modelo = str(data.get("modelo","")).upper()
    ano = str(data.get("ano_modelo") or data.get("ano") or "")
    km = fmt_km(data.get("km"))
    cambio = str(data.get("cambio","")).upper()
    combustivel = str(data.get("combustivel","")).upper()
    cor = str(data.get("cor","")).upper()
    portas = str(data.get("portas",""))

    # PREÇO OBRIGATORIAMENTE DINÂMICO
    preco = fmt_price_from_supabase(data.get("preco"))

    fotos = data.get("fotos") or []
    foto_capa = data.get("foto_capa")

    if foto_capa and foto_capa not in fotos:
        fotos = [foto_capa] + fotos

    fotos = [x for x in fotos if x]

    if not fotos:
        raise ValueError("Nenhuma foto recebida do Supabase.")

    logo_url = data.get("logo_url") or DEFAULT_LOGO_URL

    # Fotos reais do estoque
    hero = download_image(fotos[0])
    top_right = download_image(fotos[min(1, len(fotos)-1)])
    interior = download_image(fotos[min(5, len(fotos)-1)])
    rear = download_image(fotos[min(10, len(fotos)-1)])
    side = download_image(fotos[min(3, len(fotos)-1)])
    logo = clean_logo(download_image(logo_url))

    im = Image.new("RGBA", (W,H), BLACK+(255,))
    d = ImageDraw.Draw(im)

    # =========================================================
    # BLOCO SUPERIOR — 0 a 1100
    # =========================================================
    hero_h = 1100

    bg = fit_cover(hero, W, hero_h)
    bg = bg.filter(ImageFilter.GaussianBlur(22))
    bg = ImageEnhance.Brightness(bg).enhance(0.20)
    im.alpha_composite(bg, (0,0))

    overlay = Image.new("RGBA", (W,hero_h), (0,0,0,0))
    od = ImageDraw.Draw(overlay)
    for y in range(hero_h):
        a = int(135 + (y/hero_h)*65)
        od.line((0,y,W,y), fill=(0,0,0,a))
    im.alpha_composite(overlay,(0,0))
    d = ImageDraw.Draw(im)

    # logo
    lg = fit_contain(logo, 470, 185)
    im.alpha_composite(lg,(34,26))

    # selo
    txt(d,(1038,42),"S E M I N O V O S",22,WHITE,False,anchor="ra")
    txt(d,(1038,72),"D E  Q U A L I D A D E",19,WHITE,False,anchor="ra")
    d.polygon([(1000,96),(1036,96),(1022,132),(986,132)], fill=RED)

    # marca/modelo
    txt(d,(44,180),marca,46,RED,True)
    model_size = 118 if len(modelo) <= 12 else 90
    txt(d,(40,220),modelo,model_size,WHITE,True)

    # ano/câmbio/flex
    d.polygon([(38,360),(235,360),(218,438),(22,438)], fill=RED)
    txt(d,(130,398),ano,48,WHITE,True,anchor="mm")
    txt(d,(260,397),f"{cambio}  |  {combustivel}",40,WHITE,True,anchor="lm")

    txt(d,(44,460),"ESPAÇO, CONFORTO",34,WHITE,True)
    txt(d,(44,503),"E VERSATILIDADE",34,RED,True)

    # hero
    hero_fg = fit_contain(hero, 1040, 680)
    hero_fg = ImageEnhance.Contrast(hero_fg).enhance(1.05)
    hero_fg = ImageEnhance.Brightness(hero_fg).enhance(1.03)
    hero_fg = soft_edges(hero_fg, 40)

    hx = (W - hero_fg.width)//2
    hy = 535

    shadow = Image.new("RGBA", (hero_fg.width+90, hero_fg.height+90), (0,0,0,0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (45,45,hero_fg.width+45,hero_fg.height+45),
        radius=38,
        fill=(0,0,0,135)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(26))
    im.alpha_composite(shadow,(hx-45,hy-45))
    im.alpha_composite(hero_fg,(hx,hy))
    d = ImageDraw.Draw(im)

    # =========================================================
    # BARRA BENEFÍCIOS + PREÇO — 1000 a 1195
    # =========================================================
    bar_y = 1010

    d.rectangle((0,bar_y,W,1195), fill=(6,6,7,250))
    d.line((0,bar_y,W,bar_y), fill=RED, width=3)

    benefits = ["CONFORTO","ESPAÇO","TECNOLOGIA","SEGURANÇA"]
    bx = [85,245,410,575]

    for i,(lab,cx) in enumerate(zip(benefits,bx)):
        d.rounded_rectangle((cx-27,1045,cx+27,1099), radius=10, outline=RED, width=3)
        txt(d,(cx,1123),lab,19,WHITE,True,anchor="ma")
        if i < 3:
            d.line((cx+78,1040,cx+78,1145), fill=(120,0,0), width=2)

    # preço igual à composição aprovada
    d.polygon([(690,990),(W,990),(W,1195),(645,1195)], fill=(4,4,5,255))
    d.line((690,990,645,1195), fill=RED, width=8)

    txt(d,(875,1018),"POR APENAS",23,WHITE,True,anchor="ma")
    txt(d,(710,1055),"R$",42,RED,True)
    txt(d,(780,1043),preco,78,WHITE,True)

    d.rectangle((755,1135,1050,1180), fill=RED)
    txt(d,(902,1158),"FALE CONOSCO",24,WHITE,True,anchor="mm")

    # =========================================================
    # BLOCO 2 — DESTAQUES
    # =========================================================
    sec2_y = 1210
    sec2_h = 330

    d.rectangle((0,sec2_y,W,sec2_y+sec2_h), fill=(4,4,5,255))

    txt(d,(38,1240),"DESTAQUES",42,WHITE,True)
    txt(d,(38,1285),"DO VEÍCULO",42,RED,True)

    opts = data.get("opcionais") or []
    if isinstance(opts, str):
        opts = [x.strip() for x in opts.split(",") if x.strip()]

    shown = [str(x) for x in opts][:5]

    if not shown:
        shown = [
            "Ar condicionado",
            f"Câmbio {cambio.title()}",
            "Rodas de liga leve",
            "Vidros elétricos",
            "Freio ABS"
        ]

    yy = 1345
    for item in shown[:5]:
        icon_box(d,38,yy-8)
        txt(d,(100,yy+15),item,20,WHITE,False,anchor="lm")
        yy += 48

    # foto destaque à direita
    d.polygon([(610,sec2_y),(W,sec2_y),(W,sec2_y+sec2_h),(555,sec2_y+sec2_h)], fill=(10,10,12,255))
    d.line((610,sec2_y,555,sec2_y+sec2_h), fill=RED, width=5)

    rt = fit_cover(top_right, 450, 300)
    im.alpha_composite(rt,(625,1225))

    # =========================================================
    # BLOCO 3 — FICHA TÉCNICA + 3 FOTOS
    # =========================================================
    sec3_y = 1550
    sec3_h = 300

    d.rectangle((0,sec3_y,W,sec3_y+sec3_h), fill=(6,6,7,255))

    txt(d,(38,1580),"FICHA",40,WHITE,True)
    txt(d,(38,1623),"TÉCNICA",40,RED,True)

    specs = [
        ("ANO/MODELO", ano),
        ("QUILOMETRAGEM", f"{km} KM" if km else ""),
        ("COMBUSTÍVEL", combustivel),
        ("CÂMBIO", cambio),
        ("COR", cor),
        ("PORTAS", f"{portas} PORTAS" if portas else "")
    ]

    sy = 1670
    for key,val in specs:
        if not val:
            continue
        txt(d,(38,sy),key,14,GRAY,True)
        txt(d,(175,sy),val,21,WHITE,True)
        sy += 36

    # 3 fotos grandes à direita
    ph_x = 585
    ph_w = 470
    ph_h = 88

    for idx,src in enumerate([interior,rear,side]):
        ph = fit_cover(src,ph_w,ph_h)
        im.alpha_composite(ph,(ph_x,1565 + idx*94))

    d.line((560,1550,520,1850), fill=RED, width=5)

    # =========================================================
    # RODAPÉ
    # =========================================================
    d.rectangle((0,1850,W,H), fill=(0,0,0,255))

    txt(
        d,
        (35,1882),
        data.get("whatsapp","(51) 99573-4555"),
        22,
        WHITE,
        True
    )

    txt(
        d,
        (1045,1882),
        data.get("instagram","@premiumautomarcas"),
        22,
        WHITE,
        True,
        anchor="ra"
    )

    return im

@story_bp.get("/story-health")
def story_health():
    return {
        "ok":True,
        "service":"premium-story-renderer",
        "supabase":{
            "configured":bool(SUPABASE_SERVICE_KEY),
            "bucket":SUPABASE_BUCKET,
            "folder":SUPABASE_STORIES_FOLDER
        }
    }

@story_bp.post("/story")
def story():
    try:
        data = request.get_json(force=True)

        img = render_story(data)

        job = uuid.uuid4().hex

        public_url = upload_png_to_supabase(img, job)

        return jsonify({
            "status":"done",
            "id":job,
            "url":public_url,
            "story_url":public_url,
            "template":"story_aprovado_v2",
            "source_price": normalize_payload(data).get("preco")
        })

    except Exception as e:
        import traceback
        traceback.print_exc()

        return jsonify({
            "status":"error",
            "error":str(e)
        }),500
