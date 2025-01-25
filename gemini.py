import os
import uuid
import json
import threading
import base64
from io import BytesIO
from flask import Flask, request, jsonify
from PIL import Image
import google.generativeai as genai

app = Flask(__name__)

# File JSON và lock
JSON_FILE = "captcha_results.json"
lock = threading.Lock()

def load_data():
    if not os.path.exists(JSON_FILE):
        return {}
    with open(JSON_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(JSON_FILE, "w") as f:
        json.dump(data, f, indent=4)

def base64_to_image(base64_str):
    """Chuyển đổi base64 thành đối tượng ảnh."""
    try:
        # Loại bỏ phần header (ví dụ: "data:image/png;base64,")
        if "base64," in base64_str:
            base64_str = base64_str.split("base64,")[1]

        # Giải mã base64 thành dữ liệu nhị phân
        image_data = base64.b64decode(base64_str)

        # Tạo đối tượng ảnh từ dữ liệu nhị phân
        image = Image.open(BytesIO(image_data))
        return image
    except Exception as e:
        raise ValueError(f"Invalid base64 image: {str(e)}")

@app.route("/upload", methods=["POST"])
def upload_image():
    # Lấy dữ liệu từ body
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    # Lấy API key từ body
    api_key = data.get("api_key")
    if not api_key:
        return jsonify({"error": "Missing API key"}), 401

    # Lấy dữ liệu base64 từ body
    base64_image = data.get("image")
    if not base64_image:
        return jsonify({"error": "No image data provided"}), 400

    try:
        # Chuyển đổi base64 thành ảnh
        image = base64_to_image(base64_image)
        captcha_id = str(uuid.uuid4())

        # Lưu trạng thái vào file JSON
        with lock:
            data = load_data()
            data[captcha_id] = {"status": "processing", "result": None}
            save_data(data)

        # Xử lý ảnh trong background
        threading.Thread(
            target=process_image_with_gemini,
            args=(image, captcha_id, api_key),
        ).start()

        return jsonify({"captcha_id": captcha_id})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

def process_image_with_gemini(image, captcha_id, api_key):
    try:
        # Cấu hình API key trong luồng riêng
        genai.configure(api_key=api_key)
        
        # Sử dụng model mới
        model = genai.GenerativeModel("gemini-1.5-flash")  # Hoặc "gemini-1.5-pro"

        # Chuyển đổi ảnh thành định dạng phù hợp để gửi cho Gemini
        buffered = BytesIO()
        image.save(buffered, format="PNG")  # Lưu ảnh dưới dạng PNG
        image_data = buffered.getvalue()

        # Gửi ảnh đến Gemini API
        response = model.generate_content(["Extract text", {"mime_type": "image/png", "data": image_data}])

        # Cập nhật kết quả thành công
        with lock:
            data = load_data()
            if captcha_id in data:
                data[captcha_id]["status"] = "completed"
                data[captcha_id]["result"] = response.text
                save_data(data)
    except Exception as e:
        # Xử lý lỗi
        with lock:
            data = load_data()
            if captcha_id in data:
                data[captcha_id]["status"] = "error"
                data[captcha_id]["result"] = str(e)
                save_data(data)

@app.route("/result/<captcha_id>", methods=["GET"])
def get_result(captcha_id):
    with lock:
        data = load_data()
        result = data.get(captcha_id)
    
    if not result:
        return jsonify({"error": "Invalid Captcha ID"}), 404
    
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)