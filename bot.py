import telebot
from telebot import types
import random
import time
import threading
import json
from flask import Flask, request, render_template_string, redirect, session, url_for

# ====== KONFIGURASI BOT ======
BOT_TOKEN = "7635408983:AAHrM9l9mXMYMrX6K6IP_my1tR-gHCmADBM"
ADMIN_ID = 61210259
GROUP_ID = -1002279218218

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ====== DATA GAME ======
DATA_FILE = "data.json"
current_round = {"active": False, "choices": {}, "duration": 30, "manual_result": None}
lock = threading.Lock()

# ====== LOAD/SAVE DATA ======
def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {"users": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ====== CEK HASIL ======
def cek_hasil(pilihan, angka_random):
    warna_map = {
        "Merah": [0, 2, 4, 6, 8],
        "Hijau": [1, 3, 5, 7, 9],
        "Ungu": [0, 5]
    }
    besar = list(range(5, 10))
    kecil = list(range(0, 5))

    hasil = {
        "angka": angka_random,
        "warna": [],
        "tingkat": "BESAR" if angka_random in besar else "KECIL",
        "status": "GAGAL"
    }

    for w, arr in warna_map.items():
        if angka_random in arr:
            hasil["warna"].append(w)

    # Evaluasi
    if pilihan.isdigit():
        if int(pilihan) == angka_random:
            hasil["status"] = "BERHASIL"
    elif pilihan in ["Merah", "Hijau", "Ungu"]:
        if pilihan in hasil["warna"]:
            hasil["status"] = "BERHASIL"
    elif pilihan in ["BESAR", "KECIL"]:
        if pilihan == hasil["tingkat"]:
            hasil["status"] = "BERHASIL"

    return hasil

# ====== KEYBOARD ======
def get_choice_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=3)

    # Angka
    row1 = [types.InlineKeyboardButton(str(i), callback_data=f"angka_{i}") for i in range(1, 4)]
    row2 = [types.InlineKeyboardButton(str(i), callback_data=f"angka_{i}") for i in range(4, 7)]
    row3 = [types.InlineKeyboardButton(str(i), callback_data=f"angka_{i}") for i in range(7, 10)]
    row0 = [types.InlineKeyboardButton("0", callback_data="angka_0")]

    # Besar/Kecil
    row_tingkat = [
        types.InlineKeyboardButton("BESAR", callback_data="tingkat_BESAR"),
        types.InlineKeyboardButton("KECIL", callback_data="tingkat_KECIL"),
    ]

    # Warna
    row_warna = [
        types.InlineKeyboardButton("MERAH", callback_data="warna_Merah"),
        types.InlineKeyboardButton("HIJAU", callback_data="warna_Hijau"),
        types.InlineKeyboardButton("UNGU", callback_data="warna_Ungu"),
    ]

    # Info
    row_info = [types.InlineKeyboardButton("LIST INFO", callback_data="info")]

    markup.add(*row1)
    markup.add(*row2)
    markup.add(*row3)
    markup.add(*row0)
    markup.add(*row_tingkat)
    markup.add(*row_warna)
    markup.add(*row_info)
    return markup

# ====== START ROUND ======
def start_round(duration):
    global current_round
    with lock:
        current_round = {"active": True, "choices": {}, "duration": duration, "manual_result": None}

    msg = bot.send_message(GROUP_ID, f"🎮 Ronde dimulai! Waktu {duration} detik\nGunakan /mulai untuk ikut.")
    for i in range(duration, 0, -1):
        try:
            bot.edit_message_text(f"⏳ {i} detik tersisa...", GROUP_ID, msg.message_id)
        except:
            pass
        time.sleep(1)

    angka_random = current_round["manual_result"] if current_round["manual_result"] is not None else random.randint(0, 9)

    with lock:
        pemain = current_round["choices"]
        current_round["active"] = False

    for user_id, pilihan in pemain.items():
        hasil = cek_hasil(pilihan, angka_random)
        teks_hasil = f"🎲 Hasil: {hasil['angka']} / {hasil['tingkat']} / {', '.join(hasil['warna'])}\n"
        teks_hasil += f"✅ Kamu {hasil['status']} (pilihan: {pilihan})"
        bot.send_message(user_id, teks_hasil)

    hasil = cek_hasil("dummy", angka_random)
    bot.send_message(
        GROUP_ID,
        f"🎲 HASIL AKHIR RONDE:\nAngka: {hasil['angka']}\nTingkat: {hasil['tingkat']}\nWarna: {', '.join(hasil['warna'])}"
    )

