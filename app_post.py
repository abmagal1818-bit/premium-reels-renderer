
from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from pathlib import Path
import requests, uuid, os, io

post_bp = Blueprint("post_bp", __name__)
BASE = Path(__file__).parent
TEMPLATE = BASE / "post_template.png"

W,H = 1536,1024
RED=(235,25,34); WHITE=(248,248,248); BLACK=(4,4,5); GRAY=(175,175,175)

FONT_BOLD = next((p for p in [
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

def F(size,bold=False):
    p = FONT_BOLD if bold else FONT_REG
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

def contain(im,w,h):
    s=min(w/im.width,h/im.height)
    return im.resize((max(1,int(im.width*s)),max(1,int(im.height*s))),Image.Resampling.LANCZOS)

def cover(im,w,h,fx=.5,fy=.5):
    s=max(w/im.width,h/im.height)
    r=im.resize((int(im.width*s),int(im.height*s)),Image.Resampling.LANCZOS)
    mx=max(0,r.width-w); my=max(0,r.height-h)
    x=int(mx*fx); y=int(my*fy)
    return r.crop((x,y,x+w,y+h))

def fmt_price(v):
    if v is None or str(v).strip()=="":
        raise ValueError("Campo 'preco' não recebido do Supabase.")
    s=str(v).strip().replace("R$","").replace(" ","")
    if "," in s: n=float(s.replace(".","").replace(",","."))
    elif s.count(".")==1 and len(s.split(".")[1])==3: n=float(s.replace(".",""))
    else: n=float(s)
    return f"{int(round(n)):,}".replace(",",".")

def fmt_km(v):
    try:return f"{int(float(v)):,}".replace(",",".")
    except:return str(v or "")

def upload(img,job):
    if not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_KEY não configurada.")
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
        raise RuntimeError(f"Upload HTTP {r.status_code}: {r.text[:500]}")
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{name}"

def dark_rect(im,box,alpha=255):
    x1,y1,x2,y2=box
    patch=Image.new("RGBA",(x2-x1,y2-y1),(4,4,5,alpha))
    im.alpha_composite(patch,(x1,y1))

def diagonal_mask(w,h,x0,y0,p1,p2):
    mask=Image.new("L",(w,h),255)
    dd=ImageDraw.Draw(mask)
    lx1,ly1=p1
    lx2,ly2=p2
    for ly in range(h):
        gy=y0+ly
        t=(gy-ly1)/(ly2-ly1) if ly2!=ly1 else 0
        lx=lx1+(lx2-lx1)*t
        cut=int(round(lx-x0))
        if cut>0:
            dd.line((0,ly,min(cut,w)-1,ly),fill=0)
    return mask

def paste_masked(im,photo,w,h,x0,y0,p1,p2):
    img_c=cover(photo,w,h,.5,.5).convert("RGB")
    mask=diagonal_mask(w,h,x0,y0,p1,p2)
    im.paste(img_c,(x0,y0),mask)

def draw_text(d,xy,text,size,fill=WHITE,bold=True,anchor=None):
    d.text(xy,str(text),font=F(size,bold),fill=fill,anchor=anchor)

def render(raw):
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
    if not fotos: raise ValueError("Nenhuma foto recebida.")

    hero=dl(fotos[0])
    interior=dl(fotos[min(5,len(fotos)-1)])
    traseira=dl(fotos[min(10,len(fotos)-1)])
    lateral=dl(fotos[min(3,len(fotos)-1)])

    if not TEMPLATE.exists():
        raise RuntimeError("post_template.png não encontrado.")
    im=Image.open(TEMPLATE).convert("RGBA")
    if im.size!=(W,H):
        im=im.resize((W,H),Image.Resampling.LANCZOS)

    # --------- Replace photo windows only ----------
    # MAIN PHOTO WINDOW
    x1,y1,x2,y2 = 0,278,938,900
    bg=cover(hero,x2-x1,y2-y1,.5,.5)
    bg=ImageEnhance.Brightness(bg).enhance(.73)
    im.alpha_composite(bg,(x1,y1))
    fg=contain(hero,900,600)
    fg=ImageEnhance.Contrast(fg).enhance(1.04)
    fx=x1+(x2-x1-fg.width)//2
    fy=y1+(y2-y1-fg.height)//2
    shadow=Image.new("RGBA",(fg.width+40,fg.height+40),(0,0,0,0))
    sd=ImageDraw.Draw(shadow)
    sd.rounded_rectangle((20,20,fg.width+20,fg.height+20),radius=28,fill=(0,0,0,65))
    shadow=shadow.filter(ImageFilter.GaussianBlur(16))
    im.alpha_composite(shadow,(fx-20,fy-20))
    im.alpha_composite(fg,(fx,fy))

    # RIGHT PHOTOS
    paste_masked(im,interior,320,335,1216,0,(1225,0),(1127,335))
    paste_masked(im,traseira,430,272,1106,338,(1148,338),(1060,610))
    paste_masked(im,lateral,450,240,1086,710,(1155,610),(1064,950))

    d=ImageDraw.Draw(im)
    # restore red separators exactly
    d.line((1225,0,1127,335),fill=RED,width=5)
    d.line((1148,338,1060,610),fill=RED,width=5)
    d.line((1155,610,1064,950),fill=RED,width=5)

    # --------- Replace dynamic texts only ----------
    dark_rect(im,(0,130,945,300),255)
    pass
    dark_rect(im,(20,328,555,470),255)
    d=ImageDraw.Draw(im)
    marca_spaced=" ".join(list(marca)) if len(marca)<=10 else marca
    draw_text(d,(55,140),marca_spaced,34,RED,True)
    ms=108 if len(modelo)<=10 else 94 if len(modelo)<=13 else 76
    draw_text(d,(40,178),modelo,ms,WHITE,True)
    d.polygon([(34,330),(210,330),(198,389),(22,389)],fill=RED)
    draw_text(d,(112,359),ano,40,WHITE,True,anchor="mm")
    draw_text(d,(236,359),f"{cambio}  /  {combustivel}",30,WHITE,True,anchor="lm")
    draw_text(d,(44,406),"ESPAÇO, CONFORTO",26,WHITE,True)
    draw_text(d,(44,440),"E VERSATILIDADE",26,RED,True)

    # PRICE WINDOW
    dark_rect(im,(620,805,938,1024),252)
    d=ImageDraw.Draw(im)
    d.polygon([(635,805),(938,805),(938,1024),(560,1024)],fill=(4,4,5))
    d.line((635,805,560,1024),fill=RED,width=8)
    draw_text(d,(790,823),"POR APENAS",20,WHITE,True,anchor="ma")
    draw_text(d,(628,865),"R$",34,RED,True)
    draw_text(d,(685,848),preco,62 if len(preco)<=6 else 52,WHITE,True)
    d.rectangle((650,945,925,995),fill=RED)
    draw_text(d,(787,970),"FALE CONOSCO",22,WHITE,True,anchor="mm")

    # OPTIONS TEXT
    opts=data.get("opcionais") or []
    if isinstance(opts,str): opts=[x.strip() for x in opts.split(",") if x.strip()]
    if not opts:
        opts=["Motor 1.6 Flex",f"Câmbio {cambio.title()}","Direção Elétrica","Ar Condicionado","Vidros e Travas Elétricas","Rodas de Liga Leve","Central Multimídia","Airbags + ABS"]
    dark_rect(im,(1010,90,1200,338),255)
    dark_rect(im,(1010,338,1104,420),255)
    d=ImageDraw.Draw(im)
    ys=[116,156,196,236,276,316,356,396]
    for item,y in zip(opts[:8],ys):
        draw_text(d,(1020,y),item,13 if len(str(item))<=22 else 11,WHITE,False)

    # TECH VALUES
    vals=[ano,f"{km} KM" if km else "",combustivel,cambio,cor,f"{portas} PORTAS" if portas else ""]
    boxes=[(1014,690,1120,720),(1014,730,1120,760),(1014,770,1120,800),(1014,810,1120,840),(1014,850,1120,880),(1014,890,1120,925)]
    for b in boxes: dark_rect(im,b,252)
    d=ImageDraw.Draw(im)
    ys=[700,740,780,820,860,900]
    for val,y in zip(vals,ys):
        if val: draw_text(d,(1017,y),val,16,WHITE,True)

    # CONTACT
    dark_rect(im,(1005,955,1230,1024),255)
    dark_rect(im,(1248,955,1536,1024),255)
    d=ImageDraw.Draw(im)
    draw_text(d,(1042,978),data.get("whatsapp") or "(51) 99575-1376",17,WHITE,True)
    draw_text(d,(1500,978),(data.get("instagram") or "@premiumautomarcas").upper(),15,WHITE,True,anchor="ra")

    return im

@post_bp.get("/post-health")
def health():
    return {"ok":True,"service":"premium-post-final","engine":"template-window-compositor","size":"1536x1024","template_found":TEMPLATE.exists()}

@post_bp.post("/post")
def post():
    try:
        data=normalize(request.get_json(force=True))
        img=render(data)
        job=uuid.uuid4().hex
        url=upload(img,job)
        return jsonify({"status":"done","id":job,"url":url,"post_url":url,"engine":"template-window-compositor","template":"final_reference_windows","source_price":data.get("preco")})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"status":"error","error":str(e)}),500
