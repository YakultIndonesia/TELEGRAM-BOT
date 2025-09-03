# bot.py
# Telegram + Flask admin panel integrated for "55five-like" number game
# Author: generated for Arya
# NOTE: set environment variables in deployment (Railway) for production use.

import os
import time
import json
import random
import threading
from datetime import datetime
from functools import wraps

from flask import Flask, request, redirect, url_for, render_template_string, session, abort, make_response
import telebot
from telebot import types

# ---------------------------
# Configuration (ENV-friendly)
# ---------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "7635408983:AAHrM9l9mXMYMrX6K6IP_my1tR-gHCmADBM")
ADMIN_TELE_ID = int(os.getenv("ADMIN_TELE_ID", "61210259"))
GROUP_ID = int(os.getenv("GROUP_ID", "-1002279218218"))

ADMIN_WEB_USER = os.getenv("ADMIN_WEB_USER", "Arya")
ADMIN_WEB_PASS = os.getenv("ADMIN_WEB_PASS", "Arshal5445@")

DATA_FILE = os.getenv("DATA_FILE", "data.json")
PORT = int(os.getenv("PORT", os.getenv("PORT", "8080")))

# Flask secret (for session handling)
FLASK_SECRET = os.getenv("FLASK_SECRET", "please-change-this-secret-in-prod")

# defaults for behavior
DEFAULT_ROUND_DURATION = int(os.getenv("DEFAULT_ROUND_DURATION", "30"))  # seconds

# ---------------------------
# Persistent data handling
# ---------------------------
data_lock = threading.Lock()

def load_data():
    if not os.path.exists(DATA_FILE):
        base = {
            "users": {},        # per-user info: name, last_seen, history
            "rounds": [],       # history of rounds
            "current_round": None
        }
        save_data(base)
        return base
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(d):
    with data_lock:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)

data = load_data()

# ---------------------------
# Helper: ensure user
# ---------------------------
def ensure_user(user_id, name=None):
    uid = str(user_id)
    changed = False
    if uid not in data["users"]:
        data["users"][uid] = {
            "id": uid,
            "name": name or "",
            "last_seen": time.time(),
            "history": []  # list of {round_id, pilihan, result, win}
        }
        changed = True
    else:
        if name:
            data["users"][uid]["name"] = name
        data["users"][uid]["last_seen"] = time.time()
        changed = True
    if changed:
        save_data(data)

# ---------------------------
# Game logic helpers
# ---------------------------
WARNA_MAP = {
    "MERAH": [0,2,4,6,8],
    "HIJAU": [1,3,5,7,9],
    "UNGU": [0,5]
}
BESAR_RANGE = list(range(5,10))
KECIL_RANGE = list(range(0,5))

def get_attributes_from_number(n):
    warna = []
    for w, arr in WARNA_MAP.items():
        if n in arr:
            warna.append(w)
    tingkat = "BESAR" if n in BESAR_RANGE else "KECIL"
    return {"angka": n, "warna": warna, "tingkat": tingkat}

def evaluate_choice(choice, n):
    # choice: string (angka digit or MERAH/HIJAU/UNGU or BESAR/KECIL)
    # n: int 0-9
    attrs = get_attributes_from_number(n)
    status = "GAGAL"
    if choice.isdigit():
        if int(choice) == n:
            status = "BERHASIL"
    else:
        up = choice.upper()
        if up in ["MERAH","HIJAU","UNGU"]:
            if up in attrs["warna"]:
                status = "BERHASIL"
        elif up in ["BESAR","KECIL"]:
            if up == attrs["tingkat"]:
                status = "BERHASIL"
    return {
        "angka": attrs["angka"],
        "warna": attrs["warna"],
        "tingkat": attrs["tingkat"],
        "status": status
    }

# ---------------------------
# Current round structure
# ---------------------------
# current_round = {
#   "id": int,
#   "active": bool,
#   "duration": seconds,
#   "end_at": timestamp,
#   "choices": {user_id_str: {"choice": "5" or "MERAH" or "BESAR", "ts": ts, "countdown_msg": {"chat_id":.., "msg_id":..} (opt)}},
#   "countdown_group_msg_id": int  (message id in group for editing)
# }
round_lock = threading.Lock()

def new_round(duration):
    with round_lock:
        rid = int(time.time())
        cr = {
            "id": rid,
            "active": True,
            "duration": duration,
            "end_at": time.time() + duration,
            "choices": {},
            "countdown_group_msg_id": None
        }
        data["current_round"] = cr
        save_data(data)
        return cr

