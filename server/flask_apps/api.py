import os
import re
import datetime

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

    # check for keys
    assert has_keys(["item_name", "item_cost", "item_amount"], request.form.keys()), "bad keys"

    assert re.match(item_name_pattern, request.form["item_name"]), "bad format"
    assert re.match(item_amount_pattern, request.form["item_amount"]), "bad format"
    assert re.match(item_cost_pattern, request.form["item_cost"]), "bad format"

    # save in variables
    item_name = request.form["item_name"]
    item_cost = request.form["item_cost"]
    item_amount = request.form["item_amount"]

    # check user_input
    assert not has_item(item_name), "bad item"

    # add item
    items.insert({
        "name":item_name,
        "cost":item_cost,
        "amount":item_amount
    })

    # return response
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
        "timestamp": datetime.datetime.now().isoformat(),  # Verkaufszeitpunkt
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
    # check for requiered keys
    assert has_keys(["item_name_old", "item_name_new", "item_cost_new", "item_amount_new"], request.form.keys()), "bad keys"

    # check user input
    assert re.match(item_name_pattern, request.form["item_name_new"]), "bad format"
    assert re.match(item_name_pattern, request.form["item_name_old"]), "bad format"
    assert re.match(item_amount_pattern, request.form["item_amount_new"]), "bad format"
    assert re.match(item_cost_pattern, request.form["item_cost_new"]), "bad format"

    # save inforamations in variables
    item_name_old = request.form["item_name_old"]
    item_name_new = request.form["item_name_new"]
    item_cost_new = float(request.form["item_cost_new"])
    item_amount_new = int(request.form["item_amount_new"])

    # check that item exists
    assert has_item(item_name_old), "bad item"
    if item_name_new != item_name_old:
        # if item_name changed check that item doesn't already exists
        assert not has_item(item_name_new), "item already exists"


    # update item
    items.update({
            "name":item_name_new,
            "cost":item_cost_new,
            "amount":item_amount_new
        }, where("name")==item_name_old)

    # send response
    return "success", 200

# Neue API-Routen für das Login-System
@api.route("/login", methods=["POST"])
def login():
    assert has_keys(["user_code"], request.form.keys()), "bad keys"
    user_code = request.form["user_code"]
    
    assert re.match(user_code_pattern, user_code), "ungültiger Benutzercode"
    assert has_user(user_code), "Benutzer nicht gefunden"
    
    # Prüfen ob Benutzer bereits aktiv
    active_session = get_active_session(user_code)
    if active_session:
        return "Benutzer bereits angemeldet", 400
    
    # Neue Session erstellen
    sessions_db.insert({
        "user_code": user_code,
        "login_time": datetime.now(timezone.utc).isoformat(),
        "logout_time": None
    })
    
    return "success", 200

@api.route("/logout", methods=["POST"])
def logout():
    assert has_keys(["user_code"], request.form.keys()), "bad keys"
    user_code = request.form["user_code"]
    
    active_session = get_active_session(user_code)
    if not active_session:
        return "Keine aktive Session gefunden", 400
    
    # Session beenden
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