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
FONT_REG = next((p for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"] if os.path.exists(p)), None)

SUPABASE_URL=os.environ.get("SUPABASE_URL","https://kbmryoeevdxvugcelflp.supabase.co").rstrip("/")
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
            if k!="body" and k not in d: d[k]=v
        return d
    return raw or {}


def dl(url):
    r=requests.get(url,timeout=40,headers={"User-Agent":"Mozilla/5.0"})
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGBA")


def cover(im,w,h):
    s=max(w/im.width,h/im.height)
    r=im.resize((int(im.width*s),int(im.height*s)),Image.Resampling.LANCZOS)
    x=max(0,(r.width-w)//2); y=max(0,(r.height-h)//2)
    return r.crop((x,y,x+w,y+h))


def contain(im,mw,mh):
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
    if v is None or str(v).strip()=="": return ""
    try: return f"{int(float(v)):,}".replace(",",".")
    except: return str(v)


def text(draw,xy,value,size,fill=WHITE,bold=True,anchor=None):
    draw.text(xy,str(value),font=F(size,bold),fill=fill,anchor=anchor)


def dark_box(im,box,alpha=235):
    ov=Image.new("RGBA",im.size,(0,0,0,0)); d=ImageDraw.Draw(ov)
    d.rectangle(box,fill=(0,0,0,alpha))
    im.alpha_composite(ov)


def paste_photo(im,photo,box,brightness=1.0):
    x1,y1,x2,y2=box; w=x2-x1; h=y2-y1
    p=cover(photo,w,h)
    if brightness!=1.0: p=ImageEnhance.Brightness(p).enhance(brightness)
    im.alpha_composite(p,(x1,y1))


def upload(img,job):
    if not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_KEY não configurada no Render.")
    bio=io.BytesIO(); img.convert("RGB").save(bio,format="PNG",optimize=True)
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
    if capa and capa not in fotos: fotos=[capa]+fotos
    fotos=[x for x in fotos if x]
    if not fotos: raise ValueError("Nenhuma foto recebida do Supabase.")

    hero=dl(fotos[0])
    interior=dl(fotos[min(5,len(fotos)-1)])
    traseira=dl(fotos[min(10,len(fotos)-1)])
    lateral=dl(fotos[min(3,len(fotos)-1)])

    if not TEMPLATE_PATH.exists():
        raise RuntimeError("post_template.png não encontrado no repositório.")
    im=Image.open(TEMPLATE_PATH).convert("RGBA")
    if im.size!=(W,H): im=im.resize((W,H),Image.Resampling.LANCZOS)

    # 1) FOTOS: substitui somente os slots do modelo aprovado.
    # Hero esquerdo: fundo real + foto inteira por cima.
    hero_bg=cover(hero,940,690).filter(ImageFilter.GaussianBlur(10))
    hero_bg=ImageEnhance.Brightness(hero_bg).enhance(.72)
    im.alpha_composite(hero_bg,(0,205))
    hero_fg=contain(hero,910,600)
    hero_fg=ImageEnhance.Contrast(hero_fg).enhance(1.05)
    hx=(940-hero_fg.width)//2
    im.alpha_composite(hero_fg,(hx,330))

    # Slots direitos respeitando a geometria do card aprovado.
    paste_photo(im,interior,(1220,0,1536,337),1.00)
    paste_photo(im,traseira,(1085,338,1536,610),1.00)
    paste_photo(im,lateral,(1120,696,1536,950),1.00)

    d=ImageDraw.Draw(im)

    # 2) TÍTULOS ESQUERDOS: máscara local e reescrita dinâmica.
    dark_box(im,(20,128,900,466),205); d=ImageDraw.Draw(im)
    # letras espaçadas da marca
    marca_spaced=" ".join(list(marca)) if len(marca)<=10 else marca
    text(d,(55,140),marca_spaced,38,RED,True)
    msize=118 if len(modelo)<=12 else 88
    text(d,(42,175),modelo,msize,WHITE,True)

    # ano e mecânica no mesmo alinhamento do aprovado
    d.polygon([(38,330),(205,330),(190,387),(25,387)],fill=RED)
    text(d,(112,360),ano,42,WHITE,True,anchor="mm")
    dark_box(im,(220,326,600,390),220); d=ImageDraw.Draw(im)
    text(d,(235,360),f"{cambio}  /  {combustivel}",33,WHITE,True,anchor="lm")
    text(d,(45,407),"ESPAÇO, CONFORTO",27,WHITE,True)
    text(d,(45,442),"E VERSATILIDADE",27,RED,True)

    # 3) PREÇO: preserva moldura/diagonal/botão do template; troca só valor.
    dark_box(im,(635,812,928,938),242); d=ImageDraw.Draw(im)
    text(d,(760,827),"POR APENAS",21,WHITE,True,anchor="ma")
    text(d,(642,870),"R$",40,RED,True)
    psize=72 if len(preco)<=6 else 62
    text(d,(700,850),preco,psize,WHITE,True)
    # botão
    d.rectangle((640,940,920,992),fill=RED)
    text(d,(780,966),"FALE CONOSCO",25,WHITE,True,anchor="mm")

    # 4) DESTAQUES: mantém título e ícones do template, substitui textos.
    # Apaga só as frases ao lado dos ícones.
    dark_box(im,(1022,94,1215,411),245); d=ImageDraw.Draw(im)
    opts=data.get("opcionais") or []
    if isinstance(opts,str): opts=[x.strip() for x in opts.split(",") if x.strip()]
    shown=[str(x) for x in opts][:8]
    if not shown:
        shown=["Motor 1.6 Flex",f"Câmbio {cambio.title()}","Direção Elétrica","Ar Condicionado","Vidros e Travas Elétricas","Rodas de Liga Leve","Central Multimídia","Airbags + ABS"]
    ys=[116,156,196,236,276,316,356,396]
    for item,y in zip(shown,ys):
        # reduz fonte automaticamente para caber na coluna estreita
        sz=16 if len(item)<=22 else 13
        text(d,(1025,y),item,sz,WHITE,False)

    # 5) FICHA: mantém rótulos/ícones, substitui apenas valores.
    dark_box(im,(1010,688,1120,940),242); d=ImageDraw.Draw(im)
    vals=[ano,f"{km} KM" if km else "",combustivel,cambio,cor,f"{portas} PORTAS" if portas else ""]
    ys=[715,755,795,835,875,915]
    for val,y in zip(vals,ys):
        if val: text(d,(1015,y),val,18,WHITE,True)

    # 6) CONTATO: permite valor do payload, mas mantém posição do modelo.
    whatsapp=str(data.get("whatsapp") or "(51) 99575-1376")
    instagram=str(data.get("instagram") or "@premiumautomarcas")
    dark_box(im,(988,956,1536,1024),245); d=ImageDraw.Draw(im)
    text(d,(1020,986),whatsapp,20,WHITE,True)
    text(d,(1515,986),instagram.upper(),18,WHITE,True,anchor="ra")

    return im


@post_bp.get("/post-health")
def post_health():
    return {
        "ok":True,
        "service":"premium-post-renderer",
        "template":"approved-reference",
        "size":"1536x1024",
        "template_found":TEMPLATE_PATH.exists(),
        "supabase":{"configured":bool(SUPABASE_SERVICE_KEY),"bucket":SUPABASE_BUCKET,"folder":SUPABASE_POSTS_FOLDER}
    }


@post_bp.post("/post")
def post():
    try:
        raw=request.get_json(force=True); data=normalize(raw)
        img=render_post(data); job=uuid.uuid4().hex; url=upload(img,job)
        return jsonify({"status":"done","id":job,"url":url,"post_url":url,"template":"post_aprovado_fiel","source_price":data.get("preco")})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"status":"error","error":str(e)}),500