def close_round_and_set_result(result_number):
    with round_lock:
        cr = data.get("current_round")
        if not cr:
            return None
        cr["active"] = False
        cr["result_number"] = result_number
        cr["ended_at"] = time.time()

        # evaluate players
        evaluations = {}
        for uid, info in cr["choices"].items():
            evalr = evaluate_choice(info["choice"], result_number)
            evaluations[uid] = {
                "user_id": uid,
                "choice": info["choice"],
                "evaluation": evalr,
                "ts": time.time()
            }
            # append to user history
            user = data["users"].get(uid)
            if user is not None:
                user["history"].append({
                    "round_id": cr["id"],
                    "choice": info["choice"],
                    "result": result_number,
                    "evaluation": evalr,
                    "ts": time.time()
                })

        # push to rounds history
        data["rounds"].append({
            "id": cr["id"],
            "duration": cr["duration"],
            "start_at": cr.get("start_at", None),
            "end_at": cr["ended_at"],
            "result_number": result_number,
            "choices": cr["choices"]
        })
        # save and clear current round
        save_data(data)
        return {"round": cr, "evaluations": evaluations}

# ---------------------------
# Telegram bot initialization
# ---------------------------
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ---------------------------
# Keyboards
# ---------------------------
def build_time_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("30dtk", callback_data="time_30"))
    kb.add(types.InlineKeyboardButton("1mnt", callback_data="time_60"))
    kb.add(types.InlineKeyboardButton("3mnt", callback_data="time_180"))
    kb.add(types.InlineKeyboardButton("5mnt", callback_data="time_300"))
    return kb

def build_choice_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=3)
    # rows 1-3
    kb.row(*[types.InlineKeyboardButton(str(i), callback_data=f"angka_{i}") for i in range(1,4)])
    kb.row(*[types.InlineKeyboardButton(str(i), callback_data=f"angka_{i}") for i in range(4,7)])
    kb.row(*[types.InlineKeyboardButton(str(i), callback_data=f"angka_{i}") for i in range(7,10)])
    # 0 as long button (we just add single)
    kb.add(types.InlineKeyboardButton("0", callback_data="angka_0"))
    # besar/kecil
    kb.row(types.InlineKeyboardButton("BESAR", callback_data="tingkat_BESAR"),
           types.InlineKeyboardButton("KECIL", callback_data="tingkat_KECIL"))
    # warna
    kb.row(types.InlineKeyboardButton("MERAH", callback_data="warna_MERAH"),
           types.InlineKeyboardButton("HIJAU", callback_data="warna_HIJAU"),
           types.InlineKeyboardButton("UNGU", callback_data="warna_UNGU"))
    # info
    kb.add(types.InlineKeyboardButton("LIST INFO", callback_data="info_list"))
    return kb

# ---------------------------
# Bot handlers
# ---------------------------
@bot.message_handler(commands=["start"])
def handle_start(msg):
    ensure_user(msg.from_user.id, getattr(msg.from_user, "first_name", "") or "")
    bot.send_message(msg.chat.id, "Pilih durasi ronde:", reply_markup=build_time_keyboard())

@bot.message_handler(commands=["mulai"])
def handle_mulai(msg):
    ensure_user(msg.from_user.id, getattr(msg.from_user, "first_name", "") or "")
    cr = data.get("current_round")
    if not cr or not cr.get("active"):
        bot.send_message(msg.chat.id, "❌ Tidak ada ronde aktif saat ini. Tunggu admin buka ronde.")
        return
    uid = str(msg.from_user.id)
    # send keyboard and save message id for countdown editing per-user
    sent = bot.send_message(msg.chat.id, "Silakan pilih satu: (angka / warna / BESAR/KECIL)", reply_markup=build_choice_keyboard())
    with round_lock:
        # store countdown message id reference for editing later (optional)
        cr = data.get("current_round")
        if cr:
            # store only if not already chosen (we still allow keyboard but lock on selection)
            entry = cr["choices"].get(uid, {})
            entry.setdefault("countdown_msg", {})
            entry["countdown_msg"] = {"chat_id": msg.chat.id, "msg_id": sent.message_id}
            cr["choices"][uid] = entry if "choice" in entry else entry  # keep structure
            save_data(data)

