from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import requests, uuid, os, io

post_bp = Blueprint("post_bp", __name__)

W, H = 1536, 1024
LEFT_W = 938
RIGHT_X = LEFT_W

RED=(235,25,34)
WHITE=(248,248,248)
BLACK=(3,3,4)
GRAY=(175,175,175)

FONT_COND = next((p for p in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
] if os.path.exists(p)), None)
FONT_REG = next((p for p in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
] if os.path.exists(p)), None)

SUPABASE_URL=os.environ.get("SUPABASE_URL","https://kbmryoeevdxvugcelflp.supabase.co").rstrip("/")
SUPABASE_BUCKET=os.environ.get("SUPABASE_BUCKET","veiculos")
SUPABASE_SERVICE_KEY=os.environ.get("SUPABASE_SERVICE_KEY","")
SUPABASE_POSTS_FOLDER=os.environ.get("SUPABASE_POSTS_FOLDER","posts")
DEFAULT_LOGO_URL=os.environ.get(
    "PREMIUM_LOGO_URL",
    "https://kbmryoeevdxvugcelflp.supabase.co/storage/v1/object/public/veiculos/Musicas/Logo%20minimalista%20de%20carro%20esportivo.png"
)

def F(size,bold=True):
    p = FONT_COND if bold else FONT_REG
    return ImageFont.truetype(p,size) if p else ImageFont.load_default()

def txt(d,xy,val,size,fill=WHITE,bold=True,anchor=None):
    d.text(xy,str(val),font=F(size,bold),fill=fill,anchor=anchor)

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

def fit_cover(im,w,h,focus_x=.5,focus_y=.5):
    s=max(w/im.width,h/im.height)
    r=im.resize((int(im.width*s),int(im.height*s)),Image.Resampling.LANCZOS)
    max_x=max(0,r.width-w); max_y=max(0,r.height-h)
    x=int(max_x*focus_x); y=int(max_y*focus_y)
    return r.crop((x,y,x+w,y+h))

def fit_contain(im,mw,mh):
    s=min(mw/im.width,mh/im.height)
    return im.resize((max(1,int(im.width*s)),max(1,int(im.height*s))),Image.Resampling.LANCZOS)

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
    url=f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{name}"
    headers={
        "Authorization":f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey":SUPABASE_SERVICE_KEY,
        "Content-Type":"image/png",
        "x-upsert":"true",
        "cache-control":"3600"
    }
    r=requests.post(url,headers=headers,data=bio.getvalue(),timeout=180)
    if r.status_code not in (200,201):
        raise RuntimeError(f"Falha upload Post HTTP {r.status_code}: {r.text[:800]}")
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{name}"

def draw_icon(d,x,y,kind):
    # 34x34 outline icon inside a small red square — same visual weight as approved reference.
    d.rounded_rectangle((x,y,x+34,y+34),radius=6,outline=RED,width=2)
    if kind=="calendar":
        d.line((x+7,y+11,x+27,y+11),fill=RED,width=2)
        d.line((x+10,y+6,x+10,y+13),fill=RED,width=2)
        d.line((x+24,y+6,x+24,y+13),fill=RED,width=2)
    elif kind=="speed":
        d.arc((x+7,y+8,x+27,y+28),180,355,fill=RED,width=2)
        d.line((x+17,y+20,x+24,y+13),fill=RED,width=2)
    elif kind=="fuel":
        d.rectangle((x+9,y+8,x+21,y+27),outline=RED,width=2)
        d.line((x+21,y+12,x+27,y+17),fill=RED,width=2)
    elif kind=="gear":
        d.ellipse((x+10,y+10,x+24,y+24),outline=RED,width=2)
    elif kind=="color":
        d.arc((x+8,y+8,x+26,y+26),20,330,fill=RED,width=2)
    elif kind=="door":
        d.rectangle((x+10,y+7,x+24,y+27),outline=RED,width=2)

