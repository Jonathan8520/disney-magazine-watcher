import html
import json
import os
import re
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# ── Config ────────────────────────────────────────────────────────────────────
# Mots-clés utilisés pour découvrir automatiquement les magazines Disney.
# Chaque mot-clé renvoie un sous-ensemble (avec recouvrement) ; on dédoublonne
# ensuite par codif.
KEYWORDS = ["picsou", "mickey", "mickey hs", "mickey parade", "fantomiald", "donald"]

# Codifs à exclure explicitement (magazines mal catégorisés sur MLP qui matchent
# nos sources de découverte sans être réellement Disney).
SKIP_CODIFS = {
    "11560",  # ANIME CULT (classé à tort en sous-famille Disney D23)
}

# Codifs qui paraissent systématiquement par lots de deux numéros (bi-issue).
# Quand DE/MLP ne publient que la forme simple N (oubli éditeur), on synthétise
# N-(N+1) pour rester sur la forme canonique et éviter de manquer la notif.
BI_ISSUE_CODIFS = {
    "14067",  # Journal de Mickey
}

# Override manuel pour les magazines principaux : emoji et couleur dédiés.
# Pour tous les autres, on utilise DEFAULT_EMOJI / DEFAULT_COLOR.
# `inducks` = code de la série dans la base Inducks (https://inducks.org).
# Quand renseigné, on ajoute un lien "Sommaire" pointant vers la page du numéro.
# Format URL : https://inducks.org/issue.php?c=fr/<CODE>  <NUM> (deux espaces).
OVERRIDES = {
    # ── Picsou Magazine et déclinaisons ──────────────────────────────────────
    "13159": {"name": "Picsou Magazine",                       "emoji": "💰", "color": 0xFFCC00, "inducks": "PM"},
    "15681": {"name": "Picsou Magazine HS Collection Deluxe",  "emoji": "📘", "inducks": ("CD", 5)},
    "15930": {"name": "Picsou Magazine HS Collection Deluxe (vol. 2)", "emoji": "📘", "inducks": ("CD", 5)},
    "18288": {"name": "Picsou HS Castors Juniors",             "emoji": "🦫", "inducks": ("PMHS", 3, "S")},
    "19603": {"name": "Picsou HS Souvenirs du Klondike",       "emoji": "⛏️"},
    "17575": {"name": "Picsou Anniversaire en or",             "emoji": "🎂"},
    "18658": {"name": "Picsou Soir",                           "emoji": "🌆"},
    "18360": {"name": "Nouvelle Jeunesse de Picsou",           "emoji": "🌱"},
    "19607": {"name": "Le Destin de Picsou",                   "emoji": "⏳"},
    "19052": {"name": "Pochette Picsou Magazine",              "emoji": "📦"},
    # ── Super Picsou Géant et déclinaisons ───────────────────────────────────
    "14016": {"name": "Super Picsou Géant",                    "emoji": "🦆", "color": 0xFF8C00, "inducks": ("SPG", 4)},
    "12651": {"name": "SPG HS Dynastie de Picsou",             "emoji": "📜", "inducks": ("SPGHS", 3, "H")},
    "15599": {"name": "SPG HS Dynastie de Picsou (REV)",       "emoji": "📜", "inducks": ("SPGHS", 3, "H")},
    "12825": {"name": "SPG HS Super Donald Géant",             "emoji": "🦆", "inducks": ("SPGHS", 3, "D")},
    "18262": {"name": "SPG HS Super Donald Géant (REV)",       "emoji": "🦆", "inducks": ("SPGHS", 3, "D")},
    "18268": {"name": "SPG HS Donald Double Duck (REV)",       "emoji": "🦹", "inducks": ("DON", 4)},
    "13459": {"name": "SPG HS Jeux",                           "emoji": "🎲", "inducks": ("SPGHS", 3, "J")},
    # ── Trésors de Picsou ────────────────────────────────────────────────────
    "14068": {"name": "Les Trésors de Picsou",                 "emoji": "💎", "color": 0x1E90FF, "inducks": "TP"},
    # ── Journal de Mickey et déclinaisons ────────────────────────────────────
    "14067": {"name": "Journal de Mickey",                     "emoji": "🐭", "color": 0xFF0000, "inducks": ("JM", 8)},
    "14108": {"name": "Journal de Mickey HS",                  "emoji": "⭐", "color": 0xCC0000, "inducks": ("JMHSN", 3)},
    "13588": {"name": "JdM HS Spécial Aventures (REV)",        "emoji": "🗺️"},
    "16096": {"name": "Journal de Mickey + Produit",           "emoji": "🎁"},
    "15935": {"name": "Le Meilleur du Journal de Mickey",      "emoji": "🏆", "color": 0xDAA520},
    "15970": {"name": "Le Meilleur du JdM HS",                 "emoji": "🏆"},
    "18914": {"name": "Le Meilleur du JdM HS Spécial Enquêtes","emoji": "🔍"},
    # ── Mickey Junior ────────────────────────────────────────────────────────
    "15528": {"name": "Mickey Junior",                         "emoji": "🧒", "color": 0xFFA500, "inducks": "MJ"},
    "14513": {"name": "Mickey Junior HS Jeux",                 "emoji": "🎲"},
    "18875": {"name": "Mickey Junior HS Baby",                 "emoji": "🍼"},
    # ── Mickey Parade ────────────────────────────────────────────────────────
    "11068": {"name": "Pochette Mickey Parade",                "emoji": "📦"},
    # ── Fantomiald ───────────────────────────────────────────────────────────
    "15190": {"name": "Les Chroniques de Fantomiald",          "emoji": "🦸", "color": 0x6A0DAD, "inducks": "CF"},
    # ── Disney divers ────────────────────────────────────────────────────────
    "14268": {"name": "Les Incontournables de Disney",         "emoji": "🏛️", "inducks": ("LI", 4)},
    "19064": {"name": "Les Incontournables (REV)",             "emoji": "🏛️", "inducks": ("LI", 4)},
}
DEFAULT_EMOJI = "🦆"
DEFAULT_COLOR = 0x808080

