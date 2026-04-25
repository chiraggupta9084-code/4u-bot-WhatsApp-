from flask import Flask, request, jsonify
import requests
import os
import json
import re
import io
import urllib.parse
from collections import defaultdict, deque

import qrcode

from catalog import search_catalog, format_item_for_ai

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "4ubots_verify_token")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
API_URL = "https://graph.facebook.com/v19.0"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

GROCERY_UPI_ID = "paytm.s1a4w0w@pty"
GROCERY_UPI_NAME = "4U Grocery"

FASHION_PHONE_ID = "1045539971979577"
GROCERY_PHONE_ID = "1120135307844620"
GROCERY_MANAGER_NUMBER = "919729119167"

GROCERY_FLOW_ID = os.environ.get("GROCERY_FLOW_ID", "")
FASHION_FLOW_ID = os.environ.get("FASHION_FLOW_ID", "")

# ─── QR + UPI HELPERS ──────────────────────────────
def upi_link(amount: float) -> str:
    """Build a tappable upi:// deep link with amount auto-filled."""
    params = {
        "pa": GROCERY_UPI_ID,
        "pn": GROCERY_UPI_NAME,
        "am": f"{amount:.2f}",
        "cu": "INR",
    }
    return "upi://pay?" + urllib.parse.urlencode(params)


def generate_qr_png(amount: float) -> bytes:
    """Generate a UPI QR PNG with the order amount baked in."""
    img = qrcode.make(upi_link(amount))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def upload_media(phone_id: str, png_bytes: bytes) -> str | None:
    """Upload a PNG to WhatsApp Cloud, return media_id."""
    url = f"{API_URL}/{phone_id}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    files = {
        "file": ("upi_qr.png", png_bytes, "image/png"),
        "messaging_product": (None, "whatsapp"),
        "type": (None, "image/png"),
    }
    r = requests.post(url, headers=headers, files=files, timeout=20)
    print(f"Media upload: {r.status_code} {r.text[:200]}")
    return r.json().get("id") if r.ok else None


def send_image(phone_id: str, to: str, media_id: str, caption: str = "") -> dict:
    """Send a previously-uploaded image by media_id."""
    url = f"{API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"id": media_id, "caption": caption},
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    print(f"Image sent to {to}: {r.status_code}")
    return r.json()


def send_payment_qr(phone_id: str, to: str, amount: float):
    """Send the UPI deep link as text + a fresh QR image with the amount."""
    link = upi_link(amount)
    send_message(phone_id, to,
        f"💳 *Pay ₹{amount:.0f} via UPI*\n\n"
        f"Tap to pay 👇\n{link}\n\n"
        f"Or scan the QR below 📷\n"
        f"UPI ID: `{GROCERY_UPI_ID}`\n"
        f"Name: {GROCERY_UPI_NAME}"
    )
    png = generate_qr_png(amount)
    media_id = upload_media(phone_id, png)
    if media_id:
        send_image(phone_id, to, media_id,
            caption=f"Scan to pay ₹{amount:.0f} — 4U Grocery")


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
GROCERY_SYSTEM_PROMPT = """You are the friendly WhatsApp order-taking assistant for *4U Grocery*, a kirana shop in Narnaul, Haryana (Near Hero Honda Chowk).

# Your job
Reply in warm Hinglish (Hindi + English in Roman script). Help customers find items, suggest in-stock alternatives, take orders.

# Business details
- Store: 4U Grocery, Near Hero Honda Chowk, Narnaul, Haryana
- Delivery: ONLY within Narnaul. FREE above ₹500, ₹30 below ₹500
- Payment: Cash on Delivery (COD) OR UPI (you'll send a payment link with order amount auto-filled)
- Manager phone: 9729119167

# How to use the CATALOG
You will be shown a `# CATALOG MATCHES` section containing items from our actual stock that match the customer's query. Each item shows: NAME | MRP | 4U price | discount % | stock status.

RULES:
- Quote ONLY prices from the catalog. NEVER invent a price.
- If item is OUT OF STOCK, suggest similar IN STOCK alternatives from the catalog.
- If customer asks for a brand we don't carry, suggest the closest brand we DO carry from catalog.
- When showing prices to customer, format like: `~₹58~ *₹53* (8% OFF) 💰` — strikethrough MRP, bold 4U price, savings %.
- Multiple sizes? Show them as a short bullet list.
- Calculate totals from `4U price × quantity`. Be accurate — customer will pay this amount.

# Brand voice
- Warm, polite — like a friendly local kirana shop
- Hinglish, respectful (aap, ji)
- Sparingly use 🙏 😊 🛒 🚚 💰 emojis
- Replies SHORT (2-6 lines). Conversational, never formal.

# Conversation handling
- Greeting → warm welcome, ask what they need
- Item inquiry → check catalog, quote with MRP/4U/discount, ask qty
- Price question → quote from catalog if known
- Delivery question → "FREE above ₹500, ₹30 below. Same-day in Narnaul."
- Address only (no items) → ask what to order
- Items only (no address) → ask for full name + address
- Items + address shared → confirm warmly, set order_complete=true, calculate total_amount

# Order completion (CRITICAL)
Set `order_complete: true` ONLY when ALL three are present in conversation:
1. Specific item(s) with quantity from the catalog
2. Delivery address (any Narnaul location reference: ward, mohalla, near landmark, pincode)
3. (Customer name preferred but optional)

When order_complete=true:
- Set `total_amount` = sum of (4U price × quantity) for each item, PLUS ₹30 if subtotal < ₹500 (delivery fee), else 0.
- Write `order_summary` as a clean WhatsApp message for the manager containing: customer name (if known), items with qty + line totals, subtotal, delivery fee, GRAND TOTAL, full address. Use WhatsApp markdown (*bold*).

When order_complete=false: set total_amount=0 and order_summary="".

# What NOT to do
- Never quote made-up prices — only catalog prices
- Don't promise delivery outside Narnaul
- Don't be pushy
- Don't reply in pure English or pure Hindi — keep Hinglish flavor
- Don't write paragraphs — be brief"""

