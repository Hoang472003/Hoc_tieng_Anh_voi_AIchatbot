from langchain_google_genai import ChatGoogleGenerativeAI
from prompt import BASE_ROLE_PROMPT, PROMPTS, CHATBOT_PROMPT
from dotenv import load_dotenv
from flask import Flask, render_template, send_file, jsonify, request
from flask_cors import CORS
import os
import json
from struc_lesson import *
import re
from save_mysql import *
import speech_recognition as sr
from gtts import gTTS
import sounddevice as sd
import scipy.io.wavfile as wav
import pygame
from config_py import startup

load_dotenv()

app = Flask(__name__)
CORS(app)


class EnglishTeachingAgent:
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.llm = ChatGoogleGenerativeAI(
            api_key=api_key,
            model=model,
            temperature=1
        )

    def generate(self, task: str, **kwargs) -> dict:
        if task not in PROMPTS:
            raise ValueError(f"Nhiệm vụ {task} chưa được định nghĩa trong PROMPTS")

        full_prompt = BASE_ROLE_PROMPT + "\n\n" + PROMPTS[task].format(**kwargs)
        response = self.llm.invoke(full_prompt)

        try:
            result_json = json.loads(response.content)
        except json.JSONDecodeError:
            result_json = {"content": response.content}

        return result_json

API_KEY = os.getenv("GEMINI_API_KEY")
agent = EnglishTeachingAgent(api_key=API_KEY)

# Trang đăng nhập
@app.route('/')
def index():
    return render_template("login.html")

# Trang chủ
@app.route('/home')
def index_page():
    return render_template("index.html")

# Trang voice
@app.route('/voice')
def voice_page():
    return render_template("voice.html")

# Trang bài học
@app.route('/lesson')
def lesson_page():
    return render_template("lesson.html")

# TrangAI  chatbot
@app.route('/chatbot')
def chatbot_page():
    return render_template("chatbot.html")

#//////////////////////////// ADMIN ////////////////////////////////////////////////////
# Trang admin quản lý user
@app.route('/ad_user')
def ad_user():
    return render_template("ad_user.html")

# Trang admin quản lý lesson
@app.route('/ad_lesson')
def ad_lesson():
    return render_template("ad_lesson.html")

# Trang admin quản lý query
@app.route('/ad_query')
def ad_query():
    return render_template("ad_query.html")


        
#//////////////////////////////// AI CHATBOT DẠY HỌC ////////////////////////////////////////////////////

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    student_input = data.get("message", "")
    id_user = data.get("id_user")

    if not id_user or not student_input:
        return jsonify({"error": "Thiếu id_user hoặc message"}), 400

    # 🧠 Lấy lịch sử chat 5 câu gần nhất
    history = get_chat_history(id_user, limit=5)
    context = ""
    for role, msg in history:
        if role == "user":
            context += f"Người học: {msg}\n"
        else:
            context += f"AI: {msg}\n"

    # Tạo prompt gửi AI
    chat_prompt = f"""
{CHATBOT_PROMPT}

Dưới đây là lịch sử hội thoại gần đây:
{context}

Người học nói: {student_input}
"""

    # Gọi AI
    response = agent.llm.invoke(chat_prompt)
    content = response.content.strip()

    # Loại bỏ các ký tự code block nếu AI trả về
    cleaned = re.sub(r"```json\s*|\s*```|\*+", "", content).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Nếu JSON lỗi, gói nguyên content vào response_english
        parsed = {"response_english": cleaned, "explanation_vietnamese": "", "correction": ""}

    result = {
        "response_english": parsed.get("response_english") or "",
        "explanation_vietnamese": parsed.get("explanation_vietnamese") or "",
        "correction": parsed.get("correction") or ""
    }

    # Chuyển newline thành <br> để hiển thị đúng trên HTML
    for key in ["response_english", "explanation_vietnamese"]:
        if result[key]:
            result[key] = result[key].replace("\n", "<br>")

    # Lưu cả 2 tin nhắn vào DB
    save_message(id_user, "user", student_input)
    save_message(id_user, "assistant", content)

    return jsonify(result)


