from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import requests, uuid, os, io

post_bp = Blueprint("post_bp", __name__)
W,H = 1536,1024
RED=(235,25,34); WHITE=(248,248,248); BLACK=(4,4,5); GRAY=(168,168,168)

FONT_BOLD=next((p for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if os.path.exists(p)),None)
FONT_REG=next((p for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"] if os.path.exists(p)),None)

SUPABASE_URL=os.environ.get("SUPABASE_URL","https://kbmryoeevdxvugcelflp.supabase.co").rstrip("/")
SUPABASE_BUCKET=os.environ.get("SUPABASE_BUCKET","veiculos")
SUPABASE_SERVICE_KEY=os.environ.get("SUPABASE_SERVICE_KEY","")
SUPABASE_POSTS_FOLDER=os.environ.get("SUPABASE_POSTS_FOLDER","posts")
DEFAULT_LOGO_URL=os.environ.get("PREMIUM_LOGO_URL","https://kbmryoeevdxvugcelflp.supabase.co/storage/v1/object/public/veiculos/Musicas/Logo%20minimalista%20de%20carro%20esportivo.png")

def F(size,bold=False):
    p=FONT_BOLD if bold else FONT_REG
    return ImageFont.truetype(p,size) if p else ImageFont.load_default()

def txt(d,xy,val,size,fill=WHITE,bold=False,anchor=None):
    d.text(xy,str(val),font=F(size,bold),fill=fill,anchor=anchor)

def normalize_payload(raw):
    if isinstance(raw,dict) and isinstance(raw.get("body"),dict):
        d=dict(raw["body"])
        for k,v in raw.items():
            if k!="body" and k not in d: d[k]=v
        return d
    return raw or {}

def dl(url):
    r=requests.get(url,timeout=40,headers={"User-Agent":"Mozilla/5.0"}); r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGBA")

def cover(im,w,h):
    s=max(w/im.width,h/im.height)
    r=im.resize((int(im.width*s),int(im.height*s)),Image.Resampling.LANCZOS)
    x=(r.width-w)//2; y=(r.height-h)//2
    return r.crop((x,y,x+w,y+h))

def contain(im,mw,mh):
    s=min(mw/im.width,mh/im.height)
    return im.resize((int(im.width*s),int(im.height*s)),Image.Resampling.LANCZOS)

def clean_logo(logo):
    px=logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r,g,b,a=px[x,y]
            if max(r,g,b)<18: px[x,y]=(r,g,b,0)
    bb=logo.getbbox()
    return logo.crop(bb) if bb else logo

def soft(im):
    mask=Image.new("L",im.size,0); d=ImageDraw.Draw(mask)
    d.rounded_rectangle((28,28,im.width-28,im.height-28),radius=28,fill=255)
    mask=mask.filter(ImageFilter.GaussianBlur(14)); im.putalpha(mask)
    return im

def fmt_price(v):
    if v is None or str(v).strip()=="":
        raise ValueError("Campo 'preco' não recebido do Supabase.")
    s=str(v).strip().replace("R$","").replace(" ","")
    if "," in s: n=float(s.replace(".","").replace(",","."))
    elif s.count(".")==1 and len(s.split(".")[1])==3: n=float(s.replace(".",""))
    else: n=float(s)
    return f"{int(round(n)):,}".replace(",",".")

def fmt_km(v):
    if v is None or str(v).strip()=="": return ""
    try: return f"{int(float(v)):,}".replace(",",".")
    except: return str(v)

def upload(img,job):
    if not SUPABASE_SERVICE_KEY: raise RuntimeError("SUPABASE_SERVICE_KEY não configurada no Render.")
    bio=io.BytesIO(); img.convert("RGB").save(bio,format="PNG",optimize=True)
    name=f"{SUPABASE_POSTS_FOLDER}/{job}.png"
    url=f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{name}"
    h={"Authorization":f"Bearer {SUPABASE_SERVICE_KEY}","apikey":SUPABASE_SERVICE_KEY,"Content-Type":"image/png","x-upsert":"true","cache-control":"3600"}
    r=requests.post(url,headers=h,data=bio.getvalue(),timeout=180)
    if r.status_code not in (200,201): raise RuntimeError(f"Falha upload Post HTTP {r.status_code}: {r.text[:800]}")
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{name}"

def icon_box(d,x,y):
    d.rounded_rectangle((x,y,x+36,y+36),radius=7,outline=RED,width=3)

def render_post(raw):
    data=normalize_payload(raw)
    marca=str(data.get("marca","")).upper()
    modelo=str(data.get("modelo","")).upper()
    ano=str(data.get("ano_modelo") or data.get("ano") or "")
    km=fmt_km(data.get("km"))
    cambio=str(data.get("cambio","")).upper()
    combustivel=str(data.get("combustivel","")).upper()
    cor=str(data.get("cor","")).upper()
    portas=str(data.get("portas",""))
    preco=fmt_price(data.get("preco"))

    fotos=data.get("fotos") or []
    capa=data.get("foto_capa")
    if capa and capa not in fotos: fotos=[capa]+fotos
    fotos=[x for x in fotos if x]
    if not fotos: raise ValueError("Nenhuma foto recebida do Supabase.")

    hero=dl(fotos[0]); interior=dl(fotos[min(5,len(fotos)-1)]); rear=dl(fotos[min(10,len(fotos)-1)]); side=dl(fotos[min(3,len(fotos)-1)]); top=dl(fotos[min(1,len(fotos)-1)])
    logo=clean_logo(dl(data.get("logo_url") or DEFAULT_LOGO_URL))

    im=Image.new("RGBA",(W,H),BLACK+(255,)); d=ImageDraw.Draw(im)
    bg=cover(hero,W,H).filter(ImageFilter.GaussianBlur(22)); bg=ImageEnhance.Brightness(bg).enhance(.18); im.alpha_composite(bg,(0,0)); im.alpha_composite(Image.new("RGBA",(W,H),(0,0,0,145)),(0,0)); d=ImageDraw.Draw(im)

    LEFT=930
    lg=contain(logo,430,160); im.alpha_composite(lg,(35,20))
    txt(d,(895,30),"S E M I N O V O S",18,anchor="ra"); txt(d,(895,58),"D E  Q U A L I D A D E",16,anchor="ra"); d.polygon([(865,78),(895,78),(883,108),(853,108)],fill=RED)
    txt(d,(38,140),marca,40,RED,True); txt(d,(35,175),modelo,108 if len(modelo)<=12 else 82,WHITE,True)
    d.polygon([(35,305),(205,305),(190,365),(20,365)],fill=RED); txt(d,(112,335),ano,42,WHITE,True,anchor="mm"); txt(d,(230,335),f"{cambio}  |  {combustivel}",34,WHITE,True,anchor="lm")
    txt(d,(38,390),"ESPAÇO, CONFORTO",29,WHITE,True); txt(d,(38,425),"E VERSATILIDADE",29,RED,True)

    hfg=soft(contain(hero,890,560)); hx=20+(LEFT-40-hfg.width)//2; hy=430
    sh=Image.new("RGBA",(hfg.width+60,hfg.height+60),(0,0,0,0)); sd=ImageDraw.Draw(sh); sd.rounded_rectangle((30,30,hfg.width+30,hfg.height+30),radius=32,fill=(0,0,0,120)); sh=sh.filter(ImageFilter.GaussianBlur(20)); im.alpha_composite(sh,(hx-30,hy-30)); im.alpha_composite(hfg,(hx,hy)); d=ImageDraw.Draw(im)

    d.rectangle((0,875,LEFT,H),fill=(5,5,6,242))
    for i,(lab,cx) in enumerate(zip(["CONFORTO","ESPAÇO\nINTERNO","TECNOLOGIA","SEGURANÇA"],[85,250,420,590])):
        d.rounded_rectangle((cx-24,900,cx+24,948),radius=10,outline=RED,width=3); txt(d,(cx,968),lab,16,WHITE,True,anchor="ma")
        if i<3: d.line((cx+82,897,cx+82,980),fill=(120,0,0),width=2)

    d.polygon([(650,820),(LEFT,820),(LEFT,H),(590,H)],fill=(5,5,6,255)); d.line((650,820,590,H),fill=RED,width=8)
    txt(d,(790,846),"POR APENAS",22,WHITE,True,anchor="ma"); txt(d,(660,885),"R$",40,RED,True); txt(d,(725,870),preco,72,WHITE,True)
    d.rectangle((690,950,915,995),fill=RED); txt(d,(802,972),"FALE CONOSCO",22,WHITE,True,anchor="mm")

    RX=LEFT; d.rectangle((RX,0,W,H),fill=(5,5,6,242))
    txt(d,(965,30),"DESTAQUES",34,WHITE,True); txt(d,(965,67),"DO VEÍCULO",34,RED,True)
    opts=data.get("opcionais") or []
    if isinstance(opts,str): opts=[x.strip() for x in opts.split(",") if x.strip()]
    shown=[str(x) for x in opts][:8] or ["Motor 1.6 Flex",f"Câmbio {cambio.title()}","Direção Elétrica","Ar Condicionado","Vidros e Travas Elétricas","Rodas de Liga Leve","Central Multimídia","Airbags + ABS"]
    yy=122
    for item in shown[:8]:
        icon_box(d,965,yy-6); txt(d,(1018,yy+13),item,17,WHITE,False,anchor="lm"); yy+=44

    d.line((1265,0,1160,410),fill=RED,width=5); im.alpha_composite(cover(top,355,315),(1175,0))
    im.alpha_composite(cover(rear,W-RX,290),(RX,410))

    d.rectangle((RX,700,W,H),fill=(5,5,6,250)); txt(d,(965,730),"FICHA",34,WHITE,True); txt(d,(965,767),"TÉCNICA",34,RED,True)
    specs=[("ANO/MODELO",ano),("QUILOMETRAGEM",f"{km} KM" if km else ""),("COMBUSTÍVEL",combustivel),("CÂMBIO",cambio),("COR",cor),("PORTAS",f"{portas} PORTAS" if portas else "")]
    sy=815
    for k,v in specs:
        if not v: continue
        txt(d,(965,sy),k,13,GRAY,True); txt(d,(965,sy+18),v,20,WHITE,True); sy+=46

    d.line((1185,700,1120,1005),fill=RED,width=5); im.alpha_composite(cover(side,390,290),(1140,710))
    d.rectangle((RX,985,W,H),fill=(0,0,0,255)); txt(d,(950,1005),data.get("whatsapp","(51) 99573-4555"),18,WHITE,True); txt(d,(1510,1005),data.get("instagram","@premiumautomarcas"),18,WHITE,True,anchor="ra")
    return im

@post_bp.get("/post-health")
def post_health():
    return {"ok":True,"service":"premium-post-renderer","size":"1536x1024","supabase":{"configured":bool(SUPABASE_SERVICE_KEY),"bucket":SUPABASE_BUCKET,"folder":SUPABASE_POSTS_FOLDER}}

@post_bp.post("/post")
def post():
    try:
        raw=request.get_json(force=True); data=normalize_payload(raw); img=render_post(data); job=uuid.uuid4().hex; url=upload(img,job)
        return jsonify({"status":"done","id":job,"url":url,"post_url":url,"template":"post_aprovado_1536x1024","source_price":data.get("preco")})
    except Exception as e:
        import traceback; traceback.print_exc(); return jsonify({"status":"error","error":str(e)}),500