# ====== COMMAND ======
@bot.message_handler(commands=["start"])
def cmd_start(message):
    markup = types.InlineKeyboardMarkup()
    for t in [30, 60, 180, 300]:
        markup.add(types.InlineKeyboardButton(f"{t//60 if t>=60 else t}{'mnt' if t>=60 else 'dtk'}", callback_data=f"time_{t}"))
    bot.send_message(message.chat.id, "Pilih durasi ronde:", reply_markup=markup)

@bot.message_handler(commands=["mulai"])
def cmd_mulai(message):
    if not current_round["active"]:
        bot.send_message(message.chat.id, "❌ Belum ada ronde aktif.")
    else:
        bot.send_message(message.chat.id, "Silakan pilih:", reply_markup=get_choice_keyboard())

# ====== CALLBACK ======
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    global current_round

    if call.data.startswith("time_"):
        durasi = int(call.data.split("_")[1])
        threading.Thread(target=start_round, args=(durasi,)).start()

    elif call.data.startswith("angka_"):
        pilihan = call.data.split("_")[1]
        with lock:
            if current_round["active"] and call.from_user.id not in current_round["choices"]:
                current_round["choices"][call.from_user.id] = pilihan
                bot.send_message(call.from_user.id, f"✅ Kamu memilih ANGKA {pilihan}")
            else:
                bot.answer_callback_query(call.id, "❌ Kamu sudah pilih atau ronde tidak aktif.")

    elif call.data.startswith("warna_"):
        pilihan = call.data.split("_")[1]
        with lock:
            if current_round["active"] and call.from_user.id not in current_round["choices"]:
                current_round["choices"][call.from_user.id] = pilihan
                bot.send_message(call.from_user.id, f"✅ Kamu memilih WARNA {pilihan.upper()}")
            else:
                bot.answer_callback_query(call.id, "❌ Kamu sudah pilih atau ronde tidak aktif.")

    elif call.data.startswith("tingkat_"):
        pilihan = call.data.split("_")[1]
        with lock:
            if current_round["active"] and call.from_user.id not in current_round["choices"]:
                current_round["choices"][call.from_user.id] = pilihan
                bot.send_message(call.from_user.id, f"✅ Kamu memilih {pilihan}")
            else:
                bot.answer_callback_query(call.id, "❌ Kamu sudah pilih atau ronde tidak aktif.")

    elif call.data == "info":
        info = (
            "📋 INFO:\n"
            "MERAH: 0,2,4,6,8\n"
            "HIJAU: 1,3,5,7,9\n"
            "UNGU: 0,5\n"
            "KECIL: 0,1,2,3,4\n"
            "BESAR: 5,6,7,8,9"
        )
        bot.edit_message_text(info, call.message.chat.id, call.message.message_id)

# ====== FLASK ADMIN ======
app = Flask(__name__)
app.secret_key = "secretkey"

HTML_LOGIN = """
<form method="post">
  <input type="text" name="username" placeholder="Username"><br>
  <input type="password" name="password" placeholder="Password"><br>
  <button type="submit">Login</button>
</form>
"""

HTML_DASHBOARD = """
<h2>Dashboard Admin</h2>
<p>Halo, {{username}}</p>
<a href="{{url_for('logout')}}">Logout</a><br><br>
<form method="post" action="{{url_for('set_result')}}">
  <label>Set Angka Hasil Manual (0-9):</label>
  <input type="number" name="angka" min="0" max="9">
  <button type="submit">Set</button>
</form>
<h3>Pemain Aktif</h3>
<ul>
{% for uid, pilihan in choices.items() %}
  <li>User ID: {{uid}} → Pilihan: {{pilihan}}</li>
{% endfor %}
</ul>
"""

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == "Arya" and request.form["password"] == "Arshal5445@":
            session["user"] = "Arya"
            return redirect(url_for("dashboard"))
    return HTML_LOGIN

@app.route("/dashboard")
def dashboard():
    if "user" not in session: return redirect("/")
    return render_template_string(HTML_DASHBOARD, username=session["user"], choices=current_round["choices"])

@app.route("/set_result", methods=["POST"])
def set_result():
    if "user" not in session: return redirect("/")
    angka = int(request.form["angka"])
    current_round["manual_result"] = angka
    return redirect(url_for("dashboard"))

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")

# ====== RUN ======
def run_flask():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask).start()
bot.infinity_polling()
