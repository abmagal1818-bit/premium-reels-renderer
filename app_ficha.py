from flask import Blueprint, request, jsonify
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path
import requests, uuid, os, io, math
import numpy as np

ficha_bp = Blueprint("ficha_bp", __name__)
BASE = Path(__file__).parent
FONT_PATH = str(BASE / "ficha_assets" / "BigShoulders-Bold.ttf")
LOGO_PATH = str(BASE / "ficha_assets" / "premium_logo.png")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://kbmryoeevdxvugcelflp.supabase.co").rstrip("/")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "veiculos")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_POSTS_FOLDER = os.environ.get("SUPABASE_POSTS_FOLDER", "posts")

W, H = 1080, 1560
RED = (230, 57, 70)
BLACK = (8, 8, 8)
WHITE = (255, 255, 255)

# ---------------------------------------------------------------- helpers

def normalize(raw):
    if isinstance(raw, dict) and isinstance(raw.get("body"), dict):
        d = dict(raw["body"])
        for k, v in raw.items():
            if k != "body" and k not in d:
                d[k] = v
        return d
    return raw or {}


def fmt_price(v):
    if v is None or str(v).strip() == "":
        raise ValueError("Campo 'preco' não recebido do Supabase.")
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if "," in s:
        n = float(s.replace(".", "").replace(",", "."))
    elif s.count(".") == 1 and len(s.split(".")[1]) == 3:
        n = float(s.replace(".", ""))
    else:
        n = float(s)
    return f"{int(round(n)):,}".replace(",", ".")


def download_image(url, timeout=30):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def cover_crop(im, target_w, target_h):
    src_w, src_h = im.size
    src_ratio = src_w / src_h
    tgt_ratio = target_w / target_h
    if src_ratio > tgt_ratio:
        new_h = src_h
        new_w = int(src_h * tgt_ratio)
        x0 = (src_w - new_w) // 2
        box = (x0, 0, x0 + new_w, new_h)
    else:
        new_w = src_w
        new_h = int(src_w / tgt_ratio)
        y0 = (src_h - new_h) // 2
        box = (0, y0, new_w, y0 + new_h)
    return im.crop(box).resize((target_w, target_h), Image.LANCZOS)


def font(size, bold=True):
    fdir = "/usr/share/fonts/truetype/dejavu/"
    path = fdir + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    return ImageFont.truetype(path, size)


def italicize(layer, shear=0.22):
    w, h = layer.size
    new_w = w + int(h * shear)
    coeffs = (1, shear, -shear * h, 0, 1, 0)
    return layer.transform((new_w, h), Image.AFFINE, coeffs, resample=Image.BICUBIC)


def distressed_text(text, font_path, font_size, fill, stroke_w=3, roughness=1.8, cell=10, pad=50, seed=1):
    rng = np.random.RandomState(seed)
    f = ImageFont.truetype(font_path, font_size)
    tmp = Image.new("L", (10, 10), 0)
    td = ImageDraw.Draw(tmp)
    bbox = td.textbbox((0, 0), text, font=f, stroke_width=stroke_w)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    Wm, Hm = tw + pad * 2, th + pad * 2
    mask = Image.new("L", (Wm, Hm), 0)
    md = ImageDraw.Draw(mask)
    md.text((pad - bbox[0], pad - bbox[1]), text, font=f, fill=255, stroke_width=stroke_w)

    nh, nw = Hm // cell + 2, Wm // cell + 2
    n1 = Image.fromarray(rng.randint(0, 255, (nh, nw)).astype(np.uint8), mode="L").resize((Wm, Hm), Image.BICUBIC).filter(ImageFilter.GaussianBlur(2))
    n1a = np.asarray(n1).astype(np.float32)
    n1a = (n1a - n1a.mean()) / (n1a.std() + 1e-6)
    n2 = Image.fromarray(rng.randint(0, 255, (nh, nw)).astype(np.uint8), mode="L").resize((Wm, Hm), Image.BICUBIC).filter(ImageFilter.GaussianBlur(2))
    n2a = np.asarray(n2).astype(np.float32)
    n2a = (n2a - n2a.mean()) / (n2a.std() + 1e-6)

    mask_arr = np.asarray(mask).astype(np.float32)
    ys, xs = np.mgrid[0:Hm, 0:Wm]
    src_x = np.clip(xs + (n1a * roughness).astype(np.int32), 0, Wm - 1)
    src_y = np.clip(ys + (n2a * roughness * 0.7).astype(np.int32), 0, Hm - 1)
    warped = np.clip(mask_arr[src_y, src_x], 0, 255).astype(np.uint8)

    out_mask = Image.fromarray(warped, mode="L")
    colored = Image.new("RGBA", (Wm, Hm), (0, 0, 0, 0))
    solid = Image.new("RGBA", (Wm, Hm), tuple(fill) + (255,))
    colored = Image.composite(solid, colored, out_mask)
    return colored, bbox


