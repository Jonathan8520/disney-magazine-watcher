import html
import json
import os
import re
import time
import requests
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
# Mots-clés utilisés pour découvrir automatiquement les magazines Disney.
# Chaque mot-clé renvoie un sous-ensemble (avec recouvrement) ; on dédoublonne
# ensuite par codif.
KEYWORDS = ["picsou", "mickey", "mickey parade", "fantomiald", "donald"]

# Slugs à ignorer (pochettes promo / SKU "produit" qui dupliquent le mag principal).
SKIP_SLUGS = ["pochette-", "--produit"]

# Codifs à exclure explicitement (magazines mal catégorisés sur MLP qui matchent
# nos sources de découverte sans être réellement Disney).
SKIP_CODIFS = {
    "11560",  # ANIME CULT (classé à tort en sous-famille Disney D23)
}

# Override manuel pour les magazines principaux : emoji et couleur dédiés.
# Pour tous les autres, on utilise DEFAULT_EMOJI / DEFAULT_COLOR.
OVERRIDES = {
    "13159": {"name": "Picsou Magazine",                  "emoji": "💰", "color": 0xFFCC00},
    "14016": {"name": "Super Picsou Géant",               "emoji": "🦆", "color": 0xFF8C00},
    "14067": {"name": "Journal de Mickey",                "emoji": "🐭", "color": 0xFF0000},
    "14108": {"name": "Journal de Mickey HS",             "emoji": "⭐", "color": 0xCC0000},
    "15190": {"name": "Les Chroniques de Fantomiald",     "emoji": "🦸", "color": 0x6A0DAD},
    "14068": {"name": "Les Trésors de Picsou",            "emoji": "💎", "color": 0x1E90FF},
    "15528": {"name": "Mickey Junior",                    "emoji": "🧒", "color": 0xFFA500},
    "15935": {"name": "Le Meilleur du Journal de Mickey", "emoji": "🏆", "color": 0xDAA520},
}
DEFAULT_EMOJI = "🦆"
DEFAULT_COLOR = 0x808080

SEARCH_URL = "https://direct-editeurs.fr/nos-magazines"
SITE_BASE = "https://direct-editeurs.fr"
MLP_URL = "https://catalogueproduits.mlp.fr/Default.aspx"
MLP_FAMILY_URL = "https://catalogueproduits.mlp.fr/liste.aspx?ssFam={}"
# Sous-familles MLP qu'on agrège côté découverte. D23 = "Disney" (Incontournables,
# Destin de Picsou, Souvenirs du Klondike, etc. — magazines spéciaux Disney).
MLP_FAMILIES = ["D23"]
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
        "date_entree": paru_m.group(1) if paru_m else None,
        "prix": re.sub(r"\s+", " ", prix_m.group(1)).strip() if prix_m else None,
        "expired_on": expired_m.group(1) if expired_m else None,
        "cover_url": cover_url,
        "url": SITE_BASE + href_m.group(1) if href_m else SITE_BASE,
        "slug": href_m.group(2) if href_m else "",
        "site_name": html.unescape(alt_m.group(1)) if alt_m else "",
    }

