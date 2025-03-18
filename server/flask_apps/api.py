import os
import re
import datetime
import shutil

from typing import List
from flask import Flask, request, jsonify, Response
from tinydb import TinyDB, Query
from tinydb.queries import Query
from tinydb import where
from datetime import datetime, timezone

from tinydb import TinyDB, Query
from datetime import datetime
import hashlib

from server.utils.backup import backup
from server.utils.config_reader import config
from server.utils.path import get_path


# backup database before reading it
backup()

# create item DB
items = TinyDB(get_path("storages/items.db"))

# create sales log DB
sales_db = TinyDB('storages/sales_log.json')

# create users DB
users_db = TinyDB(get_path("storages/users.db"))
sessions_db = TinyDB(get_path("storages/sessions.db"))

# patterns
item_name_pattern = r"[\s\S]+"
item_amount_pattern = r"^[0-9]+$"
item_cost_pattern = r"^[0-9]+[,|.]?[0-9]*$"
user_code_pattern = r"^[A-Za-z0-9]{6,}$"
username_pattern = r"^[A-Za-z0-9\s]{3,}$"
item_purchase_price_pattern = r"^[0-9]+[,|.]?[0-9]*$"

# Utils
def has_item(item_name: str) -> bool:
    """check items DB for an item with item_name"""
    return items.contains(Query().name==item_name)

def has_keys(_keys: List[str], _list: List[str]) -> bool:
    """check a list of keys if they are in another list (of keys)"""
    return set(_keys).issubset(set(_list))
def has_user(user_code: str) -> bool:
    """Prüft, ob ein Benutzer mit dem gegebenen Code existiert"""
    return users_db.contains(Query().code == user_code)

def get_active_session(user_code: str) -> dict:
    """Gibt die aktive Session eines Benutzers zurück"""
    return sessions_db.get((Query().user_code == user_code) & (Query().logout_time == None))

# Flask app
api = Flask(__name__)

# check if it's time to backup before every request
api.before_request(backup)

# handle assertion error => raised when user input is not correct
@api.errorhandler(AssertionError)
def failed(error):
    return "failed - "+str(error), 400

# handle not founds in api
@api.errorhandler(404)
def api_fallback(error):
    return "invalid request", 400

# get all items from items DB
@api.route("/list", methods=["GET"])
def get_all():
    return jsonify(items.all()), 200

# get information from one item
@api.route("/item", methods=["GET"])
def get():
    # check for keys
    assert has_keys(["item_name"], request.args.keys()), "bad keys"

    # check user user input
    assert re.match(item_name_pattern, request.args["item_name"]), "bad format"

    # return the item
    return jsonify(items.get(Query().name == request.args["item_name"])), 200

@api.route("/additem", methods=["POST"])
def additem():
    global items

    # Schlüssel prüfen
    assert has_keys(["item_name", "item_cost", "item_amount", "item_purchase_price"], request.form.keys()), "bad keys"

    assert re.match(item_name_pattern, request.form["item_name"]), "bad format"
    assert re.match(item_amount_pattern, request.form["item_amount"]), "bad format"
    assert re.match(item_cost_pattern, request.form["item_cost"]), "bad format"
    assert re.match(item_purchase_price_pattern, request.form["item_purchase_price"]), "bad format"

    # In Variablen speichern
    item_name = request.form["item_name"]
    item_cost = request.form["item_cost"]
    item_amount = request.form["item_amount"]
    item_purchase_price = request.form["item_purchase_price"]

    assert not has_item(item_name), "bad item"

    # Item hinzufügen
    items.insert({
        "name": item_name,
        "cost": item_cost,
        "amount": item_amount,
        "purchase_price": item_purchase_price
    })

    return "success", 200

@api.route("/delete", methods=["DELETE"])
def delete():
    global items
    # check for required key
    assert has_keys(["item_name"], request.args.keys()), "bad keys"

    # read item name
    item_name = request.args["item_name"]

    # check for keys
    assert has_item(item_name), "bad item"

    # check user_input
    assert re.match(item_name_pattern, item_name), "bad format"

    # remove item from items
    items.remove(where("name") == item_name)

    return "success", 200

@api.route("/buy")
def buy():
    global items
    # check for required keys
    assert has_keys(["item_name", "item_amount"], request.args.keys()), "bad keys"
    assert re.match(item_name_pattern, request.args["item_name"]), "bad format"
    assert re.match(item_amount_pattern, request.args["item_amount"]), "bad format"

    # save in variables
    item_name = request.args["item_name"]
    item_amount = request.args["item_amount"]

    # check user input
    assert has_item(item_name), "bad item"
    assert int(items.get(Query().name==item_name).get("amount"))-int(item_amount)>=0, "item overload"

    # Verkaufsdaten erstellen
    sales_data = {
        "item_name": item_name,
        "amount_sold": int(item_amount),
        "timestamp": datetime.now().isoformat(),  # Korrigiert: datetime.datetime.now() -> datetime.now()
    }

    # Verkaufsprotokoll einfügen
    sales_db.insert(sales_data)

    # update items
    items.update({
        "amount": int(items.get(Query().name == item_name).get("amount")) - int(item_amount),
    }, where("name") == item_name)

    return "success"


