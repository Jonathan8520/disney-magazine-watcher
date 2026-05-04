# 🦆 Disney Magazine Watcher

Surveille les nouvelles sorties des magazines Disney/Picsou sur `direct-editeurs.fr` et envoie une notification Discord à chaque nouveau numéro.

## Magazines surveillés

| Magazine | Fréquence |
|---|---|
| 💰 Picsou Magazine | Bimestriel |
| 🦆 Super Picsou Géant | Bimestriel |
| 🐭 Journal de Mickey | Hebdomadaire |
| ⭐ Journal de Mickey HS | Irrégulier |
| 🦸 Les Chroniques de Fantomiald | Bimestriel |
| 💎 Les Trésors de Picsou | Trimestriel |
| 🧒 Mickey Junior | Mensuel |
| 🏆 Le Meilleur du Journal de Mickey | Trimestriel |
| 📘 Picsou HS Collection Deluxe | Irrégulier |
| 🦫 Picsou HS Castors Juniors | Irrégulier |
| ⛏️ Picsou HS Souvenirs du Klondike | Irrégulier |
| 🎂 Picsou Anniversaire en or | Irrégulier |

## Setup (5 minutes)

### 1. Fork / Clone ce repo sur GitHub

### 2. Créer un webhook Discord
1. Dans ton serveur Discord → **Paramètres du salon** → **Intégrations** → **Webhooks**
2. Clique **Nouveau Webhook**, donne-lui un nom (ex: "Magazine Watcher 🦆")
3. Copie l'URL du webhook

### 3. Ajouter le secret GitHub
1. Dans ton repo GitHub → **Settings** → **Secrets and variables** → **Actions**
2. Clique **New repository secret**
3. Nom : `DISCORD_WEBHOOK`
4. Valeur : l'URL copiée à l'étape précédente

### 4. Activer GitHub Actions
1. Va dans l'onglet **Actions** de ton repo
2. Si désactivé, clique **I understand my workflows, go ahead and enable them**

### 5. Test manuel
Dans l'onglet **Actions** → **Disney Magazine Watcher** → **Run workflow**

## Comment ça marche

- Le script tourne **toutes les 12h** (8h et 20h heure de Paris)
- Il interroge `direct-editeurs.fr` (qui agrège MLP + France Messagerie) pour chaque magazine
- Il compare le numéro actuel avec le dernier connu (stocké dans `state.json` sur la branche `datas`)
- Si nouveau numéro → notification Discord avec titre, date de parution et couverture
- Le `state.json` est automatiquement mis à jour et commité sur la branche `datas` (le code reste propre sur `main`)

## Ajouter un magazine

Dans `check_magazines.py`, ajoute une entrée dans `MAGAZINES` :
```python
{"name": "Nom du magazine", "codif": "12345", "emoji": "📰", "color": 0xFF0000},
```

Pour trouver le `codif` d'un magazine, cherche-le sur `direct-editeurs.fr/nos-magazines` : c'est l'identifiant numérique visible dans l'URL du magazine et dans le bloc "Codif :" de sa page.
