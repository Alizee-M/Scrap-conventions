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

## Déploiement sur HAOS avec Portainer

### 1. Copier les fichiers sur HAOS

Via le add-on **SSH & Web Terminal** de Home Assistant :

```bash
mkdir -p /share/scrap-conventions
```

Puis copier le contenu du repo dans `/share/scrap-conventions/` (via SAMBA, SCP, ou le File Editor).

### 2. Créer le stack dans Portainer

1. Ouvre Portainer → **Stacks** → **Add stack**
2. Donne-lui le nom `scrap-conventions`
3. Méthode : **Upload** → sélectionne `docker-compose.yml`
4. **Ou** colle directement ce contenu dans l'éditeur :

```yaml
services:
  scrap-conventions:
    build: /share/scrap-conventions
    container_name: scrap-conventions
    restart: unless-stopped
    ports:
      - "5050:5000"
    volumes:
      - /share/scrap-conventions/cache:/app/cache
```

5. Clique **Deploy the stack**

### 3. Accéder à l'app

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
├── app.py           # Flask + API REST
├── scraper.py       # Scraping lagendageek.com
├── geocoder.py      # Géocodage Nominatim + calcul haversine
├── templates/
│   └── index.html   # Interface
├── cache/           # Cache scraping + géocodage (auto-généré)
├── Dockerfile
└── docker-compose.yml
```
