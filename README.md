# Scrap-Conventions

App web qui liste les conventions manga et culture japonaise à venir (France + pays limitrophes), avec tri par date ou par distance depuis ta ville.

**Sources des données (scraping automatique, cache 24h) :**
- [lagendageek.com](https://lagendageek.com/liste-des-evenements/) — agenda geek/manga France + voisins
- [rom-game.fr](https://www.rom-game.fr/agenda/) — 200+ événements jeux/manga/culture pop
- [bede.fr](https://www.bede.fr/festivals-manga) — festivals manga spécialisés

Les résultats des 3 sources sont fusionnés et dédoublonnés automatiquement.

---

## Fonctionnalités

- Scraping automatique des conventions à venir (les 3 sources sont scrapées en parallèle)
- Recherche par ville avec autocomplétion (géocodage via l'API Adresse data.gouv.fr, repli sur Nominatim/OpenStreetMap pour l'étranger)
- Filtres par distance (slider) et par date (presets + plage), tri par **date** ou par **distance**
- Rafraîchissement manuel (limité à 1 tous les 10 min, protège les 3 sources scrapées) ou automatique toutes les 24h, sans jamais bloquer une requête
- Page `/sources` avec health-check visible par source (alerte si une source casse)
- Alerte Discord optionnelle quand une nouvelle convention correspond à ta ville/rayon, configurable depuis la page `/settings` (voir ci-dessous)
- UI dark mode, responsive, installable comme PWA sur mobile (icône d'accueil)

---

## Configuration des alertes Discord

Cette app ne nécessite **aucune variable d'environnement**. Les alertes Discord se configurent depuis la page **`/settings`** (non listée dans le menu), et sont stockées dans `cache/config.json`, sur le même volume Docker que le cache — la config survit donc à tous les redéploiements du stack, contrairement à des variables d'environnement Portainer.

1. Va sur `http://<IP-de-ton-HAOS>:5050/settings`
2. Première visite : renseigne l'URL du webhook Discord, ta ville de référence, un rayon en km, et choisis un mot de passe (nécessaire pour revenir modifier ces réglages plus tard)
3. **Enregistrer**

Pour modifier les réglages ensuite : reviens sur `/settings`, entre ton mot de passe pour déverrouiller le formulaire. Un bouton **"Envoyer un test Discord"** est disponible une fois déverrouillé, pour vérifier que le webhook fonctionne sans attendre un scrape.

Le premier scrape après avoir renseigné un webhook ne déclenche **aucune** alerte (bootstrap silencieux) : seules les conventions apparues *après* cette première exécution sont notifiées, pour ne pas spammer avec tout le cache existant.

> Si tu ajoutes une intégration future nécessitant une clé, ne jamais la mettre dans le code ni dans les variables d'environnement Portainer (peu fiables sur les stacks en mode Repository ici) : stocke-la plutôt dans `cache/` via une page de réglages, comme pour Discord.

---

## Déploiement sur HAOS avec Portainer

### Prérequis

- Portainer installé sur HAOS
- Registre GHCR configuré dans Portainer pour puller l'image :
  - **Portainer → Settings → Registries → Add registry → Custom registry**
  - URL : `ghcr.io`
  - Username : `Alizee-M`
  - Password : ton token GitHub avec le scope `read:packages`

### Créer le stack

1. Portainer → **Stacks** → **Add stack**
2. Nom : `scrap-conventions`
3. Build method : **Repository** → URL : `https://github.com/Alizee-M/Scrap-conventions`
4. Reference : `refs/heads/main` — Compose path : `docker-compose.yml`
5. *(Pas de variables d'environnement à configurer — voir section Discord ci-dessus)*
6. **Deploy the stack**

### Accéder à l'app

```
http://<IP-de-ton-HAOS>:5050
```

---

## Développement local

```bash
pip install -r requirements.txt
python app.py
```

L'app tourne sur `http://localhost:5000`.

---

## Structure

```
├── app.py                          # Flask + API REST
├── scraper.py                      # Scraping 3 sources (en parallèle)
├── geocoder.py                     # Géocodage BAN + repli Nominatim, haversine
├── alerts.py                       # Alerte Discord sur nouvelle convention (ville/rayon)
├── settings_store.py               # Config persistée (cache/config.json) : webhook, ville, rayon, mot de passe
├── templates/
│   ├── index.html                  # Interface dark mode
│   ├── sources.html                # Health-check des sources
│   └── settings.html               # Réglages des alertes Discord (page non listée dans le menu)
├── static/                         # Icônes PWA + manifest.json
├── tests/                          # Tests de régression (pytest) sur fixtures HTML réelles
├── .github/workflows/
│   └── docker-publish.yml          # pytest puis build + push image sur GHCR
├── cache/                          # Cache auto-généré (volume Docker)
├── Dockerfile
└── docker-compose.yml
```
