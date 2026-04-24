from flask import Flask, request, jsonify
import requests
import os
import json
import re

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "4ubots_verify_token")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
API_URL = "https://graph.facebook.com/v19.0"

FASHION_PHONE_ID = "1045539971979577"
GROCERY_PHONE_ID = "1120135307844620"
GROCERY_MANAGER_NUMBER = "919729119167"

GROCERY_FLOW_ID = os.environ.get("GROCERY_FLOW_ID", "")
FASHION_FLOW_ID = os.environ.get("FASHION_FLOW_ID", "")

# ─── SEND TEXT MESSAGE ─────────────────────────────
def send_message(phone_id, to, text):
    url = f"{API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    r = requests.post(url, headers=headers, json=payload)
    print(f"Message sent to {to}: {r.status_code}")
    return r.json()

# ─── SEND FLOW MESSAGE ─────────────────────────────
def send_flow(phone_id, to, flow_id, cta, header, body):
    url = f"{API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": header},
            "body": {"text": body},
            "footer": {"text": "Tap the button to start"},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_token": f"{to}_{phone_id}",
                    "flow_id": flow_id,
                    "flow_cta": cta,
                    "flow_action": "navigate",
                    "flow_action_payload": {"screen": "WELCOME"}
                }
            }
        }
    }
    r = requests.post(url, headers=headers, json=payload)
    print(f"Flow sent to {to}: {r.status_code} {r.text}")
    return r.json()

# ─── WEBHOOK VERIFICATION ──────────────────────────
@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified!")
        return challenge, 200
    return "Forbidden", 403

# ─── INCOMING MESSAGE HANDLER ──────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("Incoming:", json.dumps(data, indent=2))

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                phone_id = value.get("metadata", {}).get("phone_number_id")
                messages = value.get("messages", [])

                for message in messages:
                    from_number = message["from"]
                    msg_type = message.get("type")

                    # Flow completed by customer
                    if msg_type == "interactive":
                        interactive = message.get("interactive", {})
                        if interactive.get("type") == "nfm_reply":
                            handle_flow_response(phone_id, from_number, interactive)
                            continue

                    # Customer sent a text message
                    if msg_type == "text":
                        text_body = message.get("text", {}).get("body", "")
                        if phone_id == FASHION_PHONE_ID:
                            handle_fashion(phone_id, from_number)
                        elif phone_id == GROCERY_PHONE_ID:
                            handle_grocery(phone_id, from_number, text_body)

    except Exception as e:
        print(f"Error: {e}")

    return jsonify({"status": "ok"}), 200

# ─── 4U GROCERY ────────────────────────────────────
GROCERY_ITEMS = [
    "sugar", "cheeni", "shakkar", "milk", "doodh", "rice", "chawal",
    "atta", "flour", "maida", "dal", "moong", "chana", "rajma",
    "oil", "tel", "refined", "ghee", "salt", "namak", "tea", "chai",
    "coffee", "maggi", "biscuit", "parle", "soap", "shampoo", "detergent",
    "surf", "tide", "masala", "haldi", "mirch", "jeera", "dhaniya",
    "besan", "sooji", "rava", "poha", "namkeen", "bread", "egg", "anda",
    "butter", "paneer", "curd", "dahi", "onion", "pyaaz", "potato", "aalu",
    "tomato", "tamatar", "vegetable", "sabzi", "fruit", "phal", "namkeen",
]

ADDRESS_SIGNALS = [
    "house", "h.no", "street", "gali", "mohalla", "near", "behind",
    "opposite", "ward", "sector", "colony", "narnaul", "haryana",
    "village", "vpo", "tehsil",
]

