from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import requests, uuid, os, io

story_bp = Blueprint('story_bp', __name__)
W, H = 1080, 1920
RED=(235,25,34); WHITE=(248,248,248); BLACK=(4,4,5); GRAY=(168,168,168)

FONT_BOLD=next((p for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'] if os.path.exists(p)),None)
FONT_REG=next((p for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'] if os.path.exists(p)),None)

SUPABASE_URL=os.environ.get('SUPABASE_URL','https://kbmryoeevdxvugcelflp.supabase.co').rstrip('/')
SUPABASE_BUCKET=os.environ.get('SUPABASE_BUCKET','veiculos')
SUPABASE_SERVICE_KEY=os.environ.get('SUPABASE_SERVICE_KEY','')
SUPABASE_STORIES_FOLDER=os.environ.get('SUPABASE_STORIES_FOLDER','stories')
DEFAULT_LOGO_URL=os.environ.get('PREMIUM_LOGO_URL','https://kbmryoeevdxvugcelflp.supabase.co/storage/v1/object/public/veiculos/Musicas/Logo%20minimalista%20de%20carro%20esportivo.png')

def F(size,bold=False):
    p=FONT_BOLD if bold else FONT_REG
    return ImageFont.truetype(p,size) if p else ImageFont.load_default()

def txt(d,xy,value,size,fill=WHITE,bold=False,anchor=None):
    d.text(xy,str(value),font=F(size,bold),fill=fill,anchor=anchor)

def normalize_payload(raw):
    if isinstance(raw,dict) and isinstance(raw.get('body'),dict):
        merged=dict(raw['body'])
        for k,v in raw.items():
            if k!='body' and k not in merged: merged[k]=v
        return merged
    return raw or {}

def download_image(url):
    r=requests.get(url,timeout=40,headers={'User-Agent':'Mozilla/5.0'})
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert('RGBA')

def fit_cover(im,w,h):
    s=max(w/im.width,h/im.height)
    r=im.resize((int(im.width*s),int(im.height*s)),Image.Resampling.LANCZOS)
    x=max(0,(r.width-w)//2); y=max(0,(r.height-h)//2)
    return r.crop((x,y,x+w,y+h))

def fit_contain(im,maxw,maxh):
    s=min(maxw/im.width,maxh/im.height)
    return im.resize((max(1,int(im.width*s)),max(1,int(im.height*s))),Image.Resampling.LANCZOS)

def clean_logo(logo):
    logo=logo.convert('RGBA'); px=logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r,g,b,a=px[x,y]
            if max(r,g,b)<18: px[x,y]=(r,g,b,0)
    bb=logo.getbbox(); return logo.crop(bb) if bb else logo

def soft_edges(im,edge=48):
    im=im.convert('RGBA'); mask=Image.new('L',im.size,0); d=ImageDraw.Draw(mask)
    inset=min(edge,max(24,min(im.size)//10))
    d.rounded_rectangle((inset,inset,im.width-inset,im.height-inset),radius=max(18,inset//2),fill=255)
    mask=mask.filter(ImageFilter.GaussianBlur(max(12,inset//3))); im.putalpha(mask)
    return im

def fmt_price(v):
    if v is None or str(v).strip()=='': raise ValueError("Campo 'preco' não recebido do Supabase.")
    s=str(v).strip().replace('R$','').replace(' ','')
    try:
        if ',' in s: n=float(s.replace('.','').replace(',','.'))
        elif s.count('.')==1 and len(s.split('.')[1])==3: n=float(s.replace('.',''))
        else: n=float(s)
        return f'{int(round(n)):,}'.replace(',','.')
    except: raise ValueError(f'Preço inválido recebido do Supabase: {v}')

def fmt_km(v):
    if v is None or str(v).strip()=='': return ''
    try: return f'{int(float(v)):,}'.replace(',','.')
    except: return str(v)

def upload_png_to_supabase(img,job):
    if not SUPABASE_SERVICE_KEY: raise RuntimeError('SUPABASE_SERVICE_KEY não configurada no Render.')
    bio=io.BytesIO(); img.convert('RGB').save(bio,format='PNG',optimize=True)
    object_name=f'{SUPABASE_STORIES_FOLDER}/{job}.png'
    upload_url=f'{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_name}'
    headers={'Authorization':f'Bearer {SUPABASE_SERVICE_KEY}','apikey':SUPABASE_SERVICE_KEY,'Content-Type':'image/png','x-upsert':'true','cache-control':'3600'}
    r=requests.post(upload_url,headers=headers,data=bio.getvalue(),timeout=180)
    if r.status_code not in (200,201): raise RuntimeError(f'Falha upload Story HTTP {r.status_code}: {r.text[:800]}')
    return f'{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{object_name}'

def icon_box(d,x,y):
    d.rounded_rectangle((x,y,x+42,y+42),radius=8,outline=RED,width=3)

def render_story(raw):
    data=normalize_payload(raw)
    marca=str(data.get('marca','')).upper(); modelo=str(data.get('modelo','')).upper()
    ano=str(data.get('ano_modelo') or data.get('ano') or '')
    km=fmt_km(data.get('km')); cambio=str(data.get('cambio','')).upper(); combustivel=str(data.get('combustivel','')).upper()
    cor=str(data.get('cor','')).upper(); portas=str(data.get('portas','')); preco=fmt_price(data.get('preco'))
    fotos=data.get('fotos') or []; foto_capa=data.get('foto_capa')
    if foto_capa and foto_capa not in fotos: fotos=[foto_capa]+fotos
    fotos=[x for x in fotos if x]
    if not fotos: raise ValueError('Nenhuma foto recebida do Supabase.')

    hero=download_image(fotos[0]); top_right=download_image(fotos[min(1,len(fotos)-1)])
    interior=download_image(fotos[min(5,len(fotos)-1)]); rear=download_image(fotos[min(10,len(fotos)-1)]); side=download_image(fotos[min(3,len(fotos)-1)])
    logo=clean_logo(download_image(data.get('logo_url') or DEFAULT_LOGO_URL))

    im=Image.new('RGBA',(W,H),BLACK+(255,)); d=ImageDraw.Draw(im)
    bg=fit_cover(hero,W,H).filter(ImageFilter.GaussianBlur(34)); bg=ImageEnhance.Brightness(bg).enhance(0.16)
    im.alpha_composite(bg,(0,0)); im.alpha_composite(Image.new('RGBA',(W,H),(0,0,0,155)),(0,0)); d=ImageDraw.Draw(im)

    left_w=690
    lg=fit_contain(logo,400,150); im.alpha_composite(lg,(30,28))
    txt(d,(35,175),marca,34,RED,True); txt(d,(30,210),modelo,88 if len(modelo)<=12 else 68,WHITE,True)
    d.polygon([(30,315),(185,315),(170,375),(15,375)],fill=RED); txt(d,(100,345),ano,38,WHITE,True,anchor='mm')
    txt(d,(205,345),f'{cambio}  |  {combustivel}',30,WHITE,True,anchor='lm')
    txt(d,(32,400),'ESPAÇO, CONFORTO',26,WHITE,True); txt(d,(32,432),'E VERSATILIDADE',26,RED,True)

    hero_fg=fit_contain(hero,650,760); hero_fg=ImageEnhance.Contrast(hero_fg).enhance(1.06); hero_fg=ImageEnhance.Brightness(hero_fg).enhance(1.03); hero_fg=soft_edges(hero_fg,46)
    hx=20+(left_w-40-hero_fg.width)//2; hy=470
    shadow=Image.new('RGBA',(hero_fg.width+80,hero_fg.height+80),(0,0,0,0)); sd=ImageDraw.Draw(shadow)
    sd.rounded_rectangle((40,40,hero_fg.width+40,hero_fg.height+40),radius=40,fill=(0,0,0,140)); shadow=shadow.filter(ImageFilter.GaussianBlur(24))
    im.alpha_composite(shadow,(hx-40,hy-40)); im.alpha_composite(hero_fg,(hx,hy)); d=ImageDraw.Draw(im)

    d.rectangle((0,1230,left_w,1370),fill=(5,5,6,238))
    benefits=['CONFORTO','ESPAÇO\nINTERNO','TECNOLOGIA','SEGURANÇA']; centers=[80,245,410,575]
    for i,(label,cx) in enumerate(zip(benefits,centers)):
        d.rounded_rectangle((cx-23,1250,cx+23,1296),radius=9,outline=RED,width=3); txt(d,(cx,1320),label,17,WHITE,True,anchor='ma')
        if i<3: d.line((cx+80,1248,cx+80,1340),fill=(125,0,0),width=2)

    d.polygon([(430,1345),(left_w,1345),(left_w,1535),(380,1535)],fill=(5,5,6,255)); d.line((430,1345,380,1535),fill=RED,width=8)
    txt(d,(560,1373),'POR APENAS',20,WHITE,True,anchor='ma'); txt(d,(430,1410),'R$',38,RED,True); txt(d,(500,1398),preco,68,WHITE,True)
    d.rectangle((470,1480,675,1522),fill=RED); txt(d,(572,1501),'FALE CONOSCO',21,WHITE,True,anchor='mm')

    rx=left_w; d.rectangle((rx,0,W,H),fill=(5,5,6,235))
    txt(d,(1040,34),'S E M I N O V O S',18,WHITE,False,anchor='ra'); txt(d,(1040,60),'D E  Q U A L I D A D E',16,WHITE,False,anchor='ra')
    d.polygon([(1010,80),(1040,80),(1028,110),(998,110)],fill=RED)
    txt(d,(715,125),'DESTAQUES',34,WHITE,True); txt(d,(715,165),'DO VEÍCULO',34,RED,True)

    opts=data.get('opcionais') or []
    if isinstance(opts,str): opts=[x.strip() for x in opts.split(',') if x.strip()]
    shown=[str(x) for x in opts][:6] or ['Ar condicionado',f'Câmbio {cambio.title()}','Direção elétrica','Rodas de liga leve','Vidros elétricos','Freio ABS']
    yy=225
    for item in shown[:6]:
        icon_box(d,715,yy-7); txt(d,(772,yy+14),item,17,WHITE,False,anchor='lm'); yy+=49

    d.line((970,110,900,600),fill=RED,width=5); rimg=fit_cover(top_right,300,360); im.alpha_composite(rimg,(770,420))
    txt(d,(715,805),'FICHA',34,WHITE,True); txt(d,(715,845),'TÉCNICA',34,RED,True)
    specs=[('ANO/MODELO',ano),('QUILOMETRAGEM',f'{km} KM' if km else ''),('COMBUSTÍVEL',combustivel),('CÂMBIO',cambio),('COR',cor),('PORTAS',f'{portas} PORTAS' if portas else '')]
    sy=905
    for k,v in specs:
        if not v: continue
        txt(d,(715,sy),k,13,GRAY,True); txt(d,(715,sy+18),v,20,WHITE,True); sy+=47

    d.line((770,1140,715,1750),fill=RED,width=5); photo_x=775; photo_w=285; photo_h=155
    for idx,src in enumerate([interior,rear,side]): im.alpha_composite(fit_cover(src,photo_w,photo_h),(photo_x,1140+idx*170))

    d.rectangle((0,1768,W,H),fill=(0,0,0,255)); txt(d,(32,1810),data.get('whatsapp','(51) 99573-4555'),20,WHITE,True)
    txt(d,(1048,1810),data.get('instagram','@premiumautomarcas'),20,WHITE,True,anchor='ra')
    return im

@story_bp.get('/story-health')
def story_health():
    return {'ok':True,'service':'premium-story-renderer','supabase':{'configured':bool(SUPABASE_SERVICE_KEY),'bucket':SUPABASE_BUCKET,'folder':SUPABASE_STORIES_FOLDER}}

@story_bp.post('/story')
def story():
    try:
        raw=request.get_json(force=True); data=normalize_payload(raw); img=render_story(data); job=uuid.uuid4().hex
        public_url=upload_png_to_supabase(img,job)
        return jsonify({'status':'done','id':job,'url':public_url,'story_url':public_url,'template':'story_fiel_layout_aprovado','source_price':data.get('preco')})
    except Exception as e:
        import traceback; traceback.print_exc(); return jsonify({'status':'error','error':str(e)}),500
