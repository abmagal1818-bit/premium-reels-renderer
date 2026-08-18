
from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from pathlib import Path
import requests, uuid, os, io

post_bp = Blueprint("post_bp", __name__)
BASE = Path(__file__).parent
TEMPLATE_PATH = BASE / "post_template.png"

W, H = 1536, 1024
RED=(235,25,34); WHITE=(248,248,248); BLACK=(4,4,5); GRAY=(175,175,175)

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
SUPABASE_POSTS_FOLDER=os.environ.get("SUPABASE_POSTS_FOLDER","posts")

def F(size,bold=False):
    p=FONT_BOLD if bold else FONT_REG
    return ImageFont.truetype(p,size) if p else ImageFont.load_default()

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

def cover(im,w,h,focus_y=.5):
    s=max(w/im.width,h/im.height)
    r=im.resize((int(im.width*s),int(im.height*s)),Image.Resampling.LANCZOS)
    x=max(0,(r.width-w)//2)
    max_y=max(0,r.height-h)
    y=int(max_y*focus_y)
    return r.crop((x,y,x+w,y+h))

def fit(im,mw,mh):
    s=min(mw/im.width,mh/im.height)
    return im.resize((max(1,int(im.width*s)),max(1,int(im.height*s))),Image.Resampling.LANCZOS)

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

def put_text(d,xy,value,size,fill=WHITE,bold=True,anchor=None):
    d.text(xy,str(value),font=F(size,bold),fill=fill,anchor=anchor)

def erase(im,box,fill=(5,5,6,255)):
    ImageDraw.Draw(im).rectangle(box,fill=fill)

def paste_photo(im,photo,box,focus_y=.5):
    x1,y1,x2,y2=box
    p=cover(photo,x2-x1,y2-y1,focus_y)
    im.alpha_composite(p,(x1,y1))

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
        raise RuntimeError("post_template.png não encontrado no repositório.")

    im=Image.open(TEMPLATE_PATH).convert("RGBA")
    if im.size!=(W,H):
        im=im.resize((W,H),Image.Resampling.LANCZOS)

    # =========================================================
    # FOTOS — usa exatamente os espaços visuais do modelo aprovado
    # =========================================================

    # Foto principal: ocupa a mesma grande área da esquerda.
    # Primeiro um fundo da própria foto, depois uma leve sombra nas bordas.
    hero_box=(0,278,940,888)
    hero_img=cover(hero,940,610,.48)
    hero_img=ImageEnhance.Contrast(hero_img).enhance(1.03)
    hero_img=ImageEnhance.Brightness(hero_img).enhance(.96)

    vignette=Image.new("RGBA",(940,610),(0,0,0,0))
    vd=ImageDraw.Draw(vignette)
    for i in range(65):
        a=int(95*(1-i/65)**1.7)
        vd.rectangle((i,i,939-i,609-i),outline=(0,0,0,a),width=2)
    hero_img=Image.alpha_composite(hero_img,vignette)
    im.alpha_composite(hero_img,(0,278))

    # Fotos da coluna direita nas mesmas faixas do card.
    paste_photo(im,interior,(1220,0,1536,335),.50)
    paste_photo(im,traseira,(1088,338,1536,610),.50)
    paste_photo(im,lateral,(1088,706,1536,949),.52)

    # Redesenha as linhas vermelhas separadoras que ficam por cima das fotos.
    d=ImageDraw.Draw(im)
    d.line((1225,0,1127,335),fill=RED,width=5)
    d.line((1146,338,1060,610),fill=RED,width=5)
    d.line((1155,610,1060,949),fill=RED,width=5)

    # =========================================================
    # CABEÇALHO — apaga só os textos antigos, sem criar um painel gigante
    # =========================================================
    erase(im,(42,136,380,176),(4,4,5,245))    # CITROEN antigo
    erase(im,(38,178,720,322),(4,4,5,245))    # modelo antigo
    erase(im,(28,328,210,391),(4,4,5,245))    # ano antigo
    erase(im,(225,333,555,388),(4,4,5,245))   # manual/flex
    erase(im,(40,398,315,472),(4,4,5,225))    # slogan

    d=ImageDraw.Draw(im)
    marca_spaced=" ".join(list(marca)) if len(marca)<=10 else marca
    put_text(d,(58,140),marca_spaced,36,RED,True)

    # tamanho próximo ao card original; não extrapola o bloco.
    msize=112 if len(modelo)<=10 else 98 if len(modelo)<=13 else 78
    put_text(d,(42,177),modelo,msize,WHITE,True)

    # caixa de ano no mesmo formato do original
    d.polygon([(34,331),(210,331),(197,389),(22,389)],fill=RED)
    put_text(d,(112,360),ano,42,WHITE,True,anchor="mm")

    put_text(d,(236,360),f"{cambio}  /  {combustivel}",31,WHITE,True,anchor="lm")
    put_text(d,(45,405),"ESPAÇO, CONFORTO",27,WHITE,True)
    put_text(d,(45,441),"E VERSATILIDADE",27,RED,True)

    # =========================================================
    # PREÇO — troca somente os números, preservando o design do template
    # =========================================================
    erase(im,(650,824,915,930),(5,5,6,250))
    d=ImageDraw.Draw(im)

    # "POR APENAS" permanece praticamente no mesmo lugar.
    put_text(d,(785,834),"POR APENAS",20,WHITE,True,anchor="ma")
    put_text(d,(650,874),"R$",39,RED,True)

    psize=70 if len(preco)<=6 else 60
    put_text(d,(712,852),preco,psize,WHITE,True)

    # =========================================================
    # DESTAQUES — preserva título e ícones; muda só a descrição
    # =========================================================
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

    # cobre só a coluna de frases, nunca os ícones/título
    erase(im,(1021,100,1158,412),(5,5,6,248))
    d=ImageDraw.Draw(im)
    ys=[116,156,196,236,276,316,356,396]
    for item,y in zip(shown,ys):
        sz=15 if len(item)<=20 else 13
        put_text(d,(1028,y),item,sz,WHITE,False)

    # =========================================================
    # FICHA TÉCNICA — preserva rótulos e ícones; troca os valores
    # =========================================================
    # pequenas máscaras em cada valor
    value_boxes=[
        (1010,700,1080,727),
        (1010,740,1095,767),
        (1010,780,1085,807),
        (1010,820,1085,847),
        (1010,860,1085,887),
        (1010,900,1105,932),
    ]
    vals=[
        ano,
        f"{km} KM" if km else "",
        combustivel,
        cambio,
        cor,
        f"{portas} PORTAS" if portas else ""
    ]

    for box in value_boxes:
        erase(im,box,(5,5,6,250))

    d=ImageDraw.Draw(im)
    ys=[707,747,787,827,867,907]
    for val,y in zip(vals,ys):
        if val:
            put_text(d,(1012,y),val,17,WHITE,True)

    # =========================================================
    # CONTATO — troca apenas se payload enviar; mantém estrutura original
    # =========================================================
    whatsapp=str(data.get("whatsapp") or "(51) 99575-1376")
    instagram=str(data.get("instagram") or "@premiumautomarcas")

    erase(im,(1005,957,1225,1020),(0,0,0,250))
    erase(im,(1260,957,1535,1020),(0,0,0,250))
    d=ImageDraw.Draw(im)
    put_text(d,(1025,980),whatsapp,18,WHITE,True)
    put_text(d,(1510,980),instagram.upper(),17,WHITE,True,anchor="ra")

    return im

@post_bp.get("/post-health")
def post_health():
    return {
        "ok":True,
        "service":"premium-post-renderer",
        "template":"approved-reference-v2",
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
            "template":"post_aprovado_fiel_v2",
            "source_price":data.get("preco")
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status":"error","error":str(e)}),500