# Fenêtre calme (heure Paris, DST-aware) : on saute toute la run.
# On ne notifie PAS et on ne met PAS à jour le state pour ne pas masquer un
# nouveau numéro qui paraîtrait pendant cette plage (sinon la run du matin ne
# verrait plus la diff). Bornes inclusives sur l'heure de début, exclusives sur
# l'heure de fin : [QUIET_START, QUIET_END[.
QUIET_TZ = ZoneInfo("Europe/Paris")
QUIET_START = 23  # 23h00
QUIET_END = 7     # 07h00

SEARCH_URL = "https://direct-editeurs.fr/nos-magazines"
SITE_BASE = "https://direct-editeurs.fr"
MLP_URL = "https://catalogueproduits.mlp.fr/Default.aspx"
MLP_FAMILY_URL = "https://catalogueproduits.mlp.fr/liste.aspx?ssFam={}"
# Sous-familles MLP qu'on agrège côté découverte. D23 = "Disney" (Incontournables,
# Destin de Picsou, Souvenirs du Klondike, etc. — magazines spéciaux Disney).
MLP_FAMILIES = ["D23"]

# Glénat — éditeur des albums BD Disney en France (Picsou, Mickey, Donald,
# Fantomiald, Romano Scarpa, Don Rosa…). On surveille la page collection Disney,
# triée du plus récent au plus ancien : nouveautés et « à paraître » sont toujours
# en page 1, donc un seul fetch suffit. Le slug éditeur /glenat-disney/ filtre le
# Disney sans ambiguïté. État stocké dans le même state.json sous clés préfixées
# `glenat:<EAN>` (13 chiffres → aucune collision avec les codifs 5 chiffres).
GLENAT_COLLECTION_URL = "https://www.glenat.com/bd/collections/disney"
GLENAT_BASE = "https://www.glenat.com"
GLENAT_KEY_PREFIX = "glenat:"

STATE_FILE = "state.json"
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MagazineWatcher/1.0)"}

_session = None

def get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
        _session.get(SEARCH_URL, timeout=15)
    return _session

