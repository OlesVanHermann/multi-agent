# Erreurs Codex et Claude Code

Le dashboard passe un agent en **rouge** dès qu'une erreur bloquante explicite
est visible dans son pane tmux. Les motifs sont propres au moteur et résident
uniquement dans :

- `scripts/agent-bridge/markers.codex.yaml` ;
- `scripts/agent-bridge/markers.claude.yaml`.

Le texte ordinaire d'une conversation ne doit pas suffire. Côté Codex, les
motifs sont ancrés sur la carte d'erreur `■`. Côté Claude Code, ils utilisent
un code `API Error:` ou un identifiant d'erreur explicite. Le marqueur Claude
générique `API Error:` conserve un seuil de trois occurrences afin d'éviter un
rouge sur une erreur isolée déjà récupérée.

## Familles rendues rouges

| Famille | Codex | Claude Code | Interprétation |
|---|---|---|---|
| Requête invalide | carte `■` avec 400/404 ou `invalid_request_error` | 400/404, `invalid_request_error`, `not_found_error` | requête, ressource ou modèle inutilisable |
| Authentification | 401, `authentication_error`, `ip_not_authorized` | 401, `authentication_error`, `organization disabled` | session, compte ou jeton à corriger |
| Autorisation | 403, `permission_error` | 403, `permission_error`, `model not available` | compte sans droit sur le workspace ou le modèle |
| Taille | 413 | 413, `request_too_large` | entrée trop volumineuse |
| Quota et débit | 429, `rate_limit_error`, usage limit | 429, `rate_limit_error`, `5-hour limit reached` | attendre le reset ou changer de capacité |
| Fournisseur | 500–599, `Service Unavailable`, circuit ouvert | 500, 529, `api_error`, `overloaded_error` | incident temporaire du fournisseur |
| Transport | carte `■` avec network/WebSocket/timeout | erreurs API répétées ou disparition anormale du statut | réseau, proxy, TLS ou transport interrompu |

## Sources officielles

OpenAI documente les erreurs HTTP, les pics de 5xx, les timeouts et les
problèmes réseau dans son
[guide de diagnostic des erreurs et de la latence](https://help.openai.com/en/articles/1000499).
Le statut 429 et le backoff sont décrits dans
[la documentation rate limit](https://help.openai.com/en/articles/5955604-how-can-i-solve-429-too-many-requests-errors).
Les problèmes de connexion et de workspace sont couverts par
[le guide d'authentification](https://help.openai.com/en/articles/10489721-authentication-troubleshooting-faq).

Anthropic décrit les codes 400, 401, 403, 404, 413, 429, 500 et 529 dans
[la référence des erreurs API](https://docs.anthropic.com/en/api/errors).
Les erreurs Claude Code d'installation, TLS, authentification et accès modèle
sont recensées dans
[le guide de dépannage Claude Code](https://support.claude.com/en/articles/14552646-troubleshoot-claude-code-installation-and-authentication).
Les limites de forfait et de contexte sont expliquées dans
[le guide des limites Claude Code](https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code).

## Effet dans le framework

Une correspondance positionne `api_error=true` dans l'état du pane. Le cache
web journalise la transition et le dashboard affiche l'agent en rouge. Le
bridge peut retenter une erreur transitoire avec son backoff borné, mais la
couleur reste rouge tant que l'erreur est encore visible.

Une erreur non transitoire — authentification, permission, modèle indisponible
ou limite de forfait — exige une intervention opérateur. Ne pas relancer en
boucle et ne jamais basculer silencieusement vers une clé API.