@bot.message_handler(commands=["stop"])
def handle_stop(msg):
    uid = str(msg.from_user.id)
    cr = data.get("current_round")
    if cr and uid in cr.get("choices", {}):
        with round_lock:
            cr["choices"].pop(uid, None)
            save_data(data)
        bot.send_message(msg.chat.id, "✅ Kamu keluar dari ronde (pilihan dihapus).")
    else:
        bot.send_message(msg.chat.id, "❌ Kamu belum memilih di ronde aktif.")

# Callback query handler for inline buttons
@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    data_cb = call.data
    user = call.from_user
    uid = str(user.id)
    ensure_user(user.id, getattr(user, "first_name", "") or "")

    # Time selection: start a new round
    if data_cb.startswith("time_"):
        seconds = int(data_cb.split("_",1)[1])
        # start round thread only if not active
        with round_lock:
            cr = data.get("current_round")
            if cr and cr.get("active"):
                bot.answer_callback_query(call.id, "❌ Sudah ada ronde aktif.")
                return
            # create new round
            cr = new_round(seconds)
            cr["start_at"] = time.time()
            save_data(data)
        bot.answer_callback_query(call.id, f"Ronde dibuka: {seconds} detik.")
        threading.Thread(target=run_round_countdown, args=(cr["id"],), daemon=True).start()
        return

    # Info list
    if data_cb == "info_list":
        info_text = ("📋 INFO:\n"
                     "MERAH: 0,2,4,6,8\n"
                     "HIJAU: 1,3,5,7,9\n"
                     "UNGU: 0,5\n"
                     "KECIL: 0,1,2,3,4\n"
                     "BESAR: 5,6,7,8,9\n\n"
                     "Pesan ini akan dihapus otomatis.")
        # reply and delete after short time
        try:
            bot.answer_callback_query(call.id)
            m = bot.send_message(call.message.chat.id, info_text)
            time.sleep(3)
            bot.delete_message(m.chat.id, m.message_id)
        except Exception:
            pass
        return

    # Choices (angka / warna / tingkat)
    if data_cb.startswith("angka_") or data_cb.startswith("warna_") or data_cb.startswith("tingkat_"):
        with round_lock:
            cr = data.get("current_round")
            if not cr or not cr.get("active"):
                bot.answer_callback_query(call.id, "❌ Tidak ada ronde aktif.")
                return
            # check if user already chose
            if uid in cr["choices"] and "choice" in cr["choices"][uid]:
                bot.answer_callback_query(call.id, "❌ Kamu sudah memilih di ronde ini.")
                return
            # record choice
            if data_cb.startswith("angka_"):
                choice = data_cb.split("_",1)[1]
            elif data_cb.startswith("warna_"):
                choice = data_cb.split("_",1)[1]
            else:
                choice = data_cb.split("_",1)[1]  # BESAR/KECIL

            cr["choices"].setdefault(uid, {})
            cr["choices"][uid]["choice"] = choice
            cr["choices"][uid]["ts_choice"] = time.time()
            # Keep countdown_msg ref if exists
            save_data(data)

        # send confirmation to user
        pretty = choice
        if choice.isdigit():
            bot.send_message(user.id, f"✅ KAMU MEMILIH ANGKA {pretty}")
        else:
            bot.send_message(user.id, f"✅ KAMU MEMILIH {pretty.upper()}")
        bot.answer_callback_query(call.id, "Pilihan disimpan.")
        return