def handle_grocery(phone_id, from_number, text):
    msg = (text or "").lower().strip()

    # Greeting → send Flow if configured, else welcome text
    if msg in ("hi", "hello", "hey", "start") or any(
        w in msg for w in ["namaste", "namaskar", "ram ram", "good morning", "good evening"]
    ):
        if GROCERY_FLOW_ID:
            send_flow(
                phone_id, from_number, GROCERY_FLOW_ID,
                "Order Now 🛒", "4U Grocery 🛒",
                "Fresh groceries delivered in Narnaul!\nTap below to place your order."
            )
            return
        send_message(phone_id, from_number,
            "Namaste! 🙏 Welcome to *4U Grocery* 🛒\n\n"
            "Fresh groceries delivered in Narnaul!\n"
            "📍 Near Hero Honda Chowk, Narnaul\n\n"
            "Bataiye kya chahiye? Sugar, atta, dal, oil, masala — sab available hai 😊\n\n"
            "📞 9729119167"
        )
        return

    # Location
    if any(w in msg for w in ["where are you", "kahan ho", "location", "shop", "store kahan", "address kya"]):
        send_message(phone_id, from_number,
            "📍 *4U Mall* — Near Hero Honda Chowk, Narnaul, Haryana\n\n"
            "🚚 Home delivery only within Narnaul\n"
            "📞 9729119167"
        )
        return

    # Delivery
    if any(w in msg for w in ["delivery", "deliver", "kab aayega", "shipping", "courier"]):
        send_message(phone_id, from_number,
            "🚚 *Delivery in Narnaul:*\n"
            "✅ FREE above ₹500\n"
            "📦 ₹30 below ₹500\n"
            "⏱️ Same-day delivery in most areas\n\n"
            "Apna address aur items batao! 😊"
        )
        return

    # Payment
    if any(w in msg for w in ["payment", "cod", "upi", "online pay", "cash"]):
        send_message(phone_id, from_number,
            "💵 *Payment Options:*\n"
            "💰 Cash on Delivery (COD)\n"
            "📲 UPI: 9729119167\n\n"
            "Order karne ke liye items aur address bhejiye! 😊"
        )
        return

    # Price inquiry (generic, no item)
    found_items = [i for i in GROCERY_ITEMS if i in msg]
    has_qty = bool(re.search(
        r"\d+\s*(kg|gm|g|litre|liter|ltr|l|ml|packet|pkt|piece|pc|dozen)\b", msg
    ))
    if any(w in msg for w in ["price", "rate", "kitna", "how much", "kitne ka"]) and not found_items:
        send_message(phone_id, from_number,
            "Aap kaunsa item lena chahte ho? 😊\n"
            "Item ka naam aur quantity batao, hum exact price bata denge!\n\n"
            "Example: Sugar 2kg, Atta 5kg, Dal 1kg"
        )
        return

    # Address detection
    has_address = (
        any(s in msg for s in ADDRESS_SIGNALS)
        or bool(re.search(r"\b\d{6}\b", msg))   # pincode
    )

    # Full order: items/qty + address → confirm + alert manager
    if has_address and (found_items or has_qty):
        send_message(phone_id, from_number,
            "✅ *Order Received!* 🛒\n\n"
            "Aapka order humein mil gaya hai. Manager 5-10 min me confirm karenge with total amount.\n\n"
            "🚚 Delivery: FREE above ₹500, ₹30 below\n"
            "💵 Payment: COD / UPI 9729119167\n\n"
            "Dhanyavaad! 🙏"
        )
        send_message(phone_id, GROCERY_MANAGER_NUMBER,
            "🛒 *NEW GROCERY ORDER!*\n\n"
            f"📱 From: +{from_number}\n"
            f"📝 Message:\n{text}\n\n"
            "➡️ Confirm karo with total amount + dispatch."
        )
        return

    # Items mentioned without address
    if found_items or has_qty:
        items_str = ", ".join(found_items) if found_items else "aapke items"
        send_message(phone_id, from_number,
            f"Ji haan! 😊 Ye available hai — *{items_str}*.\n\n"
            "Order confirm karne ke liye please bhejiye:\n"
            "1️⃣ Poora *naam*\n"
            "2️⃣ *Address* (Narnaul me)\n"
            "3️⃣ Items + quantity (e.g. Sugar 2kg, Atta 5kg)\n\n"
            "🚚 Free delivery above ₹500 | ₹30 below"
        )
        return

    # Default fallback
    send_message(phone_id, from_number,
        "Namaste! 🙏 *4U Grocery* — Narnaul\n\n"
        "Bataiye aapko kya chahiye? Sugar, atta, dal, oil, masala — sab available hai 😊\n\n"
        "📍 Near Hero Honda Chowk, Narnaul\n"
        "📞 9729119167"
    )

# ─── 4U FASHION ────────────────────────────────────
def handle_fashion(phone_id, from_number):
    if FASHION_FLOW_ID:
        send_flow(
            phone_id, from_number,
            FASHION_FLOW_ID,
            "Order Now 👗",
            "4U Fashion 👗",
            "Beautiful Chikankari Kurta Sets at ₹1,799!\nTap below to place your order."
        )
    else:
        send_message(phone_id, from_number,
            "Welcome to 4U Fashion! 👗\n"
            "Chikankari Kurta Sets at ₹1,799\n"
            "Call us: 9853547098"
        )

# ─── HANDLE COMPLETED FLOW ORDER ───────────────────
def handle_flow_response(phone_id, from_number, interactive):
    try:
        response_json = interactive.get("nfm_reply", {}).get("response_json", "{}")
        order = json.loads(response_json)

        name     = order.get("customer_name", "Customer")
        items    = order.get("quantities_note", order.get("items_list", "-"))
        address  = order.get("address", "-")
        slot     = order.get("delivery_slot", order.get("delivery_time", "-"))
        amount   = order.get("amount_paid", "-")
        utr      = order.get("utr_number", "-")
        recurring = order.get("recurring", "one_time")

        send_message(phone_id, from_number,
            f"✅ Order Confirmed! Thank you {name}!\n\n"
            f"🛒 Items: {items}\n"
            f"📍 Address: {address}\n"
            f"🕐 Slot: {slot}\n"
            f"💰 Amount Paid: Rs.{amount}\n"
            f"🔖 UTR: {utr}\n"
            f"🔁 Recurring: {recurring}\n\n"
            f"We will verify your payment and dispatch shortly!\n"
            f"For queries: 9729119167"
        )

        # If recurring order, note it
        if recurring != "one_time":
            send_message(phone_id, from_number,
                f"📅 Your recurring order ({recurring}) has been noted. "
                f"We will send you the order form automatically every time!"
            )

    except Exception as e:
        print(f"Flow response error: {e}")
        send_message(phone_id, from_number,
            "✅ Order received! Our team will contact you shortly.\n"
            "For queries: 9729119167"
        )

# ─── HEALTH CHECK ──────────────────────────────────
@app.route("/", methods=["GET"])
def home():
    return "4U Bots Running 24/7 ✅", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
