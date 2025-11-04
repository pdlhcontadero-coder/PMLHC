# =========================
# Imports y carga de .env
# =========================
from dotenv import load_dotenv
import os
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient

# Carga el archivo .env
load_dotenv()

# Definir UTC para datetime
UTC = timezone.utc

# =========================
# Configuración de la app
# =========================
INGEST_TOKEN = os.environ.get("INGEST_TOKEN")   # opcional: header "X-INGEST-TOKEN"
PORT = int(os.environ.get("PORT", "5000"))      # puerto donde corre Flask

# Conexión a MongoDB Atlas (usa directamente tu URI)
MONGO_URI = ""
mongo_client = MongoClient(MONGO_URI)

# Base de datos y colección según tu Atlas
db = mongo_client["IoT_PMLH"]
collection = db["sensordata"]

# Crear app Flask
app = Flask(__name__)

# Últimos valores en memoria
LATEST = {
    "temp_air": None,
    "hum_air": None,
    "ph": None,
    "ec": None,
    "temp_water": None,
    "distance_cm": None,
    "level1": None,
    "level2": None,
    "level3": None,
    "level4": None,
    "ts": None
}

# =========================
# Funciones auxiliares
# =========================
def to_float_or_none(x):
    try:
        if x is None:
            return None
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except Exception:
        return None

def norm_level(x):
    if x is None:
        return None
    s = str(x).strip().lower()
    if s in ("alto", "high", "arriba", "on", "1", "true"):
        return "alto"
    if s in ("bajo", "low", "abajo", "off", "0", "false"):
        return "bajo"
    return None

def compute_temp_water_from_parts(t_ph, t_ec):
    v1 = t_ph is not None and -40.0 < t_ph < 125.0
    v2 = t_ec is not None and -40.0 < t_ec < 125.0 and t_ec != -1000.0
    if v1 and v2:
        return (t_ph + t_ec) / 2.0
    if v1:
        return t_ph
    if v2:
        return t_ec
    return None

def save_to_mongo(data_dict):
    """Guarda un diccionario en MongoDB"""
    collection.insert_one(data_dict)

# =========================
# Rutas de Flask
# =========================
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/api/ingest", methods=["POST"])
def ingest():
    if INGEST_TOKEN:
        hdr = request.headers.get("X-INGEST-TOKEN")
        if not hdr or hdr != INGEST_TOKEN:
            return jsonify({"ok": False, "error": "invalid token"}), 401

    data = request.get_json(silent=True) or {}
    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    temp_air = to_float_or_none(data.get("temp_air"))
    hum_air  = to_float_or_none(data.get("hum_air"))
    ph       = to_float_or_none(data.get("ph"))

    # EC normalizada a mS/cm
    ec = None
    if "ec" in data:
        ec = to_float_or_none(data.get("ec"))
    elif "ec_mScm" in data:
        ec = to_float_or_none(data.get("ec_mScm"))
    elif "ec_uScm" in data:
        v_us = to_float_or_none(data.get("ec_uScm"))
        ec = (v_us / 1000.0) if v_us is not None else None

    temp_water = to_float_or_none(data.get("temp_water"))
    if temp_water is None:
        t_ph = to_float_or_none(data.get("t_ph"))
        t_ec = to_float_or_none(data.get("t_ec"))
        temp_water = compute_temp_water_from_parts(t_ph, t_ec)

    distance_cm = to_float_or_none(data.get("distance_cm"))

    level1 = norm_level(data.get("level1"))
    level2 = norm_level(data.get("level2"))
    level3 = norm_level(data.get("level3"))
    level4 = norm_level(data.get("level4"))

    LATEST.update({
        "temp_air": temp_air,
        "hum_air": hum_air,
        "ph": ph,
        "ec": ec,
        "temp_water": temp_water,
        "distance_cm": distance_cm,
        "level1": level1,
        "level2": level2,
        "level3": level3,
        "level4": level4,
        "ts": now_iso
    })

    # Guardar en MongoDB
    save_to_mongo(LATEST.copy())

    return jsonify({"ok": True, "saved": LATEST})

@app.route("/api/latest", methods=["GET"])
def latest():
    doc = collection.find_one(sort=[("ts", -1)])
    if doc:
        doc["_id"] = str(doc["_id"])  # convertir ObjectId a string
    return jsonify(doc or {})

@app.route("/api/history", methods=["GET"])
def history():
    limit = request.args.get("limit", default=100, type=int)
    limit = max(1, min(limit, 1000))
    docs = list(collection.find().sort("ts", -1).limit(limit))
    for d in docs:
        d["_id"] = str(d["_id"])  # convertir ObjectId a string
    return jsonify({"rows": docs, "count": len(docs)})

@app.route("/api/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True, "ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00","Z")})

# =========================
# Ejecutar app
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)