# In-memory conversation history per phone number
# Lost on Render restart — acceptable for low-volume kirana bot
GROCERY_HISTORY = defaultdict(lambda: deque(maxlen=12))

def _build_catalog_context(query: str) -> str:
    """Search catalog and format matches as a system context block."""
    matches = search_catalog(query, limit=20)
    if not matches:
        return "# CATALOG MATCHES\n(no matches in catalog for this query — ask customer to clarify the item)"
    lines = "\n".join(format_item_for_ai(m) for m in matches)
    return f"# CATALOG MATCHES\n{lines}"


def gemini_grocery_reply(from_number, text):
    """Returns (reply_text, order_complete, order_summary, total_amount)."""
    if not GEMINI_API_KEY:
        return ("Namaste! 🙏 Welcome to 4U Grocery. Bataiye kya chahiye?\n📞 9729119167", False, "", 0.0)

    history = GROCERY_HISTORY[from_number]
    history.append({"role": "user", "parts": [{"text": text}]})

    catalog_block = _build_catalog_context(text)
    system_text = GROCERY_SYSTEM_PROMPT + "\n\n" + catalog_block

    payload = {
        "contents": list(history),
        "systemInstruction": {"parts": [{"text": system_text}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "reply": {"type": "string"},
                    "order_complete": {"type": "boolean"},
                    "order_summary": {"type": "string"},
                    "total_amount": {"type": "number"},
                },
                "required": ["reply", "order_complete", "order_summary", "total_amount"],
            },
            "temperature": 0.5,
            "maxOutputTokens": 1000,
        },
    }

    try:
        r = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=payload,
            timeout=25,
        )
        r.raise_for_status()
        data = r.json()
        text_out = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text_out)
        reply = parsed.get("reply", "").strip()
        order_complete = bool(parsed.get("order_complete", False))
        order_summary = (parsed.get("order_summary") or "").strip()
        total_amount = float(parsed.get("total_amount") or 0)

        history.append({"role": "model", "parts": [{"text": reply}]})

        return (reply, order_complete, order_summary, total_amount)
    except Exception as e:
        print(f"Gemini API error: {e}")
        return ("Namaste! 🙏 Thoda technical issue hai, ek minute me reply karte hain 😊\n📞 9729119167", False, "", 0.0)


def handle_grocery(phone_id, from_number, text):
    reply, order_complete, order_summary, total_amount = gemini_grocery_reply(from_number, text)
    send_message(phone_id, from_number, reply)

    if order_complete and order_summary:
        # Customer payment QR (only if amount known)
        if total_amount > 0:
            send_payment_qr(phone_id, from_number, total_amount)

        # Manager alert
        send_message(phone_id, GROCERY_MANAGER_NUMBER,
            "🛒 *NEW GROCERY ORDER!*\n\n"
            f"📱 From: +{from_number}\n"
            f"💰 Total: ₹{total_amount:.0f}\n\n"
            f"{order_summary}\n\n"
            "➡️ Confirm + dispatch."
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
