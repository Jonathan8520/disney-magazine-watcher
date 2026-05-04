import html
import json
import os
import re
import requests
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
# Mots-clés utilisés pour découvrir automatiquement les magazines Disney.
# Chaque mot-clé renvoie un sous-ensemble (avec recouvrement) ; on dédoublonne
# ensuite par codif.
KEYWORDS = ["picsou", "mickey", "fantomiald", "donald"]

# Slugs à ignorer (pochettes promo / SKU "produit" qui dupliquent le mag principal).
SKIP_SLUGS = ["pochette-", "--produit"]

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
        "cover_url": cover_url,
        "url": SITE_BASE + href_m.group(1) if href_m else SITE_BASE,
        "slug": href_m.group(2) if href_m else "",
        "site_name": html.unescape(alt_m.group(1)) if alt_m else "",
    }

def discover():
    """Recherche tous les magazines Disney via les mots-clés, dédoublonne par codif."""
    s = get_session()
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
            by_codif.setdefault(info["codif"], info)
    return list(by_codif.values())

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
    embed = {
        "title": f"{emoji} {full_title}",
        "url": info["url"],
        "color": color,
        "fields": [],
        "footer": {"text": "Source : direct-editeurs.fr"},
        "timestamp": datetime.utcnow().isoformat(),
    }
    if info["date_entree"]:
        embed["fields"].append({"name": "📅 En kiosque depuis", "value": info["date_entree"], "inline": True})
    if info["cover_url"]:
        embed["image"] = {"url": info["cover_url"]}

    payload = {
        "content": f"🆕 **Nouveau numéro disponible !** — {name}",
        "embeds": [embed],
    }
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()
    print(f"  ✅ Notification Discord envoyée pour {name} n°{info['numero']}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    state = load_state()
    updated = False

    print("🔎 Découverte des magazines Disney sur direct-editeurs.fr…")
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
        try:
            send_discord(name, emoji, color, info)
        except Exception as e:
            print(f"  ❌ Erreur Discord : {e}")
            continue
        state[codif] = {
            "name": name,
            "numero": numero,
            "date_entree": info["date_entree"],
            "detected_at": datetime.utcnow().isoformat(),
        }
        updated = True

    if updated:
        save_state(state)
        print("\n💾 State mis à jour.")
    else:
        print("\n✅ Aucun nouveau numéro détecté.")

if __name__ == "__main__":
    main()