def discover_de():
    """Recherche tous les magazines Disney sur Direct Éditeurs via les mots-clés.
    Les pochettes promo et les magazines marqués 'Trop vieux' (date passée) sont
    ignorés."""
    s = get_session()
    today = datetime.now().date()
    by_codif = {}
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
            if any(p in info["slug"] for p in SKIP_SLUGS):
                continue
            if info["expired_on"]:
                d, m, y = info["expired_on"].split("/")
                if datetime(int(y), int(m), int(d)).date() < today:
                    continue
            by_codif.setdefault(info["codif"], info)
    return by_codif

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
    Retourne un dict (codif, site_name, numero, date_entree, date_sortie, prix,
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
            "date_entree": date("spanJe", "spanMe", "spanAe"),
            "date_sortie": date("spanJs", "spanMs", "spanAs"),
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
    """Liste les magazines MLP d'une sous-famille (ex: D23 = Disney). Filtre
    pochettes et bundles comme discover_mlp(). Sans ASP.NET viewstate (GET simple)."""
    try:
        r = requests.get(MLP_FAMILY_URL.format(ss_fam), headers=HEADERS, timeout=15)
        r.raise_for_status()
        codifs = set()
        for m in re.finditer(
            r'<span id="[^"]*_titre">([^<]+)</span>\s*</p>\s*'
            r'<p[^>]*>\s*<span id="[^"]*_titCode">(\d+)</span>',
            r.text,
        ):
            titre, codif = m.group(1).strip(), m.group(2)
            t = titre.upper()
            if t.startswith("POCH") or "+ PRODU" in t:
                continue
            codifs.add(codif)
        return codifs
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
            for m in re.finditer(
                r'<span id="[^"]*_titre">([^<]+)</span>\s*</p>\s*'
                r'<p[^>]*>\s*<span id="[^"]*_titCode">(\d+)</span>',
                r.text,
            ):
                titre, codif = m.group(1).strip(), m.group(2)
                # Skip pochettes et bundles "AVEC + PRODU" (équivalent de SKIP_SLUGS sur DE).
                t = titre.upper()
                if t.startswith("POCH") or "+ PRODU" in t:
                    continue
                codifs.add(codif)
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
def send_discord(name, emoji, color, info):
    title_tail = info["site_name"] or name
    full_title = f"{title_tail} N°{info['numero']}" if info["numero"] else title_tail
    source = "catalogueproduits.mlp.fr" if "mlp.fr" in info["url"] else "direct-editeurs.fr"
    embed = {
        "title": f"{emoji} {full_title}",
        "url": info["url"],
        "color": color,
        "fields": [],
        "footer": {"text": f"Source : {source}"},
        "timestamp": datetime.utcnow().isoformat(),
    }
    if info["date_entree"]:
        embed["fields"].append({"name": "📅 En kiosque depuis", "value": info["date_entree"], "inline": True})
    if info.get("date_sortie"):
        embed["fields"].append({"name": "🗓️ Jusqu'au", "value": info["date_sortie"], "inline": True})
    if info.get("prix"):
        embed["fields"].append({"name": "💶 Prix", "value": info["prix"], "inline": True})
    if info["cover_url"]:
        embed["image"] = {"url": info["cover_url"]}

    payload = {
        "content": f"🆕 **Nouveau numéro disponible !** — {name}",
        "embeds": [embed],
    }
    # Discord webhook limit ~5 req/s : on retry sur 429 en respectant Retry-After.
    for _ in range(4):
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        if r.status_code == 429:
            retry_after = float(r.json().get("retry_after", 1))
            print(f"  ⏳ Rate limit Discord, attente {retry_after:.1f}s")
            time.sleep(retry_after + 0.3)
            continue
        r.raise_for_status()
        break
    else:
        raise RuntimeError("Discord rate limit non résolu après plusieurs tentatives")
    print(f"  ✅ Notification Discord envoyée pour {name} n°{info['numero']}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
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
        # date_sortie peut déjà être renseignée si l'info vient de fetch_mlp_product
        # (cas des magazines MLP-only). Sinon on fait le lookup MLP maintenant.
        if not info.get("date_sortie"):
            mlp_info = fetch_mlp_product(codif)
            info["date_sortie"] = mlp_info.get("date_sortie") if mlp_info else None
        try:
            send_discord(name, emoji, color, info)
        except Exception as e:
            print(f"  ❌ Erreur Discord : {e}")
            continue
        state[codif] = {
            "name": name,
            "numero": numero,
            "date_entree": info["date_entree"],
            "date_sortie": info["date_sortie"],
            "prix": info.get("prix"),
            "detected_at": datetime.utcnow().isoformat(),
        }
        updated = True
        # Throttle pour rester sous la limite Discord (~5 webhooks/s).
        time.sleep(1)

    if updated:
        save_state(state)
        print("\n💾 State mis à jour.")
    else:
        print("\n✅ Aucun nouveau numéro détecté.")

if __name__ == "__main__":
    main()
