from flask import Blueprint, request, jsonify
from pathlib import Path
from playwright.sync_api import sync_playwright
import requests, os, uuid, json

post_bp = Blueprint("post_bp", __name__)
BASE = Path(__file__).parent
HTML_PATH = BASE / "post_template.html"

SUPABASE_URL=os.environ.get("SUPABASE_URL","https://kbmryoeevdxvugcelflp.supabase.co").rstrip("/")
SUPABASE_BUCKET=os.environ.get("SUPABASE_BUCKET","veiculos")
SUPABASE_SERVICE_KEY=os.environ.get("SUPABASE_SERVICE_KEY","")
SUPABASE_POSTS_FOLDER=os.environ.get("SUPABASE_POSTS_FOLDER","posts")

def normalize(raw):
    if isinstance(raw,dict) and isinstance(raw.get("body"),dict):
        d=dict(raw["body"])
        for k,v in raw.items():
            if k!="body" and k not in d: d[k]=v
        return d
    return raw or {}

def fmt_price(v):
    if v is None or str(v).strip()=="":
        raise ValueError("Campo preco não recebido.")
    s=str(v).strip().replace("R$","").replace(" ","")
    if "," in s: n=float(s.replace(".","").replace(",","."))
    elif s.count(".")==1 and len(s.split(".")[1])==3: n=float(s.replace(".",""))
    else: n=float(s)
    return f"{int(round(n)):,}".replace(",",".")

def fmt_km(v):
    try: return f"{int(float(v)):,}".replace(",",".")
    except: return str(v or "")

def choose(data):
    fotos=data.get("fotos") or []
    capa=data.get("foto_capa")
    if capa and capa not in fotos: fotos=[capa]+fotos
    fotos=[x for x in fotos if x]
    if not fotos: raise ValueError("Nenhuma foto recebida.")
    return fotos

def view(data):
    fotos=choose(data)
    opts=data.get("opcionais") or []
    if isinstance(opts,str): opts=[x.strip() for x in opts.split(",") if x.strip()]
    return {
        "marca":str(data.get("marca","")).upper(),
        "modelo":str(data.get("modelo","")).upper(),
        "ano":str(data.get("ano_modelo") or data.get("ano") or ""),
        "km":fmt_km(data.get("km")),
        "cambio":str(data.get("cambio","")).upper(),
        "combustivel":str(data.get("combustivel","")).upper(),
        "cor":str(data.get("cor","")).upper(),
        "portas":str(data.get("portas","") or ""),
        "preco":fmt_price(data.get("preco")),
        "opcionais":[str(x) for x in opts[:8]],
        "whatsapp":str(data.get("whatsapp") or "(51) 99575-1376"),
        "instagram":str(data.get("instagram") or "@premiumautomarcas"),
        "hero":fotos[0],
        "interior":fotos[min(5,len(fotos)-1)],
        "rear":fotos[min(10,len(fotos)-1)],
        "side":fotos[min(3,len(fotos)-1)],
    }

def screenshot(v,path):
    html=HTML_PATH.read_text(encoding="utf-8").replace("__DATA_JSON__",json.dumps(v,ensure_ascii=False))
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"])
        page=browser.new_page(viewport={"width":1536,"height":1024},device_scale_factor=1)
        page.set_content(html,wait_until="networkidle")
        page.screenshot(path=str(path),full_page=False)
        browser.close()

def upload(path,job):
    if not SUPABASE_SERVICE_KEY: raise RuntimeError("SUPABASE_SERVICE_KEY não configurada.")
    name=f"{SUPABASE_POSTS_FOLDER}/{job}.png"
    url=f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{name}"
    headers={"Authorization":f"Bearer {SUPABASE_SERVICE_KEY}","apikey":SUPABASE_SERVICE_KEY,"Content-Type":"image/png","x-upsert":"true","cache-control":"3600"}
    r=requests.post(url,headers=headers,data=Path(path).read_bytes(),timeout=180)
    if r.status_code not in (200,201): raise RuntimeError(f"Upload falhou HTTP {r.status_code}: {r.text[:500]}")
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{name}"

@post_bp.get("/post-health")
def health():
    return {"ok":True,"service":"premium-post-html-renderer","engine":"playwright-chromium","size":"1536x1024","template_found":HTML_PATH.exists()}

@post_bp.post("/post")
def post():
    tmp=None
    try:
        data=normalize(request.get_json(force=True))
        v=view(data)
        job=uuid.uuid4().hex
        tmp=Path("/tmp")/f"{job}.png"
        screenshot(v,tmp)
        url=upload(tmp,job)
        return jsonify({"status":"done","id":job,"url":url,"post_url":url,"template":"post_html_css_v1","engine":"playwright-chromium","source_price":data.get("preco")})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"status":"error","error":str(e)}),500
    finally:
        if tmp and tmp.exists():
            try: tmp.unlink()
            except: pass