# ---------------------------
# Round runner + countdown editing
# ---------------------------
def run_round_countdown(round_id):
    # find the round data (by id) to operate
    # We'll edit one group message for countdown and edit per-user countdown messages if available
    try:
        with round_lock:
            cr = data.get("current_round")
            if not cr or cr["id"] != round_id:
                return
            duration = int(cr["duration"])
            # send initial group message and save message id
            msg = bot.send_message(GROUP_ID, f"🎮 Ronde #{cr['id']} dimulai — waktu: {duration} detik\nSilakan pemain ketik /mulai untuk mendapat tombol.")
            cr["countdown_group_msg_id"] = msg.message_id
            cr["start_at"] = time.time()
            save_data(data)

        # countdown loop
        for t in range(duration, 0, -1):
            with round_lock:
                cr = data.get("current_round")
                if not cr or not cr.get("active"):
                    break
                # edit group message
                try:
                    bot.edit_message_text(f"⏳ Ronde #{cr['id']} — {t} detik tersisa...", GROUP_ID, cr.get("countdown_group_msg_id"))
                except Exception:
                    pass
                # edit per-user countdown messages if present
                # iterate choices to find countdown_msg references
                for uid, entry in list(cr.get("choices", {}).items()):
                    cm = entry.get("countdown_msg")
                    if cm:
                        try:
                            bot.edit_message_text(f"⏳ {t} detik tersisa untuk ronde #{cr['id']}...", cm["chat_id"], cm["msg_id"])
                        except Exception:
                            # ignore edit failures (might be because of permissions)
                            pass
            time.sleep(1)

        # time's up: choose random result and evaluate
        result_num = random.randint(0,9)
        res = close_round_and_set_result(result_num)
        # build announcement text
        attrs = get_attributes_from_number(result_num)
        announcement = (f"🎲 HASIL RONDE #{res['round']['id']}:\n"
                        f"Angka: <b>{result_num}</b>\n"
                        f"Tingkat: <b>{attrs['tingkat']}</b>\n"
                        f"Warna: <b>{', '.join(attrs['warna'])}</b>\n\n"
                        f"Detail hasil telah dikirim ke pemain yang ikut.")
        try:
            bot.send_message(GROUP_ID, announcement)
        except Exception:
            pass

        # send private results to each player
        evals = res["evaluations"]
        for uid, e in evals.items():
            try:
                ev = e["evaluation"]
                text = (f"🎲 Ronde #{res['round']['id']} — HASIL\n"
                        f"Angka: <b>{ev['angka']}</b>\n"
                        f"Tingkat: <b>{ev['tingkat']}</b>\n"
                        f"Warna: <b>{', '.join(ev['warna'])}</b>\n\n"
                        f"Pilihanmu: <b>{e['choice']}</b>\n"
                        f"➡️ <b>{ev['status']}</b>")
                bot.send_message(int(uid), text)
            except Exception:
                pass

        # auto start new round with same duration (auto repeat)
        # small delay before starting next round
        time.sleep(2)
        with round_lock:
            # If you want always auto start: create new round
            # Recreate round with same duration
            next_cr = new_round(duration)
            next_cr["start_at"] = time.time()
            save_data(data)
        # start next countdown in a new thread
        threading.Thread(target=run_round_countdown, args=(next_cr["id"],), daemon=True).start()

    except Exception as e:
        print("Error in run_round_countdown:", e)

# ---------------------------
# Admin-only Flask Web Panel
# ---------------------------
app = Flask(__name__)
app.secret_key = FLASK_SECRET

TPL_LOGIN = """
<!doctype html>
<title>Login - Admin Panel</title>
<style>
body{font-family:Arial;max-width:900px;margin:30px auto}
.card{background:#f6f8fa;padding:16px;border-radius:8px}
input{padding:8px;margin:6px 0;width:100%}
button{padding:8px 12px}
</style>
<h2>Admin Login</h2>
<div class="card">
<form method="post" action="/admin/login">
  <label>Username</label><br><input name="username"><br>
  <label>Password</label><br><input name="password" type="password"><br>
  <button type="submit">Login</button>
</form>
</div>
"""

TPL_DASH = """
<!doctype html>
<title>Admin Panel</title>
<style>
body{font-family:Arial;max-width:1100px;margin:20px auto}
.header{display:flex;justify-content:space-between;align-items:center}
.card{background:#f6f8fa;padding:12px;border-radius:8px;margin:10px 0}
table{width:100%;border-collapse:collapse}
th,td{border-bottom:1px solid #ddd;padding:8px;text-align:left}
.btn{padding:8px 12px;border-radius:6px;text-decoration:none;background:#2b6cb0;color:white}
.small{font-size:12px;color:#666}
</style>
<div class="header">
  <h2>Admin Panel</h2>
  <div>
    <a class="btn" href="/admin/logout">Logout</a>
  </div>
</div>

<div class="card">
  <h3>Ronde Saat Ini</h3>
  {% if cr %}
    <p>ID: {{cr.id}} | Active: {{cr.active}} | Duration: {{cr.duration}}s | Ends at: {{cr.end_at|datetime}}</p>
    <form method="post" action="/admin/action">
      <input type="hidden" name="action" value="close">
      <button class="btn" type="submit">Close Round</button>
    </form>
    <form method="post" action="/admin/action" style="margin-top:8px">
      <input type="hidden" name="action" value="roll">
      <label>Set Result (0-9):</label><input name="manual_result" pattern='\\d' maxlength="1" style="width:50px">
      <input type="hidden" name="action" value="roll">
      <button class="btn" type="submit">Roll Now</button>
    </form>
  {% else %}
    <p>Tidak ada ronde aktif.</p>
    <form method="post" action="/admin/action">
      <input type="hidden" name="action" value="open">
      <label>Duration (s): </label><input name="duration" value="30" style="width:70px">
      <button class="btn" type="submit">Open Round</button>
    </form>
  {% endif %}
</div>

<div class="card">
  <h3>Pemain Saat Ini (pilih di ronde ini)</h3>
  {% if cr and cr.choices %}
    <table><tr><th>User ID</th><th>Nama</th><th>Pilihan</th><th>Waktu</th></tr>
    {% for uid,entry in cr.choices.items() %}
      <tr>
        <td>{{uid}}</td>
        <td>{{ users.get(uid, {}).get('name') }}</td>
        <td>{{ entry.get('choice') or '-' }}</td>
        <td>{{ entry.get('ts_choice')|datetime }}</td>
      </tr>
    {% endfor %}
    </table>
  {% else %}
    <p>Tidak ada pemain.</p>
  {% endif %}
</div>

<div class="card">
  <h3>Riwayat Ronde (terakhir 10)</h3>
  {% for r in rounds[-10:]|reverse %}
    <div style="padding:8px;margin-bottom:8px;border-radius:6px;background:white">
      <b>Ronde {{r.id}}</b> | result: {{r.result_number}} | started: {{r.start_at|datetime}} | ended: {{r.end_at|datetime}}
      <div class="small">players: {{ r.choices|length }}</div>
    </div>
  {% else %}
    <p>Tidak ada riwayat.</p>
  {% endfor %}
</div>
"""

