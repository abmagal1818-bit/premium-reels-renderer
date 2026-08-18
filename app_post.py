from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from pathlib import Path
import requests, uuid, os, io

post_bp = Blueprint("post_bp", __name__)

BASE = Path(__file__).parent
TEMPLATE_PATH = BASE / "post_template.png"

W, H = 1536, 1024
RED = (235,25,34)
WHITE = (248,248,248)
BLACK = (4,4,5)
GRAY = (175,175,175)

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
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET","veiculos")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY","")
SUPABASE_POSTS_FOLDER = os.environ.get("SUPABASE_POSTS_FOLDER","posts")

def F(size,bold=False):
    p = FONT_BOLD if bold else FONT_REG
    return ImageFont.truetype(p,size) if p else ImageFont.load_default()

def txt(d,xy,value,size,fill=WHITE,bold=False,anchor=None):
    d.text(xy,str(value),font=F(size,bold),fill=fill,anchor=anchor)

def normalize(raw):
    if isinstance(raw,dict) and isinstance(raw.get("body"),dict):
        d=dict(raw["body"])
        for k,v in raw.items():
            if k!="body" and k not in d:
                d[k]=v
        return d
    return raw or {}

def dl(url):
    r=requests.get(url,timeout=40,headers={"User-Agent":"Mozilla/5.0"})
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGBA")

def fit_cover(im,w,h,fx=.5,fy=.5):
    s=max(w/im.width,h/im.height)
    r=im.resize((int(im.width*s),int(im.height*s)),Image.Resampling.LANCZOS)
    mx=max(0,r.width-w); my=max(0,r.height-h)
    x=int(mx*fx); y=int(my*fy)
    return r.crop((x,y,x+w,y+h))

def fit_contain(im,mw,mh):
    s=min(mw/im.width,mh/im.height)
    return im.resize(
        (max(1,int(im.width*s)),max(1,int(im.height*s))),
        Image.Resampling.LANCZOS
    )

def fmt_price(v):
    if v is None or str(v).strip()=="":
        raise ValueError("Campo 'preco' não recebido do Supabase.")
    s=str(v).strip().replace("R$","").replace(" ","")
    if "," in s:
        n=float(s.replace(".","").replace(",","."))
    elif s.count(".")==1 and len(s.split(".")[1])==3:
        n=float(s.replace(".",""))
    else:
        n=float(s)
    return f"{int(round(n)):,}".replace(",",".")

def fmt_km(v):
    if v is None or str(v).strip()=="":
        return ""
    try:
        return f"{int(float(v)):,}".replace(",",".")
    except:
        return str(v)

def upload(img,job):
    if not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_KEY não configurada no Render.")

    bio=io.BytesIO()
    img.convert("RGB").save(bio,format="PNG",optimize=True)

    name=f"{SUPABASE_POSTS_FOLDER}/{job}.png"
    upload_url=f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{name}"

    headers={
        "Authorization":f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey":SUPABASE_SERVICE_KEY,
        "Content-Type":"image/png",
        "x-upsert":"true",
        "cache-control":"3600"
    }

    r=requests.post(upload_url,headers=headers,data=bio.getvalue(),timeout=180)
    if r.status_code not in (200,201):
        raise RuntimeError(f"Falha upload Post HTTP {r.status_code}: {r.text[:800]}")

    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{name}"

def dark_patch(im,box,alpha=245):
    x1,y1,x2,y2=box
    patch=Image.new("RGBA",(x2-x1,y2-y1),(4,4,5,alpha))
    im.alpha_composite(patch,(x1,y1))

def image_with_dark_edges(photo,w,h,fx=.5,fy=.5):
    p=fit_cover(photo,w,h,fx,fy)
    p=ImageEnhance.Contrast(p).enhance(1.03)
    p=ImageEnhance.Brightness(p).enhance(.96)

    shade=Image.new("RGBA",(w,h),(0,0,0,0))
    sd=ImageDraw.Draw(shade)
    edge=55
    for i in range(edge):
        a=int(95*(1-i/edge)**1.6)
        sd.rectangle((i,i,w-1-i,h-1-i),outline=(0,0,0,a),width=2)
    return Image.alpha_composite(p,shade)

