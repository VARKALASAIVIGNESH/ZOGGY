from flask import Flask, request, jsonify, render_template, redirect, url_for
import json
import os
import uuid
import logging
import requests
import re

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your_secret_key'

ORDERS_FILE = "orders.json"
GEMINI_API_KEY = "AIzaSyBB8j1Q8D8fwaft3U9GVGSX0lDWCRXz8iQ"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

# Ensure orders file exists
if not os.path.exists(ORDERS_FILE):
    with open(ORDERS_FILE, "w") as f:
        json.dump({}, f)

def load_json(filename):
    try:
        if os.path.exists(filename) and os.stat(filename).st_size > 0:
            with open(filename, "r") as f:
                return json.load(f)
        return {}
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_json(filename, data):
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=4)
        logger.debug(f"Saved data to {filename}: {data}")
    except Exception as e:
        logger.error(f"Failed to save to {filename}: {str(e)}")

def initialize_order(user_id):
    orders = load_json(ORDERS_FILE)
    if user_id not in orders:
        orders[user_id] = {
            "name": "",
            "phone": "",
            "address": "",
            "category": "",
            "order": "",
            "restaurant": "",
            "mart": "",
            "store": "",
            "extras": "",
            "payment": "",
            "expected_delivery_time": "30-45 minutes",
            "status": "Pending"
        }
        save_json(ORDERS_FILE, orders)
        logger.debug(f"Initialized order for user_id {user_id}: {orders[user_id]}")
    return orders[user_id]

def get_delivery_response(user_input, user_id):
    orders = load_json(ORDERS_FILE)
    current_state = orders.get(user_id, {})
    logger.debug(f"Starting get_delivery_response with state for {user_id}: {current_state}")

    # Check order status if requested
    if "where is my order" in user_input.lower():
        if not current_state.get("phone") or not current_state.get("name"):
            return "I need your name and phone number to check your order. What’s your name?"
        user_orders = [order for order in orders.values() if order.get("phone") == current_state["phone"] and order.get("name") == current_state["name"]]
        if user_orders:
            latest_order = user_orders[-1]
            order_status = latest_order.get("status", "Pending")
            if order_status == "Delivered":
                return f"🎉 Hurray, {current_state['name']}! Your order **{latest_order['order']}** has been delivered. Enjoy!"
            return f"Hi {current_state['name']}! Your latest order ({latest_order['order']}) is currently **'{order_status}'**."
        return f"Hi {current_state['name']}! I couldn’t find any orders linked to your name and number. Want to place a new one?"

    # Define required fields
    required_fields = ["name", "phone", "address", "order"]
    source_field = {
        "food": "restaurant",
        "groceries": "mart",
        "medicine": "store"
    }.get(current_state.get("category", ""), None)
    if source_field:
        required_fields.append(source_field)

    # Check if all required fields are filled
    if all(current_state.get(field) for field in required_fields):
        logger.debug(f"All required fields filled for {user_id}: {current_state}")
        if not current_state.get("payment"):
            return f"Order looks good, {current_state['name']}! How would you like to pay?"
        orders[user_id]["status"] = "Confirmed"
        save_json(ORDERS_FILE, orders)
        source_value = current_state[source_field] if source_field else "a nearby place"
        return (
            f"All set, {current_state['name']}! Your order for {current_state['order']} "
            f"from {source_value} to {current_state['address']} is confirmed. "
            f"Payment is {current_state['payment'] or 'cash on delivery'}. "
            "It’ll be there in 30-45 minutes!"
        )

    # Prompt with explicit checks
    prompt = (
        f"You’re a friendly delivery assistant. The user said: '{user_input}'. "
        f"Current order details: {json.dumps(current_state)}. "
        "Ask for missing details one at a time in this exact order: name, phone, address, category, order, "
        "source (restaurant for food, mart for groceries, store for medicine), extras (for food only), payment. "
        "Follow these rules strictly:\n"
        "- If 'name' is blank, ask 'Hi! What’s your name?' and stop.\n"
        "- If 'name' is filled but 'phone' is blank, ask 'Hi {current_state['name']}! What’s your phone number?' and stop.\n"
        "- If 'phone' is filled but 'address' is blank, ask 'Hi {current_state['name']}! What’s your address?' and stop.\n"
        "- If 'address' is filled but 'category' is blank, ask 'Hi {current_state['name']}! What would you like to order: food, groceries, or medicine?' and stop.\n"
        "- If 'category' is 'food' and 'order' is blank, ask 'Hi {current_state['name']}! What food would you like to order?' and stop.\n"
        "- If 'category' is 'food' and 'order' is filled but 'restaurant' is blank, ask 'Hi {current_state['name']}! Which restaurant would you like it from?' and stop.\n"
        "- If 'category' is 'food' and 'restaurant' is filled but 'extras' is blank, ask 'Hi {current_state['name']}! Any extras like drinks or dessert?' and stop.\n"
        "- If 'category' is 'groceries' and 'order' is blank, ask 'Hi {current_state['name']}! What groceries would you like to order?' and stop.\n"
        "- If 'category' is 'groceries' and 'order' is filled but 'mart' is blank, ask 'Hi {current_state['name']}! Which mart would you like it from?' and stop.\n"
        "- If 'category' is 'medicine' and 'order' is blank, ask 'Hi {current_state['name']}! What medicine would you like to order?' and stop.\n"
        "- If 'category' is 'medicine' and 'order' is filled but 'store' is blank, ask 'Hi {current_state['name']}! Which store would you like it from?' and stop.\n"
        "- If the user complains about repeating (e.g., 'I said already' or 'what man'), say 'Sorry about that, {current_state['name'] or ''}! I’ve got it now.' and move to the next blank field.\n"
        "Do NOT ask for a field if it’s already filled in the state. Keep it conversational and stop after asking one question."
    )

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 150, "temperature": 0.7}
    }

    try:
        response = requests.post(GEMINI_API_URL, json=data, headers={"Content-Type": "application/json"})
        if response.status_code == 200:
            response_json = response.json()
            reply = response_json.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "Sorry, I didn’t get that.")
            logger.debug(f"Gemini response for {user_id}: {reply}")
            return reply
        else:
            logger.error(f"API Error: {response.status_code} - {response.text}")
            return f"Error: API returned {response.status_code} - {response.text}"
    except Exception as e:
        logger.error(f"Error calling Gemini API: {str(e)}")
        return f"Error calling Gemini API: {str(e)}"

