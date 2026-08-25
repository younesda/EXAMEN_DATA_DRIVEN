import os
from pathlib import Path
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from data_service import build_export_lignes, ensure_warehouse, get_payload, supabase_configured
from ml_live import fetch_models_live

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "teranga-bi-secret")

USER = os.getenv("ADMIN_USER", "admin")
PASSWORD = os.getenv("ADMIN_PASSWORD", "teranga2026")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("username") == USER and request.form.get("password") == PASSWORD:
            session["user"] = USER
            # Précharge le warehouse pendant la connexion
            try:
                ensure_warehouse()
                get_payload({})
                opts = get_payload({}).get("filter_options") or {}
                for y in (opts.get("annees") or [])[:4]:
                    get_payload({"annee": str(y)})
            except Exception:  # noqa: BLE001
                pass
            return redirect(url_for("home"))
        error = "Identifiants incorrects"
    if session.get("user"):
        return redirect(url_for("home"))
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    return render_template("app.html", user=session["user"])


@app.route("/api/dashboard")
@login_required
def api_dashboard():
    payload = get_payload(filters=dict(request.args))
    return jsonify(_pack(payload))


@app.route("/api/refresh")
@login_required
def api_refresh():
    return jsonify(_pack(get_payload(filters=dict(request.args), force=True)))


@app.route("/api/export/lignes")
@login_required
def api_export_lignes():
    rows, total = build_export_lignes(dict(request.args))
    return jsonify({"lignes": rows, "total": total, "truncated": total > len(rows)})


@app.route("/api/models")
@login_required
def api_models():
    force = request.args.get("force") in ("1", "true", "yes")
    payload = fetch_models_live(force=force)
    # Rafraîchir le cache disque pour affichage instantané au prochain chargement
    if payload.get("ok"):
        try:
            import json
            from pathlib import Path

            cache_path = Path(__file__).resolve().parent / "static" / "data" / "models_cache.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    return jsonify(payload)


def _pack(payload):
    payload = dict(payload)
    payload["live"] = payload.get("source") == "supabase"
    payload["configured"] = supabase_configured()
    return payload


if __name__ == "__main__":
    # Warm-up au démarrage pour connexion + filtres année immédiats
    try:
        ensure_warehouse()
        get_payload({})
        opts = get_payload({}).get("filter_options") or {}
        for y in (opts.get("annees") or [])[:4]:
            get_payload({"annee": str(y)})
        print("Warm-up OK — années en cache:", opts.get("annees"))
        # Précharge aussi les modèles (évite écran vide au 1er clic)
        try:
            from ml_live import fetch_models_live
            m = fetch_models_live(force=True)
            print("Warm-up modèles OK — forecast", len((m.get("tables") or {}).get("forecast") or []))
        except Exception as mex:  # noqa: BLE001
            print("Warm-up modèles:", mex)
    except Exception as exc:  # noqa: BLE001
        print("Warm-up:", exc)
    port = int(os.getenv("PORT", "5055"))
    app.run(debug=os.getenv("FLASK_DEBUG", "1") == "1", host="0.0.0.0", port=port, use_reloader=False)
