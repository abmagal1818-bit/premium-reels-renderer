
from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import requests, uuid, os, io

story_bp = Blueprint("story_bp", __name__)

W, H = 1080, 1920
RED=(232,22,32); WHITE=(247,247,247); BLACK=(6,6,7); GRAY=(175,175,175)

FONT_BOLD = next((p for p in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
] if os.path.exists(p)), None)

FONT_REG = next((p for p in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
] if os.path.exists(p)), None)

SUPABASE_URL=os.environ.get(
    "SUPABASE_URL",
    "https://kbmryoeevdxvugcelflp.supabase.co"
).rstrip("/")
SUPABASE_BUCKET=os.environ.get("SUPABASE_BUCKET","veiculos")
SUPABASE_SERVICE_KEY=os.environ.get("SUPABASE_SERVICE_KEY","")
SUPABASE_STORIES_FOLDER=os.environ.get("SUPABASE_STORIES_FOLDER","stories")

DEFAULT_LOGO_URL=os.environ.get(
    "PREMIUM_LOGO_URL",
    "https://kbmryoeevdxvugcelflp.supabase.co/storage/v1/object/public/veiculos/Musicas/Logo%20minimalista%20de%20carro%20esportivo.png"
)

def F(size,bold=False):
    p=FONT_BOLD if bold else FONT_REG
    return ImageFont.truetype(p,size) if p else ImageFont.load_default()

def download_image(url):
    r=requests.get(url,timeout=40,headers={"User-Agent":"Mozilla/5.0"})
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGBA")

def fit_contain(im,maxw,maxh):
    s=min(maxw/im.width,maxh/im.height)
    return im.resize((max(1,int(im.width*s)),max(1,int(im.height*s))),Image.Resampling.LANCZOS)

