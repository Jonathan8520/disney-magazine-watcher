import json
import os
import re
import requests
from datetime import datetime

# ── Config magazines ──────────────────────────────────────────────────────────
# `codif` = identifiant numérique du magazine sur direct-editeurs.fr
# (visible dans l'URL et le bloc "Codif :" de la page).
MAGAZINES = [
    {"name": "Picsou Magazine",                  "codif": "13159", "emoji": "💰", "color": 0xFFCC00},
    {"name": "Super Picsou Géant",               "codif": "14016", "emoji": "🦆", "color": 0xFF8C00},
    {"name": "Journal de Mickey",                "codif": "14067", "emoji": "🐭", "color": 0xFF0000},
    {"name": "Journal de Mickey HS",             "codif": "14108", "emoji": "⭐", "color": 0xCC0000},
    {"name": "Les Chroniques de Fantomiald",     "codif": "15190", "emoji": "🦸", "color": 0x6A0DAD},
    {"name": "Les Trésors de Picsou",            "codif": "14068", "emoji": "💎", "color": 0x1E90FF},
    {"name": "Mickey Junior",                    "codif": "15528", "emoji": "🧒", "color": 0xFFA500},
    {"name": "Le Meilleur du Journal de Mickey", "codif": "15935", "emoji": "🏆", "color": 0xDAA520},
    {"name": "Picsou HS Collection Deluxe",      "codif": "15681", "emoji": "📘", "color": 0x4169E1},
    {"name": "Picsou HS Castors Juniors",        "codif": "18288", "emoji": "🦫", "color": 0x228B22},
    {"name": "Picsou HS Souvenirs du Klondike",  "codif": "19603", "emoji": "⛏️", "color": 0xB8860B},
    {"name": "Picsou Anniversaire en or",        "codif": "17575", "emoji": "🎂", "color": 0xFFD700},
]

SEARCH_URL = "https://direct-editeurs.fr/nos-magazines"
SITE_BASE = "https://direct-editeurs.fr"
STATE_FILE = "state.json"
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MagazineWatcher/1.0)"
}

# Une session partagée pour tous les magazines (cookies + jsessionid).
_session = None

def get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
        _session.get(SEARCH_URL, timeout=15)
    return _session

# ── Scraping ──────────────────────────────────────────────────────────────────
def fetch_magazine(codif):
    """
    Recherche le magazine par son codif sur direct-editeurs.fr et extrait
    les infos de la parution courante (numéro, date, couverture, lien).
    """
    s = get_session()
    resp = s.post(SEARCH_URL, data={"searchParution.title": codif}, timeout=15)
    resp.raise_for_status()
    text = resp.text

    # Le bloc <div class="info-mag"> du résultat de recherche contient tout :
    # codif, n° de parution, date "Paru le", couverture, messagerie.
    marker = f"<span>Codif :</span> {codif}"
    i = text.find(marker)
    if i < 0:
        raise ValueError(f"Aucun résultat pour codif {codif}")

    start = text.rfind('class="info-mag"', 0, i)
    end = text.find('class="info-mag"', i + 1)
    block = text[start:end] if end > 0 else text[start:start + 5000]

    num_match = re.search(r"N° de parution\s*:</span>\s*([^<\s]+)", block)
    numero = num_match.group(1) if num_match else None

    paru_match = re.search(r"Paru le\s*:</span>\s*([^<\s]+)", block)
    date_entree = paru_match.group(1) if paru_match else None

    # Date de relève (souvent vide pour la parution courante)
    relev_match = re.search(r"Relev&eacute; le\s*:</span>\s*([0-9/]+)", block)
    if not relev_match:
        relev_match = re.search(r"Relevé le\s*:</span>\s*([0-9/]+)", block)
    date_sortie = relev_match.group(1) if relev_match else None

    # Cover : on prend la version pleine taille (sans préfixe 240x240)
    img_match = re.search(r'<img src="([^"]+/parutions/[^"]+)"', block)
    cover_url = None
    if img_match:
        cover_url = re.sub(r"/\d+x\d+/parutions/", "/parutions/", img_match.group(1))

    # Lien direct vers la page produit
    href_match = re.search(r'href="(/magazine/[^"]+)"', block)
    page_url = SITE_BASE + href_match.group(1) if href_match else SITE_BASE

    # Nom affiché par le site (l'attribut alt= de la cover, en MAJUSCULES)
    alt_match = re.search(r'<img src="[^"]+/parutions/[^"]+"\s+alt="([^"]+)"', block)
    site_name = alt_match.group(1) if alt_match else ""
    full_title = f"{site_name} N°{numero}" if site_name and numero else site_name

    return {
        "numero": numero,
        "full_title": full_title,
        "date_entree": date_entree,
        "date_sortie": date_sortie,
        "cover_url": cover_url,
        "url": page_url,
    }

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
def send_discord(mag, info):
    embed = {
        "title": f"{mag['emoji']} {info['full_title']}",
        "url": info["url"],
        "color": mag["color"],
        "fields": [],
        "footer": {"text": "Source : direct-editeurs.fr"},
        "timestamp": datetime.utcnow().isoformat(),
    }
    if info["date_entree"]:
        embed["fields"].append({"name": "📅 En kiosque depuis", "value": info["date_entree"], "inline": True})
    if info["date_sortie"]:
        embed["fields"].append({"name": "🗓️ Jusqu'au", "value": info["date_sortie"], "inline": True})
    if info["cover_url"]:
        embed["image"] = {"url": info["cover_url"]}

    payload = {
        "content": f"🆕 **Nouveau numéro disponible !** — {mag['name']}",
        "embeds": [embed],
    }
    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    r.raise_for_status()
    print(f"  ✅ Notification Discord envoyée pour {mag['name']} n°{info['numero']}")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    state = load_state()
    updated = False

    for mag in MAGAZINES:
        name = mag["name"]
        print(f"🔍 Vérification : {name}")
        try:
            info = fetch_magazine(mag["codif"])
            numero = info["numero"]

            if not numero:
                print(f"  ⚠️  Impossible de détecter le numéro pour {name}")
                continue

            last_known = state.get(name, {}).get("numero")

            if last_known != numero:
                print(f"  🆕 Nouveau numéro détecté : n°{numero} (précédent : {last_known})")
                send_discord(mag, info)
                state[name] = {
                    "numero": numero,
                    "full_title": info["full_title"],
                    "date_entree": info["date_entree"],
                    "date_sortie": info["date_sortie"],
                    "detected_at": datetime.utcnow().isoformat(),
                }
                updated = True
            else:
                print(f"  ✔️  Pas de changement (n°{numero})")

        except Exception as e:
            print(f"  ❌ Erreur pour {name} : {e}")

    if updated:
        save_state(state)
        print("\n💾 State mis à jour.")
    else:
        print("\n✅ Aucun nouveau numéro détecté.")

if __name__ == "__main__":
    main()
