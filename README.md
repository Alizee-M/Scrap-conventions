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
- Alerte Discord optionnelle quand une nouvelle convention correspond à ta ville/rayon (voir variables d'environnement ci-dessous)
- UI dark mode, responsive, installable comme PWA sur mobile (icône d'accueil)

---

## Variables d'environnement

Le géocodage (API Adresse data.gouv.fr + Nominatim) ne nécessite aucune clé.

Les alertes Discord sont **optionnelles** — sans `DISCORD_WEBHOOK_URL`, la fonctionnalité est simplement désactivée :

| Variable | Requis | Description |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | non | URL du webhook Discord. Si absente, aucune alerte n'est envoyée. |
| `ALERT_CITY` | non | Ville de référence pour le filtre de distance (ex. `Tours`). Sans elle, toute nouvelle convention alerte. |
| `ALERT_RADIUS_KM` | non | Rayon en km autour de `ALERT_CITY` (défaut : `50`). |
| `ALERT_TEST_PASSWORD` | non | Mot de passe pour tester l'envoi Discord sans attendre un scrape (voir ci-dessous). Sans elle, la route de test est indisponible. |

Le premier scrape après activation de `DISCORD_WEBHOOK_URL` ne déclenche **aucune** alerte (bootstrap silencieux) : seules les conventions apparues *après* cette première exécution sont notifiées, pour ne pas spammer avec tout le cache existant.

### Tester le webhook Discord sans attendre un scrape

Une fois `DISCORD_WEBHOOK_URL` et `ALERT_TEST_PASSWORD` configurés (et le stack redéployé), envoie un message de test :

```bash
curl -X POST -H "X-Test-Password: <ton mot de passe>" http://<IP-de-ton-HAOS>:5050/api/test-alert
```

Réponse `{"ok": true}` + message reçu sur Discord → le webhook fonctionne. Sans `ALERT_TEST_PASSWORD` configuré, ou avec un mauvais mot de passe, la route répond 404 (elle ne révèle pas son existence).

> Si tu ajoutes une intégration future nécessitant une clé, ne jamais la mettre dans le code :  
> configure-la comme variable d'environnement dans Portainer (voir section déploiement).

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
5. *(Pas de variables d'environnement à configurer pour ce projet)*
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
├── templates/
│   ├── index.html                  # Interface dark mode
│   └── sources.html                # Health-check des sources
├── static/                         # Icônes PWA + manifest.json
├── tests/                          # Tests de régression (pytest) sur fixtures HTML réelles
├── .github/workflows/
│   └── docker-publish.yml          # pytest puis build + push image sur GHCR
├── cache/                          # Cache auto-généré (volume Docker)
├── Dockerfile
└── docker-compose.yml
```
