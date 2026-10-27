import asyncio
import json
import os
import shutil
import html
import random
import re
import time
import traceback
from threading import Thread, Lock
from urllib.parse import quote
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

app = Flask(__name__)

data_lock = Lock()
BOT_APPLICATION = None
BOT_LOOP = None

# Render: attach a Persistent Disk at /var/data and set DATA_DIR=/var/data.
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_DIR, exist_ok=True)

def data_path(filename):
    target = os.path.join(DATA_DIR, filename)
    legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    if target != legacy and not os.path.exists(target) and os.path.isfile(legacy):
        try:
            shutil.copy2(legacy, target)
        except Exception as exc:
            print(f"Could not migrate {filename} to DATA_DIR: {exc}")
    return target

KEY_FILE = data_path("keys_stock.json")
USER_FILE = data_path("users_db.json")
ORDERS_FILE = data_path("pending_orders.json")
QR_EXPIRY_SECONDS = 300  # 5 Minutes

def load_pending_orders():
    if os.path.exists(ORDERS_FILE):
        try:
            with open(ORDERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_pending_orders(orders):
    try:
        with open(ORDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(orders, f, indent=4)
    except Exception as e:
        print(f"Error saving orders: {e}")

def get_pending_orders():
    return load_pending_orders()

def set_pending_orders(orders):
    save_pending_orders(orders)

def load_keys():
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    default_stock = {
    "phanthom_1_hour": ["PHTM-877F-00E5-3333"],
    "phanthom_3_hour": ["PHTM-877F-00E5-1111"],
    "phanthom_6_hour": ["PHTM-877F-00E5-2222"],
    "phanthom_12_hour": ["PHTM-877F-00E5-0000"],
    "phanthom_1_day": ["PHTM-877F-00E5-9999"],
    "phanthom_3_days": ["PHTM-877F-00E5-8080"],
    "phanthom_7_days": ["PHTM-877F-00E5-7749"],
    "phanthom_30_days": ["PHTM-877F-00E5-0067"],
    }
    save_keys(default_stock)
    return default_stock

def save_keys(stock_data):
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        json.dump(stock_data, f, indent=4)

def load_users():
    if os.path.exists(USER_FILE):
        try:
            with open(USER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_users(users_data):
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump(users_data, f, indent=4)

def get_user_balance(user_id):
    users = load_users()
    str_uid = str(user_id)
    if str_uid not in users:
        users[str_uid] = {"balance": 0.0, "purchases": 0, "history": []}
        save_users(users)
    return users[str_uid]["balance"]

def update_user_balance(user_id, amount, desc=""):
    with data_lock:
        users = load_users()
        str_uid = str(user_id)
        if str_uid not in users:
            users[str_uid] = {"balance": 0.0, "purchases": 0, "history": []}
        users[str_uid]["balance"] += amount
        if desc:
            if "history" not in users[str_uid]:
                users[str_uid]["history"] = []
            users[str_uid]["history"].append(desc)
        save_users(users)

def get_user_history(user_id):
    users = load_users()
    str_uid = str(user_id)
    if str_uid not in users or "history" not in users[str_uid]:
        return ["No transaction history yet."]
    return users[str_uid]["history"]

def get_key_from_stock(plan):
    with data_lock:
        stock = load_keys()
        if stock.get(plan) and len(stock[plan]) > 0:
            assigned_key = stock[plan].pop(0)
            save_keys(stock)
            return assigned_key
        return None

def get_product_price(prod, plan):
    if prod.lower() != "phanthom":
        return None
    prices = {
        "1_hour": 20.0, "3_hour": 50.0, "6_hour": 80.0, "12_hour": 100.0,
        "1_day": 150.0, "3_days": 300.0, "7_days": 600.0, "30_days": 2000.0,
    }
    return prices.get(plan)

@app.route("/")
def home():
    return "Momshad X Panel Bot Gateway is running!"

@app.route("/payment-webhook", methods=["POST", "GET"])
def payment_webhook():
    try:
        req_json = request.get_json(silent=True) or {}
        req_form = request.form.to_dict()
        req_args = request.args.to_dict()
        req_data = request.get_data(as_text=True)

        print("=== WEBHOOK RECEIVED ===")
        print(f"JSON: {req_json}")
        print(f"Form: {req_form}")
        print(f"Args: {req_args}")
        print(f"Raw Data: {req_data}")

        combined_text = f"{json.dumps(req_json)} {str(req_form)} {str(req_args)} {req_data}"

        matches = re.findall(r'\d+(?:\.\d+)?', combined_text)
        amounts_found = [float(m) for m in matches if float(m) > 0]

        target_user_id = None
        order_type = None
        matched_data = None
        matched_amount = 0.0
        current_time = time.time()

        with data_lock:
            pending_orders = get_pending_orders()
            expired_users = [uid for uid, info in pending_orders.items() if current_time > info["expiry"]]
            for eu in expired_users:
                del pending_orders[eu]

            print(f"Current Pending Orders: {pending_orders}")
            print(f"Amounts Extracted: {amounts_found}")

            for uid, order_info in list(pending_orders.items()):
                order_amt = order_info["amount"]
                for amt in amounts_found:
                    if abs(order_amt - amt) < 0.50:
                        target_user_id = int(uid)
                        order_type = order_info["type"]
                        matched_data = order_info
                        matched_amount = amt
                        del pending_orders[uid]
                        break
                if target_user_id:
                    break
            
            if not target_user_id and pending_orders:
                uid, order_info = list(pending_orders.items())[-1]
                target_user_id = int(uid)
                order_type = order_info["type"]
                matched_data = order_info
                matched_amount = amounts_found[0] if amounts_found else order_info["amount"]
                del pending_orders[uid]
                print(f"SMART AUTO-MATCHED PENDING ORDER FOR USER {uid}!")

            set_pending_orders(pending_orders)

        if target_user_id and order_type:
            print(f"MATCHED ORDER FOR USER {target_user_id}! Type: {order_type}")
            if order_type == "deposit":
                dep_amount = matched_data["dep_amount"]
                update_user_balance(target_user_id, dep_amount, f"Deposit Added: +₹{dep_amount:.2f}")
                if BOT_APPLICATION and BOT_LOOP:
                    asyncio.run_coroutine_threadsafe(
                        send_deposit_success(target_user_id, dep_amount),
                        BOT_LOOP
                    )
                return {"status": "success", "message": "Balance deposited successfully!"}, 200
            
            elif order_type == "product":
                plan = matched_data["plan"]
                prod = matched_data["prod"]
                order_id = matched_data.get("order_id", "ORD997673")
                assigned_key = get_key_from_stock(plan)
                
                update_user_balance(target_user_id, 0.0, f"Purchased {prod} ({plan}): Key {assigned_key}")
                if BOT_APPLICATION and BOT_LOOP:
                    asyncio.run_coroutine_threadsafe(
                        send_key_to_user(target_user_id, assigned_key, prod, plan, order_id, matched_amount),
                        BOT_LOOP
                    )
                return {"status": "success", "message": "Key delivered automatically!"}, 200
        else:
            print("NO PENDING ORDERS FOUND AT ALL.")
            return {"status": "not_found", "message": "No active pending order found.", "extracted_amounts": amounts_found}, 404
            
    except Exception as e:
        print(f"WEBHOOK ERROR: {str(e)}")
        traceback.print_exc()
        return {"status": "error", "message": str(e)}, 500

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8950060993:AAGdwk7vFPvzJIPQXo2S120fS3YtNuXk4DI").strip()
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "8380823727"))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "@Momshad_00")
FAMPAY_UPI = os.environ.get("FAMPAY_UPI", "islam-momshad.khan@fam").strip()
PAYMENT_WEBHOOK_SECRET = os.environ.get("PAYMENT_WEBHOOK_SECRET", "momshad_secret_123").strip()

