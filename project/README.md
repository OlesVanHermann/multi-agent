# Webapp de détection de médias falsifiés

Application locale en français pour analyser un texte ou envoyer une image, un fichier audio ou une vidéo à l'API UncovAI. Le navigateur appelle uniquement le backend FastAPI local. La clé fournisseur reste dans l'environnement du serveur et n'est ni renvoyée, ni journalisée, ni incluse dans les fichiers frontend.

La colonne gauche est divisée en deux : saisie de texte en haut et dépôt de fichier en bas. Le texte doit contenir entre 200 et 4 000 caractères et son analyse démarre avec le bouton dédié. À chaque nouvelle sélection de fichier, l'ancien aperçu et son résultat sont retirés, puis le nouveau média est affiché immédiatement. L'analyse du média démarre automatiquement après validation du fichier et, pour l'audio, de sa durée. La zone de dépôt reste verrouillée jusqu'à la réponse ou l'erreur. Le résultat distingue clairement un contenu probablement authentique, probablement falsifié ou indéterminé et rappelle qu'il s'agit d'une estimation, pas d'une preuve définitive.

## Prérequis et installation

- Python 3.11 ou plus récent
- Node.js 18 ou plus récent, uniquement pour les tests frontend sans dépendance
- FFmpeg et `libheif-examples` pour les conversions WAV et HEIC/HEIF

```bash
cd /home/ubuntu/multi-agent/project
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
sudo apt-get install ffmpeg libheif-examples
cp .env.example .env
```

Renseigner `UNCOVAI_API_KEY` dans `.env`, puis charger explicitement ce fichier dans l'environnement d'exécution. `.env` est ignoré par Git et n'est pas chargé automatiquement :

```bash
set -a
. ./.env
set +a
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Avec le fichier d'exemple fourni, ouvrir ensuite `http://127.0.0.1:8000/uncovai/`. Ne jamais exposer directement ce serveur de développement à Internet. Pour servir l'application à la racine en local, laisser `UNCOVAI_PUBLIC_PATH` vide.

Variables facultatives :

- `UNCOVAI_TIMEOUT_SECONDS` : délai fournisseur, 60 secondes par défaut ;
- `UNCOVAI_PUBLIC_PATH` : préfixe public, configuré à `/uncovai` dans l'exemple ;
- `UNCOVAI_BASE_URL` : URL fournisseur, utile uniquement pour un environnement de test contrôlé.

## Déploiement sous `/uncovai`

Le serveur sait monter toutes ses routes sous le préfixe public. Un reverse proxy doit conserver ce préfixe lorsqu'il transmet la requête :

```nginx
location /uncovai/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Le déploiement de production utilise `https://multi-test.di2amp.com/uncovai/`, avec certificat Let's Encrypt et renouvellement automatique Certbot. La configuration nginx de référence inclut la redirection HTTP vers HTTPS.

Les fichiers de déploiement de référence se trouvent dans `deploy/`. Le service systemd charge la clé avec `LoadCredentialEncrypted`; le secret n'est donc pas stocké en clair dans le dépôt ou dans l'unité systemd.

## Observabilité

Chaque requête reçoit un `X-Request-ID`, généré par nginx puis propagé au backend. Les journaux couvrent les étapes navigateur, nginx, backend et fournisseur. `api_request_duration_ms` mesure uniquement l'appel du backend vers l'API fournisseur : le chronomètre démarre après réception et validation complètes du média, donc sans le temps d'upload navigateur. `http_request_duration_ms` reste disponible séparément pour le diagnostic HTTP global. Les événements frontend sont limités à une liste de champs assainis; les noms de fichiers, contenus médias, corps fournisseur et secrets ne sont jamais journalisés.

```bash
# Backend, validation, appels fournisseur et événements frontend
sudo journalctl -u fake-media-api.service -f

# Chaîne nginx au format JSON et erreurs de proxy
sudo tail -f /var/log/nginx/uncovai_access.log
sudo tail -f /var/log/nginx/uncovai_error.log
```

Rechercher un même `request_id` dans le journal nginx et le journal systemd permet de suivre une requête sur toute la chaîne.

## Formats et limites

L'interface accepte les formats utilisés par cette mission :

- texte de 200 à 4 000 caractères ;
- images JPEG, PNG, WebP et GIF envoyées directement ;
- images HEIC/HEIF converties localement en JPEG ;
- audio MP3 envoyé directement ;
- audio WAV converti localement en MP3 à 128 kbit/s ;
- MP3/WAV source jusqu'à 80 Mo, réduit à 9 Mo maximum au-delà de 10 Mo, uniquement si sa durée ne dépasse pas 6 minutes ;
- vidéo MP4, AVI, MOV, MKV, WMV, FLV ou WebM ;
- vidéo source jusqu'à 200 Mo, convertie en MP4 de 90 Mo maximum au-delà de 100 Mo ;
- 6 minutes maximum pour l'audio et la vidéo après réduction.

L'extension, le MIME, la taille, le nom, la signature binaire et la durée MP3 sont contrôlés côté serveur. Un MP3 de plus de 6 minutes est refusé, y compris lorsqu'il dépasse 10 Mo : il n'est jamais tronqué pour contourner la limite fournisseur. WAV est converti en mémoire. HEIC/HEIF utilise le répertoire temporaire privé du service; son contenu est supprimé à la fin de chaque conversion, succès ou échec. Les métadonnées ne sont pas demandées lors de la conversion.

## Tests

```bash
python3 -m pytest tests/ -v
npm run test:frontend
```

Les appels fournisseur sont simulés dans la suite automatisée. Aucun appel facturable n'est lancé. Le contrat détaillé et le mapping des verdicts figurent dans [docs/API_CONTRACT.md](docs/API_CONTRACT.md).

Un test réel n'est à lancer que si `UNCOVAI_API_KEY` contient déjà une clé valide et si l'appel potentiellement facturable a été autorisé. Sans ce secret, l'application et tous ses parcours simulés restent vérifiables; seul l'appel réel au fournisseur est bloqué.