# ── Parsing ───────────────────────────────────────────────────────────────────
def parse_block(block):
    """Extrait codif/numéro/date/cover/url/slug d'un bloc <div class='info-mag'>."""
    codif_m = re.search(r"<span>Codif :</span>\s*(\d+)", block)
    if not codif_m:
        return None
    num_m = re.search(r"N° de parution\s*:</span>\s*([^<\s]+)", block)
    paru_m = re.search(r"Paru le\s*:</span>\s*([^<\s]+)", block)
    prix_m = re.search(r"Prix :</span>\s*([0-9.,]+\s*€)", block)
    expired_m = re.search(r"Trop vieux le\s*:</span>\s*(\d{2}/\d{2}/\d{4})", block)
    img_m = re.search(r'<img src="([^"]+/parutions/[^"]+)"', block)
    href_m = re.search(r'href="(/magazine/\d+_([a-z0-9-]+)[^"]*)"', block)
    alt_m = re.search(r'<img src="[^"]+/parutions/[^"]+"\s+alt="([^"]+)"', block)

    cover_url = None
    if img_m:
        # Direct Éditeurs sert les vignettes en 240x240 ; on prend la pleine taille.
        cover_url = re.sub(r"/\d+x\d+/parutions/", "/parutions/", img_m.group(1))

    return {
        "codif": codif_m.group(1),
        "numero": num_m.group(1) if num_m else None,
        "date_mise_en_vente": paru_m.group(1) if paru_m else None,
        "prix": re.sub(r"\s+", " ", prix_m.group(1)).strip() if prix_m else None,
        "expired_on": expired_m.group(1) if expired_m else None,
        "cover_url": cover_url,
        "url": SITE_BASE + href_m.group(1) if href_m else SITE_BASE,
        "slug": href_m.group(2) if href_m else "",
        "site_name": html.unescape(alt_m.group(1)) if alt_m else "",
    }

def discover_de():
    """Recherche tous les magazines Disney sur Direct Éditeurs via les mots-clés.
    Les magazines marqués 'Trop vieux' (date passée) sont ignorés.

    DE indexe parfois plusieurs entrées par codif pour la même parution (ex: JdM
    apparaît à la fois en n°3854 et n°3854-3855). On garde l'entrée la plus
    récente par 'Paru le' ; à date égale, on préfère le format à tiret (forme
    canonique éditeur + Inducks). Ne PAS préférer le tiret sans regarder la
    date, sinon un dash plus vieux écrase un simple plus récent — typique quand
    l'éditeur publie le simple avant le tiret pour le numéro suivant."""
    s = get_session()
    today = datetime.now().date()
    candidates = {}  # codif → list of info dicts (dédupliqués par numero)
    for kw in KEYWORDS:
        r = s.post(SEARCH_URL, data={"searchParution.title": kw}, timeout=15)
        r.raise_for_status()
        text = r.text
        # Délimite chaque bloc info-mag par la position du suivant.
        starts = [m.start() for m in re.finditer(r'<div class="info-mag"', text)]
        starts.append(len(text))
        for i in range(len(starts) - 1):
            info = parse_block(text[starts[i]:starts[i + 1]])
            if not info:
                continue
            if info["expired_on"]:
                d, m, y = info["expired_on"].split("/")
                if datetime(int(y), int(m), int(d)).date() < today:
                    continue
            lst = candidates.setdefault(info["codif"], [])
            if not any(c["numero"] == info["numero"] for c in lst):
                lst.append(info)

    def freshness(info):
        d = info.get("date_mise_en_vente")
        try:
            dd, mm, yy = d.split("/")
            parsed = datetime(int(yy), int(mm), int(dd))
        except (AttributeError, ValueError):
            parsed = datetime.min
        has_dash = "-" in (info.get("numero") or "")
        return (parsed, has_dash)  # tri décroissant : (date, dash) — dash préféré à date égale

    picked = {codif: max(lst, key=freshness) for codif, lst in candidates.items()}

    # Bi-issue : si le plus récent est sous forme simple "N", on le réécrit en
    # "N-(N+1)" (l'URL reste sur la page simple, c'est la page réellement publiée).
    for codif, info in picked.items():
        if codif in BI_ISSUE_CODIFS and info.get("numero") and "-" not in info["numero"]:
            m = re.match(r"(\d+)$", info["numero"])
            if m:
                n = int(m.group(1))
                info["numero"] = f"{n}-{n + 1}"
    return picked

def discover():
    """Découverte hybride : Direct Éditeurs (riche, structuré) + MLP en complément
    pour les magazines que DE n'indexe pas (ex: Picsou Soir, Destin de Picsou).
    Les codifs uniquement présents sur MLP sont enrichis via fetch_mlp_product."""
    de_results = discover_de()
    mlp_codifs = discover_mlp()
    for fam in MLP_FAMILIES:
        mlp_codifs |= discover_mlp_family(fam)
    # Retire les codifs explicitement blacklistés (DE comme MLP).
    for codif in SKIP_CODIFS:
        de_results.pop(codif, None)
    mlp_codifs -= SKIP_CODIFS
    extras = mlp_codifs - de_results.keys()
    if extras:
        print(f"   ⤷ {len(extras)} magazines MLP-only à enrichir : {', '.join(sorted(extras))}")
    for codif in extras:
        info = fetch_mlp_product(codif)
        if info:
            de_results[codif] = info
    return list(de_results.values())

