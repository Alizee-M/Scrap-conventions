# Scrap-Conventions

App web qui liste les conventions manga et culture japonaise à venir (France + pays limitrophes), avec tri par date ou par distance depuis ta ville.

**Sources des données (scraping automatique, cache 24h) :**
- [lagendageek.com](https://lagendageek.com/liste-des-evenements/) — agenda geek/manga France + voisins
- [rom-game.fr](https://www.rom-game.fr/agenda/) — 200+ événements jeux/manga/culture pop
- [bede.fr](https://www.bede.fr/festivals-manga) — festivals manga spécialisés

Les résultats des 3 sources sont fusionnés et dédoublonnés automatiquement.

---

## Fonctionnalités

- Scraping automatique des conventions à venir
- Recherche par ville (géocodage via Nominatim/OpenStreetMap)
- Tri par **date** ou par **distance**
- Rafraîchissement manuel ou automatique toutes les 24h
- UI dark mode, responsive

---

## Variables d'environnement

Cette app ne nécessite **aucune variable d'environnement** — pas d'API key, pas de token.  
Elle utilise uniquement Nominatim (OpenStreetMap, gratuit et sans clé) pour le géocodage.

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
├── scraper.py                      # Scraping 3 sources
├── geocoder.py                     # Géocodage Nominatim + haversine
├── templates/
│   └── index.html                  # Interface dark mode
├── .github/workflows/
│   └── docker-publish.yml          # Build + push image sur GHCR
├── cache/                          # Cache auto-généré (volume Docker)
├── Dockerfile
└── docker-compose.yml
```
