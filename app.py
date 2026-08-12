import os, uuid, subprocess, math
from pathlib import Path
from urllib.parse import urlparse
import requests
from flask import Flask, request, jsonify, send_from_directory
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

APP = Flask(__name__)

def log(msg):
    print(f"[premium-renderer] {msg}", flush=True)
BASE = Path(__file__).parent
TMP = BASE / "tmp"
VIDEOS = BASE / "videos"
TMP.mkdir(exist_ok=True)
VIDEOS.mkdir(exist_ok=True)

W,H,FPS = 1080,1920,30
RED=(235,35,42); WHITE=(248,248,248); BLACK=(5,5,5)
FONT_CANDIDATES = {
    "cond": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/local/lib/python3.12/site-packages/PIL/fonts/DejaVuSansCondensed-Bold.ttf",
    ],
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/local/lib/python3.12/site-packages/PIL/fonts/DejaVuSans-Bold.ttf",
    ],
    "reg": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/local/lib/python3.12/site-packages/PIL/fonts/DejaVuSans.ttf",
    ],
}

def resolve_font(kind):
    for p in FONT_CANDIDATES[kind]:
        if os.path.exists(p):
            return p
    # fc-match is installed with fontconfig pulled by Debian font packages in most images.
    try:
        family = {"cond":"DejaVu Sans Condensed:style=Bold","bold":"DejaVu Sans:style=Bold","reg":"DejaVu Sans"}[kind]
        p = subprocess.check_output(["fc-match","-f","%{file}",family], text=True).strip()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    return None

FONT_COND=resolve_font("cond")
FONT_BOLD=resolve_font("bold")
FONT_REG=resolve_font("reg")

LOGO_URL=os.environ.get(
    "PREMIUM_LOGO_URL",
    "https://kbmryoeevdxvugcelflp.supabase.co/storage/v1/object/public/veiculos/Musicas/Logo%20minimalista%20de%20carro%20esportivo.png"
)
MUSIC_URL=os.environ.get("PREMIUM_MUSIC_URL","")

def F(path,size):
    if path:
        try:
            return ImageFont.truetype(path,size)
        except Exception:
            pass
    # Last-resort fallback prevents "cannot open resource".
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()

def download(url, dest):
    r=requests.get(url,timeout=40)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest

def clean_logo(path):
    logo=Image.open(path).convert("RGBA")
    pix=logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r,g,b,a=pix[x,y]
            lum=max(r,g,b)
            alpha=max(0,min(255,int((lum-10)*7.5)))
            pix[x,y]=(r,g,b,alpha)
    bb=logo.getbbox()
    return logo.crop(bb) if bb else logo

def make_bg(photo):
    src=Image.open(photo).convert("RGB")
    scale=max(W/src.width,H/src.height)
    bg=src.resize((int(src.width*scale),int(src.height*scale)),Image.Resampling.LANCZOS)
    l=(bg.width-W)//2; t=(bg.height-H)//2
    bg=bg.crop((l,t,l+W,t+H)).filter(ImageFilter.GaussianBlur(38))
    bg=ImageEnhance.Brightness(bg).enhance(.20).convert("RGBA")
    return Image.alpha_composite(bg,Image.new("RGBA",(W,H),(0,0,0,110)))