def extract_details_with_gemini(user_input, user_id):
    orders = load_json(ORDERS_FILE)
    current_state = orders.get(user_id, {})
    
    prompt = (
        f"Extract delivery order details from this user input: '{user_input}'. "
        f"Current order details: {json.dumps(current_state)}. "
        "Return the extracted details as valid JSON with these fields: name, phone, address, category, order, "
        "restaurant, mart, store, extras, payment. Leave fields blank if not provided in the input. "
        "Do NOT overwrite existing details unless the input explicitly changes them. Merge new details with existing ones. "
        "Important: 'category' is the type of order (food, groceries, medicine), and 'order' is the specific item (e.g., 'chicken biryani'). "
        "If the input specifies an item (e.g., 'chicken biryani'), set it as 'order', not 'category'. "
        "Ensure the response is valid JSON like {{\"name\": \"example\", \"order\": \"chicken biryani\"}}."
    )

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 150, "temperature": 0.3}
    }

    try:
        response = requests.post(GEMINI_API_URL, json=data, headers={"Content-Type": "application/json"})
        if response.status_code == 200:
            response_json = response.json()
            extracted_text = response_json.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
            logger.debug(f"Raw Gemini extraction for '{user_input}': {extracted_text}")
            cleaned_text = re.sub(r'```json|```', '', extracted_text).strip()
            logger.debug(f"Cleaned extraction: {cleaned_text}")
            extracted_data = json.loads(cleaned_text)
            for key, value in extracted_data.items():
                if value and not current_state.get(key):  # Only update if field is blank
                    current_state[key] = value
                elif key == "order" and value:  # Always update 'order' if specified
                    current_state[key] = value
            orders[user_id] = current_state
            save_json(ORDERS_FILE, orders)
            logger.debug(f"Updated order for {user_id}: {current_state}")
        else:
            logger.error(f"Extraction Error: API returned {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Extraction Error: {str(e)}")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()

    # Get or set user_id from the request
    user_id = data.get("user_id")
    if not user_id:
        user_id = str(uuid.uuid4())
        initialize_order(user_id)
        logger.debug(f"New user_id assigned: {user_id}")

    extract_details_with_gemini(user_message, user_id)
    chatbot_response = get_delivery_response(user_message, user_id)

    logger.debug(f"Chat response for user {user_id}: {chatbot_response}")
    return jsonify({"response": chatbot_response, "user_id": user_id})

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/admin", methods=["GET"])
def admin():
    orders = load_json(ORDERS_FILE)
    return render_template("admin.html", orders=orders)

@app.route("/update_order_status/<order_id>", methods=["POST"])
def update_order_status(order_id):
    orders = load_json(ORDERS_FILE)
    if order_id in orders:
        new_status = request.form.get("status")
        orders[order_id]["status"] = new_status
        save_json(ORDERS_FILE, orders)
        return redirect(url_for('admin'))
    return "Order not found", 404

if __name__ == "__main__":
    app.run(debug=True)