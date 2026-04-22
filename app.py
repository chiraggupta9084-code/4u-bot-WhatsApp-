from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

# Config
VERIFY_TOKEN = "4ufashion_bot_2026"
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
API_URL = "https://graph.facebook.com/v19.0"

# Phone number IDs
FASHION_PHONE_ID = "1045539971979577"
GROCERY_PHONE_ID = "1120135307844620"

# In-memory order state tracker
order_states = {}

# ─────────────────────────────────────────
# SEND MESSAGE HELPER
# ─────────────────────────────────────────
def send_message(phone_number_id, to_number, text):
    url = f"{API_URL}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }
    response = requests.post(url, headers=headers, json=payload)
    print(f"Send to {to_number}: {response.status_code} {response.text}")
    return response.json()

# ─────────────────────────────────────────
# WEBHOOK VERIFICATION
# ─────────────────────────────────────────
@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified!")
        return challenge, 200
    return "Forbidden", 403

# ─────────────────────────────────────────
# INCOMING MESSAGE HANDLER
# ─────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("Incoming:", data)

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                phone_number_id = value.get("metadata", {}).get("phone_number_id")
                messages = value.get("messages", [])

                for message in messages:
                    if message.get("type") != "text":
                        continue
                    from_number = message["from"]
                    msg_text = message["text"]["body"].strip()

                    if phone_number_id == FASHION_PHONE_ID:
                        handle_fashion(phone_number_id, from_number, msg_text)
                    elif phone_number_id == GROCERY_PHONE_ID:
                        handle_grocery(phone_number_id, from_number, msg_text)

    except Exception as e:
        print(f"Error: {e}")

    return jsonify({"status": "ok"}), 200

# ─────────────────────────────────────────
# 4U FASHION BOT
# ─────────────────────────────────────────
def handle_fashion(phone_id, from_number, msg_text):
    state = order_states.get(from_number, {"step": 0, "data": {}})
    step = state["step"]
    msg_lower = msg_text.lower()

    greeting_keywords = ["hi", "hello", "hlo", "hey", "order", "buy", "interested", "price", "kurta", "suit"]

    if step == 0 or any(w in msg_lower for w in greeting_keywords):
        reply = (
            "Namaste! 🙏 Welcome to *4U Fashion* 👗\n\n"
            "We have beautiful *Chikankari Kurta Sets* in:\n"
            "🟡 Olive Green\n"
            "🤍 Cream\n"
            "🟤 Brown\n"
            "💚 Mint Green\n\n"
            "*Price: ₹1,799 only* (Kurta + Dupatta + Pants)\n\n"
            "To place your order, please share:\n"
            "1️⃣ Your *full name*\n"
            "2️⃣ *Complete address* with pincode\n"
            "3️⃣ *Colour* you want\n"
            "4️⃣ *Size* (S / M / L / XL / XXL)"
        )
        order_states[from_number] = {"step": 1, "data": {}}
        send_message(phone_id, from_number, reply)

    elif step == 1:
        order_states[from_number] = {"step": 2, "data": {"details": msg_text}}
        reply = (
            "✅ *Order Received!* 🎉\n\n"
            f"📝 Details noted:\n_{msg_text}_\n\n"
            "👗 Product: Chikankari Kurta Set\n"
            "💰 Price: ₹1,799\n"
            "🚚 Dispatch: 2-3 business days\n\n"
            "Our team will confirm your order shortly.\n"
            "For queries call: *9853547098*\n\n"
            "Thank you for shopping with *4U Fashion*! 💕"
        )
        send_message(phone_id, from_number, reply)
        order_states[from_number] = {"step": 0, "data": {}}

    else:
        reply = (
            "Thank you for contacting *4U Fashion*! 😊\n"
            "For any queries, call us: *9853547098*\n\n"
            "Type *hi* to place a new order 👗"
        )
        send_message(phone_id, from_number, reply)
        order_states[from_number] = {"step": 0, "data": {}}

# ─────────────────────────────────────────
# 4U GROCERY BOT
# ─────────────────────────────────────────
def handle_grocery(phone_id, from_number, msg_text):
    state = order_states.get(f"g_{from_number}", {"step": 0, "data": {}})
    step = state["step"]
    msg_lower = msg_text.lower()

    greeting_keywords = ["hi", "hello", "hlo", "hey", "order", "buy", "grocery", "sabzi", "vegetables"]

    if step == 0 or any(w in msg_lower for w in greeting_keywords):
        reply = (
            "Namaste! 🙏 Welcome to *4U Grocery* 🛒\n\n"
            "We deliver fresh groceries right to your door!\n\n"
            "To place your order, please share:\n"
            "1️⃣ Your *full name*\n"
            "2️⃣ *Complete address* with pincode\n"
            "3️⃣ *Items you need* (with quantity)\n\n"
            "We'll confirm availability & price shortly! 😊"
        )
        order_states[f"g_{from_number}"] = {"step": 1, "data": {}}
        send_message(phone_id, from_number, reply)

    elif step == 1:
        order_states[f"g_{from_number}"] = {"step": 2, "data": {"details": msg_text}}
        reply = (
            "✅ *Order Received!* 🎉\n\n"
            f"📝 Your order:\n_{msg_text}_\n\n"
            "🛒 Our team will check availability and confirm the price.\n"
            "🚚 Delivery: Same day or next day\n\n"
            "For queries call: *9729119167*\n\n"
            "Thank you for choosing *4U Grocery*! 🥦🍅"
        )
        send_message(phone_id, from_number, reply)
        order_states[f"g_{from_number}"] = {"step": 0, "data": {}}

    else:
        reply = (
            "Thank you for contacting *4U Grocery*! 😊\n"
            "For queries call: *9729119167*\n\n"
            "Type *hi* to place a new order 🛒"
        )
        send_message(phone_id, from_number, reply)
        order_states[f"g_{from_number}"] = {"step": 0, "data": {}}

# ─────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────
@app.route("/", methods=["GET"])
def home():
    return "4U Bots Running 24/7 ✅", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
