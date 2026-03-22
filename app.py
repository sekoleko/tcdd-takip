import os
import json
import threading
from flask import Flask, render_template, request, jsonify
from tracker import motor, sefer_ara_headless

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "tcdd-secret-2026")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/ayarlar", methods=["POST"])
def ayarlar():
    data = request.json
    motor.tg_token = data.get("tg_token", "")
    motor.tg_chat  = data.get("tg_chat", "")
    return jsonify({"ok": True})

@app.route("/api/sefer-ara", methods=["POST"])
def sefer_ara():
    data   = request.json
    kalkis = data.get("kalkis", "")
    varis  = data.get("varis", "")
    tarih  = data.get("tarih", "")

    if not kalkis or not varis or not tarih:
        return jsonify({"ok": False, "hata": "Eksik bilgi"})

    # Arka planda çalıştır, sonucu döndür
    result = {"seferler": None, "hata": None}
    event  = threading.Event()

    def _ara():
        seferler, hata = sefer_ara_headless(kalkis, varis, tarih)
        result["seferler"] = seferler
        result["hata"]     = hata
        event.set()

    t = threading.Thread(target=_ara, daemon=True)
    t.start()
    event.wait(timeout=60)

    if result["seferler"] is None:
        return jsonify({"ok": False, "hata": result["hata"] or "Zaman aşımı"})

    return jsonify({"ok": True, "seferler": result["seferler"]})

@app.route("/api/ekle", methods=["POST"])
def ekle():
    data        = request.json
    kalkis      = data.get("kalkis")
    varis       = data.get("varis")
    tarih       = data.get("tarih")
    saatler_tr  = data.get("saatler_tr", [])
    saatler_utc = data.get("saatler_utc", [])

    if not all([kalkis, varis, tarih, saatler_tr]):
        return jsonify({"ok": False, "hata": "Eksik bilgi"})

    motor.sefer_ekle(kalkis, varis, tarih, saatler_tr, saatler_utc)
    return jsonify({"ok": True})

@app.route("/api/sil/<int:idx>", methods=["DELETE"])
def sil(idx):
    motor.sefer_sil(idx)
    return jsonify({"ok": True})

@app.route("/api/baslat", methods=["POST"])
def baslat():
    data   = request.json or {}
    aralik = int(data.get("aralik", 30))
    if not motor.takip_listesi:
        return jsonify({"ok": False, "hata": "Takip listesi boş"})
    motor.baslat(aralik)
    return jsonify({"ok": True})

@app.route("/api/durdur", methods=["POST"])
def durdur():
    motor.durdur()
    return jsonify({"ok": True})

@app.route("/api/durum")
def durum():
    return jsonify(motor.durum_json())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