async def check_qr_expiry_background(application):
    while True:
        await asyncio.sleep(10)
        current_time = time.time()
        expired_users = []
        with data_lock:
            pending_orders = get_pending_orders()
            for uid, info in list(pending_orders.items()):
                if current_time > info["expiry"]:
                    expired_users.append((uid, info))
                    del pending_orders[uid]
            set_pending_orders(pending_orders)
        
        for uid, info in expired_users:
            msg_id = info.get("msg_id")
            order_id = info.get("order_id", "ORDA61CE420A62C")
            expired_text = (
                "⏱️ <b>PAYMENT EXPIRED & INVALID</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔒 <b>Order ID:</b> <code>{order_id}</code>\n"
                "❌ <b>Not paid within 5 minutes.</b>\n"
                "🔒 <i>This QR code is now expired and invalid. No keys or balance will be credited.</i>\n\n"
                "Tap /start to begin a new order."
            )
            try:
                if msg_id:
                    await application.bot.edit_message_caption(
                        chat_id=int(uid),
                        message_id=int(msg_id),
                        caption=expired_text,
                        parse_mode="HTML"
                    )
                else:
                    await application.bot.send_message(chat_id=int(uid), text=expired_text, parse_mode="HTML")
            except Exception as e:
                print(f"Error expiring QR for user {uid}: {e}")

