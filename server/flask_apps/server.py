import threading
from flask import Flask, request, Response, render_template, send_from_directory, abort
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from jinja2.exceptions import TemplateNotFound
import os
from datetime import datetime
from tinydb import Query

# Importiere die API-App und Items aus der api.py
from .api import api, items

# Konfigurations- und Hilfsfunktionen importieren
from server.utils.config_reader import languages, config, introConfig
from server.utils.path import get_path

# Hauptanwendung
app = Flask(__name__, template_folder=get_path("/server/frontend"))

# Allgemeine API-Anwendung
general_api = Flask(__name__)

# Middleware für die Firewall
@api.before_request
@app.before_request
@general_api.before_request
def firewall():
    if config.firewall.active and request.remote_addr not in config.firewall.allowed_ips:
        return "You have no access to this application.", 401

# Fehlerhandler für 404
@app.errorhandler(404)
def app_fallback(error):
    return Response("Not found"), 404

# Route für statische Dateien im 'storages'-Ordner
@app.route('/storages/<path:filename>')
def serve_storages(filename):
    storages_path = get_path("/storages")
    return send_from_directory(storages_path, filename)

# Statische Dateien und Templates
@app.route('/', defaults={'req_path': 'index.html'})
@app.route('/<path:req_path>')
def app_serve(req_path: str):
    lang = request.cookies.get("lang", config.userinterface_defaults.language).upper()
    theme = request.cookies.get("theme", config.userinterface_defaults.theme).lower()
    firstrun = request.cookies.get("first", "True")

    if lang not in languages.keys():
        lang = config.userinterface_defaults.language.upper()
    if theme + ".css" not in os.listdir(get_path("/server/frontend/css/themes")):
        theme = config.userinterface_defaults.theme

    try:
        if req_path.endswith(".html"):
            return render_template(req_path, **{
                "lang": languages[lang],
                "langs": languages.keys(),
                "active_language": lang,
                "themes": [x.replace(".css", "") for x in os.listdir(get_path("/server/frontend/css/themes"))],
                "active_theme": theme,
                "firstrun": firstrun,
                "feedback_url": config.application.feedback_url,
                "welcome_message": config.welcome_message,
                "contact": config.contact,
                "items": items,
                "query": Query(),
                "active": os.path.split(req_path)[1]
            })
        else:
            return send_from_directory(get_path("/server/frontend"), req_path)
    except (TemplateNotFound, FileNotFoundError):
        return abort(404)

# Sales-Seite
@app.route("/sales")
def sales_page():
    today = datetime.now().date()
    daily_sales = [
        sale for sale in items.all()
        if datetime.fromisoformat(sale["timestamp"]).date() == today
    ]
    total_items = sum(sale["amount"] for sale in daily_sales)
    total_revenue = sum(sale["price"] for sale in daily_sales)

    return render_template(
        "daily_sales.html",
        date=today.isoformat(),
        total_items=total_items,
        total_revenue=total_revenue,
        sales=daily_sales
    )

# API für Intro-Konfiguration
@general_api.route("/intro")
def generate_intro_config():
    lang = request.cookies.get("lang", config.userinterface_defaults.language).upper()
    if lang not in languages.keys():
        lang = config.userinterface_defaults.language.upper()
    lang = languages[lang]

    final_config = {"options": introConfig["options"], "tours": {}}
    for pagek, pagev in introConfig["tours"].items():
        final_config["tours"][pagek] = {"steps": []}
        for stepk, stepv in pagev["steps"].items():
            final_config["tours"][pagek]["steps"].append({**stepv, **lang["tours"][pagek]["steps"][stepk]})
        if "next_page" in pagev:
            final_config["tours"][pagek]["next_page"] = pagev["next_page"]
    return final_config

# Dispatcher für die kombinierte App
application = DispatcherMiddleware(app, {
    '/api/shop': api,
    '/api': general_api
})

# Funktion, um die API separat zu starten
def start_api():
    api.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False)

# Hauptstarter
if __name__ == "__main__":
    # Starte die API in einem separaten Thread
    threading.Thread(target=start_api, daemon=True).start()

    # Starte die Hauptanwendung
    app.run(host='127.0.0.1', port=5000, debug=True)
