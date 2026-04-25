from flask import Flask, request, jsonify
import requests
import os
import json
import re
from collections import defaultdict, deque

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "4ubots_verify_token")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
API_URL = "https://graph.facebook.com/v19.0"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

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

# ─── 4U GROCERY (Gemini AI brain) ──────────────────
GROCERY_SYSTEM_PROMPT = """You are the friendly WhatsApp order-taking assistant for *4U Grocery*, a small kirana shop in Narnaul, Haryana (Near Hero Honda Chowk).

# Your job
Reply to incoming customer WhatsApp messages in warm, natural Hinglish (Hindi + English mix in Roman script). Help them place grocery orders, answer questions, and collect orders for the manager.

# Business details
- Store: 4U Grocery, Near Hero Honda Chowk, Narnaul, Haryana
- Delivery area: ONLY within Narnaul (no outside-Narnaul delivery)
- Delivery charges: FREE above ₹500, ₹30 below ₹500
- Payment: Cash on Delivery (COD) or UPI to 9729119167
- Manager phone: 9729119167
- Items: sugar, atta, dal, rice, oil, ghee, salt, masala (haldi/mirch/jeera), tea, coffee, biscuits, soap, shampoo, detergent, vegetables, fruits, dairy (milk/paneer/curd/butter), eggs, bread, namkeen, maggi — basically all everyday grocery items.
- Pricing: DON'T quote made-up prices. Say "manager confirm karenge with exact rate" or ask for brand/quantity.

# Brand voice
- Warm, polite, friendly — like a local kirana shop
- Hinglish (mix Hindi + English), respectful (aap, ji)
- Use 🙏 😊 🛒 🚚 emojis sparingly
- Use *bold* (WhatsApp markdown) for prices/totals
- Keep replies SHORT — 2-5 lines max. Conversational, not formal.

# Conversation handling
- Greeting (hi/hello/namaste) → Welcome warmly, ask what they need
- Item inquiry → Confirm available, ask quantity/brand if needed
- Price question → Ask brand/qty, OR say manager will quote shortly
- Delivery question → "FREE above ₹500, ₹30 below. Same-day in Narnaul."
- Address only (no items) → Ask what they want to order
- Items only (no address) → Ask for full name + address in Narnaul
- Items + address shared → Confirm warmly, set order_complete=true

# Order completion (CRITICAL)
Set "order_complete": true ONLY when the customer has shared BOTH in this conversation:
1. Specific items they want (with at least an approximate quantity), AND
2. A delivery address (any text mentioning a Narnaul location, ward, mohalla, near landmark, pincode 6 digits, etc.)

Then write order_summary as clean text for the manager:
- Customer name (if shared)
- Items + quantities (one per line with bullet •)
- Full delivery address

Otherwise order_complete=false and order_summary="".

# What NOT to do
- Don't quote made-up prices
- Don't promise delivery outside Narnaul
- Don't be pushy or salesy
- Don't reply in pure English — always mix Hindi
- Don't write paragraphs — be brief, conversational"""

# In-memory conversation history per phone number
# Lost on Render restart — acceptable for low-volume kirana bot
GROCERY_HISTORY = defaultdict(lambda: deque(maxlen=12))

def gemini_grocery_reply(from_number, text):
    """Call Gemini to generate a reply. Returns (reply_text, order_complete, order_summary)."""
    if not GEMINI_API_KEY:
        return ("Namaste! 🙏 Welcome to 4U Grocery. Bataiye kya chahiye?\n📞 9729119167", False, "")

    history = GROCERY_HISTORY[from_number]
    history.append({"role": "user", "parts": [{"text": text}]})

    payload = {
        "contents": list(history),
        "systemInstruction": {"parts": [{"text": GROCERY_SYSTEM_PROMPT}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "reply": {"type": "string"},
                    "order_complete": {"type": "boolean"},
                    "order_summary": {"type": "string"},
                },
                "required": ["reply", "order_complete", "order_summary"],
            },
            "temperature": 0.6,
            "maxOutputTokens": 800,
        },
    }

    try:
        r = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=payload,
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        text_out = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text_out)
        reply = parsed.get("reply", "").strip()
        order_complete = bool(parsed.get("order_complete", False))
        order_summary = (parsed.get("order_summary") or "").strip()

        # Save assistant turn
        history.append({"role": "model", "parts": [{"text": reply}]})

        return (reply, order_complete, order_summary)
    except Exception as e:
        print(f"Gemini API error: {e}")
        return ("Namaste! 🙏 Thoda technical issue hai, ek minute me reply karte hain. Aap apna order share kar dijiye 😊\n📞 9729119167", False, "")


def handle_grocery(phone_id, from_number, text):
    reply, order_complete, order_summary = gemini_grocery_reply(from_number, text)
    send_message(phone_id, from_number, reply)

    if order_complete and order_summary:
        send_message(phone_id, GROCERY_MANAGER_NUMBER,
            "🛒 *NEW GROCERY ORDER!*\n\n"
            f"📱 From: +{from_number}\n\n"
            f"{order_summary}\n\n"
            "➡️ Confirm karo with total amount + dispatch."
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