def brush_stroke(width, height, color, seed=5):
    rng = np.random.RandomState(seed)
    pad = 20
    Wm, Hm = width + pad * 2, height + pad * 2
    mask = Image.new("L", (Wm, Hm), 0)
    md = ImageDraw.Draw(mask)
    md.rectangle([pad, pad, pad + width, pad + height], fill=255)
    cell = 16
    nh, nw = Hm // cell + 2, Wm // cell + 2
    n1 = Image.fromarray(rng.randint(0, 255, (nh, nw)).astype(np.uint8), mode="L").resize((Wm, Hm), Image.BICUBIC).filter(ImageFilter.GaussianBlur(3))
    n1a = np.asarray(n1).astype(np.float32)
    n1a = (n1a - n1a.mean()) / (n1a.std() + 1e-6)
    n2 = Image.fromarray(rng.randint(0, 255, (nh, nw)).astype(np.uint8), mode="L").resize((Wm, Hm), Image.BICUBIC).filter(ImageFilter.GaussianBlur(3))
    n2a = np.asarray(n2).astype(np.float32)
    n2a = (n2a - n2a.mean()) / (n2a.std() + 1e-6)
    mask_arr = np.asarray(mask).astype(np.float32)
    ys, xs = np.mgrid[0:Hm, 0:Wm]
    rgh = height * 0.35
    src_x = np.clip(xs + (n1a * rgh * 0.3).astype(np.int32), 0, Wm - 1)
    src_y = np.clip(ys + (n2a * rgh).astype(np.int32), 0, Hm - 1)
    warped = np.clip(mask_arr[src_y, src_x], 0, 255).astype(np.uint8)
    out_mask = Image.fromarray(warped, mode="L")
    colored = Image.new("RGBA", (Wm, Hm), (0, 0, 0, 0))
    solid = Image.new("RGBA", (Wm, Hm), tuple(color) + (255,))
    return Image.composite(solid, colored, out_mask)


def icon(d, cx, cy, r, kind):
    lw = 5
    d.ellipse([cx - r - 10, cy - r - 10, cx + r + 10, cy + r + 10], outline=RED, width=3)
    if kind == "ac":
        for a in range(6):
            ang = math.pi / 3 * a
            x2, y2 = cx + math.cos(ang) * r, cy + math.sin(ang) * r
            d.line([(cx, cy), (x2, y2)], fill=RED, width=lw)
    elif kind == "wheel":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=RED, width=lw)
        ir = r * 0.22
        d.ellipse([cx - ir, cy - ir, cx + ir, cy + ir], outline=RED, width=lw)
        for a in range(3):
            ang = (2 * math.pi / 3) * a - math.pi / 2
            d.line([(cx + math.cos(ang) * ir, cy + math.sin(ang) * ir), (cx + math.cos(ang) * r * 0.95, cy + math.sin(ang) * r * 0.95)], fill=RED, width=lw)
    elif kind == "window":
        d.rounded_rectangle([cx - r * 0.75, cy - r * 0.85, cx + r * 0.75, cy + r * 0.85], radius=8, outline=RED, width=lw)
        d.line([(cx - r * 0.55, cy - r * 0.15), (cx + r * 0.55, cy - r * 0.15)], fill=RED, width=lw)
        d.line([(cx - r * 0.3, cy + r * 0.3), (cx + r * 0.3, cy + r * 0.3)], fill=RED, width=lw - 2)
    elif kind == "sensor":
        d.ellipse([cx - r * 0.55, cy + r * 0.25, cx - r * 0.05, cy + r * 0.75], outline=RED, width=lw)
        for i in range(1, 4):
            rad = r * 0.35 * i
            d.arc([cx - rad + r * 0.1, cy + r * 0.5 - rad, cx + rad + r * 0.1, cy + r * 0.5 + rad], start=210, end=330, fill=RED, width=lw - 1)
    elif kind == "shield":
        pts = [(cx, cy - r), (cx + r * 0.8, cy - r * 0.5), (cx + r * 0.8, cy + r * 0.3), (cx, cy + r), (cx - r * 0.8, cy + r * 0.3), (cx - r * 0.8, cy - r * 0.5)]
        d.polygon(pts, outline=RED, width=lw)
        d.line([(cx - r * 0.35, cy), (cx - r * 0.1, cy + r * 0.3), (cx + r * 0.4, cy - r * 0.3)], fill=RED, width=lw, joint="curve")