def vignette_overlay(size, strength=120, edge=95):
    w,h=size
    ov=Image.new("RGBA",(w,h),(0,0,0,0))
    d=ImageDraw.Draw(ov)
    for i in range(edge):
        a=int(strength*(1-i/edge)**1.7)
        d.rectangle((i,i,w-1-i,h-1-i),outline=(0,0,0,a),width=2)
    return ov

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
    logo=clean_logo(dl(data.get("logo_url") or DEFAULT_LOGO_URL))

    # =========================================================
    # CANVAS / FOTO PRINCIPAL
    # =========================================================
    canvas=Image.new("RGBA",(W,H),BLACK+(255,))

    # A referência aprovada usa a foto principal como fundo de toda a área esquerda.
    hero_bg=fit_cover(hero,LEFT_W,H,.50,.48)
    hero_bg=ImageEnhance.Contrast(hero_bg).enhance(1.06)
    hero_bg=ImageEnhance.Brightness(hero_bg).enhance(.90)
    canvas.alpha_composite(hero_bg,(0,0))

    # sombreado/vinheta da referência, sem "caixas" artificiais
    canvas.alpha_composite(vignette_overlay((LEFT_W,H),135,110),(0,0))

    # topo escurecido para leitura
    top_grad=Image.new("RGBA",(LEFT_W,470),(0,0,0,0))
    tg=ImageDraw.Draw(top_grad)
    for y in range(470):
        a=int(205*(1-y/470)**.35)
        tg.line((0,y,LEFT_W,y),fill=(0,0,0,a))
    canvas.alpha_composite(top_grad,(0,0))

    # rodapé levemente escurecido
    foot=Image.new("RGBA",(LEFT_W,175),(0,0,0,155))
    canvas.alpha_composite(foot,(0,849))

    d=ImageDraw.Draw(canvas)

    # =========================================================
    # LOGO / CABEÇALHO
    # =========================================================
    lg=fit_contain(logo,420,145)
    canvas.alpha_composite(lg,(30,12))

    txt(d,(885,30),"S E M I N O V O S",18,WHITE,False,anchor="ra")
    txt(d,(885,58),"D E  Q U A L I D A D E",16,WHITE,False,anchor="ra")
    d.polygon([(855,76),(888,76),(875,108),(842,108)],fill=RED)

    # Marca com espaçamento visual
    marca_spaced=" ".join(list(marca)) if len(marca)<=10 else marca
    txt(d,(42,140),marca_spaced,36,RED,True)

    # Modelo
    model_size=116 if len(modelo)<=10 else 102 if len(modelo)<=13 else 82
    txt(d,(35,178),modelo,model_size,WHITE,True)

    # ano e mecânica
    d.polygon([(34,329),(210,329),(197,389),(22,389)],fill=RED)
    txt(d,(112,359),ano,42,WHITE,True,anchor="mm")
    txt(d,(235,360),f"{cambio}  /  {combustivel}",31,WHITE,True,anchor="lm")

    txt(d,(42,405),"ESPAÇO, CONFORTO",27,WHITE,True)
    txt(d,(42,439),"E VERSATILIDADE",27,RED,True)

    # =========================================================
    # BENEFÍCIOS
    # =========================================================
    benefit_y=918
    centers=[72,185,298,411]
    labels=["CONFORTO","ESPAÇO\nINTERNO","TECNOLOGIA","SEGURANÇA"]
    for i,(cx,lab) in enumerate(zip(centers,labels)):
        d.rounded_rectangle((cx-14,benefit_y-26,cx+14,benefit_y+2),radius=6,outline=RED,width=2)
        txt(d,(cx,benefit_y+24),lab,14,WHITE,True,anchor="ma")
        if i<3:
            d.line((cx+54,benefit_y-28,cx+54,benefit_y+52),fill=(125,0,0),width=2)

    # =========================================================
    # PREÇO
    # =========================================================
    # bloco diagonal exatamente no canto inferior direito do painel esquerdo
    d.polygon([(628,815),(LEFT_W,815),(LEFT_W,1024),(555,1024)],fill=(4,4,5,248))
    d.line((628,815,555,1024),fill=RED,width=8)

    txt(d,(785,835),"POR APENAS",20,WHITE,True,anchor="ma")
    txt(d,(635,880),"R$",40,RED,True)
    txt(d,(700,856),preco,74,WHITE,True)
    d.rectangle((655,947,920,995),fill=RED)
    txt(d,(787,971),"FALE CONOSCO",22,WHITE,True,anchor="mm")

    # =========================================================
    # COLUNA DIREITA
    # =========================================================
    d.rectangle((RIGHT_X,0,W,H),fill=(5,5,6,255))

    # Destaques — coluna texto
    txt(d,(965,28),"DESTAQUES",34,WHITE,True)
    txt(d,(965,64),"DO VEÍCULO",34,RED,True)

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

    yy=112
    for item in shown[:8]:
        d.rounded_rectangle((965,yy-5,995,yy+25),radius=5,outline=RED,width=2)
        txt(d,(1010,yy+10),item,15,WHITE,False,anchor="lm")
        yy+=40

    # Foto interior direita superior
    interior_box=(1210,0,1536,335)
    canvas.alpha_composite(fit_cover(interior,326,335,.5,.50),(1210,0))
    d.line((1210,0,1117,335),fill=RED,width=5)

    # Foto traseira no meio
    mid_box=(1060,338,1536,610)
    canvas.alpha_composite(fit_cover(traseira,476,272,.50,.50),(1060,338))
    d.line((1148,338,1060,610),fill=RED,width=5)

    # =========================================================
    # FICHA TÉCNICA
    # =========================================================
    txt(d,(965,625),"FICHA",34,WHITE,True)
    txt(d,(965,662),"TÉCNICA",34,RED,True)

    specs=[
        ("ANO/MODELO",ano,"calendar"),
        ("QUILOMETRAGEM",f"{km} KM" if km else "","speed"),
        ("COMBUSTÍVEL",combustivel,"fuel"),
        ("CÂMBIO",cambio,"gear"),
        ("COR",cor,"color"),
        ("PORTAS",f"{portas} PORTAS" if portas else "","door"),
    ]

    sy=708
    for k,v,kind in specs:
        if not v:
            continue
        draw_icon(d,965,sy-10,kind)
        txt(d,(1012,sy-2),k,11,GRAY,True)
        txt(d,(1012,sy+16),v,17,WHITE,True)
        sy+=47

    # Foto lateral inferior direita
    canvas.alpha_composite(fit_cover(lateral,410,244,.50,.50),(1126,706))
    d.line((1155,610,1062,950),fill=RED,width=5)

    # =========================================================
    # RODAPÉ DIREITO
    # =========================================================
    d.rectangle((RIGHT_X,952,W,H),fill=(0,0,0,255))
    whatsapp=str(data.get("whatsapp") or "(51) 99575-1376")
    instagram=str(data.get("instagram") or "@premiumautomarcas")

    txt(d,(970,986),whatsapp,17,WHITE,True)
    txt(d,(1510,986),instagram.upper(),16,WHITE,True,anchor="ra")

    return canvas

@post_bp.get("/post-health")
def post_health():
    return {
        "ok":True,
        "service":"premium-post-renderer",
        "template":"approved-layout-v3",
        "size":"1536x1024",
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
            "template":"post_aprovado_v3",
            "source_price":data.get("preco")
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status":"error","error":str(e)}),500
