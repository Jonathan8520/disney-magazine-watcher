# 🦆 Disney Magazine Watcher

Surveille les nouvelles sorties des magazines Disney/Picsou sur MLP et envoie une notification Discord à chaque nouveau numéro.

## Magazines surveillés

| Magazine | Fréquence |
|---|---|
| 💰 Picsou Magazine | Bimestriel |
| 🦆 Super Picsou Géant | Bimestriel |
| 🐭 Journal de Mickey | Hebdomadaire |
| ⭐ Journal de Mickey HS | Irrégulier |
| 🦸 Fantomiald | Bimestriel |
| 💎 Les Trésors de Picsou | Trimestriel |
| 🌟 Mon 1er Journal de Mickey | Irrégulier |

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
- Il scrape `catalogueproduits.mlp.fr` pour chaque magazine
- Il compare le numéro actuel avec le dernier connu (stocké dans `state.json`)
- Si nouveau numéro → notification Discord avec titre, dates et couverture
- Le `state.json` est automatiquement mis à jour et commité dans le repo

## Ajouter un magazine

Dans `check_magazines.py`, ajoute une entrée dans `MAGAZINES` :
```python
{"name": "Nom du magazine", "tit_code": "XXXXX=", "emoji": "📰", "color": 0xFF0000},
```

Pour trouver le `tit_code` d'un magazine, cherche-le sur `catalogueproduits.mlp.fr` et copie la valeur du paramètre `tit_code` dans l'URL de la page produit.
