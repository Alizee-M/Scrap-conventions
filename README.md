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
- Recherche par ville avec autocomplétion (géocodage via l'API Adresse data.gouv.fr, repli sur Nominatim/OpenStreetMap pour l'étranger), ou géolocalisation directe via le bouton **"📍 Près de moi"**
- Filtres par distance (slider) et par date (presets + plage), tri par **date** ou par **distance**
- Rafraîchissement manuel (limité à 1 tous les 10 min, protège les 3 sources scrapées) ou automatique toutes les 24h, sans jamais bloquer une requête
- Page `/sources` avec health-check visible par source
- Alertes Discord optionnelles (configurables depuis `/settings`) : nouvelle convention correspondant à ta ville/rayon, et source qui casse ou se rétablit
- UI dark mode, responsive, installable comme PWA sur mobile (icône d'accueil)

---

## Configuration des alertes Discord

Cette app ne nécessite **aucune variable d'environnement**. Les alertes Discord se configurent depuis la page **`/settings`** (non listée dans le menu), et sont stockées dans `cache/config.json`, sur le même volume Docker que le cache — la config survit donc à tous les redéploiements du stack, contrairement à des variables d'environnement Portainer.

1. Va sur `http://<IP-de-ton-HAOS>:5050/settings`
2. Première visite : renseigne l'URL du webhook Discord, ta ville de référence, un rayon en km, et choisis un mot de passe (nécessaire pour revenir modifier ces réglages plus tard)
3. **Enregistrer**

Pour modifier les réglages ensuite : reviens sur `/settings`, entre ton mot de passe pour déverrouiller le formulaire. Un bouton **"Envoyer un test Discord"** est disponible une fois déverrouillé, pour vérifier que le webhook fonctionne sans attendre un scrape.

### Alerte quand une source casse

Dès qu'un webhook Discord est configuré, une alerte est aussi envoyée quand une des 3 sources scrapées (lagendageek, rom-game, bede) tombe à 0 événement ou renvoie une erreur — plus besoin d'aller vérifier `/sources` toi-même. Un seul message est envoyé au moment où la source casse (pas un par jour tant qu'elle reste cassée), et un message "rétablie" est envoyé quand elle refonctionne.

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

En HTTPS, une fois Caddy configuré (voir section suivante) :

```
https://<ton-nom>.duckdns.org:8443
```

---

## Activer le HTTPS (Caddy + DuckDNS)

Le stack inclut un service `caddy` qui obtient et renouvelle automatiquement
un certificat Let's Encrypt via un **challenge DNS** (module `caddy-dns/duckdns`),
donc sans avoir besoin des ports 80/443 (souvent déjà pris par autre chose sur
un HAOS). Seul le port `8443` doit être accessible pour servir le trafic HTTPS.

### Prérequis

- Un nom DuckDNS existant (ex: `maisonlilinono.duckdns.org`), déjà maintenu à
  jour vers l'IP publique de la maison (souvent déjà géré par un add-on HAOS
  pour Home Assistant — vérifie que ce nom pointe bien vers chez toi).
- Le port `8443` forwardé sur ta box vers l'IP locale du HAOS.

### Configuration (une seule fois)

Le vrai `Caddyfile` (avec ton token DuckDNS en clair) **ne doit jamais** être
commité dans ce repo ni passé en variable d'environnement Portainer — même
règle que pour le webhook Discord (voir plus haut et `CLAUDE.md`). Il vit
uniquement dans le volume Docker `scrap-conventions-caddy-config`, qui
survit aux redéploiements.

1. Récupère ton token sur [duckdns.org](https://www.duckdns.org) (visible sur
   ta page de compte, à côté de tes domaines)
2. Portainer → **Volumes** → `scrap-conventions-caddy-config` → **Browse** →
   crée un fichier nommé `Caddyfile` avec ce contenu (adapte le domaine et le
   token) — voir aussi `Caddyfile.example` dans ce repo :

   ```
   maisonlilinono.duckdns.org:8443 {
       tls {
           dns duckdns <TON_TOKEN_DUCKDNS>
       }
       reverse_proxy scrap-conventions:5000
   }
   ```

3. Redémarre le conteneur `scrap-conventions-caddy` (Portainer → Containers →
   Restart)
4. Accède à `https://maisonlilinono.duckdns.org:8443` — le premier chargement
   peut prendre quelques secondes le temps que Caddy obtienne le certificat

Si tu changes de nom DuckDNS ou de token plus tard : édite ce même fichier
puis redémarre le conteneur `scrap-conventions-caddy`.

### Revenir à une version précédente (rollback)

Chaque build CI publie l'image sous deux tags : `latest` (toujours la dernière version) et `sha-<commit complet>` (une version figée par commit, conservée sur GHCR). Si un déploiement casse quelque chose :

1. Trouve le commit à restaurer (`git log` sur le repo, ou l'historique des runs dans l'onglet **Actions** sur GitHub)
2. Portainer → stack `scrap-conventions` → **Editor**
3. Remplace temporairement `image: ghcr.io/alizee-m/scrap-conventions:latest` par `image: ghcr.io/alizee-m/scrap-conventions:sha-<le SHA complet>`
4. **Update the stack** (coche "Re-pull image")
5. Une fois le correctif poussé sur `main` et vérifié, repasse l'image sur `:latest` pour reprendre les mises à jour automatiques

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