def render_post(raw):
    data=normalize(raw)

    marca=str(data.get("marca","")).upper()
    modelo=str(data.get("modelo","")).upper()
    ano=str(data.get("ano_modelo") or data.get("ano") or "")
    km=fmt_km(data.get("km"))
    cambio=str(data.get("cambio","")).upper()
    combustivel=str(data.get("combustivel","")).upper()
    cor=str(data.get("cor","")).upper()
    portas=str(data.get("portas","") or "")
    preco=fmt_price(data.get("preco"))

    fotos=data.get("fotos") or []
    capa=data.get("foto_capa")
    if capa and capa not in fotos:
        fotos=[capa]+fotos
    fotos=[x for x in fotos if x]
    if not fotos:
        raise ValueError("Nenhuma foto recebida do Supabase.")

    hero=dl(fotos[0])
    interior=dl(fotos[min(5,len(fotos)-1)])
    traseira=dl(fotos[min(10,len(fotos)-1)])
    lateral=dl(fotos[min(3,len(fotos)-1)])

    if not TEMPLATE_PATH.exists():
        raise RuntimeError("post_template.png não encontrado.")

    # O modelo aprovado é a própria base.
    im=Image.open(TEMPLATE_PATH).convert("RGBA")
    if im.size!=(W,H):
        im=im.resize((W,H),Image.Resampling.LANCZOS)

    # ============================================================
    # 1. FOTO PRINCIPAL
    # Mantém exatamente a geometria do modelo: grande área esquerda,
    # carro inteiro, sem zoom exagerado.
    # ============================================================
    main_box=(0,278,938,900)
    x1,y1,x2,y2=main_box
    mw,mh=x2-x1,y2-y1

    # Fundo natural da própria foto.
    back=fit_cover(hero,mw,mh,.50,.48)
    back=ImageEnhance.Brightness(back).enhance(.75)
    back=ImageEnhance.Contrast(back).enhance(1.02)
    im.alpha_composite(back,(x1,y1))

    # Carro/foto inteira por cima, usando contain para evitar cortes.
    fg=fit_contain(hero,900,595)
    fg=ImageEnhance.Contrast(fg).enhance(1.04)
    fg=ImageEnhance.Brightness(fg).enhance(.98)

    fx=x1+(mw-fg.width)//2
    fy=y1+(mh-fg.height)//2+8

    # sombra suave
    shadow=Image.new("RGBA",(fg.width+50,fg.height+50),(0,0,0,0))
    sh=ImageDraw.Draw(shadow)
    sh.rounded_rectangle(
        (25,25,fg.width+25,fg.height+25),
        radius=25,
        fill=(0,0,0,70)
    )
    shadow=shadow.filter(ImageFilter.GaussianBlur(18))
    im.alpha_composite(shadow,(fx-25,fy-25))
    im.alpha_composite(fg,(fx,fy))

    # vinheta leve para integração igual ao card aprovado
    edge=Image.new("RGBA",(mw,mh),(0,0,0,0))
    ed=ImageDraw.Draw(edge)
    for i in range(70):
        a=int(100*(1-i/70)**1.5)
        ed.rectangle((i,i,mw-1-i,mh-1-i),outline=(0,0,0,a),width=2)
    im.alpha_composite(edge,(x1,y1))

    # ============================================================
    # 2. FOTOS DIREITAS — mesmas regiões do modelo aprovado
    # ============================================================
    # Interior
    im.alpha_composite(image_with_dark_edges(interior,330,335,.50,.48),(1206,0))
    # restaura coluna preta à esquerda da diagonal
    d=ImageDraw.Draw(im)
    d.polygon([(938,0),(1226,0),(1127,335),(938,335)],fill=(4,4,5,252))
    d.line((1226,0,1127,335),fill=RED,width=5)

    # Traseira
    im.alpha_composite(image_with_dark_edges(traseira,440,274,.50,.50),(1096,336))
    d=ImageDraw.Draw(im)
    d.polygon([(938,336),(1145,336),(1060,610),(938,610)],fill=(4,4,5,252))
    d.line((1145,336,1060,610),fill=RED,width=5)

    # Lateral inferior
    im.alpha_composite(image_with_dark_edges(lateral,455,240,.50,.50),(1081,710))
    d=ImageDraw.Draw(im)
    d.polygon([(938,610),(1155,610),(1064,950),(938,950)],fill=(4,4,5,252))
    d.line((1155,610,1064,950),fill=RED,width=5)

    # ============================================================
    # 3. CABEÇALHO DINÂMICO
    # Apaga apenas os textos variáveis; logo e decoração permanecem.
    # ============================================================
    dark_patch(im,(38,135,405,178),245)
    dark_patch(im,(35,178,710,325),245)
    dark_patch(im,(20,328,570,472),238)

    d=ImageDraw.Draw(im)

    marca_spaced=" ".join(list(marca)) if len(marca)<=10 else marca
    txt(d,(58,140),marca_spaced,34,RED,True)

    model_size=110 if len(modelo)<=10 else 96 if len(modelo)<=13 else 78
    txt(d,(42,178),modelo,model_size,WHITE,True)

    d.polygon([(34,330),(210,330),(198,389),(22,389)],fill=RED)
    txt(d,(112,359),ano,40,WHITE,True,anchor="mm")
    txt(d,(236,359),f"{cambio}  /  {combustivel}",30,WHITE,True,anchor="lm")

    txt(d,(44,406),"ESPAÇO, CONFORTO",26,WHITE,True)
    txt(d,(44,440),"E VERSATILIDADE",26,RED,True)

    # ============================================================
    # 4. PREÇO
    # Preserva a área diagonal e troca somente o conteúdo.
    # ============================================================
    d.polygon([(635,804),(938,804),(938,1024),(560,1024)],fill=(4,4,5,250))
    d.line((635,804,560,1024),fill=RED,width=8)

    txt(d,(790,823),"POR APENAS",20,WHITE,True,anchor="ma")
    txt(d,(645,860),"R$",38,RED,True)

    psize=70 if len(preco)<=6 else 60
    txt(d,(708,843),preco,psize,WHITE,True)

    d.rectangle((650,945,925,995),fill=RED)
    txt(d,(787,970),"FALE CONOSCO",22,WHITE,True,anchor="mm")

    # ============================================================
    # 5. DESTAQUES
    # Mantém título/ícones do modelo e troca somente frases.
    # ============================================================
    opts=data.get("opcionais") or []
    if isinstance(opts,str):
        opts=[x.strip() for x in opts.split(",") if x.strip()]
    shown=[str(x) for x in opts][:8]

    if not shown:
        shown=[
            "Motor 1.6 Flex",
            f"Câmbio {cambio.title()}",
            "Direção Elétrica",
            "Ar Condicionado",
            "Vidros e Travas Elétricas",
            "Rodas de Liga Leve",
            "Central Multimídia",
            "Airbags + ABS"
        ]

    # Região somente das descrições
    dark_patch(im,(1015,95,1128,420),252)
    d=ImageDraw.Draw(im)

    ys=[116,156,196,236,276,316,356,396]
    for item,y in zip(shown,ys):
        size=14 if len(item)<=22 else 12
        txt(d,(1020,y),item,size,WHITE,False)

    # ============================================================
    # 6. FICHA TÉCNICA
    # Mantém ícones e rótulos do template, troca somente valores.
    # ============================================================
    values=[
        ano,
        f"{km} KM" if km else "",
        combustivel,
        cambio,
        cor,
        f"{portas} PORTAS" if portas else ""
    ]

    # Máscaras pequenas, uma por valor.
    value_boxes=[
        (1015,692,1095,720),
        (1015,732,1110,760),
        (1015,772,1095,800),
        (1015,812,1095,840),
        (1015,852,1095,880),
        (1015,892,1115,925)
    ]
    for box in value_boxes:
        dark_patch(im,box,252)

    d=ImageDraw.Draw(im)
    ys=[700,740,780,820,860,900]
    for val,y in zip(values,ys):
        if val:
            txt(d,(1017,y),val,16,WHITE,True)

    # ============================================================
    # 7. CONTATO
    # ============================================================
    whatsapp=str(data.get("whatsapp") or "(51) 99575-1376")
    instagram=str(data.get("instagram") or "@premiumautomarcas")

    dark_patch(im,(1000,955,1230,1024),255)
    dark_patch(im,(1245,955,1536,1024),255)
    d=ImageDraw.Draw(im)
    txt(d,(1020,978),whatsapp,17,WHITE,True)
    txt(d,(1510,978),instagram.upper(),16,WHITE,True,anchor="ra")

    return im

@post_bp.get("/post-health")
def post_health():
    return {
        "ok":True,
        "service":"premium-post-renderer",
        "template":"approved-reference-v4",
        "size":"1536x1024",
        "template_found":TEMPLATE_PATH.exists(),
        "supabase":{
            "configured":bool(SUPABASE_SERVICE_KEY),
            "bucket":SUPABASE_BUCKET,
            "folder":SUPABASE_POSTS_FOLDER
        }
    }

@post_bp.post("/post")
def post():
    try:
        raw=request.get_json(force=True)
        data=normalize(raw)
        img=render_post(data)
        job=uuid.uuid4().hex
        url=upload(img,job)

        return jsonify({
            "status":"done",
            "id":job,
            "url":url,
            "post_url":url,
            "template":"post_aprovado_v4",
            "source_price":data.get("preco")
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status":"error","error":str(e)}),500