# ── MLP : page produit (utilisée pour l'enrichissement et le fallback) ────────
# Sert pour deux cas :
#   - récupérer la date de relève prévisionnelle (DE ne l'a jamais pour la parution
#     courante)
#   - scraper toutes les infos d'un magazine MLP-only (que DE n'indexe pas, ex:
#     Picsou Soir codif 18658)
def _mlp_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    r0 = s.get(MLP_URL, timeout=15)
    def vs(name):
        m = re.search(rf'name="{name}"[^>]*value="([^"]*)"', r0.text)
        return m.group(1) if m else ""
    return s, {
        "__VIEWSTATE": vs("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": vs("__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": vs("__EVENTVALIDATION"),
    }

def fetch_mlp_product(codif):
    """POST recherche MLP par codif → page produit.
    Retourne un dict (codif, site_name, numero, date_mise_en_vente, date_retrait, prix,
    cover_url, url, slug, expired_on) ou None si introuvable."""
    try:
        s, viewstate = _mlp_session()
        data = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            **viewstate,
            "ctl00$searchBar$txtSearchByTitre": "",
            "ctl00$searchBar$txtSearchByCode": codif,
            "ctl00$searchBar$imgSearchValide.x": "5",
            "ctl00$searchBar$imgSearchValide.y": "5",
            "ctl00$searchBar$txtMisEnVenteDu": "",
            "ctl00$searchBar$txtMisEnVenteAu": "",
        }
        r1 = s.post(MLP_URL, data=data, timeout=15, allow_redirects=True)
        if "tit_code" not in r1.url:
            return None
        text = r1.text
        def find(suffix):
            m = re.search(
                rf'id="ContentPlaceHolder1_[^"]*{suffix}"[^>]*>([^<]+)</span>',
                text, re.IGNORECASE,
            )
            return m.group(1).strip() if m else None
        def date(j, mo, y):
            jj, mm, yy = find(j), find(mo), find(y)
            return f"{jj}/{mm}/{yy}" if (jj and mm and yy) else None
        # Cover image — l'ordre des attributs varie (src avant ou après id),
        # donc on extrait le tag entier puis le src à l'intérieur.
        img_tag = re.search(r'<img[^>]*id="couverture_1"[^>]*>', text)
        cover = None
        if img_tag:
            src_m = re.search(r'src="([^"]+)"', img_tag.group(0))
            if src_m:
                src = src_m.group(1)
                cover = src if src.startswith("http") else "https://catalogueproduits.mlp.fr/" + src.lstrip("/")
        # Numéro : extrait juste les chiffres + suffixe alpha (ex N°593H → 593H)
        num_raw = find("_num") or ""
        num_match = re.search(r"(\d+[A-Z]*)", num_raw)
        return {
            "codif": codif,
            "site_name": find("_tit1") or "",
            "numero": num_match.group(1) if num_match else None,
            "date_mise_en_vente": date("spanJe", "spanMe", "spanAe"),
            "date_retrait": date("spanJs", "spanMs", "spanAs"),
            "prix": find("_prix"),
            "cover_url": cover,
            "url": r1.url,
            "slug": "",
            "expired_on": None,
        }
    except Exception as e:
        print(f"  ⚠️  Lookup MLP échoué pour codif {codif} : {e}")
        return None

def discover_mlp_family(ss_fam):
    """Liste les magazines MLP d'une sous-famille (ex: D23 = Disney). GET simple,
    sans ASP.NET viewstate."""
    try:
        r = requests.get(MLP_FAMILY_URL.format(ss_fam), headers=HEADERS, timeout=15)
        r.raise_for_status()
        return set(re.findall(r'<span id="[^"]*_titCode">(\d+)</span>', r.text))
    except Exception as e:
        print(f"⚠️  discover_mlp_family({ss_fam}) échoué : {e}")
        return set()

def discover_mlp():
    """Recherche MLP par chaque mot-clé, dédoublonne par codif, renvoie un set
    de codifs. On ne récupère que les identifiants ; les infos détaillées seront
    ensuite chargées via fetch_mlp_product() pour les codifs MLP-only."""
    try:
        s, viewstate = _mlp_session()
        codifs = set()
        for kw in KEYWORDS:
            data = {
                "__EVENTTARGET": "",
                "__EVENTARGUMENT": "",
                **viewstate,
                "ctl00$searchBar$txtSearchByTitre": kw,
                "ctl00$searchBar$txtSearchByCode": "",
                "ctl00$searchBar$imgSearchValide.x": "5",
                "ctl00$searchBar$imgSearchValide.y": "5",
                "ctl00$searchBar$txtMisEnVenteDu": "",
                "ctl00$searchBar$txtMisEnVenteAu": "",
            }
            r = s.post(MLP_URL, data=data, timeout=15, allow_redirects=True)
            codifs.update(re.findall(r'<span id="[^"]*_titCode">(\d+)</span>', r.text))
        return codifs
    except Exception as e:
        print(f"⚠️  discover_mlp échoué : {e}")
        return set()

# ── State ─────────────────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

# ── Discord ───────────────────────────────────────────────────────────────────
def _post_discord(payload):
    """POST le payload au webhook en gérant le rate limit Discord (~5 req/s) :
    retry jusqu'à 4 fois en respectant l'en-tête Retry-After."""
    for _ in range(4):
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        if r.status_code == 429:
            retry_after = float(r.json().get("retry_after", 1))
            print(f"  ⏳ Rate limit Discord, attente {retry_after:.1f}s")
            time.sleep(retry_after + 0.3)
            continue
        r.raise_for_status()
        return
    raise RuntimeError("Discord rate limit non résolu après plusieurs tentatives")

def build_inducks_url(inducks, numero):
    """Construit l'URL Inducks pour un numéro. Format: 'fr/<CODE><ISSUE>' où
    l'issue est cadré à droite sur N caractères, éventuellement avec un préfixe
    lettre pour les HS multi-sous-séries (ex: SPGHS D6 = SPG HS Donald Géant 6).

    `inducks` accepte :
      - str → (code, largeur 5, sans préfixe)        ex: 'PM'
      - (code, largeur)                              ex: ('JMHSN', 3)
      - (code, largeur, préfixe)                     ex: ('SPGHS', 3, 'D')"""
    if not inducks or not numero:
        return None
    if isinstance(inducks, tuple):
        if len(inducks) == 3:
            code, pad, prefix = inducks
        else:
            code, pad = inducks
            prefix = ""
    else:
        code, pad, prefix = inducks, 5, ""
    # Bi-issue (ex: 3854-3855) : Inducks utilise la forme courte 3854-55.
    bi = re.match(r"(\d+)-(\d+)", numero)
    if bi:
        nstr = f"{bi.group(1)}-{bi.group(2)[-2:]}"
    else:
        # Strippe le suffixe alpha éventuel (594H → 594) pour la lookup Inducks.
        n = re.match(r"\d+", numero)
        if not n:
            return None
        nstr = n.group(0)
    from urllib.parse import quote_plus
    issue_padded = (prefix + nstr).rjust(pad)
    return "https://inducks.org/issue.php?c=" + quote_plus(f"fr/{code}{issue_padded}")

def send_discord(name, emoji, color, info, inducks_code=None):
    title_tail = info["site_name"] or name
    full_title = f"{title_tail} N°{info['numero']}" if info["numero"] else title_tail
    source = "catalogueproduits.mlp.fr" if "mlp.fr" in info["url"] else "direct-editeurs.fr"
    inducks_url = build_inducks_url(inducks_code, info["numero"])
    embed = {
        "title": f"{emoji} {full_title}",
        "url": info["url"],
        "color": color,
        "fields": [],
        "footer": {"text": f"Source : {source}"},
        "timestamp": datetime.utcnow().isoformat(),
    }
    if inducks_url:
        embed["description"] = f"[📋 Sommaire sur Inducks]({inducks_url})"
    if info["date_mise_en_vente"]:
        embed["fields"].append({"name": "📅 En kiosque depuis", "value": info["date_mise_en_vente"], "inline": True})
    if info.get("date_retrait"):
        embed["fields"].append({"name": "🗓️ Jusqu'au", "value": info["date_retrait"], "inline": True})
    if info.get("prix"):
        embed["fields"].append({"name": "💶 Prix", "value": info["prix"], "inline": True})
    if info["cover_url"]:
        embed["image"] = {"url": info["cover_url"]}

    # REV (Remis En Vente) et pochettes = ré-éditions/lots, pas une vraie nouveauté.
    is_rev = bool(re.search(r"\b(REV|POCH(?:ETTE)?)\b", name, re.IGNORECASE))
    headline = "🔁 **Remis en vente !**" if is_rev else "🆕 **Nouveau numéro disponible !**"
    payload = {
        "content": f"{headline} — {name}",
        "embeds": [embed],
    }
    _post_discord(payload)
    print(f"  ✅ Notification Discord envoyée pour {name} n°{info['numero']}")

# ── Glénat (BD Disney) ────────────────────────────────────────────────────────
# Deux événements distincts peuvent notifier pour un même album, parfois à des
# mois d'intervalle :
#   1. ANNONCE — l'album apparaît « à paraître » (tag `soon`)            → 📢
#   2. SORTIE  — sa date de parution est atteinte (tag `new` / date)     → 📚
# Un album du fonds (aucun tag) qui apparaît est enregistré en silence pour ne
# pas notifier d'anciens albums (ex: bloc « à découvrir »). Au tout premier run
# (aucune clé `glenat:`), on seed tout en silence.
_GLENAT_CARD_RE = re.compile(
    r'<a[^>]*href="(/glenat-disney/[a-z0-9-]+-(\d{13})/)"(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_GLENAT_TITLE_RE = re.compile(r'class="[^"]*\bTitle\b[^"]*"[^>]*>([^<]+)<')
_GLENAT_ARIA_RE = re.compile(r'aria-label="([^"]+)"')
_GLENAT_DATE_RE = re.compile(r'class="[^"]*\bReleaseDate\b[^"]*"[^>]*>\s*(\d{2}/\d{2}/\d{4})')
_GLENAT_TAG_RE = re.compile(r'type="(soon|new)"')

def _parse_glenat_cards(text):
    """Extrait les cartes BD Disney : ean, titre, date (dd/mm/yyyy), tag, url.
    `tag` vaut 'soon' (à paraître), 'new' (sortie récente) ou None (fonds)."""
    out, seen = [], set()
    for href, ean, body in _GLENAT_CARD_RE.findall(text):
        if ean in seen:
            continue
        seen.add(ean)
        tm = _GLENAT_TITLE_RE.search(body) or _GLENAT_ARIA_RE.search(body)
        dm = _GLENAT_DATE_RE.search(body)
        tag = _GLENAT_TAG_RE.search(body)
        out.append({
            "ean": ean,
            "title": html.unescape(tm.group(1)).strip() if tm else None,
            "date": dm.group(1) if dm else None,
            "tag": tag.group(1) if tag else None,
            "url": GLENAT_BASE + href,
        })
    return out

def discover_glenat():
    """Liste les BD Disney de la page collection Glénat (page 1, récent→ancien)."""
    try:
        r = requests.get(GLENAT_COLLECTION_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
        r.encoding = "utf-8"  # le serveur annonce ISO-8859-1 à tort → forcer UTF-8
        return _parse_glenat_cards(r.text)
    except Exception as e:
        print(f"⚠️  discover_glenat échoué : {e}")
        return []

def fetch_glenat_product(url):
    """Enrichit un album via sa fiche : cover HD, prix, série, collection, résumé.
    Tout est dans le blob __NEXT_DATA__ (props.pageProps.data)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        r.encoding = "utf-8"
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
        if not m:
            return {}
        d = json.loads(m.group(1))["props"]["pageProps"]["data"]
        ean = d.get("ean", "")
        cov = re.search(
            rf'https://media\.hachette\.fr/fit-in/\d+x\d+/imgArticle/GLENAT/\d+/{ean}-001-X\.jpe?g[^"\\]*',
            r.text,
        )
        resume = re.sub(r"<[^>]+>", "", html.unescape(d.get("resume") or "")).strip()
        return {
            "title": d.get("titre_de_couverture"),
            "serie": d.get("serie_label"),
            "collection": d.get("collection_label"),
            "prix": d.get("prix_ttc"),
            "resume": resume,
            # html.unescape : l'URL brute contient &amp; (encodé HTML) → &
            "cover_url": html.unescape(cov.group(0)) if cov else None,
        }
    except Exception as e:
        print(f"  ⚠️  Fiche Glénat échouée ({url}) : {e}")
        return {}

def send_glenat_discord(item, enrich, kind):
    """Notifie un album BD Disney Glénat. kind = 'announced' | 'released'."""
    title = enrich.get("title") or item["title"] or "BD Disney"
    if kind == "released":
        emoji, color = "📚", 0x009688
        headline = "📚 **BD Disney en librairie !**"
        date_label = "📅 En librairie le"
    else:
        emoji, color = "📆", 0x3F51B5
        headline = "📢 **Nouvelle BD Disney annoncée !**"
        date_label = "🗓️ Parution prévue le"
    embed = {
        "title": f"{emoji} {title}",
        "url": item["url"],
        "color": color,
        "fields": [],
        "footer": {"text": "Source : glenat.com (Glénat Disney)"},
        "timestamp": datetime.utcnow().isoformat(),
    }
    desc = []
    if enrich.get("serie"):
        desc.append(f"*Série : {enrich['serie']}*")
    if enrich.get("resume"):
        txt = enrich["resume"]
        desc.append(txt[:300] + ("…" if len(txt) > 300 else ""))
    if desc:
        embed["description"] = "\n".join(desc)
    if item.get("date"):
        embed["fields"].append({"name": date_label, "value": item["date"], "inline": True})
    if enrich.get("prix"):
        embed["fields"].append({"name": "💶 Prix", "value": f"{enrich['prix']} €", "inline": True})
    if enrich.get("collection"):
        embed["fields"].append({"name": "📚 Collection", "value": enrich["collection"], "inline": True})
    if enrich.get("cover_url"):
        embed["image"] = {"url": enrich["cover_url"]}
    _post_discord({"content": f"{headline} — {title}", "embeds": [embed]})
    print(f"  ✅ Notif Glénat envoyée ({kind}) : {title}")

def check_glenat(state):
    """Surveille les BD Disney Glénat. Retourne True si le state a changé.
    Clés `glenat:<EAN>`. 1er run (aucune clé glenat:) = seed silencieux."""
    print("\n📚 Découverte des BD Disney (Glénat)…")
    items = discover_glenat()
    if not items:
        print("   (aucune carte récupérée — state Glénat inchangé)")
        return False
    print(f"   {len(items)} BD Disney en page 1")

    seeding = not any(k.startswith(GLENAT_KEY_PREFIX) for k in state)
    if seeding:
        print("   🌱 1er run Glénat : seed silencieux (aucune notif)")
    today = datetime.now().date()
    now = datetime.utcnow().isoformat()
    updated = False

    def _parse_fr(d):
        try:
            dd, mm, yy = d.split("/")
            return datetime(int(yy), int(mm), int(dd)).date()
        except (AttributeError, ValueError):
            return None

    for item in items:
        key = GLENAT_KEY_PREFIX + item["ean"]
        live_date = _parse_fr(item.get("date"))
        is_out = (live_date is not None and live_date <= today) or item.get("tag") == "new"
        st = state.get(key)

        # ── Seed : on enregistre tout sans notifier ──────────────────────────
        if seeding:
            state[key] = {
                "title": item["title"], "date_parution": item.get("date"),
                "url": item["url"], "announced_at": now,
                "released_at": now if is_out else None, "seeded": True,
            }
            updated = True
            continue

        # ── Nouvel album jamais vu ───────────────────────────────────────────
        if st is None:
            tag = item.get("tag")
            if tag == "soon":
                kind = "announced"
            elif tag == "new":
                kind = "released"
            else:
                # Fonds de catalogue sans tag (souvent un bloc « à découvrir ») :
                # on l'enregistre en silence pour ne pas notifier d'anciens albums.
                # NB : on classe une *première apparition* au tag seul ; la date
                # (is_out) ne sert qu'à la transition d'un album déjà connu.
                state[key] = {
                    "title": item["title"], "date_parution": item.get("date"),
                    "url": item["url"], "announced_at": now,
                    "released_at": now if is_out else None, "backfilled": True,
                }
                updated = True
                continue
            enrich = fetch_glenat_product(item["url"])
            print(f"   🆕 {item['title']} ({item['ean']}) → {kind}")
            try:
                send_glenat_discord(item, enrich, kind)
                sent = True
            except Exception as e:
                print(f"   ❌ Erreur Discord Glénat : {e}")
                sent = False
            state[key] = {
                "title": enrich.get("title") or item["title"],
                "serie": enrich.get("serie"),
                "date_parution": item.get("date"),
                "prix": enrich.get("prix"),
                "url": item["url"],
                "cover_url": enrich.get("cover_url"),
                "announced_at": now,
                "released_at": now if kind == "released" else None,
                "detected_at": now,
            }
            updated = True
            if sent:
                time.sleep(1)
            continue

        # ── Album connu : notif « sortie » quand la date est atteinte ────────
        if st.get("released_at") is None and is_out:
            enrich = fetch_glenat_product(item["url"])
            print(f"   📚 {item['title']} ({item['ean']}) → date atteinte (released)")
            try:
                send_glenat_discord(item, enrich, "released")
            except Exception as e:
                print(f"   ❌ Erreur Discord Glénat : {e}")
            st["released_at"] = now
            st["date_parution"] = item.get("date")
            if enrich.get("prix"):
                st["prix"] = enrich["prix"]
            if enrich.get("cover_url"):
                st["cover_url"] = enrich["cover_url"]
            updated = True
            time.sleep(1)

    return updated

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # Heures calmes : on quitte avant tout, sans même charger l'état (la
    # première run en sortie de plage repèrera les nouveautés de la nuit).
    hour = datetime.now(QUIET_TZ).hour
    in_quiet = (QUIET_START <= hour) or (hour < QUIET_END) if QUIET_START > QUIET_END \
               else (QUIET_START <= hour < QUIET_END)
    if in_quiet:
        print(f"😴 Heures calmes ({QUIET_START}h-{QUIET_END}h Paris, il est {hour}h) — run sautée.")
        return

    state = load_state()
    updated = False

    print("🔎 Découverte des magazines Disney (Direct Éditeurs + MLP)…")
    magazines = discover()
    print(f"   {len(magazines)} magazines trouvés\n")

    for info in magazines:
        codif = info["codif"]
        ov = OVERRIDES.get(codif, {})
        name = ov.get("name") or info["site_name"] or f"Magazine {codif}"
        emoji = ov.get("emoji", DEFAULT_EMOJI)
        color = ov.get("color", DEFAULT_COLOR)

        print(f"{emoji} {name} (codif {codif})")
        numero = info["numero"]
        if not numero:
            print("  ⚠️  Pas de numéro détecté, skip")
            continue

        last_known = state.get(codif, {}).get("numero")
        if last_known == numero:
            print(f"  ✔️  Pas de changement (n°{numero})")
            continue

        print(f"  🆕 Nouveau numéro : n°{numero} (précédent : {last_known})")
        # Enrichissement MLP : on l'interroge systématiquement à la notif pour
        # avoir date_retrait (DE ne l'a pas) ET corriger le prix (DE est parfois
        # désynchro — ex: JdM affiché 4,9€ alors que le vrai prix MLP est 5,9€).
        # Garde-fou : on ne copie depuis MLP que si la base numérique correspond
        # (DE="3858" ou "3858-3859" ↔ MLP="3858H" : même magazine, prix valide ;
        # mais si MLP est en retard et renvoie 3856, on ne mélange pas).
        mlp_info = fetch_mlp_product(codif) if "mlp.fr" not in info["url"] else None
        def _num_base(s):
            m = re.match(r"\d+", s or "")
            return m.group(0) if m else None
        if mlp_info and _num_base(mlp_info.get("numero")) == _num_base(numero):
            if not info.get("date_retrait"):
                info["date_retrait"] = mlp_info.get("date_retrait")
            if mlp_info.get("prix"):
                info["prix"] = mlp_info["prix"]
        elif mlp_info:
            print(f"  ⚠️  MLP renvoie n°{mlp_info.get('numero')} ≠ DE n°{numero} — pas d'enrichissement")
        # Numéro déjà retiré de la vente : on enregistre dans le state pour garder
        # la trace, mais on ne notifie pas (analogue au filtre 'Trop vieux' DE,
        # appliqué au flux MLP qui ne pré-filtre pas).
        notify = True
        if info.get("date_retrait"):
            d, m, y = info["date_retrait"].split("/")
            if datetime(int(y), int(m), int(d)).date() < datetime.now().date():
                notify = False
                print(f"  🔇 Périmé ({info['date_retrait']}) — ajouté au state sans notif")
        if notify:
            try:
                send_discord(name, emoji, color, info, inducks_code=ov.get("inducks"))
            except Exception as e:
                print(f"  ❌ Erreur Discord : {e}")
                continue
        state[codif] = {
            "name": name,
            "numero": numero,
            "date_mise_en_vente": info["date_mise_en_vente"],
            "date_retrait": info["date_retrait"],
            "prix": info.get("prix"),
            "url": info["url"],
            "inducks_url": build_inducks_url(ov.get("inducks"), numero),
            "detected_at": datetime.utcnow().isoformat(),
        }
        updated = True
        if notify:
            # Throttle pour rester sous la limite Discord (~5 webhooks/s).
            time.sleep(1)

    # BD Disney chez Glénat (même webhook, même state.json). Isolé du flux
    # magazines : une erreur ici ne doit jamais faire échouer la run principale.
    try:
        if check_glenat(state):
            updated = True
    except Exception as e:
        print(f"⚠️  Bloc Glénat ignoré (erreur inattendue) : {e}")

    if updated:
        save_state(state)
        print("\n💾 State mis à jour.")
    else:
        print("\n✅ Aucun nouveau numéro détecté.")

if __name__ == "__main__":
    main()