@app.template_filter('datetime')
def _jinja2_filter_datetime(ts):
    if not ts:
        return "-"
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect("/admin/login")
        return view(*args, **kwargs)
    return wrapped

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "GET":
        return render_template_string(TPL_LOGIN)
    username = request.form.get("username","")
    password = request.form.get("password","")
    if username == ADMIN_WEB_USER and password == ADMIN_WEB_PASS:
        session["admin_logged_in"] = True
        return redirect("/admin")
    return "Login gagal", 401

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect("/admin/login")

@app.route("/admin")
@login_required
def admin_index():
    return render_template_string(TPL_DASH, cr=data.get("current_round"), users=data.get("users",{}), rounds=data.get("rounds",[]))

@app.route("/admin/action", methods=["POST"])
@login_required
def admin_action():
    action = request.form.get("action")
    if action == "open":
        dur = int(request.form.get("duration", "30"))
        with round_lock:
            cr = data.get("current_round")
            if cr and cr.get("active"):
                return "Sudah ada ronde aktif", 400
            nr = new_round(dur)
            nr["start_at"] = time.time()
            save_data(data)
        threading.Thread(target=run_round_countdown, args=(nr["id"],), daemon=True).start()
        return redirect("/admin")
    if action == "close":
        # set active false, but no result (manual close)
        with round_lock:
            cr = data.get("current_round")
            if cr:
                cr["active"] = False
                save_data(data)
        return redirect("/admin")
    if action == "roll":
        # manual roll result (use manual_result if provided)
        manual = request.form.get("manual_result", None)
        try:
            num = int(manual) if manual is not None and manual != "" else random.randint(0,9)
        except:
            num = random.randint(0,9)
        res = close_round_and_set_result(num)
        # announce to group
        try:
            attrs = get_attributes_from_number(num)
            bot.send_message(GROUP_ID, f"🎲 HASIL MANUAL ROLL: {num} / {attrs['tingkat']} / {', '.join(attrs['warna'])}")
        except:
            pass
        return redirect("/admin")
    return "Unknown action", 400

# ---------------------------
# Run Flask + Bot
# ---------------------------
def start_bot_polling():
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=50)
        except Exception as e:
            print("Bot polling error:", e)
            time.sleep(5)

if __name__ == "__main__":
    # ensure data file
    save_data(data)

    # start bot polling in background thread
    t = threading.Thread(target=start_bot_polling, daemon=True)
    t.start()

    # If there is an active current_round at startup, restart countdown thread
    with round_lock:
        cr = data.get("current_round")
        if cr and cr.get("active"):
            # compute remaining seconds
            rem = int(cr.get("end_at", time.time()) - time.time())
            if rem > 1:
                # start countdown for existing round id
                threading.Thread(target=run_round_countdown, args=(cr["id"],), daemon=True).start()
            else:
                # expired — close it quickly
                close_round_and_set_result(random.randint(0,9))

    # run flask (Railway will expect this to listen on PORT)
    print("Starting Flask on port", PORT)
    app.run(host="0.0.0.0", port=PORT)

