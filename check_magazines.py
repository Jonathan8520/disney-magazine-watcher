import json
import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import quote

# ── Config magazines ──────────────────────────────────────────────────────────
MAGAZINES = [
    {"name": "Picsou Magazine",          "tit_code": "njphxbE4HOM=",  "emoji": "💰", "color": 0xFFCC00},
    {"name": "Super Picsou Géant",       "tit_code": "lWSO/eJV+aI=",  "emoji": "🦆", "color": 0xFF8C00},
    {"name": "Journal de Mickey",        "tit_code": "m6XSnFo3ZUQ=",  "emoji": "🐭", "color": 0xFF0000},
    {"name": "Journal de Mickey HS",     "tit_code": "sIixRZCuH84=",  "emoji": "⭐", "color": 0xCC0000},
    {"name": "Fantomiald",               "tit_code": "l4QEZfnUEIk=",  "emoji": "🦸", "color": 0x6A0DAD},
    {"name": "Les Trésors de Picsou",    "tit_code": "6suANHFJ4cU=",  "emoji": "💎", "color": 0x1E90FF},
    {"name": "Mon 1er Journal de Mickey","tit_code": "bR3wPNssFY4=",  "emoji": "🌟", "color": 0xFF69B4},
]

BASE_URL = "https://catalogueproduits.mlp.fr/produit.aspx?tit_code={}"
STATE_FILE = "state.json"
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MagazineWatcher/1.0)"
}

# ── Scraping ──────────────────────────────────────────────────────────────────
def fetch_magazine(tit_code):
    url = BASE_URL.format(quote(tit_code, safe=""))
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Nom du magazine (ex: "PICSOU MAGAZINE") — span id se termine par "_tit1"
    name_span = soup.find("span", id=lambda x: x and x.endswith("_tit1"))
    mag_name = name_span.get_text(strip=True) if name_span else ""

    # Numéro (ex: "N°593H" → "593") — span id se termine par "_num"
    num_span = soup.find("span", id=lambda x: x and x.endswith("_num"))
    num_text = num_span.get_text(strip=True) if num_span else ""
    num_match = re.search(r"(\d+[A-Z]*)", num_text)
    numero = num_match.group(1) if num_match else None

    full_title = f"{mag_name} N°{numero}" if mag_name and numero else (mag_name or num_text)

    # Dates (jour/mois/année peuvent manquer individuellement)
    def get_date(day_id, month_id, year_id):
        d = soup.find("span", id=lambda x: x and x.endswith(day_id))
        m = soup.find("span", id=lambda x: x and x.endswith(month_id))
        y = soup.find("span", id=lambda x: x and x.endswith(year_id))
        parts = [s.text.strip() for s in (d, m, y) if s and s.text.strip()]
        return "/".join(parts) if parts else None

    date_entree = get_date("spanJe", "spanMe", "spanAe")
    date_sortie = get_date("spanJs", "spanMs", "spanAs")

    # Image de couverture (id="couverture_1" sur la page produit)
    img = soup.find("img", id="couverture_1")
    cover_url = None
    if img and img.get("src"):
        src = img["src"]
        if src.startswith("http"):
            cover_url = src
        else:
            cover_url = "https://catalogueproduits.mlp.fr/" + src.lstrip("/")

    return {
        "numero": numero,
        "full_title": full_title,
        "date_entree": date_entree,
        "date_sortie": date_sortie,
        "cover_url": cover_url,
        "url": url,
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
        "footer": {"text": "Source : catalogueproduits.mlp.fr"},
        "timestamp": datetime.utcnow().isoformat(),
    }
    if info["date_entree"]:
        embed["fields"].append({"name": "📅 En kiosque depuis", "value": info["date_entree"], "inline": True})
    if info["date_sortie"]:
        embed["fields"].append({"name": "🗓️ Jusqu'au", "value": info["date_sortie"], "inline": True})
    if info["cover_url"]:
        embed["thumbnail"] = {"url": info["cover_url"]}

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
            info = fetch_magazine(mag["tit_code"])
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
