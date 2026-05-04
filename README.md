# 🦆 Disney Magazine Watcher

Surveille les nouvelles sorties des magazines Disney/Picsou sur `direct-editeurs.fr` et envoie une notification Discord à chaque nouveau numéro.

## Magazines surveillés

Le watcher **découvre automatiquement** tous les magazines Disney en interrogeant à la fois `direct-editeurs.fr` (riche et structuré) et `catalogueproduits.mlp.fr` (qui rattrape les titres absents de DE comme Picsou Soir, Destin de Picsou, Nouvelle Jeunesse de Picsou…) avec les mots-clés `picsou`, `mickey`, `mickey parade`, `fantomiald`, `donald`. Les pochettes promo et les magazines retirés du catalogue ("trop vieux") sont automatiquement écartés. Aucune liste à maintenir : un nouveau hors-série Disney apparaît dans le catalogue → il sera notifié au run suivant.

Magazines principaux (avec emoji/couleur dédiés via `OVERRIDES` dans `check_magazines.py`) :

| Magazine |
|---|
| 💰 Picsou Magazine |
| 🦆 Super Picsou Géant |
| 🐭 Journal de Mickey |
| ⭐ Journal de Mickey HS |
| 🦸 Les Chroniques de Fantomiald |
| 💎 Les Trésors de Picsou |
| 🧒 Mickey Junior |
| 🏆 Le Meilleur du Journal de Mickey |

Tous les autres magazines / HS découverts sont notifiés avec un emoji 🦆 par défaut.

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
- Il interroge `direct-editeurs.fr` puis complète avec `catalogueproduits.mlp.fr` pour découvrir tous les magazines Disney actifs (DE n'étant pas exhaustif)
- Il compare le numéro actuel avec le dernier connu (stocké dans `state.json` sur la branche `datas`)
- Pour chaque nouveau numéro détecté, il interroge MLP pour récupérer la date de relève prévisionnelle (« Jusqu'au »)
- Notification Discord avec titre, numéro, prix, date de parution, date de relève et couverture en grand
- Le `state.json` est automatiquement mis à jour et commité sur la branche `datas` (le code reste propre sur `main`)
- Throttle 1s + retry automatique sur 429 pour respecter la limite Discord (~5 webhooks/s)

## Personnaliser un magazine

Pour donner un emoji et une couleur dédiés à un magazine découvert automatiquement, ajoute son codif à `OVERRIDES` dans `check_magazines.py` :

```python
OVERRIDES = {
    "12345": {"name": "Nom affiché", "emoji": "📰", "color": 0xFF0000},
    ...
}
```

Le codif est l'identifiant numérique visible dans l'URL et le bloc "Codif :" sur `direct-editeurs.fr`.

## Élargir la couverture

Pour suivre d'autres familles de magazines, modifie `KEYWORDS` dans `check_magazines.py` (par défaut : `picsou`, `mickey`, `mickey parade`, `fantomiald`, `donald`).
