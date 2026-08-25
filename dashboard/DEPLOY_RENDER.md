# Déployer Teranga BI sur Render

## Prérequis

1. Compte [Render](https://render.com)
2. Repo GitHub avec le dossier `dashboard/` (ex. fork `Fatoumata7703/EXAMEN_DATA_DRIVEN`)
3. Variables Supabase (URL + clé, ou `DATABASE_URL`)

## Créer le service Web

1. Render → **New** → **Web Service**
2. Connecter le repo GitHub
3. Réglages :

| Champ | Valeur |
|-------|--------|
| **Root Directory** | `dashboard` |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120` |
| **Instance** | Free (ou Starter) |

4. **Environment** → ajouter :

| Variable | Exemple / note |
|----------|----------------|
| `FLASK_SECRET_KEY` | Chaîne longue aléatoire |
| `ADMIN_USER` | `admin` |
| `ADMIN_PASSWORD` | Mot de passe fort |
| `SUPABASE_URL` | URL projet Supabase |
| `SUPABASE_KEY` | Clé `anon` ou `service_role` |
| `DATABASE_URL` | *(optionnel)* URI Postgres pour contourner RLS |
| `FLASK_DEBUG` | `0` en production |

5. **Create Web Service** → attendre le build.

6. Ouvrir l’URL `https://….onrender.com` → login Teranga BI.

## Notes

- Sur le plan **Free**, le service s’endort après inactivité (~50 s au réveil).
- Le warm-up warehouse peut allonger le **premier** démarrage.
- Ne jamais committer le fichier `.env` (déjà dans `.gitignore`).
- Si le build échoue sur `psycopg2`, garder `psycopg2-binary` (déjà dans `requirements.txt`).

## Mise à jour

```bash
git push origin feat/teranga-bi-dashboard
```

Render redéploie automatiquement si *Auto-Deploy* est activé sur la branche choisie.