ICON_KEYWORDS = [
    ("ac", ["ar condicionado", "ar-condicionado", "ar cond"]),
    ("wheel", ["direção", "direcao", "rodas de liga", "roda de liga"]),
    ("window", ["vidro", "trava elétric", "trava eletric", "vidros e travas"]),
    ("sensor", ["sensor de estacionamento", "sensor ré", "sensor re", "câmera de ré", "camera de re"]),
    ("shield", []),  # fallback kind, used for anything else
]


def kind_for_label(label):
    low = label.lower()
    for kind, keywords in ICON_KEYWORDS:
        for kw in keywords:
            if kw in low:
                return kind
    return "shield"


def split_tokens(label):
    tokens = []
    for part in label.split(" "):
        if "-" in part:
            sub = part.split("-")
            for k, s in enumerate(sub):
                tokens.append(s + ("-" if k < len(sub) - 1 else ""))
        else:
            tokens.append(part)
    return tokens


def wrap_and_fit(d, label, max_w, start_size, min_size=15):
    size = start_size
    lines = [label]
    while size >= min_size:
        f = font(size)
        tokens = split_tokens(label)
        lines, line = [], ""
        for t in tokens:
            sep = "" if line.endswith("-") or line == "" else " "
            test = line + sep + t
            tb = d.textbbox((0, 0), test, font=f)
            if tb[2] - tb[0] > max_w and line:
                lines.append(line)
                line = t
            else:
                line = test
        lines.append(line)
        ok = all(d.textbbox((0, 0), l, font=f)[2] - d.textbbox((0, 0), l, font=f)[0] <= max_w for l in lines)
        if ok:
            return f, lines
        size -= 2
    return font(min_size), lines


