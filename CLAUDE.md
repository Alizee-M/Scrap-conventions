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
