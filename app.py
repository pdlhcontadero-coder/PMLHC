from dotenv import load_dotenv
import os
import json
import threading
import time
from statistics import mean
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient




load_dotenv()

UTC = timezone.utc

INGEST_TOKEN = os.environ.get("INGEST_TOKEN")   
PORT = int(os.environ.get("PORT", "5000"))     

MONGO_URI = os.environ.get("MONGO_URI") or "mongodb+srv://IoT_datos:SocorroDelCarmen.20@pmlh.cfngjxa.mongodb.net/?retryWrites=true&w=majority&appName=PMLH"
mongo_client = MongoClient(MONGO_URI)

db = mongo_client["IoT_PMLH"]
collection = db["sensordata"]  

app = Flask(__name__)

# MODIFICADO: Agregamos level5, level6, level7
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
    "level5": None,
    "level6": None,
    "level7": None,
    "ts": None
}

PENDING_FILE = "pending_samples.jsonl"  
BUFFER = []
BUFFER_LOCK = threading.Lock()
LATEST_LOCK = threading.Lock()
FLUSH_INTERVAL = 600 

def to_float_or_none(x):
    try:
        if x is None:
            return None
        v = float(x)
        if v != v:  
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

def append_to_persistent_buffer(snapshot):
    """Añade snapshot al buffer en memoria y lo escribe en archivo JSONL (append).
       snapshot debe ser un dict con claves presentes (no incluir claves con None)."""
    s = snapshot.copy()
    with BUFFER_LOCK:
        BUFFER.append(s)
    try:
        with open(PENDING_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    except Exception as e:
        print("Error escribiendo pending file:", e)

def load_pending_file():
    """Devuelve la lista de muestras actualmente en el archivo y borra el archivo (se procesa)."""
    if not os.path.exists(PENDING_FILE):
        return []
    out = []
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        try:
            os.remove(PENDING_FILE)
        except Exception:
            pass
    except Exception as e:
        print("Error leyendo pending file:", e)
    return out

def clear_pending_file():
    try:
        if os.path.exists(PENDING_FILE):
            os.remove(PENDING_FILE)
    except Exception as e:
        print("Error borrando pending file:", e)

def aggregate_block(samples):
    """Agrega lista de muestras y devuelve documento de bloque listo para insertar.
       samples: lista de dicts (cada dict es una snapshot con claves solo con valores reales)."""
    if not samples:
        return None

    numeric_fields = ["temp_air","hum_air","ph","ec","temp_water","distance_cm"]
    # MODIFICADO: Agregamos level5, level6 y level7 a los campos de agregación
    level_fields = ["level1","level2","level3","level4","level5","level6","level7"]

    agg = {}
    times = [s.get("ts") for s in samples if s.get("ts")]
    agg["start_ts"] = times[0] if times else None
    agg["end_ts"]   = times[-1] if times else None
    agg["count"] = len(samples)

    for f in numeric_fields:
        vals = [v for v in (s.get(f) for s in samples) if (v is not None)]
        try:
            agg[f] = float(mean(vals)) if vals else None
        except Exception:
            agg[f] = None

    for f in level_fields:
        last = None
        for s in samples:
            if s.get(f) is not None:
                last = s.get(f)
        agg[f] = last

    agg["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00","Z")
    return agg

def flush_worker():
    while True:
        time.sleep(FLUSH_INTERVAL)

        samples = load_pending_file()
        with BUFFER_LOCK:
            if BUFFER:
                samples.extend(BUFFER)
                BUFFER.clear()   # Muy importante: limpia dentro del lock

        if not samples:
            continue

        block_doc = aggregate_block(samples)
        if block_doc is None:
            continue

        try:
            clean_block = {k: v for k, v in block_doc.items() if v is not None}
            numeric_fields = ["temp_air", "hum_air", "ph", "ec", "temp_water", "distance_cm"]
            if not any(clean_block.get(f) is not None for f in numeric_fields):
                print("[flush_worker] Bloque descartado: sin datos numéricos válidos")
                continue

            clean_block["inserted_at"] = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00","Z")
            ts_val = clean_block.get("end_ts") or clean_block.get("start_ts") or clean_block.get("inserted_at")
            if ts_val:
                clean_block["ts"] = ts_val

            collection.insert_one(clean_block)
            print(f"[flush_worker] Inserted block count={clean_block.get('count')} {clean_block.get('start_ts')} -> {clean_block.get('end_ts')}")
        except Exception as e:
            print("[flush_worker] Error inserting block to Mongo:", e)
            try:
                with open(PENDING_FILE, "a", encoding="utf-8") as f:
                    for s in samples:
                        f.write(json.dumps(s, ensure_ascii=False) + "\n")
            except Exception as e2:
                print("Error reescribiendo pending file tras fallo:", e2)
            with BUFFER_LOCK:
                BUFFER[0:0] = samples 

_flusher = threading.Thread(target=flush_worker, daemon=True, name="mongo-flush-worker")
_flusher.start()

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

    nivel_arr = data.get("nivel")
    # MODIFICADO: Extraer hasta 7 niveles si vienen en arreglo, o individuales
    if isinstance(nivel_arr, (list, tuple)) and len(nivel_arr) >= 7:
        level1 = norm_level(nivel_arr[0])
        level2 = norm_level(nivel_arr[1])
        level3 = norm_level(nivel_arr[2])
        level4 = norm_level(nivel_arr[3])
        level5 = norm_level(nivel_arr[4])
        level6 = norm_level(nivel_arr[5])
        level7 = norm_level(nivel_arr[6])
    else:
        level1 = norm_level(data.get("level1"))
        level2 = norm_level(data.get("level2"))
        level3 = norm_level(data.get("level3"))
        level4 = norm_level(data.get("level4"))
        level5 = norm_level(data.get("level5"))
        level6 = norm_level(data.get("level6"))
        level7 = norm_level(data.get("level7"))

    incoming = {
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
        "level5": level5,  # Añadido
        "level6": level6,  # Añadido
        "level7": level7   # Añadido
    }

    with LATEST_LOCK:
      for k, v in incoming.items():
        if v is not None:
            LATEST[k] = v
      LATEST["ts"] = now_iso

    snapshot = {k: v for k, v in incoming.items() if v is not None}
    snapshot["ts"] = now_iso

    valid_fields = [k for k, v in snapshot.items() if k != "ts" and v is not None]
    if valid_fields:
     append_to_persistent_buffer(snapshot)
    else:
     print("[ingest] muestra ignorada: sin valores numéricos o de nivel válidos")
    return jsonify({"ok": True, "saved_in_memory": LATEST})

@app.route("/api/latest", methods=["GET"])
def latest():
    MAX_AGE_S = 15 * 60  # tiempo máximo antes de mostrar "--"
    with LATEST_LOCK:
        snap = dict(LATEST)

    ts = snap.get("ts")

    # Si nunca se ha recibido ningún dato
    if not ts:
        out = {k: None for k in snap.keys() if k != "ts"}
        out["ts"] = None
        return jsonify(out)

    def parse_iso_ts(ts_str):
        try:
            if not ts_str:
                return None
            ts_str = ts_str.replace("Z", "+00:00")
            return datetime.fromisoformat(ts_str)
        except Exception:
            try:
                return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S%z")
            except Exception as e:
                print("Error parseando ts:", ts_str, e)
                return None

    dt = parse_iso_ts(ts)
    if dt is None:
        age = float("inf")
    else:
        age = (datetime.now(UTC) - dt).total_seconds()

    if age <= MAX_AGE_S:
        return jsonify(snap)
    else:
        out = {}
        for k in snap.keys():
            if k != "ts" and not k.startswith("_"):
                out[k] = "--"
        out["ts"] = None
        out["_latest_age_s"] = int(age) if age != float("inf") else None
        return jsonify(out)

@app.route("/api/history", methods=["GET"])
def history():
    # Pedir hasta 10000 por defecto
    limit = request.args.get("limit", default=10000, type=int) 
    # Subir el tope a 50000 para asegurarnos de que traiga todo tu historial
    limit = max(1, min(limit, 50000)) 
    docs = list(collection.find().sort("end_ts", -1).limit(limit))
    
    out = []
    for d in docs:
        d["_id"] = str(d["_id"])
        ts_val = d.get("end_ts") or d.get("start_ts") or d.get("inserted_at") or None
        if ts_val:
            d["ts"] = ts_val
        out.append(d)

    return jsonify({"rows": out, "count": len(out)})


@app.route("/api/blocks", methods=["GET"])
def get_blocks():
    return history()

@app.route("/api/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True, "ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00","Z")})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)


#nuevo2