# API đăng nhập
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"status": "error", "message": "Thiếu email hoặc mật khẩu!"}), 400

    connection = connect_to_mysql()
    if connection is None:
        return jsonify({"status": "error", "message": "Lỗi kết nối CSDL"}), 500

    try:
        cursor = connection.cursor(dictionary=True)
        sql = "SELECT * FROM users WHERE email = %s AND password = %s"
        cursor.execute(sql, (email, password))
        user = cursor.fetchone()

        if user:
            return jsonify({
                "status": "success",
                "message": "Đăng nhập thành công!",
                "redirect": "/home",
                "id_user": user["id"],       # 🔹 trả id_user
                "username": user["username"],# 🔹 trả username
                "role": user["role"]         # 🔹 trả role
            }), 200
        else:
            return jsonify({"status": "error", "message": "Sai email hoặc mật khẩu!"}), 401
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

#/////////////////////// Quyền ADMIN //////////////////////////////////
@app.route("/update_user", methods=["PUT"])
def api_update_user():
    """Cập nhật thông tin user"""
    data = request.get_json()
    user_id = data.get("id")
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")
    role = data.get("role")

    if not all([user_id, username, email, password, role]):
        return jsonify({"status": "error", "message": "Thiếu dữ liệu!"}), 400

    success = update_user(user_id, username, email, password, role)
    if success:
        return jsonify({"status": "success", "message": f"User {user_id} đã cập nhật thành công!"})
    else:
        return jsonify({"status": "error", "message": f"Không thể cập nhật user {user_id}!"}), 500


# ====== API delete user ======
@app.route("/delete_user/<int:user_id>", methods=["DELETE"])
def api_delete_user(user_id):
    success = delete_user(user_id)
    if success:
        print(f"🗑️ User {user_id} đã bị xóa!")
        return jsonify({"status": "success", "message": f"User {user_id} đã bị xóa!"})
    else:
        print(f"❌ Không tìm thấy user {user_id}!")
        return jsonify({"status": "error", "message": f"Không tìm thấy user {user_id}!"}), 404

# ====== API get all users ======
@app.route("/get_all/users", methods=["GET"])
def api_get_users():
    users = show_all_users()
    return jsonify(users), 200

# ====== API add new user (admin) ======
@app.route("/add/users", methods=["POST"])
def api_add_user():
    data = request.get_json()
    username = data.get("username")   # 🔹 sửa "name" -> "username"
    email = data.get("email")
    password = data.get("password")
    role = data.get("role", "user")

    success, msg = admin_insert_user(username, email, password, role)
    status = "success" if success else "error"
    print(f"➕ Thêm user: {msg}🤡")
    return jsonify({"status": status, "message": msg}), (200 if success else 400)

# API nhận query
@app.route("/run_query", methods=["POST"])
def run_query():
    data = request.get_json()
    sql_query = data.get("query", "").strip()

    if not sql_query:
        return jsonify({"status": "error", "result": "❌ Vui lòng nhập lệnh SQL!"}), 400

    connection = connect_to_mysql()
    if connection is None:
        return jsonify({"status": "error", "result": "❌ Không kết nối được MySQL!"}), 500

    try:
        cursor = connection.cursor()
        cursor.execute(sql_query)

        if sql_query.lower().startswith("select"):
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = [dict(zip(columns, row)) for row in rows]
        else:
            connection.commit()
            result = f"✅ Query thành công! {cursor.rowcount} hàng bị ảnh hưởng."

        return jsonify({"status": "success", "result": result})
    except Error as e:
        return jsonify({"status": "error", "result": f"❌ Lỗi khi thực hiện query: {e}"})
    finally:
        cursor.close()
        connection.close() 

@app.route("/show_all", methods=["GET"])
def api_show_all():
    """API trả về toàn bộ dữ liệu database dưới dạng JSON"""
    data = get_all_tables_data()
    return jsonify({"status": "success", "result": data})


#///////////////////////////////////////////////////////////////////////////////
if __name__ == "__main__":
    startup()
    app.run(debug=False, port=5000, host="0.0.0.0")