# Scrap-Conventions — notes pour agents

## Ne pas utiliser les variables d'environnement Portainer pour de la config persistante

Sur le HAOS d'Alizee, le stack Portainer de cette app (mode "Repository") perd les
valeurs de sa section "Environment variables" après certains redéploiements —
même en éditant la liste clé/valeur dédiée de l'UI, pas le texte du compose file.
Cause exacte non identifiée côté Portainer, mais reproductible.

**En conséquence** : `docker-compose.yml` ne déclare volontairement aucune
variable d'environnement. Toute config qui doit persister (webhook Discord,
ville, rayon, mot de passe) passe par `settings_store.py`, stockée dans
`cache/config.json` sur le volume Docker `scrap-conventions-cache` — ce volume
survit à tous les redéploiements, contrairement aux env vars Portainer.

Si un futur besoin de config apparaît (nouvelle clé d'API, nouveau réglage) :
suivre le même pattern (fichier dans `cache/` + page de réglages protégée par
mot de passe comme `/settings`), ne pas réintroduire de variable d'environnement
pour quoi que ce soit qui doit tenir dans la durée.

## Autres repères rapides

- Déploiement : Portainer sur HAOS, port `5050` (voir README pour les étapes).
- Tests : `pytest` (voir `requirements-dev.txt`), CI bloque le build/push GHCR si les tests échouent.
- Mot de passe de `/settings` : haché via `werkzeug.security`, jamais stocké en clair.
- `alerts.py` gère deux types d'alerte Discord distincts, chacun avec son propre fichier d'état dans `cache/` pour éviter le spam à chaque scrape :
  - `check_and_notify` (conventions proches) → `cache/alerted_events.json`
  - `check_source_health` (source cassée/rétablie) → `cache/source_alert_state.json`
- La CI publie chaque image sous deux tags : `latest` et `sha-<commit complet>`. Le second permet un rollback (voir README) sans dépendre de l'historique GHCR de `latest` qui s'écrase à chaque push. Ne pas retirer ce second tag sans proposer une autre méthode de rollback à la place.
- HTTPS : un service `caddy` (voir `docker-compose.yml`, `Dockerfile.caddy`) sert l'app en HTTPS sur le port `8443`, certificat Let's Encrypt via challenge DNS (module `caddy-dns/duckdns`) — choisi précisément parce que les ports 80/443 ne sont pas fiables/libres sur ce HAOS. Le `Caddyfile` réel (avec le token DuckDNS) vit uniquement dans le volume Docker `scrap-conventions-caddy-config`, jamais dans ce repo ni en variable d'environnement Portainer — même règle que pour le webhook Discord ci-dessus. `Caddyfile.example` documente le format attendu sans secret. Voir README pour la procédure de configuration.