def fit_distressed(d, text, start_size, color, max_w, seed):
    size = start_size
    layer = None
    while size > 30:
        layer, bbox = distressed_text(text, FONT_PATH, size, color, stroke_w=max(2, size // 40), roughness=size * 0.013, cell=10, seed=seed)
        layer = italicize(layer, 0.22)
        if layer.width <= max_w:
            return layer
        size -= 4
    return layer


# ---------------------------------------------------------------- data shaping

def build_render_data(raw):
    data = normalize(raw)

    marca = str(data.get("marca", "")).upper()
    modelo = str(data.get("modelo", "")).upper()
    ano = str(data.get("ano_modelo") or data.get("ano") or "")
    preco = fmt_price(data.get("preco"))

    fotos = data.get("fotos") or []
    capa = data.get("foto_capa")
    if capa and capa not in fotos:
        fotos = [capa] + fotos
    fotos = [x for x in fotos if x]
    if len(fotos) < 4:
        raise ValueError("São necessárias pelo menos 4 fotos (1 principal + 3 na grade).")

    photo_main = fotos[0]
    photo_small = fotos[1:4]

    opts = data.get("opcionais") or []
    if isinstance(opts, str):
        opts = [x.strip() for x in opts.split(",") if x.strip()]
    opts = [o for o in opts if o][:5]
    if not opts:
        opts = ["AR-CONDICIONADO", "DIREÇÃO HIDRÁULICA", "VIDROS E TRAVAS ELÉTRICOS", "RODAS DE LIGA LEVE", "ÓTIMO ESTADO DE CONSERVAÇÃO"]
    features = [(kind_for_label(o), o.upper()) for o in opts]

    ribbon_text = str(data.get("ribbon_text") or "COMPLETO").upper()
    tagline = str(data.get("tagline") or "EXCELENTE OPORTUNIDADE!").upper()
    whatsapp_number = str(data.get("whatsapp") or "(51) 99573-4555")

    return {
        "marca": marca, "modelo": modelo, "ano": ano, "preco": preco,
        "ribbon_text": ribbon_text, "tagline": tagline,
        "features": features, "photo_main": photo_main, "photo_small": photo_small,
        "whatsapp_number": whatsapp_number,
    }


def render_png(raw):
    rd = build_render_data(raw)
    marca, modelo, ano = rd["marca"], rd["modelo"], rd["ano"]
    ribbon_text, tagline, features = rd["ribbon_text"], rd["tagline"], rd["features"]
    whatsapp_number = rd["whatsapp_number"]

    img = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(img)

    header_h = 230
    ribbon_y, ribbon_h = 230, 60
    photo_y, photo_h = 290, 610
    photo_w = int(W * 0.72)
    grid_y, grid_h = 900, 210
    tag_y, tag_h = 1110, 450
    diag_shift = 90

    main_im = download_image(rd["photo_main"])
    mp = cover_crop(main_im, photo_w, photo_h)
    img.paste(mp, (0, photo_y))

    shade = Image.new("RGB", (photo_w, 40), (0, 0, 0))
    overlay = Image.new("L", (photo_w, 40), 0)
    for yy in range(40):
        overlay.putpixel((0, yy), int(120 * (1 - yy / 40)))
    overlay = overlay.resize((photo_w, 40))
    img.paste(shade, (0, photo_y), overlay)

    d.polygon([(0, 0), (W, 0), (W, 1), (int(W * 0.70) - diag_shift, header_h), (0, header_h)], fill=BLACK)
    d.polygon([(int(W * 0.70) - diag_shift, 0), (W, 0), (W, ribbon_y + ribbon_h), (photo_w - diag_shift, ribbon_y + ribbon_h), (photo_w, ribbon_y)], fill=BLACK)

    tf = font(70)
    bbox = d.textbbox((0, 0), marca, font=tf)
    while bbox[2] - bbox[0] > W * 0.60 and tf.size > 30:
        tf = font(tf.size - 4)
        bbox = d.textbbox((0, 0), marca, font=tf)
    d.text((40, 28), marca, font=tf, fill=WHITE, stroke_width=2, stroke_fill="black")

    mf = font(70)
    bbox = d.textbbox((0, 0), modelo, font=mf)
    while bbox[2] - bbox[0] > W * 0.60 and mf.size > 30:
        mf = font(mf.size - 4)
        bbox = d.textbbox((0, 0), modelo, font=mf)
    d.text((40, 100), modelo, font=mf, fill=WHITE, stroke_width=2, stroke_fill="black")

    af = font(54)
    d.text((40, 172), ano, font=af, fill=RED, stroke_width=2, stroke_fill="black")
    abbox = d.textbbox((40, 172), ano, font=af)
    d.line([(abbox[2] + 16, 185), (abbox[2] + 220, 185)], fill=RED, width=5)
    d.line([(abbox[2] + 16, 198), (abbox[2] + 180, 198)], fill=RED, width=3)

    badge_w, badge_h = 360, 108
    badge_x = W - 40 - badge_w
    badge_y = 22
    d.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h], radius=16, fill=WHITE, outline=RED, width=4)

    logo_im = Image.open(LOGO_PATH).convert("RGB")
    pad = 18
    max_w, max_h = badge_w - pad * 2, badge_h - pad * 2
    lw_, lh_ = logo_im.size
    scale = min(max_w / lw_, max_h / lh_)
    new_w, new_h = int(lw_ * scale), int(lh_ * scale)
    logo_resized = logo_im.resize((new_w, new_h), Image.LANCZOS)
    lx = badge_x + (badge_w - new_w) // 2
    ly = badge_y + (badge_h - new_h) // 2
    img.paste(logo_resized, (lx, ly))

    def whatsapp_icon(cx, cy, r):
        wa_green = (37, 211, 102)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=wa_green)
        phone_f = font(int(r * 1.3))
        glyph = "☎"
        gb = d.textbbox((0, 0), glyph, font=phone_f)
        gw, gh = gb[2] - gb[0], gb[3] - gb[1]
        d.text((cx - gw / 2 - gb[0], cy - gh / 2 - gb[1]), glyph, font=phone_f, fill="white")

    wf_num = font(34)
    nbb = d.textbbox((0, 0), whatsapp_number, font=wf_num)
    num_w = nbb[2] - nbb[0]
    icon_r = 22
    gap = 14
    total_w = icon_r * 2 + gap + num_w
    start_x = badge_x + badge_w - total_w
    text_cy = badge_y + badge_h + 16 + icon_r
    whatsapp_icon(start_x + icon_r, text_cy, icon_r)
    d.text((start_x + icon_r * 2 + gap, text_cy - (nbb[3] - nbb[1]) / 2 - nbb[1]), whatsapp_number, font=wf_num, fill="white", stroke_width=1, stroke_fill="black")

    d.rectangle([0, ribbon_y, W, ribbon_y + ribbon_h], fill=RED)
    rf = font(40)
    bbox = d.textbbox((0, 0), ribbon_text, font=rf)
    d.text(((W - (bbox[2] - bbox[0])) / 2, ribbon_y + (ribbon_h - (bbox[3] - bbox[1])) / 2 - 6), ribbon_text, font=rf, fill=WHITE)

    list_x = photo_w + 55
    text_x = list_x + 85
    text_w = W - 30 - text_x
    row_h = photo_h / len(features)

    for i, (kind, label) in enumerate(features):
        fy = photo_y + row_h * i + row_h / 2
        icon_cx = list_x + 40
        icon(d, icon_cx, fy, 24, kind)
        f, lines = wrap_and_fit(d, label, text_w, 27)
        lh_px = f.size + 6
        start_y = fy - (len(lines) - 1) * lh_px / 2
        for j, l in enumerate(lines):
            d.text((text_x, start_y + j * lh_px - f.size / 2), l, font=f, fill=WHITE)
        if i < len(features) - 1:
            sep_y = photo_y + row_h * (i + 1)
            d.line([(list_x, sep_y), (W - 30, sep_y)], fill=(120, 30, 34), width=2)

    gap_px = 6
    cell_w = (W - gap_px * 4) // 3
    x = gap_px
    for p in rd["photo_small"]:
        im = download_image(p)
        im = cover_crop(im, cell_w, grid_h)
        img.paste(im, (x, grid_y))
        x += cell_w + gap_px

    d.polygon([(0, tag_y), (W, tag_y - 24), (W, tag_y + tag_h), (0, tag_y + tag_h)], fill=BLACK)
    d.line([(0, tag_y + 6), (W, tag_y - 18)], fill=RED, width=8)

    words = tagline.split(" ")
    w1 = words[0]
    w2 = " ".join(words[1:]) if len(words) > 1 else ""

    layer1 = fit_distressed(d, w1, 150, (255, 255, 255), int(W * 0.95), seed=11)
    layer2 = fit_distressed(d, w2, 120, (220, 30, 38), int(W * 0.95), seed=22) if w2 else None

    ty = tag_y + 20
    ty2 = ty + layer1.height - 30

    stroke1 = brush_stroke(int(W * 0.6), 14, RED, seed=31)
    stroke2 = brush_stroke(int(W * 0.35), 9, RED, seed=32)
    under_y = ty2 + (layer2.height if layer2 else layer1.height) - 40
    img.paste(stroke1, (int(W * 0.2), under_y), stroke1)
    img.paste(stroke2, (int(W * 0.08), under_y + 20), stroke2)

    img.paste(layer1, (int((W - layer1.width) / 2), ty), layer1)
    if layer2:
        img.paste(layer2, (int((W - layer2.width) / 2), ty2), layer2)

    return img, rd["preco"]


def upload(img, job):
    if not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_KEY não configurada.")
    bio = io.BytesIO()
    img.convert("RGB").save(bio, format="PNG", optimize=True)
    name = f"{SUPABASE_POSTS_FOLDER}/{job}.png"
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{name}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": "image/png",
        "x-upsert": "true",
        "cache-control": "3600",
    }
    r = requests.post(url, headers=headers, data=bio.getvalue(), timeout=180)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Upload HTTP {r.status_code}: {r.text[:500]}")
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{name}"


@ficha_bp.get("/ficha-health")
def health():
    return {
        "ok": True,
        "service": "premium-ficha-tecnica",
        "engine": "pillow-distressed-compositor",
        "size": f"{W}x{H}",
        "font_found": Path(FONT_PATH).exists(),
        "logo_found": Path(LOGO_PATH).exists(),
    }


@ficha_bp.post("/ficha")
def ficha():
    try:
        raw = request.get_json(force=True)
        img, preco = render_png(raw)
        job = uuid.uuid4().hex
        url = upload(img, job)
        return jsonify({
            "status": "done", "id": job, "url": url, "post_url": url,
            "engine": "pillow-distressed-compositor", "template": "ficha_tecnica",
            "source_price": preco,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "error": str(e)}), 500