def fit_cover(im,w,h):
    s=max(w/im.width,h/im.height)
    r=im.resize((int(im.width*s),int(im.height*s)),Image.Resampling.LANCZOS)
    x=max(0,(r.width-w)//2); y=max(0,(r.height-h)//2)
    return r.crop((x,y,x+w,y+h))

def clean_logo(logo):
    logo=logo.convert("RGBA")
    px=logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r,g,b,a=px[x,y]
            if max(r,g,b)<18:
                px[x,y]=(r,g,b,0)
    bb=logo.getbbox()
    return logo.crop(bb) if bb else logo

def feather(im,edge=65):
    im=im.convert("RGBA")
    mask=Image.new("L",im.size,0)
    d=ImageDraw.Draw(mask)
    inset=min(edge,max(28,min(im.size)//8))
    d.rounded_rectangle(
        (inset,inset,im.width-inset,im.height-inset),
        radius=max(24,inset//2),
        fill=255
    )
    mask=mask.filter(ImageFilter.GaussianBlur(max(16,inset//3)))
    im.putalpha(mask)
    return im

def txt(d,xy,val,size,fill=WHITE,bold=False,anchor=None):
    d.text(xy,str(val),font=F(size,bold),fill=fill,anchor=anchor)

def fmt_price(v):
    try:
        return f"{float(v):,.0f}".replace(",",".")
    except:
        return str(v or "")

def fmt_km(v):
    try:
        return f"{int(float(v)):,}".replace(",",".")
    except:
        return str(v or "")

def upload_png_to_supabase(img, job):
    if not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_KEY não configurada no Render.")

    bio=io.BytesIO()
    img.convert("RGB").save(bio,format="PNG",optimize=True)

    object_name=f"{SUPABASE_STORIES_FOLDER}/{job}.png"
    upload_url=f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_name}"

    headers={
        "Authorization":f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey":SUPABASE_SERVICE_KEY,
        "Content-Type":"image/png",
        "x-upsert":"true",
        "cache-control":"3600"
    }

    r=requests.post(upload_url,headers=headers,data=bio.getvalue(),timeout=180)
    if r.status_code not in (200,201):
        raise RuntimeError(f"Falha upload Story no Supabase HTTP {r.status_code}: {r.text[:800]}")

    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{object_name}"

def render_story(data):
    marca=str(data.get("marca","")).upper()
    modelo=str(data.get("modelo","")).upper()
    ano=data.get("ano_modelo") or data.get("ano") or ""
    km=fmt_km(data.get("km",""))
    cambio=str(data.get("cambio","")).upper()
    combustivel=str(data.get("combustivel","")).upper()
    preco=fmt_price(data.get("preco",""))
    cor=str(data.get("cor","")).upper()
    portas=str(data.get("portas",""))

    fotos=data.get("fotos") or []
    foto_capa=data.get("foto_capa")
    if foto_capa and foto_capa not in fotos:
        fotos=[foto_capa]+fotos
    fotos=[x for x in fotos if x]
    if not fotos:
        raise ValueError("Nenhuma foto recebida.")

    hero=download_image(fotos[0])
    interior=download_image(fotos[min(5,len(fotos)-1)])
    traseira=download_image(fotos[min(10,len(fotos)-1)])
    lateral=download_image(fotos[min(3,len(fotos)-1)])
    logo=clean_logo(download_image(data.get("logo_url") or DEFAULT_LOGO_URL))

    canvas=Image.new("RGBA",(W,H),BLACK+(255,))
    d=ImageDraw.Draw(canvas)

    bg=fit_cover(hero,W,1230).filter(ImageFilter.GaussianBlur(24))
    bg=ImageEnhance.Brightness(bg).enhance(0.30)
    canvas.alpha_composite(bg,(0,0))
    d=ImageDraw.Draw(canvas)

    lg=fit_contain(logo,440,190)
    canvas.alpha_composite(lg,(42,38))

    txt(d,(1030,58),"SEMINOVOS",28,anchor="ra")
    txt(d,(1030,92),"DE QUALIDADE",24,anchor="ra")
    d.polygon([(1000,118),(1030,118),(1017,148),(987,148)],fill=RED)

    txt(d,(48,210),marca,42,RED,True)
    txt(d,(42,250),modelo,112,WHITE,True)
    d.rounded_rectangle((42,385,220,458),radius=8,fill=RED)
    txt(d,(130,420),ano,46,WHITE,True,anchor="mm")
    txt(d,(252,418),f"{cambio}  |  {combustivel}",38,WHITE,True,anchor="lm")
    txt(d,(48,495),"ESPAÇO, CONFORTO",34,WHITE,True)
    txt(d,(48,537),"E VERSATILIDADE",34,RED,True)

    hp=feather(fit_contain(hero,1020,760),58)
    canvas.alpha_composite(hp,((W-hp.width)//2,585))

    d.polygon([(0,1260),(W,1260),(W,1430),(0,1490)],fill=(7,7,8,235))
    d.line((0,1260,W,1260),fill=RED,width=4)

    features=["CONFORTO","ESPAÇO INTERNO","TECNOLOGIA","SEGURANÇA"]
    xs=[90,330,600,860]
    for i,(lab,xx) in enumerate(zip(features,xs)):
        d.rounded_rectangle((xx-36,1310,xx+36,1382),radius=14,outline=RED,width=3)
        txt(d,(xx,1410),lab,22,WHITE,True,anchor="ma")
        if i<3:
            d.line((xx+100,1305,xx+100,1438),fill=(120,0,0),width=2)

    d.polygon([(565,1175),(W,1175),(W,1495),(500,1495)],fill=(5,5,6,250))
    d.line((565,1175,500,1495),fill=RED,width=10)
    txt(d,(720,1210),"POR APENAS",28,WHITE,True)
    txt(d,(710,1260),"R$",46,RED,True)
    txt(d,(775,1285),preco,92,WHITE,True)
    d.rectangle((620,1390,1060,1470),fill=RED)
    txt(d,(840,1430),"FALE CONOSCO",34,WHITE,True,anchor="mm")

    d.rectangle((0,1510,W,H),fill=(5,5,6,255))
    txt(d,(42,1555),"DESTAQUES",42,WHITE,True)
    txt(d,(42,1602),"DO VEÍCULO",42,RED,True)

    opts=data.get("opcionais") or []
    shown=[str(x) for x in opts][:6] or [
        "Motor 1.6 Flex",
        f"Câmbio {cambio.title()}",
        "Ar Condicionado",
        "Airbags + ABS"
    ]

    yy=1665
    for item in shown[:6]:
        d.rounded_rectangle((42,yy,82,yy+40),radius=8,outline=RED,width=2)
        txt(d,(103,yy+20),item,23,WHITE,False,anchor="lm")
        yy+=49

    for im,pos in [
        (interior,(265,1535)),
        (traseira,(265,1685)),
        (lateral,(265,1835))
    ]:
        canvas.alpha_composite(fit_cover(im,265,145),pos)

    d.polygon([(540,1510),(W,1510),(W,H),(635,H)],fill=(9,9,10,255))
    d.line((620,1510,545,H),fill=RED,width=5)
    txt(d,(650,1555),"FICHA",42,WHITE,True)
    txt(d,(650,1602),"TÉCNICA",42,RED,True)

    specs=[
        ("ANO/MODELO",str(ano)),
        ("QUILOMETRAGEM",f"{km} KM" if km else ""),
        ("COMBUSTÍVEL",combustivel),
        ("CÂMBIO",cambio),
        ("COR",cor),
        ("PORTAS",f"{portas} PORTAS" if portas else "")
    ]

    yy=1660
    for k,v in specs:
        if not v:
            continue
        txt(d,(650,yy),k,18,GRAY,True)
        txt(d,(650,yy+24),v,25,WHITE,True)
        yy+=52

    d.rectangle((0,1870,W,H),fill=(0,0,0,255))
    txt(d,(42,1894),data.get("whatsapp","(51) 99573-4555"),24,WHITE,True)
    txt(d,(1040,1894),data.get("instagram","@premiumautomarcas"),24,WHITE,True,anchor="ra")

    return canvas

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
            "template":"story_01"
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status":"error","error":str(e)}),500