def integrated_car(im, photo, top=300, maxw=1070, maxh=760, feather=105):
    # Versão otimizada para pouca RAM/CPU:
    # sem loop Python pixel-a-pixel; cria máscara a partir de retângulos + GaussianBlur.
    src=Image.open(photo).convert("RGB")
    sc=min(maxw/src.width,maxh/src.height)
    fg=src.resize((int(src.width*sc),int(src.height*sc)),Image.Resampling.LANCZOS)
    fg=ImageEnhance.Contrast(fg).enhance(1.05)
    fg=ImageEnhance.Brightness(fg).enhance(1.02).convert("RGBA")
    fw,fh=fg.size
    x=(W-fw)//2

    # Máscara central opaca, bordas suavizadas por blur.
    mask=Image.new("L",(fw,fh),0)
    md=ImageDraw.Draw(mask)
    inset=max(35,min(feather, min(fw,fh)//4))
    md.rounded_rectangle(
        (inset,inset,fw-inset,fh-inset),
        radius=max(20,inset//2),
        fill=255
    )
    mask=mask.filter(ImageFilter.GaussianBlur(max(24,inset//2)))
    fg.putalpha(mask)

    # Sombra menor para economizar memória.
    shadow=Image.new("RGBA",(fw+60,fh+60),(0,0,0,0))
    sd=ImageDraw.Draw(shadow)
    sd.rounded_rectangle((30,30,fw+30,fh+30),35,fill=(0,0,0,150))
    shadow=shadow.filter(ImageFilter.GaussianBlur(28))
    im.alpha_composite(shadow,(x-30,top-30))
    im.alpha_composite(fg,(x,top))

    # Libera referências grandes cedo.
    del shadow, mask, fg, src

def center_text(d,y,text,f,fill=WHITE,stroke=0,stroke_fill=BLACK):
    bb=d.textbbox((0,0),text,font=f,stroke_width=stroke)
    d.text(((W-(bb[2]-bb[0]))/2,y),text,font=f,fill=fill,stroke_width=stroke,stroke_fill=stroke_fill)

def icon_calendar(d,cx,cy):
    d.rounded_rectangle((cx-28,cy-24,cx+28,cy+24),6,outline=WHITE,width=4)
    d.line((cx-28,cy-8,cx+28,cy-8),fill=RED,width=4)
    d.line((cx-15,cy-31,cx-15,cy-17),fill=WHITE,width=4)
    d.line((cx+15,cy-31,cx+15,cy-17),fill=WHITE,width=4)

def icon_speed(d,cx,cy):
    d.arc((cx-30,cy-30,cx+30,cy+30),180,360,fill=WHITE,width=5)
    d.line((cx,cy,cx+18,cy-18),fill=RED,width=5)
    d.ellipse((cx-4,cy-4,cx+4,cy+4),fill=WHITE)

def icon_gear(d,cx,cy):
    d.line((cx,cy-27,cx,cy+18),fill=WHITE,width=5)
    d.ellipse((cx-6,cy-33,cx+6,cy-21),outline=RED,width=4)
    d.line((cx-24,cy+18,cx+24,cy+18),fill=WHITE,width=5)
    d.line((cx-20,cy+18,cx-20,cy+30),fill=WHITE,width=4)
    d.line((cx+20,cy+18,cx+20,cy+30),fill=WHITE,width=4)

def icon_fuel(d,cx,cy):
    d.rectangle((cx-20,cy-28,cx+14,cy+28),outline=WHITE,width=4)
    d.rectangle((cx-13,cy-19,cx+7,cy-5),outline=RED,width=3)
    d.arc((cx+10,cy-15,cx+35,cy+25),270,90,fill=RED,width=4)

def fmt_km(v):
    try: return f"{int(float(v)):,}".replace(",",".")+" KM"
    except: return str(v or "")

def fmt_price(v):
    try: return f"{int(float(v)):,}".replace(",",".")
    except: return str(v or "")

def build_frame(photo, logo, data, out):
    im=make_bg(photo); d=ImageDraw.Draw(im)
    marca=str(data.get("marca","")).upper()
    modelo=str(data.get("modelo","")).upper()
    versao=str(data.get("versao") or data.get("spec_completa") or "").upper()
    ano_f=str(data.get("ano_fabricacao") or "")
    ano_m=str(data.get("ano_modelo") or ano_f)
    ano=f"{ano_f}/{ano_m}" if ano_f and ano_m else (ano_m or ano_f)
    km=fmt_km(data.get("km"))
    cambio=str(data.get("cambio","")).upper()
    combustivel=str(data.get("combustivel","")).upper()
    preco=fmt_price(data.get("preco"))

    # topo sem logo (o Instagram já ocupa essa área)
    d.text((55,65),marca,font=F(FONT_COND,48),fill=RED)
    model_font=F(FONT_COND,92 if len(modelo)<=12 else 72)
    d.text((55,110),modelo,font=model_font,fill=WHITE,stroke_width=2,stroke_fill=(20,20,20))
    d.rectangle((55,218,575,224),fill=RED)
    d.text((72,235),versao[:34],font=F(FONT_COND,34),fill=WHITE)

    # foto grande, inteira, integrada pelas bordas
    integrated_car(im,photo,top=300,maxw=1070,maxh=760,feather=105)

    # especificações
    spec_y=1110
    xs=[145,405,675,930]
    labels=[("ANO/MODELO",ano),("QUILOMETRAGEM",km),("CÂMBIO",cambio),("COMBUSTÍVEL",combustivel)]
    icons=[icon_calendar,icon_speed,icon_gear,icon_fuel]
    for j,(cx,(lab,val),ico) in enumerate(zip(xs,labels,icons)):
        ico(d,cx,spec_y)
        f1=F(FONT_REG,19); f2=F(FONT_COND,29 if len(val)<13 else 24)
        bb=d.textbbox((0,0),lab,font=f1)
        d.text((cx-(bb[2]-bb[0])/2,spec_y+48),lab,font=f1,fill=WHITE)
        bb=d.textbbox((0,0),val,font=f2)
        d.text((cx-(bb[2]-bb[0])/2,spec_y+78),val,font=f2,fill=RED)
        if j<3: d.line((cx+125,spec_y-28,cx+125,spec_y+118),fill=(120,120,120,120),width=2)

    # preço integrado, sem caixa vermelha
    center_text(d,1290,"POR APENAS",F(FONT_REG,28),WHITE)
    f_rs=F(FONT_COND,48); f_price=F(FONT_COND,104)
    rs="R$"; wr=d.textbbox((0,0),rs,font=f_rs)[2]; wp=d.textbbox((0,0),preco,font=f_price)[2]
    start=(W-(wr+18+wp))/2
    d.text((start,1340),rs,font=f_rs,fill=RED)
    d.text((start+wr+18,1310),preco,font=f_price,fill=WHITE,stroke_width=2,stroke_fill=(50,50,50))
    d.line((245,1435,835,1435),fill=RED,width=3)

    # área escura inferior com logo grande
    d.rectangle((0,1480,W,H),fill=(0,0,0,95))
    lg=logo.copy()
    sc=min(690/lg.width,260/lg.height)
    lg=lg.resize((int(lg.width*sc),int(lg.height*sc)),Image.Resampling.LANCZOS)
    im.alpha_composite(lg,((W-lg.width)//2,1510))
    center_text(d,1768,"(51) 99573-4555",F(FONT_COND,37),WHITE)
    center_text(d,1818,"premiumautomarcas.net.br",F(FONT_REG,27),WHITE)
    d.line((225,1750,855,1750),fill=RED,width=2)

    im.convert("RGB").save(out,quality=96,subsampling=0)

def render_video(data):
    import gc
    job=uuid.uuid4().hex
    work=TMP/job
    work.mkdir(parents=True,exist_ok=True)
    log(f"{job}: início")

    fotos=data.get("fotos") or []
    if data.get("foto_capa") and data["foto_capa"] not in fotos:
        fotos=[data["foto_capa"]]+fotos
    fotos=[x for x in fotos if x][:5]
    if not fotos:
        raise ValueError("Nenhuma foto recebida.")

    log(f"{job}: baixando logo")
    logo_path=work/"logo.png"
    download(LOGO_URL,logo_path)
    logo=clean_logo(logo_path)
    log(f"{job}: logo OK")

    # Renderiza e codifica UMA cena por vez, liberando memória entre elas.
    segs=[]
    for i,url in enumerate(fotos):
        log(f"{job}: foto {i+1}/{len(fotos)} download")
        p=work/f"photo{i}.jpg"
        download(url,p)

        log(f"{job}: foto {i+1} card")
        card=work/f"card{i}.jpg"
        build_frame(p,logo,data,card)
        gc.collect()

        log(f"{job}: foto {i+1} ffmpeg")
        seg=work/f"seg{i}.mp4"
        segs.append(seg)
        duration=3
        frames=duration*FPS
        vf=(f"zoompan=z='min(zoom+0.00010,1.006)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s=1080x1920:fps={FPS},format=yuv420p")
        subprocess.run([
            "ffmpeg","-y","-threads","1","-loop","1","-i",str(card),
            "-vf",vf,"-t",str(duration),"-r",str(FPS),
            "-c:v","libx264","-preset","ultrafast","-crf","20",
            "-pix_fmt","yuv420p",str(seg)
        ],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        # Remove foto/card depois de codificar para reduzir disco/RAM cache.
        try: p.unlink(missing_ok=True)
        except: pass
        try: card.unlink(missing_ok=True)
        except: pass
        gc.collect()

    while len(segs)<5:
        segs.append(segs[-1])

    log(f"{job}: concatenando")
    concat=work/"concat.txt"
    concat.write_text("".join([f"file '{s}'\n" for s in segs[:5]]))
    silent=work/"silent.mp4"
    subprocess.run([
        "ffmpeg","-y","-threads","1","-f","concat","-safe","0","-i",str(concat),
        "-c","copy","-movflags","+faststart",str(silent)
    ],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)

    final=VIDEOS/f"{job}.mp4"
    music_url=data.get("music_url") or MUSIC_URL
    if music_url:
        log(f"{job}: áudio")
        music=work/"music.mp3"
        download(music_url,music)
        subprocess.run([
            "ffmpeg","-y","-threads","1","-i",str(silent),"-i",str(music),
            "-map","0:v:0","-map","1:a:0","-c:v","copy",
            "-c:a","aac","-b:a","128k","-shortest",
            "-movflags","+faststart",str(final)
        ],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    else:
        final.write_bytes(silent.read_bytes())

    log(f"{job}: pronto {final.name}")
    return job, final

@APP.get("/health")
def health():
    return {
        "ok": True,
        "service":"premium-renderer",
        "fonts": {
            "cond": FONT_COND,
            "bold": FONT_BOLD,
            "reg": FONT_REG
        }
    }

@APP.post("/render")
def render():
    try:
        data=request.get_json(force=True)
        job, final=render_video(data)
        base=request.host_url.rstrip("/")
        return jsonify({"status":"done","id":job,"url":f"{base}/videos/{job}.mp4"})
    except subprocess.CalledProcessError as e:
        import traceback
        log("FFmpeg falhou")
        print(e.stderr or str(e), flush=True)
        traceback.print_exc()
        return jsonify({"status":"error","stage":"ffmpeg","error":str(e),"stderr":(e.stderr or "")[-3000:]}),500
    except Exception as e:
        import traceback
        log(f"erro: {e}")
        traceback.print_exc()
        return jsonify({"status":"error","error":str(e)}),500

@APP.get("/videos/<name>")
def videos(name):
    return send_from_directory(VIDEOS,name,mimetype="video/mp4")

if __name__=="__main__":
    APP.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
