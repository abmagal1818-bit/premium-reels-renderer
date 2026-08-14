
from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import requests, uuid, os, io

story_bp = Blueprint("story_bp", __name__)

W, H = 1080, 1920

RED = (235, 25, 34)
WHITE = (248, 248, 248)
BLACK = (4, 4, 5)
GRAY = (170, 170, 170)
DARK = (10, 10, 12)

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
    return r.crop((x,y,x+w,y+h))

def fit_contain(im, maxw, maxh):
    s = min(maxw / im.width, maxh / im.height)
    return im.resize((max(1,int(im.width*s)), max(1,int(im.height*s))), Image.Resampling.LANCZOS)

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

def soft_edges(im, edge=45):
    im = im.convert("RGBA")
    mask = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(mask)
    inset = min(edge, max(22, min(im.size)//10))
    d.rounded_rectangle(
        (inset, inset, im.width-inset, im.height-inset),
        radius=max(18, inset//2),
        fill=255
    )
    mask = mask.filter(ImageFilter.GaussianBlur(max(12, inset//3)))
    im.putalpha(mask)
    return im

def fmt_price(v):
    s = str(v or "").strip().replace("R$","").replace(" ","")
    try:
        if "," in s:
            n = float(s.replace(".","").replace(",","."))
        else:
            n = float(s)
        return f"{int(round(n)):,}".replace(",",".")
    except:
        return s

def fmt_km(v):
    try:
        return f"{int(float(v)):,}".replace(",",".")
    except:
        return str(v or "")

def upload_png_to_supabase(img, job):
    if not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_KEY não configurada no Render.")

    bio = io.BytesIO()
    img.convert("RGB").save(bio, format="PNG", optimize=True)

    object_name = f"{SUPABASE_STORIES_FOLDER}/{job}.png"
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_name}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": "image/png",
        "x-upsert": "true",
        "cache-control": "3600"
    }
    r = requests.post(url, headers=headers, data=bio.getvalue(), timeout=180)
    if r.status_code not in (200,201):
        raise RuntimeError(f"Falha upload Story HTTP {r.status_code}: {r.text[:800]}")

    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{object_name}"

# ------------ ícones simples ------------
def icon_box(d, x, y):
    d.rounded_rectangle((x,y,x+42,y+42), radius=8, outline=RED, width=3)

def icon_calendar(d, x, y):
    icon_box(d,x,y)
    d.line((x+8,y+14,x+34,y+14),fill=RED,width=2)

def icon_speed(d,x,y):
    icon_box(d,x,y)
    d.arc((x+8,y+9,x+34,y+35),180,355,fill=RED,width=2)
    d.line((x+21,y+24,x+29,y+16),fill=RED,width=2)

def icon_fuel(d,x,y):
    icon_box(d,x,y)
    d.rectangle((x+11,y+9,x+25,y+31),outline=RED,width=2)

def icon_gear(d,x,y):
    icon_box(d,x,y)
    d.ellipse((x+14,y+14,x+28,y+28),outline=RED,width=2)

def render_story(data):
    marca = str(data.get("marca","")).upper()
    modelo = str(data.get("modelo","")).upper()
    ano = str(data.get("ano_modelo") or data.get("ano") or "")
    km = fmt_km(data.get("km"))
    cambio = str(data.get("cambio","")).upper()
    combustivel = str(data.get("combustivel","")).upper()
    preco = fmt_price(data.get("preco"))
    cor = str(data.get("cor","")).upper()
    portas = str(data.get("portas",""))

    fotos = data.get("fotos") or []
    foto_capa = data.get("foto_capa")
    if foto_capa and foto_capa not in fotos:
        fotos = [foto_capa] + fotos
    fotos = [x for x in fotos if x]
    if not fotos:
        raise ValueError("Nenhuma foto recebida.")

    # fotos reais do estoque
    hero = download_image(fotos[0])
    photo_top_right = download_image(fotos[min(1, len(fotos)-1)])
    interior = download_image(fotos[min(5, len(fotos)-1)])
    rear = download_image(fotos[min(10, len(fotos)-1)])
    side = download_image(fotos[min(3, len(fotos)-1)])
    logo = clean_logo(download_image(data.get("logo_url") or DEFAULT_LOGO_URL))

    im = Image.new("RGBA", (W,H), BLACK+(255,))
    d = ImageDraw.Draw(im)

    # =========================================================
    # BLOCO 1 — HERO igual ao post aprovado
    # =========================================================
    hero_h = 1040
    bg = fit_cover(hero, W, hero_h).filter(ImageFilter.GaussianBlur(18))
    bg = ImageEnhance.Brightness(bg).enhance(0.22)
    im.alpha_composite(bg,(0,0))

    # sombra preta sobre fundo
    grad = Image.new("RGBA",(W,hero_h),(0,0,0,0))
    gd = ImageDraw.Draw(grad)
    for y in range(hero_h):
        a = int(120 + 80*(y/hero_h))
        gd.line((0,y,W,y), fill=(0,0,0,a))
    im.alpha_composite(grad,(0,0))
    d = ImageDraw.Draw(im)

    # logo topo esquerdo
    lg = fit_contain(logo, 400, 170)
    im.alpha_composite(lg,(32,24))

    # selo topo direito
    txt(d,(1038,40),"S E M I N O V O S",20,WHITE,False,anchor="ra")
    txt(d,(1038,70),"D E  Q U A L I D A D E",18,WHITE,False,anchor="ra")
    d.polygon([(1010,92),(1035,92),(1024,118),(998,118)],fill=RED)

    # título grande
    txt(d,(42,155),marca,42,RED,True)
    model_size = 108 if len(modelo)<=12 else 82
    txt(d,(40,195),modelo,model_size,WHITE,True)

    # ano + câmbio + combustível
    d.polygon([(40,330),(220,330),(205,398),(28,398)], fill=RED)
    txt(d,(125,363),ano,44,WHITE,True,anchor="mm")
    txt(d,(245,363),f"{cambio}  |  {combustivel}",38,WHITE,True,anchor="lm")

    txt(d,(42,420),"ESPAÇO, CONFORTO",31,WHITE,True)
    txt(d,(42,460),"E VERSATILIDADE",31,RED,True)

    # foto principal enorme
    hero_fg = fit_contain(hero, 1030, 640)
    hero_fg = ImageEnhance.Contrast(hero_fg).enhance(1.06)
    hero_fg = ImageEnhance.Brightness(hero_fg).enhance(1.03)
    hero_fg = soft_edges(hero_fg, 36)
    hx=(W-hero_fg.width)//2
    hy=500

    shadow = Image.new("RGBA",(hero_fg.width+80,hero_fg.height+80),(0,0,0,0))
    sd=ImageDraw.Draw(shadow)
    sd.rounded_rectangle((40,40,hero_fg.width+40,hero_fg.height+40),radius=35,fill=(0,0,0,130))
    shadow=shadow.filter(ImageFilter.GaussianBlur(24))
    im.alpha_composite(shadow,(hx-40,hy-40))
    im.alpha_composite(hero_fg,(hx,hy))

    # benefícios na base do hero
    base_y=895
    d.rectangle((0,base_y,W,1040),fill=(7,7,8,245))
    d.line((0,base_y,W,base_y),fill=(100,0,0),width=2)

    benefits=["CONFORTO","ESPAÇO\nINTERNO","TECNOLOGIA","SEGURANÇA"]
    bx=[88,280,480,675]
    for i,(lab,x) in enumerate(zip(benefits,bx)):
        d.rounded_rectangle((x-25,920,x+25,970),radius=10,outline=RED,width=3)
        txt(d,(x,995),lab,18,WHITE,True,anchor="ma")
        if i<3:
            d.line((x+85,918,x+85,1015),fill=(115,0,0),width=2)

    # preço inclinado à direita
    d.polygon([(700,880),(W,880),(W,1040),(655,1040)],fill=(4,4,5,255))
    d.line((700,880,655,1040),fill=RED,width=8)
    txt(d,(875,907),"POR APENAS",22,WHITE,True,anchor="ma")
    txt(d,(720,942),"R$",38,RED,True)
    txt(d,(790,930),preco,72,WHITE,True)
    d.rectangle((750,995,1060,1036),fill=RED)
    txt(d,(905,1015),"FALE CONOSCO",24,WHITE,True,anchor="mm")

    # =========================================================
    # BLOCO 2 — DESTAQUES + FOTO
    # =========================================================
    sec2_y=1050
    sec2_h=410
    d.rectangle((0,sec2_y,W,sec2_y+sec2_h),fill=(4,4,5,255))

    # esquerda
    txt(d,(35,1080),"DESTAQUES",42,WHITE,True)
    txt(d,(35,1126),"DO VEÍCULO",42,RED,True)

    opts=data.get("opcionais") or []
    preferred = [
        "Motor 1.6 Flex",
        f"Câmbio {cambio.title()}",
        "Direção Elétrica",
        "Ar Condicionado",
        "Vidros e Travas Elétricas",
        "Rodas de Liga Leve",
        "Central Multimídia",
        "Airbags + ABS"
    ]
    shown = []
    low=[str(x).lower() for x in opts]
    for p in preferred:
        if not opts or any(p.lower().split()[0] in o for o in low):
            shown.append(p)
    shown=shown[:6]

    yy=1180
    for item in shown:
        icon_box(d,35,yy-8)
        txt(d,(95,yy+13),item,20,WHITE,False,anchor="lm")
        yy+=46

    # foto direita com diagonal vermelha
    right_x=570
    d.polygon([(right_x,sec2_y),(W,sec2_y),(W,sec2_y+sec2_h),(520,sec2_y+sec2_h)],fill=(12,12,14,255))
    d.line((right_x,sec2_y,520,sec2_y+sec2_h),fill=RED,width=5)
    top_right = fit_cover(photo_top_right, 480, 380)
    im.alpha_composite(top_right,(595,1070))

    # =========================================================
    # BLOCO 3 — FICHA TÉCNICA + 3 FOTOS
    # =========================================================
    sec3_y=1470
    sec3_h=390
    d.rectangle((0,sec3_y,W,sec3_y+sec3_h),fill=(6,6,7,255))

    txt(d,(35,1500),"FICHA",40,WHITE,True)
    txt(d,(35,1545),"TÉCNICA",40,RED,True)

    specs=[
        ("ANO/MODELO",ano,icon_calendar),
        ("QUILOMETRAGEM",f"{km} KM",icon_speed),
        ("COMBUSTÍVEL",combustivel,icon_fuel),
        ("CÂMBIO",cambio,icon_gear),
        ("COR",cor,icon_box),
        ("PORTAS",f"{portas} PORTAS" if portas else "",icon_box)
    ]

    sy=1600
    for k,v,ico in specs:
        if not v:
            continue
        ico(d,35,sy-8)
        txt(d,(92,sy),k,14,GRAY,True)
        txt(d,(92,sy+20),v,21,WHITE,True)
        sy+=52

    # 3 fotos à direita empilhadas
    ph_x=560
    ph_w=500
    ph_h=112
    p1=fit_cover(interior,ph_w,ph_h)
    p2=fit_cover(rear,ph_w,ph_h)
    p3=fit_cover(side,ph_w,ph_h)
    im.alpha_composite(p1,(ph_x,1490))
    im.alpha_composite(p2,(ph_x,1610))
    im.alpha_composite(p3,(ph_x,1730))
    d.line((540,1470,490,1860),fill=RED,width=5)

    # =========================================================
    # RODAPÉ
    # =========================================================
    d.rectangle((0,1860,W,H),fill=(0,0,0,255))
    txt(d,(35,1890),data.get("whatsapp","(51) 99573-4555"),22,WHITE,True)
    txt(d,(1045,1890),data.get("instagram","@premiumautomarcas"),22,WHITE,True,anchor="ra")

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
        data=request.get_json(force=True)
        img=render_story(data)
        job=uuid.uuid4().hex
        public_url=upload_png_to_supabase(img,job)
        return jsonify({
            "status":"done",
            "id":job,
            "url":public_url,
            "story_url":public_url,
            "template":"story_aprovado_v1"
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status":"error","error":str(e)}),500
