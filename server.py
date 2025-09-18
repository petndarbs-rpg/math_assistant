from flask import Flask, request, jsonify, render_template
import sqlite3
import os
import uuid
import re
from dotenv import load_dotenv
import google.generativeai as genai
from gtts import gTTS

# === API atslēga ===
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

app = Flask(__name__, static_folder="static", template_folder="templates")

# === DB inicializācija ===
def init_db():
    conn = sqlite3.connect("math_assistant.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS responses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            response TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
init_db()

@app.route("/")
def index():
    return render_template("index.html")

# =====================================================
# 1. Solis – ģenerē “pareizo atbildi”, bet neatklāj to bērnam
# =====================================================
@app.route("/get_correct_answer", methods=["POST"])
def get_correct_answer():
    data = request.get_json()
    question = data.get("question", "").strip().lower()
    if not question or len(question) < 2:
        return jsonify({"error": "Lūdzu, uzdod saprotamu jautājumu."}), 400

    answer = find_or_generate_answer(question)
    if not answer:
        answer = "Piedod, es nevarēju saprast jautājumu."
    # sūtām tikai ID, lai 2. solī varētu pārbaudīt
    session_id = str(uuid.uuid4())
    # saglabā pareizo atbildi pagaidu glabātuvē (vienkāršībai – atmiņā)
    correct_cache[session_id] = answer
    return jsonify({"session_id": session_id})

# =====================================================
# 2. Solis – pārbauda bērna atbildi
# =====================================================
@app.route("/check_answer", methods=["POST"])
def check_answer():
    data = request.get_json()
    session_id = data.get("session_id")
    user_answer = data.get("user_answer", "").strip().lower()

    if not session_id or session_id not in correct_cache:
        return jsonify({"error": "Sesija nav atrasta."}), 400

    correct = correct_cache.pop(session_id)  # izņem no keša
    # Vienkārša salīdzināšana (bez diakritikas var pielāgot)
    if user_answer and user_answer in correct.lower():
        return jsonify({"result": "Pareizi!", "correct_answer": correct})
    else:
        return jsonify({"result": "Nepareizi!", "correct_answer": correct})

# =====================================================
# Atbalsta funkcijas
# =====================================================
correct_cache = {}  # vienkāršs pagaidu kešs {session_id: correct_answer}

def find_or_generate_answer(question: str) -> str:
    # 1. Glosārijs
    glossary_resp = generate_local_response(question)
    if glossary_resp:
        return glossary_resp

    # 2. DB
    conn = sqlite3.connect("math_assistant.db")
    cur = conn.cursor()
    cur.execute("SELECT response FROM responses WHERE keyword = ?", (question,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row[0]

    # 3. Matemātiskais aprēķins
    math_resp = calculate_math(question)
    if math_resp:
        save_response(cur, conn, question, math_resp)
        return math_resp

    # 4. Gemini AI
    try:
        prompt = f"Izpaskaidro īsi un saprotami 6. klases skolēnam latviešu valodā: {question}"
        gemini_resp = model.generate_content(prompt)
        text = gemini_resp.text.strip()
        if not text or len(text.split()) < 3:
            text = "Piedod, es nevarēju saprast jautājumu."
        save_response(cur, conn, question, text)
        return text
    except Exception as e:
        return f"Kļūda AI: {str(e)}"

def save_response(cur, conn, question, resp):
    cur.execute("INSERT INTO responses(keyword, response) VALUES (?,?)", (question, resp))
    conn.commit()
    conn.close()

def calculate_math(text):
    text = text.replace(",", ".")
    safe_expr = re.sub(r"[^0-9\+\-\*/\.\(\) ]", "", text)
    if not safe_expr.strip():
        return None
    try:
        res = eval(safe_expr)
        return f"Rezultāts: {round(res,4)}"
    except:
        return None

def generate_local_response(q):
    glossary = {
        "cipars":"Cipars ir viens skaitlis no 0 līdz 9, piemēram, 3 vai 7.",
        "skaitlis":"Skaitlis parāda daudzumu vai secību, piemēram, 5 vai 10.",
        "summa":"Summa ir rezultāts, kad saskaita skaitļus kopā.",
        "reizinājums":"Reizinājums ir skaitļu reizināšanas rezultāts.",
        "dalījums":"Dalījums ir rezultāts, kad skaitlis tiek sadalīts vienādās daļās.",
        "saskaitīšana":"Saskaitīšana ir darbība, kad vairākus skaitļus liek kopā.",
        "atņemšana":"Atņemšana ir darbība, kad no viena skaitļa atņem otru.",
        "reizināšana":"Reizināšana ir darbība, kad skaitli pieskaita vairākas reizes.",
        "dalīšana":"Dalīšana ir darbība, kad skaitli sadala vienādās daļās.",
        "vienādība":"Vienādība nozīmē, ka divas lietas ir vienādas.",
        "nevienādība":"Nevienādība nozīmē, ka divas lietas nav vienādas."
    }
    for k,v in glossary.items():
        if k in q:
            return v
    return None

# =====================================================
# Balss sintezators
# =====================================================
@app.route("/sinteze", methods=["POST"])
def sinteze():
    try:
        data = request.get_json()
        text = data.get("text","").strip()
        if not text: return jsonify({"error":"Teksts ir tukšs"}),400
        filename = f"{uuid.uuid4()}.mp3"
        path = os.path.join("static","tts",filename)
        os.makedirs(os.path.dirname(path),exist_ok=True)
        gTTS(text=text,lang="lv").save(path)
        return jsonify({"audio_url": f"/static/tts/{filename}"})
    except Exception as e:
        return jsonify({"error": f"Kļūda: {str(e)}"}),500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