@api.route("/edit", methods=["POST"])
def edit():
    global items
    # Schlüssel prüfen
    assert has_keys(["item_name_old", "item_name_new", "item_cost_new", "item_amount_new", "item_purchase_price_new"], request.form.keys()), "bad keys"

    # Benutzereingaben prüfen
    assert re.match(item_name_pattern, request.form["item_name_new"]), "bad format"
    assert re.match(item_name_pattern, request.form["item_name_old"]), "bad format"
    assert re.match(item_amount_pattern, request.form["item_amount_new"]), "bad format"
    assert re.match(item_cost_pattern, request.form["item_cost_new"]), "bad format"
    assert re.match(item_purchase_price_pattern, request.form["item_purchase_price_new"]), "bad format"

    # In Variablen speichern
    item_name_old = request.form["item_name_old"]
    item_name_new = request.form["item_name_new"]
    item_cost_new = float(request.form["item_cost_new"])
    item_amount_new = int(request.form["item_amount_new"])
    item_purchase_price_new = float(request.form["item_purchase_price_new"])

    # Prüfen ob Item existiert
    assert has_item(item_name_old), "bad item"
    if item_name_new != item_name_old:
        assert not has_item(item_name_new), "item already exists"

    # Item aktualisieren
    items.update({
            "name": item_name_new,
            "cost": item_cost_new,
            "amount": item_amount_new,
            "purchase_price": item_purchase_price_new
        }, where("name")==item_name_old)

    return "success", 200

# Neue API-Routen für das Login-System
@api.route("/login", methods=["POST"])
def login():
    assert has_keys(["user_code1", "user_code2"], request.form.keys()), "bad keys"
    user_code1 = request.form["user_code1"]
    user_code2 = request.form["user_code2"]
    
    # Beide Codes müssen unterschiedlich sein
    assert user_code1 != user_code2, "beide Benutzer müssen unterschiedlich sein"
    
    # Beide Benutzer müssen existieren
    assert has_user(user_code1), "Benutzer 1 nicht gefunden"
    assert has_user(user_code2), "Benutzer 2 nicht gefunden"
    
    # Beide Benutzer dürfen nicht bereits angemeldet sein
    assert not get_active_session(user_code1), "Benutzer 1 bereits angemeldet"
    assert not get_active_session(user_code2), "Benutzer 2 bereits angemeldet"
    
    # Sessions für beide Benutzer erstellen
    for code in [user_code1, user_code2]:
        sessions_db.insert({
            "user_code": code,
            "login_time": datetime.now(timezone.utc).isoformat(),
            "logout_time": None,
            "partner_code": user_code2 if code == user_code1 else user_code1
        })
    
    return "success", 200

@api.route("/logout", methods=["POST"])
def logout():
    assert has_keys(["user_code1", "user_code2"], request.form.keys()), "bad keys"
    user_code1 = request.form["user_code1"]
    user_code2 = request.form["user_code2"]
    
    # Beide Sessions beenden
    for code in [user_code1, user_code2]:
        active_session = get_active_session(code)
        if active_session:
            sessions_db.update(
                {"logout_time": datetime.now(timezone.utc).isoformat()},
                doc_ids=[active_session.doc_id]
            )
    
    return "success", 200

@api.route("/users", methods=["GET"])
def get_users():
    return jsonify(users_db.all()), 200

@api.route("/user/add", methods=["POST"])
def add_user():
    assert has_keys(["user_code", "username"], request.form.keys()), "bad keys"
    
    user_code = request.form["user_code"]
    username = request.form["username"]
    
    assert re.match(user_code_pattern, user_code), "ungültiger Benutzercode"
    assert re.match(username_pattern, username), "ungültiger Benutzername"
    assert not has_user(user_code), "Benutzer existiert bereits"
    
    users_db.insert({
        "code": user_code,
        "username": username,
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    return "success", 200

@api.route("/user/delete", methods=["DELETE"])
def delete_user():
    assert has_keys(["user_code"], request.args.keys()), "bad keys"
    user_code = request.args["user_code"]
    
    assert has_user(user_code), "Benutzer nicht gefunden"
    
    users_db.remove(Query().code == user_code)
    return "success", 200

@api.route("/sessions/<user_code>", methods=["GET"])
def get_user_sessions(user_code):
    assert has_user(user_code), "Benutzer nicht gefunden"
    sessions = sessions_db.search(Query().user_code == user_code)
    return jsonify(sessions), 200

@api.route("/admin/delete-all", methods=["DELETE"])
def delete_all_data():
    # Sicherheitsüberprüfung
    assert has_keys(["admin_password"], request.args.keys()), "Admin-Passwort erforderlich"
    assert request.args["admin_password"] == config.get("ADMIN_PASSWORD"), "Ungültiges Admin-Passwort"
    
    try:
        # Lösche alle Datenbanken
        db_files = [
            get_path("storages/items.db"),
            get_path("storages/users.db"),
            get_path("storages/sessions.db"),
            'storages/sales_log.json'
        ]
        
        # Lösche Backups
        backup_dir = get_path("storages/backups")
        for filename in os.listdir(backup_dir):
            file_path = os.path.join(backup_dir, filename)
            if os.path.isfile(file_path):
                os.unlink(file_path)
        
        # Lösche Hauptdatenbanken
        for db_file in db_files:
            if os.path.exists(db_file):
                os.remove(db_file)
                # Neue leere Datenbank erstellen
                TinyDB(db_file).close()
        
        # Cache leeren
        cache_dir = get_path("storages/cache")
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
            os.makedirs(cache_dir)
            
        return "Alle Daten wurden erfolgreich gelöscht", 200
        
    except Exception as e:
        return f"Fehler beim Löschen: {str(e)}", 500