async def send_deposit_success(user_id, amount):
    try:
        msg = (
            "🎉 <b>DEPOSIT SUCCESSFUL & CREDITED!</b> 🎉\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Added to Wallet:</b> <code>₹{amount:.2f}</code>\n"
            f"💼 <b>Current Balance:</b> <code>₹{get_user_balance(user_id):.2f}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🚀 <i>You can now buy any panel instantly using your wallet balance with 1-click!</i>"
        )
        await BOT_APPLICATION.bot.send_message(chat_id=int(user_id), text=msg, parse_mode="HTML")
    except Exception as e:
        print(f"Error in send_deposit_success: {e}")
        traceback.print_exc()

async def send_admin_purchase_alert(user_id, username, full_name, prod, plan, panel_key, paid_amount, method, order_id):
    if not BOT_APPLICATION or not ADMIN_CHAT_ID:
        print("Admin purchase alert skipped: bot/admin configuration missing.")
        return
    safe_name = html.escape(full_name or "Unknown")
    safe_username = html.escape("@" + username if username else "Not set")
    safe_prod = html.escape(str(prod))
    safe_plan = html.escape(str(plan).replace("_", " ").title())
    safe_key = html.escape(str(panel_key))
    safe_method = html.escape(str(method))
    safe_order = html.escape(str(order_id))
    alert = (
        "🛒 <b>NEW PURCHASE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Name:</b> {safe_name}\n"
        f"🔗 <b>Username:</b> {safe_username}\n"
        f"🆔 <b>User ID:</b> <code>{int(user_id)}</code>\n"
        f"📦 <b>Product:</b> {safe_prod} ({safe_plan})\n"
        f"💵 <b>Paid:</b> ₹{float(paid_amount):.2f}\n"
        f"💳 <b>Payment:</b> {safe_method}\n"
        f"🧾 <b>Order:</b> <code>{safe_order}</code>\n"
        f"🔑 <b>Key:</b> <code>{safe_key}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    await BOT_APPLICATION.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=alert, parse_mode="HTML")

async def send_key_to_user(user_id, panel_key, prod, plan, order_id, paid_amount):
    try:
        if not panel_key:
            print(f"No stock key available for order {order_id}; key was not delivered.")
            return
        clean_plan = plan
        prefix = f"{prod.lower()}_"
        if clean_plan.lower().startswith(prefix):
            clean_plan = clean_plan[len(prefix):]
        plan_display = clean_plan.replace('_', ' ').title()
        success_msg = (
            "🎉 <b>PAYMENT SUCCESSFUL</b> 🎉\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Thank you for your purchase!</i>\n\n"
            "📋 <b>Order Details</b>\n"
            f"— 🆔 <b>ID:</b> <code>{order_id}</code>\n"
            f"— 📦 <b>Product:</b> {prod} ({plan_display})\n"
            f"— 🔢 <b>Quantity:</b> 1\n"
            f"— 💳 <b>Method:</b> 📲 UPI Payment\n"
            f"— 💵 <b>Paid:</b> ₹{paid_amount:.2f} INR\n\n"
            "🔑 <b>Your Key</b>\n"
            f"<code>{panel_key}</code>\n\n"
            "💡 <i>Tap the key above to copy. Enjoy your game!</i>"
        )
        await BOT_APPLICATION.bot.send_message(chat_id=int(user_id), text=success_msg, parse_mode="HTML")
        
        username, full_name = None, "Unknown"
        try:
            chat = await BOT_APPLICATION.bot.get_chat(int(user_id))
            username = getattr(chat, "username", None)
            full_name = getattr(chat, "full_name", None) or getattr(chat, "first_name", None) or "Unknown"
        except Exception as user_lookup_error:
            print(f"Could not fetch Telegram profile for {user_id}: {user_lookup_error}")
        await send_admin_purchase_alert(
            user_id, username, full_name, prod, clean_plan, panel_key,
            paid_amount, "UPI", order_id
        )
    except Exception as e:
        print(f"Error in send_key_to_user: {e}")
        traceback.print_exc()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = get_user_balance(user.id)
    
    keyboard = [
        [InlineKeyboardButton("🛍️ License Shop", callback_data="shop_menu")],
        [InlineKeyboardButton("💰 Deposit Balance", callback_data="deposit_menu"), InlineKeyboardButton("📊 All History", callback_data="history")],
        [InlineKeyboardButton("👤 Reseller Profile", callback_data="profile"), InlineKeyboardButton("👥 Referral", callback_data="referral")],
        [InlineKeyboardButton("🏷️ Buy at Low Price?", callback_data="low_price"), InlineKeyboardButton("🌐 Share Friends", callback_data="share")],
        [InlineKeyboardButton("🔓 UNLOCK VIP SELLER", callback_data="vip_seller"), InlineKeyboardButton("🆘 Help Line Support", callback_data="support")],
        [InlineKeyboardButton("📂 File Channel", url="https://t.me/File99channel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "⚡ <b>WELCOME TO MOMSHAD X PANEL STORE</b> ⚡\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👋 Hello <b>{user.first_name}</b>!\n\n"
        "👑 <b>License Manager Reseller Hub</b>\n"
        "🌐 <i>Your Business, Your Ultimate Growth!</i>\n\n"
        "💎 <b>Supported UPI:</b> PhonePe, GPay, Paytm, FamPay\n"
        "⚡ <b>Instant Auto-Add Balance & 1-Click Delivery</b>\n"
        f"🇮🇳 <b>FamPay UPI:</b> <code>{FAMPAY_UPI}</code>\n\n"
        f"💼 <b>Your Wallet Balance:</b> <code>₹{balance:.2f}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 <b>Owner / Support:</b> {ADMIN_USERNAME}"
    )
    
    if update.callback_query:
        try:
            await update.callback_query.message.delete()
        except:
            pass
        await context.bot.send_message(chat_id=user.id, text=welcome_text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="HTML")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    
    if data == "shop_menu":
        keyboard = [
            [InlineKeyboardButton("🔥 Phanthom Android + iOS", callback_data="prod_Phanthom")],
            [InlineKeyboardButton("« Back to Home", callback_data="home")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(
                "🛍️ <b>PREMIUM LICENSE SHOP</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select your desired cheat panel below:</i>",
                reply_markup=reply_markup, parse_mode="HTML"
            )
        except Exception:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(
                chat_id=user.id,
                text="🛍️ <b>PREMIUM LICENSE SHOP</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select your desired cheat panel below:</i>",
                reply_markup=reply_markup, parse_mode="HTML"
            )
        
    elif data == "home":
        await start(update, context)
        
    elif data.startswith("prod_"):
        prod_name = data.replace("prod_", "")
        if prod_name.lower() != "phanthom":
            await query.answer("This product is no longer available.", show_alert=True)
            return
        if prod_name.lower() == "phanthom":
            keyboard = [
                [InlineKeyboardButton("⚡ 1 Hour (₹20)", callback_data=f"buy_{prod_name}_1_hour"),
                 InlineKeyboardButton("⚡ 3 Hours (₹50)", callback_data=f"buy_{prod_name}_3_hour")],
                [InlineKeyboardButton("🔥 6 Hours (₹80)", callback_data=f"buy_{prod_name}_6_hour"),
                 InlineKeyboardButton("🔥 12 Hours (₹100)", callback_data=f"buy_{prod_name}_12_hour")],
                [InlineKeyboardButton("💎 1 Day (₹150)", callback_data=f"buy_{prod_name}_1_day"),
                 InlineKeyboardButton("💎 3 Days (₹300)", callback_data=f"buy_{prod_name}_3_days")],
                [InlineKeyboardButton("👑 7 Days (₹600)", callback_data=f"buy_{prod_name}_7_days")],
                [InlineKeyboardButton("🏆 30 Days (₹2,000)", callback_data=f"buy_{prod_name}_30_days")],
                [InlineKeyboardButton("« Back to Shop", callback_data="shop_menu")]
            ]
            header_text = "🔥 <b>Phanthom Android + iOS</b> 🔥\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select your duration plan:</i>"
        else:
            keyboard = [
                [InlineKeyboardButton("⏱️ 1 Day Plan (₹50)", callback_data=f"buy_{prod_name}_1_day")],
                [InlineKeyboardButton("📅 7 Days Plan (₹200)", callback_data=f"buy_{prod_name}_7_days")],
                [InlineKeyboardButton("🏆 30 Days Plan (₹500)", callback_data=f"buy_{prod_name}_30_days")],
                [InlineKeyboardButton("« Back to Shop", callback_data="shop_menu")]
            ]
            header_text = f"📦 <b>Product:</b> <code>{prod_name}</code>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select your duration plan:</i>"
            
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(header_text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(
                chat_id=user.id,
                text=header_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        
    elif data.startswith("buy_"):
        parts = data.split("_")
        prod = parts[1]
        plan = "_".join(parts[2:])
        
        base_price = get_product_price(prod, plan)
        if base_price is None:
            await query.answer("This product or plan is unavailable.", show_alert=True)
            return
        
        balance = get_user_balance(user.id)
        if balance >= base_price:
            keyboard = [
                [InlineKeyboardButton("💳 Pay via Wallet Balance (1-Click)", callback_data=f"walletpay_{prod}_{plan}")],
                [InlineKeyboardButton("📲 Pay via Any UPI App (QR / UPI ID)", callback_data=f"upipay_{prod}_{plan}")],
                [InlineKeyboardButton("« Back to Plans", callback_data=f"prod_{prod}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            try:
                await query.message.edit_text(
                    "💳 <b>CHECKOUT OPTIONS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📦 <b>Product:</b> <code>{prod}</code> ({plan.replace('_', ' ').title()})\n"
                    f"💰 <b>Price:</b> <code>₹{base_price:.2f}</code>\n"
                    f"💼 <b>Wallet Balance:</b> <code>₹{balance:.2f}</code> (Sufficient!)\n\n"
                    "<i>Choose your payment method:</i>",
                    reply_markup=reply_markup, parse_mode="HTML"
                )
            except Exception:
                try:
                    await query.message.delete()
                except:
                    pass
                await context.bot.send_message(
                    chat_id=user.id,
                    text=(
                        "💳 <b>CHECKOUT OPTIONS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📦 <b>Product:</b> <code>{prod}</code> ({plan.replace('_', ' ').title()})\n"
                        f"💰 <b>Price:</b> <code>₹{base_price:.2f}</code>\n"
                        f"💼 <b>Wallet Balance:</b> <code>₹{balance:.2f}</code> (Sufficient!)\n\n"
                        "<i>Choose your payment method:</i>"
                    ),
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
        else:
            expiry_time = time.time() + QR_EXPIRY_SECONDS
            order_id = f"ORD{random.randint(100000, 999999)}"
            with data_lock:
                pending_orders = get_pending_orders()
                while True:
                    unique_cents = random.randint(1, 99) * 0.01
                    unique_amount = base_price + unique_cents
                    if not any(abs(o["amount"] - unique_amount) < 0.001 for o in pending_orders.values()):
                        break
                
                stock_key = f"{prod.lower()}_{plan}"
                pending_orders[str(user.id)] = {
                    "type": "product",
                    "prod": prod,
                    "plan": stock_key,
                    "amount": unique_amount,
                    "expiry": expiry_time,
                    "order_id": order_id,
                    "msg_id": None
                }
                set_pending_orders(pending_orders)
            
            upi_link = f"upi://pay?pa={FAMPAY_UPI}&pn=Momshad%20Khan&am={unique_amount:.2f}&cu=INR"
            qr_url = f"https://quickchart.io/qr?text={quote(upi_link)}&size=300&margin=2&format=png"
            
            checkout_text = (
                "💳 <b>UNIVERSAL UPI CHECKOUT</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Product:</b> {prod} ({plan.replace('_', ' ').title()})\n"
                f"💰 <b>Amount:</b> ₹{unique_amount:.2f} INR\n"
                f"🔒 <b>Order:</b> {order_id}\n"
                f"⏱️ <b>UPI ID:</b> {FAMPAY_UPI}\n"
                "⏳ <b>Valid for:</b> 5:00 minutes\n\n"
                "ℹ️ <b>How to pay</b>\n"
                "— 1️⃣ Scan the QR with any UPI app (GPay, PhonePe, Paytm)\n"
                "— 2️⃣ Or tap the UPI ID above to copy it\n"
                f"— 3️⃣ Pay exactly ₹{unique_amount:.2f} INR\n"
                "— 4️⃣ Wait — keys auto-deliver in seconds\n\n"
                "⚠️ <i>Pay the EXACT amount or auto-verify will fail. This QR is single-use and expires in 5 minutes.</i>"
            )
            keyboard = [[InlineKeyboardButton("« Back to Plans", callback_data=f"prod_{prod}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.message.delete()
                sent_msg = await context.bot.send_photo(
                    chat_id=user.id,
                    photo=qr_url,
                    caption=checkout_text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
                with data_lock:
                    pending_orders = get_pending_orders()
                    if str(user.id) in pending_orders:
                        pending_orders[str(user.id)]["msg_id"] = sent_msg.message_id
                        set_pending_orders(pending_orders)
            except Exception as e:
                await query.message.edit_text(checkout_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data.startswith("walletpay_"):
        parts = data.split("_")
        prod = parts[1]
        plan = "_".join(parts[2:])
        base_price = get_product_price(prod, plan)
        
        balance = get_user_balance(user.id)
        if balance >= base_price:
            update_user_balance(user.id, -base_price, f"Wallet Purchase {prod} ({plan}): -₹{base_price:.2f}")
            stock_key = f"{prod.lower()}_{plan}"
            assigned_key = get_key_from_stock(stock_key)
            if assigned_key:
                update_user_balance(user.id, 0.0, f"Key Assigned: {assigned_key}")
                try:
                    await send_admin_purchase_alert(
                        user.id, user.username, user.full_name, prod, plan,
                        assigned_key, base_price, "Wallet balance", f"WALLET-{user.id}-{int(time.time())}"
                    )
                except Exception as admin_error:
                    print(f"Could not send wallet purchase admin alert: {admin_error}")
                success_msg = (
                    "🎉 <b>1-CLICK PURCHASE SUCCESSFUL!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📦 <b>Product:</b> <code>{prod}</code> ({plan.replace('_', ' ').title()})\n"
                    f"🔑 <b>License Key:</b> <code>{assigned_key}</code>\n"
                    f"💼 <b>Remaining Balance:</b> <code>₹{get_user_balance(user.id):.2f}</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n🚀 <i>Enjoy your game!</i>"
                )
                keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
                try:
                    await query.message.edit_text(success_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
                except Exception:
                    try:
                        await query.message.delete()
                    except:
                        pass
                    await context.bot.send_message(chat_id=user.id, text=success_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            else:
                update_user_balance(user.id, base_price, f"Refunded ₹{base_price:.2f} due to out of stock")
                err_msg = "❌ <b>Error: Key Out of Stock! Amount refunded to wallet.</b>"
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("« Home", callback_data="home")]])
                try:
                    await query.message.edit_text(err_msg, reply_markup=keyboard, parse_mode="HTML")
                except Exception:
                    try:
                        await query.message.delete()
                    except:
                        pass
                    await context.bot.send_message(chat_id=user.id, text=err_msg, reply_markup=keyboard, parse_mode="HTML")
        else:
            err_msg = "❌ <b>Insufficient wallet balance! Please deposit balance first.</b>"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("« Home", callback_data="home")]])
            try:
                await query.message.edit_text(err_msg, reply_markup=keyboard, parse_mode="HTML")
            except Exception:
                try:
                    await query.message.delete()
                except:
                    pass
                await context.bot.send_message(chat_id=user.id, text=err_msg, reply_markup=keyboard, parse_mode="HTML")

    elif data.startswith("upipay_"):
        parts = data.split("_")
        prod = parts[1]
        plan = "_".join(parts[2:])
        base_price = get_product_price(prod, plan)
        if base_price is None:
            await query.answer("This product or plan is unavailable.", show_alert=True)
            return
        
        stock_key = f"{prod.lower()}_{plan}"
        available_stock = load_keys().get(stock_key, [])
        if not available_stock:
            await query.message.reply_text(
                "❌ No keys are currently available for this plan. Please try again later or contact support."
            )
            return
        expiry_time = time.time() + QR_EXPIRY_SECONDS
        order_id = f"ORD{random.randint(100000, 999999)}"
        with data_lock:
            pending_orders = get_pending_orders()
            while True:
                unique_cents = random.randint(1, 99) * 0.01
                unique_amount = base_price + unique_cents
                if not any(abs(o["amount"] - unique_amount) < 0.001 for o in pending_orders.values()):
                    break
            stock_key = f"{prod.lower()}_{plan}"
            pending_orders[str(user.id)] = {
                "type": "product",
                "prod": prod,
                "plan": stock_key,
                "amount": unique_amount,
                "expiry": expiry_time,
                "order_id": order_id,
                "msg_id": None
            }
            set_pending_orders(pending_orders)
        
        upi_link = f"upi://pay?pa={FAMPAY_UPI}&pn=Momshad%20Khan&am={unique_amount:.2f}&cu=INR"
        qr_url = f"https://quickchart.io/qr?text={quote(upi_link)}&size=300&margin=2&format=png"
        
        checkout_text = (
            "💳 <b>UNIVERSAL UPI CHECKOUT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Product:</b> {prod} ({plan.replace('_', ' ').title()})\n"
            f"💰 <b>Amount:</b> ₹{unique_amount:.2f} INR\n"
            f"🔒 <b>Order:</b> {order_id}\n"
            f"⏱️ <b>UPI ID:</b> {FAMPAY_UPI}\n"
            "⏳ <b>Valid for:</b> 5:00 minutes\n\n"
            "ℹ️ <b>How to pay</b>\n"
            "— 1️⃣ Scan the QR with any UPI app (GPay, PhonePe, Paytm)\n"
            "— 2️⃣ Or tap the UPI ID above to copy it\n"
            f"— 3️⃣ Pay exactly ₹{unique_amount:.2f} INR\n"
            "— 4️⃣ Wait — keys auto-deliver in seconds\n\n"
            "⚠️ <i>Pay the EXACT amount or auto-verify will fail. This QR is single-use and expires in 5 minutes.</i>"
        )
        keyboard = [[InlineKeyboardButton("« Back to Plans", callback_data=f"prod_{prod}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.message.delete()
            sent_msg = await context.bot.send_photo(
                chat_id=user.id,
                photo=qr_url,
                caption=checkout_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            with data_lock:
                pending_orders = get_pending_orders()
                if str(user.id) in pending_orders:
                    pending_orders[str(user.id)]["msg_id"] = sent_msg.message_id
                    set_pending_orders(pending_orders)
        except Exception as e:
            await query.message.edit_text(checkout_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "deposit_menu":
        keyboard = [
            [InlineKeyboardButton("➕ Add ₹50", callback_data="dep_50"), InlineKeyboardButton("➕ Add ₹100", callback_data="dep_100")],
            [InlineKeyboardButton("➕ Add ₹200", callback_data="dep_200"), InlineKeyboardButton("➕ Add ₹500", callback_data="dep_500")],
            [InlineKeyboardButton("« Back to Home", callback_data="home")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(
                "💰 <b>DEPOSIT BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select amount to add to your wallet:</i>",
                reply_markup=reply_markup, parse_mode="HTML"
            )
        except Exception:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(
                chat_id=user.id,
                text="💰 <b>DEPOSIT BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select amount to add to your wallet:</i>",
                reply_markup=reply_markup, parse_mode="HTML"
            )
        
    elif data.startswith("dep_"):
        dep_amt = float(data.replace("dep_", ""))
        expiry_time = time.time() + QR_EXPIRY_SECONDS
        order_id = f"ORD{random.randint(100000, 999999)}"
        with data_lock:
            pending_orders = get_pending_orders()
            while True:
                unique_cents = random.randint(1, 99) * 0.01
                unique_amount = dep_amt + unique_cents
                if not any(abs(o["amount"] - unique_amount) < 0.001 for o in pending_orders.values()):
                    break
            pending_orders[str(user.id)] = {
                "type": "deposit",
                "dep_amount": dep_amt,
                "amount": unique_amount,
                "expiry": expiry_time,
                "order_id": order_id,
                "msg_id": None
            }
            set_pending_orders(pending_orders)
        
        upi_link = f"upi://pay?pa={FAMPAY_UPI}&pn=Momshad%20Khan&am={unique_amount:.2f}&cu=INR"
        qr_url = f"https://quickchart.io/qr?text={quote(upi_link)}&size=300&margin=2&format=png"
        
        dep_text = (
            "💳 <b>ADD BALANCE CHECKOUT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Deposit Amount:</b> ₹{dep_amt:.2f}\n"
            f"💰 <b>Exact Amount:</b> ₹{unique_amount:.2f} INR\n"
            f"🔒 <b>Order:</b> {order_id}\n"
            f"⏱️ <b>UPI ID:</b> {FAMPAY_UPI}\n"
            "⏳ <b>Valid for:</b> 5:00 minutes\n\n"
            f"⚠️ <i>Scan QR code or pay exact ₹{unique_amount:.2f} within 5 mins!</i>"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.message.delete()
            sent_msg = await context.bot.send_photo(
                chat_id=user.id,
                photo=qr_url,
                caption=dep_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            with data_lock:
                pending_orders = get_pending_orders()
                if str(user.id) in pending_orders:
                    pending_orders[str(user.id)]["msg_id"] = sent_msg.message_id
                    set_pending_orders(pending_orders)
        except Exception as e:
            await query.message.edit_text(dep_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "profile":
        balance = get_user_balance(user.id)
        prof_text = (
            "👤 <b>RESELLER PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📛 <b>Name:</b> {user.full_name}\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
            f"💼 <b>Wallet Balance:</b> <code>₹{balance:.2f}</code>\n"
            "👑 <b>Status:</b> Verified Reseller 🟢\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(prof_text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=prof_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "history":
        balance = get_user_balance(user.id)
        history_list = get_user_history(user.id)
        hist_str = "\n".join([f"• {h}" for h in history_list[-10:]])
        hist_text = (
            "📊 <b>TRANSACTION & PURCHASE HISTORY</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 <b>Wallet Balance:</b> <code>₹{balance:.2f}</code>\n\n"
            f"<b>Recent Activity:</b>\n{hist_str}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(hist_text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=hist_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "referral":
        ref_link = f"https://t.me/{context.bot.username}?start=ref_{user.id}"
        ref_text = (
            "👥 <b>REFERRAL PROGRAM</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Invite your friends and earn rewards!</i>\n\n"
            "🔗 <b>Your Referral Link:</b>\n"
            f"<code>{ref_link}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(ref_text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=ref_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "low_price":
        low_price_text = (
            "🏷️ <b>WHOLESALE LOW PRICE INFO</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "We offer direct wholesale panel prices with maximum profit margins for resellers.\n\n"
            f"Contact owner <b>{ADMIN_USERNAME}</b> to get wholesale reseller pricing!"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(low_price_text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=low_price_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "share":
        share_text = (
            "🌐 <b>SHARE OUR BOT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Invite your gaming friends and community to our store:\n"
            f"👉 https://t.me/{context.bot.username}\n\n"
            "<i>Grow your network and earn rewards!</i>"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(share_text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=share_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "vip_seller":
        vip_text = (
            "🔓 <b>UNLOCK VIP SELLER</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Get VIP Reseller status, custom branding, and lowest wholesale rates!\n\n"
            f"👑 Contact Owner: <b>{ADMIN_USERNAME}</b> to upgrade your account now."
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(vip_text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=vip_text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "support":
        supp_text = (
            "🆘 <b>HELP LINE SUPPORT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Need assistance or have payment issues?\n\n"
            f"💬 Contact Owner & Support: <b>{ADMIN_USERNAME}</b>"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await query.message.edit_text(supp_text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=supp_text, reply_markup=reply_markup, parse_mode="HTML")

def main():
    global BOT_APPLICATION, BOT_LOOP
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is required.")
    if not ADMIN_CHAT_ID:
        raise RuntimeError("ADMIN_CHAT_ID environment variable is required.")
    if not FAMPAY_UPI:
        raise RuntimeError("FAMPAY_UPI environment variable is required.")
    keep_alive()
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    BOT_LOOP = loop
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    BOT_APPLICATION = app_bot

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(button_handler))
    
    async def post_init(application):
        asyncio.create_task(check_qr_expiry_background(application))
        
    app_bot.post_init = post_init
    
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
