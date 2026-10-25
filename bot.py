import asyncio
import json
import os
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

KEY_FILE = "keys_stock.json"
USER_FILE = "users_db.json"
ORDERS_FILE = "pending_orders.json"
PROMO_FILE = "promos.json"
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
    # Phanthom Android + iOS stock stock with 30 days priced at ₹2000
    default_stock = {
        "phanthom_1_hour": ["PHTM-1HR-AAAA-1111", "PHTM-1HR-BBBB-2222", "PHTM-1734-B61A-0BF0"],
        "phanthom_3_hour": ["PHTM-3HR-CCCC-3333"],
        "phanthom_6_hour": ["PHTM-6HR-DDDD-4444"],
        "phanthom_12_hour": ["PHTM-12HR-EEEE-5555"],
        "phanthom_1_day": ["PHTM-1DAY-FFFF-6666"],
        "phanthom_3_days": ["PHTM-3DAY-GGGG-7777"],
        "phanthom_7_days": ["PHTM-7DAY-HHHH-8888"],
        "phanthom_30_days": ["PHTM-30DAY-IIII-2000"]
    }
    save_keys(default_stock)
    return default_stock

def save_keys(stock_data):
    with data_lock:
        try:
            with open(KEY_FILE, "w", encoding="utf-8") as f:
                json.dump(stock_data, f, indent=4)
            print("Successfully saved keys_stock.json persistently!")
        except Exception as e:
            print(f"Error saving keys: {e}")

def load_users():
    if os.path.exists(USER_FILE):
        try:
            with open(USER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_users(users_data):
    with data_lock:
        try:
            with open(USER_FILE, "w", encoding="utf-8") as f:
                json.dump(users_data, f, indent=4)
        except Exception as e:
            print(f"Error saving users: {e}")

def load_promos():
    if os.path.exists(PROMO_FILE):
        try:
            with open(PROMO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    default_promos = {"MOMSHAD10": 10.0, "VIP20": 20.0}
    save_promos(default_promos)
    return default_promos

def save_promos(promos_data):
    try:
        with open(PROMO_FILE, "w", encoding="utf-8") as f:
            json.dump(promos_data, f, indent=4)
    except Exception as e:
        print(f"Error saving promos: {e}")

def get_user_balance(user_id):
    users = load_users()
    str_uid = str(user_id)
    if str_uid not in users:
        users[str_uid] = {"balance": 0.0, "purchases": 0, "history": [], "applied_promo": None}
        save_users(users)
    return users[str_uid]["balance"]

def update_user_balance(user_id, amount, desc=""):
    with data_lock:
        users = load_users()
        str_uid = str(user_id)
        if str_uid not in users:
            users[str_uid] = {"balance": 0.0, "purchases": 0, "history": [], "applied_promo": None}
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
            remaining_count = len(stock[plan])
            save_keys(stock)
            
            if remaining_count <= 2 and BOT_APPLICATION and BOT_LOOP:
                asyncio.run_coroutine_threadsafe(
                    send_low_stock_alert(plan, remaining_count),
                    BOT_LOOP
                )
            return assigned_key
        return "PHTM-DEFAULT-KEY-9999"

async def send_low_stock_alert(plan, count):
    try:
        alert_msg = (
            "⚠️ <b>LOW STOCK ALERT!</b> ⚠️\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Product Plan:</b> <code>{plan}</code>\n"
            f"📉 <b>Remaining Keys:</b> <code>{count}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Please use /addkey to refill stock immediately!</i>"
        )
        await BOT_APPLICATION.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=alert_msg, parse_mode="HTML")
    except Exception as e:
        print(f"Error sending low stock alert: {e}")

def get_product_price(plan, user_id=None):
    # Phanthom Android + iOS pricing with 30 days at ₹2000
    prices = {
        "1_hour": 20.0,
        "3_hour": 50.0,
        "6_hour": 80.0,
        "12_hour": 100.0,
        "1_day": 150.0,
        "3_days": 300.0,
        "7_days": 600.0,
        "30_days": 2000.0
    }
    base = prices.get(plan, 20.0)
    
    if user_id:
        users = load_users()
        str_uid = str(user_id)
        promo = users.get(str_uid, {}).get("applied_promo")
        if promo:
            promos = load_promos()
            discount_pct = promos.get(promo, 0.0)
            if discount_pct > 0:
                base = base * (1.0 - discount_pct / 100.0)
    return round(base, 2)

@app.route("/")
def home():
    return "Phanthom Android + iOS Panel Bot Gateway is running!"

@app.route("/payment-webhook", methods=["POST", "GET"])
def payment_webhook():
    try:
        req_json = request.get_json(silent=True) or {}
        req_form = request.form.to_dict()
        req_args = request.args.to_dict()
        req_data = request.get_data(as_text=True)

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

            set_pending_orders(pending_orders)

        if target_user_id and order_type:
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
                user_name = matched_data.get("user_name", "Unknown")
                username = matched_data.get("username", "None")
                assigned_key = get_key_from_stock(plan)
                
                update_user_balance(target_user_id, 0.0, f"Purchased {prod} ({plan}): Key {assigned_key}")
                if BOT_APPLICATION and BOT_LOOP:
                    asyncio.run_coroutine_threadsafe(
                        send_key_to_user(target_user_id, assigned_key, prod, plan, order_id, matched_amount, user_name, username),
                        BOT_LOOP
                    )
                return {"status": "success", "message": "Key delivered automatically!"}, 200
        else:
            return {"status": "not_found", "message": "No active pending order found."}, 404
            
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}, 500

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

BOT_TOKEN = '8950060993:AAGkCFKwgwOK3CWWlLti40a2b9zZqP-Lfus'
ADMIN_CHAT_ID = 8380823727
ADMIN_USERNAME = "@Momshad_00"
FAMPAY_UPI = "islam-momshad.khan@fam"

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
                print(f"Error expiring QR: {e}")

async def send_deposit_success(user_id, amount):
    try:
        msg = (
            "🎉 <b>DEPOSIT SUCCESSFUL & CREDITED!</b> 🎉\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Added to Wallet:</b> <code>₹{amount:.2f}</code>\n"
            f"💼 <b>Current Balance:</b> <code>₹{get_user_balance(user_id):.2f}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🚀 <i>You can now buy Phanthom Android + iOS panel instantly using your wallet balance with 1-click!</i>"
        )
        await BOT_APPLICATION.bot.send_message(chat_id=int(user_id), text=msg, parse_mode="HTML")
    except Exception as e:
        print(f"Error: {e}")

async def send_key_to_user(user_id, panel_key, prod, plan, order_id, paid_amount, user_name, username):
    try:
        plan_display = plan.replace('_', ' ').title()
        success_msg = (
            "🎉 <b>PAYMENT SUCCESSFUL</b> 🎉\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Thank you for your purchase!</i>\n\n"
            "📋 <b>Order Details</b>\n"
            f"— 🆔 <b>ID:</b> <code>{order_id}</code>\n"
            f"— 📦 <b>Product:</b> Phanthom Android + iOS ({plan_display})\n"
            f"— 🔢 <b>Quantity:</b> 1\n"
            f"— 💳 <b>Method:</b> 📲 UPI Payment\n"
            f"— 💵 <b>Paid:</b> ₹{paid_amount:.2f} INR\n\n"
            "🔑 <b>Your Key</b>\n"
            f"<code>{panel_key}</code>\n\n"
            "💡 <i>Tap the key above to copy. Enjoy your game!</i>"
        )
        await BOT_APPLICATION.bot.send_message(chat_id=int(user_id), text=success_msg, parse_mode="HTML")
        
        admin_alert = (
            "🔔 <b>SECURE AUTO-SALE SUCCESSFUL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Name:</b> {user_name}\n"
            f"🔗 <b>Username:</b> {username}\n"
            f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
            f"📦 <b>Product:</b> Phanthom Android + iOS ({plan})\n"
            f"🔑 <b>Key Delivered:</b> <code>{panel_key}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await BOT_APPLICATION.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=admin_alert, parse_mode="HTML")
    except Exception as e:
        print(f"Error: {e}")

async def admin_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    stock = load_keys()
    stock_text = "📦 <b>PHANTHOM ANDROID + IOS STOCK SUMMARY</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for plan, keys in stock.items():
        stock_text += f"• <code>{plan}</code>: <b>{len(keys)}</b> keys left\n"
    stock_text += "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n💡 <i>Use /addkey [plan] [key] to add stock.</i>"
    await update.message.reply_text(stock_text, parse_mode="HTML")

async def admin_addkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("⚠️ <b>Usage:</b> /addkey [plan_name] [license_key]\nExample: /addkey phanthom_1_hour PHTM-1234", parse_mode="HTML")
        return
    plan = args[0].lower()
    new_key = " ".join(args[1:])
    with data_lock:
        stock = load_keys()
        if plan not in stock:
            stock[plan] = []
        stock[plan].append(new_key)
        save_keys(stock)
    await update.message.reply_text(f"✅ Successfully added key to <code>{plan}</code>!\nTotal keys: {len(stock[plan])}", parse_mode="HTML")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    message_text = " ".join(context.args)
    if not message_text:
        await update.message.reply_text("⚠️ <b>Usage:</b> /broadcast [Your message]", parse_mode="HTML")
        return
    users = load_users()
    success, fail = 0, 0
    broadcast_msg = f"📢 <b>PHANTHOM STORE ANNOUNCEMENT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{message_text}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    for uid_str in users.keys():
        try:
            await context.bot.send_message(chat_id=int(uid_str), text=broadcast_msg, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)
        except:
            fail += 1
    await update.message.reply_text(f"📢 Broadcast Done!\n✅ Delivered: {success}\n❌ Failed: {fail}", parse_mode="HTML")

async def promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promos = load_promos()
    promo_list = "\n".join([f"• <code>{code}</code>: <b>{discount}% OFF</b>" for code, discount in promos.items()])
    text = f"🏷️ <b>PROMO CODES</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{promo_list}\n\n💡 Type: <code>/applypromo [CODE]</code>"
    await update.message.reply_text(text, parse_mode="HTML")

async def apply_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ Example: /applypromo MOMSHAD10", parse_mode="HTML")
        return
    code = args[0].upper()
    promos = load_promos()
    if code in promos:
        with data_lock:
            users = load_users()
            str_uid = str(update.effective_user.id)
            if str_uid not in users:
                users[str_uid] = {"balance": 0.0, "purchases": 0, "history": [], "applied_promo": None}
            users[str_uid]["applied_promo"] = code
            save_users(users)
        await update.message.reply_text(f"🎉 Promo <code>{code}</code> applied! ({promos[code]}% OFF)", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Invalid promo code!", parse_mode="HTML")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = get_user_balance(user.id)
    
    # Check for referral start parameter
    if context.args and context.args[0].startswith("ref_"):
        try:
            referrer_id = int(context.args[0].replace("ref_", ""))
            if referrer_id != user.id:
                users = load_users()
                str_uid = str(user.id)
                if str_uid not in users or users[str_uid].get("purchases", 0) == 0:
                    ref_bonus = 10.0
                    update_user_balance(referrer_id, ref_bonus, f"Referral Bonus from {user.full_name}: +₹{ref_bonus:.2f}")
                    if BOT_APPLICATION and BOT_LOOP:
                        asyncio.run_coroutine_threadsafe(
                            BOT_APPLICATION.bot.send_message(
                                chat_id=referrer_id,
                                text=f"🎉 <b>REFERRAL BONUS!</b>\nNew user <b>{user.full_name}</b> joined via your link! ₹{ref_bonus:.2f} added to your wallet.",
                                parse_mode="HTML"
                            ),
                            BOT_LOOP
                        )
        except Exception as e:
            print(f"Referral error: {e}")

    keyboard = [
        [InlineKeyboardButton("🔥 Phanthom Android + iOS", callback_data="shop_phanthom")],
        [InlineKeyboardButton("💰 Deposit Balance", callback_data="deposit_menu"), InlineKeyboardButton("📊 All History", callback_data="history")],
        [InlineKeyboardButton("👤 Reseller Profile", callback_data="profile"), InlineKeyboardButton("👥 Referral", callback_data="referral")],
        [InlineKeyboardButton("🏷️ Promo Codes", callback_data="promo_menu"), InlineKeyboardButton("🌐 Share Friends", callback_data="share")],
        [InlineKeyboardButton("🆘 Help Line Support", callback_data="support")],
        [InlineKeyboardButton("📂 File Channel", url="https://t.me/File99channel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = (
        "⚡ <b>WELCOME TO PHANTHOM ANDROID + IOS STORE</b> ⚡\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👋 Hello <b>{user.first_name}</b>!\n\n"
        "👑 <b>Official Phanthom Android + iOS Hub</b>\n"
        "🌐 <i>Fast, Secure & 100% Anti-Ban Performance!</i>\n\n"
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
    
    if data == "shop_phanthom":
        keyboard = [
            [InlineKeyboardButton("⚡ 1 Hour (₹20)", callback_data="buy_Phanthom_1_hour"), InlineKeyboardButton("⚡ 3 Hour (₹50)", callback_data="buy_Phanthom_3_hour")],
            [InlineKeyboardButton("🔥 6 Hour (₹80)", callback_data="buy_Phanthom_6_hour"), InlineKeyboardButton("🔥 12 Hour (₹100)", callback_data="buy_Phanthom_12_hour")],
            [InlineKeyboardButton("💎 1 Day (₹150)", callback_data="buy_Phanthom_1_day"), InlineKeyboardButton("💎 3 Days (₹300)", callback_data="buy_Phanthom_3_days")],
            [InlineKeyboardButton("👑 7 Days (₹600)", callback_data="buy_Phanthom_7_days"), InlineKeyboardButton("🏆 30 Days (₹2000)", callback_data="buy_Phanthom_30_days")],
            [InlineKeyboardButton("« Back to Home", callback_data="home")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        header_text = "🔥 <b>Phanthom Android + iOS Panel</b> 🔥\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select your duration plan below:</i>"
        try:
            await query.message.edit_text(header_text, reply_markup=reply_markup, parse_mode="HTML")
        except:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=header_text, reply_markup=reply_markup, parse_mode="HTML")
        
    elif data == "home":
        await start(update, context)

    elif data == "promo_menu":
        promos = load_promos()
        promo_list = "\n".join([f"• <code>{code}</code>: <b>{discount}% OFF</b>" for code, discount in promos.items()])
        promo_text = f"🏷️ <b>ACTIVE PROMO CODES</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{promo_list}\n\n💡 Type: <code>/applypromo [CODE]</code>"
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        try:
            await query.message.edit_text(promo_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        except:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=promo_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        
    elif data.startswith("buy_"):
        parts = data.split("_")
        prod = parts[1]
        plan = "_".join(parts[2:])
        base_price = get_product_price(plan, user.id)
        balance = get_user_balance(user.id)
        
        if balance >= base_price:
            keyboard = [
                [InlineKeyboardButton("💳 Pay via Wallet (1-Click)", callback_data=f"walletpay_{prod}_{plan}")],
                [InlineKeyboardButton("📲 Pay via UPI QR", callback_data=f"upipay_{prod}_{plan}")],
                [InlineKeyboardButton("« Back to Home", callback_data="home")]
            ]
            try:
                await query.message.edit_text(
                    f"💳 <b>CHECKOUT OPTIONS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📦 <b>Product:</b> Phanthom Android + iOS ({plan.replace('_', ' ').title()})\n"
                    f"💰 <b>Price:</b> <code>₹{base_price:.2f}</code>\n"
                    f"💼 <b>Wallet Balance:</b> <code>₹{balance:.2f}</code> (Sufficient!)\n\n"
                    f"<i>Choose your payment method:</i>",
                    reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
                )
            except:
                try:
                    await query.message.delete()
                except:
                    pass
                await context.bot.send_message(chat_id=user.id, text="💳 <b>CHECKOUT</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        else:
            expiry_time = time.time() + QR_EXPIRY_SECONDS
            order_id = f"ORD{random.randint(100000, 999999)}"
            with data_lock:
                pending_orders = get_pending_orders()
                while True:
                    unique_amount = base_price + (random.randint(1, 99) * 0.01)
                    if not any(abs(o["amount"] - unique_amount) < 0.001 for o in pending_orders.values()):
                        break
                pending_orders[str(user.id)] = {
                    "type": "product", "prod": prod, "plan": f"{prod.lower()}_{plan}",
                    "amount": unique_amount, "expiry": expiry_time, "order_id": order_id,
                    "msg_id": None, "user_name": user.full_name, "username": f"@{user.username}" if user.username else "None"
                }
                set_pending_orders(pending_orders)
            
            upi_link = f"upi://pay?pa={FAMPAY_UPI}&pn=Momshad%20Khan&am={unique_amount:.2f}&cu=INR"
            qr_url = f"https://quickchart.io/qr?text={quote(upi_link)}&size=300&margin=2&format=png"
            checkout_text = (
                "💳 <b>UNIVERSAL UPI CHECKOUT</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Product:</b> Phanthom Android + iOS ({plan.replace('_', ' ').title()})\n"
                f"💰 <b>Amount:</b> ₹{unique_amount:.2f} INR\n"
                f"🔒 <b>Order:</b> {order_id}\n"
                f"⏱️ <b>UPI ID:</b> {FAMPAY_UPI}\n"
                "⏳ <b>Valid for:</b> 5:00 minutes\n\n"
                "ℹ️ <b>How to pay</b>\n"
                "— 1️⃣ Scan QR with any UPI app (GPay, PhonePe, Paytm)\n"
                "— 2️⃣ Or tap UPI ID above to copy\n"
                f"— 3️⃣ Pay exactly ₹{unique_amount:.2f}\n"
                "— 4️⃣ Wait — keys auto-deliver in seconds!\n\n"
                "⚠️ <i>Pay exact amount or verification will fail.</i>"
            )
            
            try:
                await query.message.delete()
                sent_msg = await context.bot.send_photo(
                    chat_id=user.id, photo=qr_url, caption=checkout_text,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Home", callback_data="home")]]),
                    parse_mode="HTML"
                )
                with data_lock:
                    pending_orders = get_pending_orders()
                    if str(user.id) in pending_orders:
                        pending_orders[str(user.id)]["msg_id"] = sent_msg.message_id
                        set_pending_orders(pending_orders)
            except Exception as e:
                print(f"Error: {e}")

    elif data.startswith("walletpay_"):
        parts = data.split("_")
        prod = parts[1]
        plan = "_".join(parts[2:])
        base_price = get_product_price(plan, user.id)
        if get_user_balance(user.id) >= base_price:
            update_user_balance(user.id, -base_price, f"Wallet Purchase Phanthom Android + iOS ({plan}): -₹{base_price:.2f}")
            assigned_key = get_key_from_stock(f"{prod.lower()}_{plan}")
            success_msg = (
                "🎉 <b>1-CLICK PURCHASE SUCCESSFUL!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Product:</b> Phanthom Android + iOS ({plan.replace('_', ' ').title()})\n"
                f"🔑 <b>License Key:</b> <code>{assigned_key}</code>\n"
                f"💼 <b>Remaining Balance:</b> <code>₹{get_user_balance(user.id):.2f}</code>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n🚀 <i>Enjoy your game!</i>"
            )
            try:
                await query.message.edit_text(success_msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Home", callback_data="home")]]), parse_mode="HTML")
            except:
                try:
                    await query.message.delete()
                except:
                    pass
                await context.bot.send_message(chat_id=user.id, text=success_msg, parse_mode="HTML")
            
            try:
                admin_alert = (
                    "🔔 <b>SECURE WALLET SALE SUCCESSFUL</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>Name:</b> {user.full_name}\n"
                    f"🔗 <b>Username:</b> @{user.username or 'None'}\n"
                    f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
                    f"📦 <b>Product:</b> Phanthom Android + iOS ({plan})\n"
                    f"🔑 <b>Key Delivered:</b> <code>{assigned_key}</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
                await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=admin_alert, parse_mode="HTML")
            except: pass
        else:
            await query.message.reply_text("❌ Insufficient balance!")

    elif data.startswith("upipay_"):
        parts = data.split("_")
        prod = parts[1]
        plan = "_".join(parts[2:])
        base_price = get_product_price(plan, user.id)
        expiry_time = time.time() + QR_EXPIRY_SECONDS
        order_id = f"ORD{random.randint(100000, 999999)}"
        with data_lock:
            pending_orders = get_pending_orders()
            while True:
                unique_amount = base_price + (random.randint(1, 99) * 0.01)
                if not any(abs(o["amount"] - unique_amount) < 0.001 for o in pending_orders.values()):
                    break
            pending_orders[str(user.id)] = {
                "type": "product", "prod": prod, "plan": f"{prod.lower()}_{plan}",
                "amount": unique_amount, "expiry": expiry_time, "order_id": order_id,
                "msg_id": None, "user_name": user.full_name, "username": f"@{user.username}" if user.username else "None"
            }
            set_pending_orders(pending_orders)
        
        upi_link = f"upi://pay?pa={FAMPAY_UPI}&pn=Momshad%20Khan&am={unique_amount:.2f}&cu=INR"
        qr_url = f"https://quickchart.io/qr?text={quote(upi_link)}&size=300&margin=2&format=png"
        checkout_text = (
            "💳 <b>UNIVERSAL UPI CHECKOUT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>Product:</b> Phanthom Android + iOS ({plan.replace('_', ' ').title()})\n"
            f"💰 <b>Amount:</b> ₹{unique_amount:.2f} INR\n"
            f"🔒 <b>Order:</b> {order_id}\n"
            f"⏱️ <b>UPI ID:</b> {FAMPAY_UPI}\n"
            "⏳ <b>Valid for:</b> 5:00 minutes"
        )
        try:
            await query.message.delete()
            sent_msg = await context.bot.send_photo(
                chat_id=user.id, photo=qr_url, caption=checkout_text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Home", callback_data="home")]]),
                parse_mode="HTML"
            )
            with data_lock:
                pending_orders = get_pending_orders()
                if str(user.id) in pending_orders:
                    pending_orders[str(user.id)]["msg_id"] = sent_msg.message_id
                    set_pending_orders(pending_orders)
        except Exception as e:
            print(f"Error: {e}")

    elif data == "deposit_menu":
        keyboard = [
            [InlineKeyboardButton("➕ Add ₹50", callback_data="dep_50"), InlineKeyboardButton("➕ Add ₹100", callback_data="dep_100")],
            [InlineKeyboardButton("➕ Add ₹200", callback_data="dep_200"), InlineKeyboardButton("➕ Add ₹500", callback_data="dep_500")],
            [InlineKeyboardButton("« Back to Home", callback_data="home")]
        ]
        try:
            await query.message.edit_text("💰 <b>DEPOSIT BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select amount to add to wallet:</i>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        except:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text="💰 <b>DEPOSIT BALANCE</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("dep_"):
        dep_amt = float(data.replace("dep_", ""))
        expiry_time = time.time() + QR_EXPIRY_SECONDS
        order_id = f"ORD{random.randint(100000, 999999)}"
        with data_lock:
            pending_orders = get_pending_orders()
            while True:
                unique_amount = dep_amt + (random.randint(1, 99) * 0.01)
                if not any(abs(o["amount"] - unique_amount) < 0.001 for o in pending_orders.values()):
                    break
            pending_orders[str(user.id)] = {
                "type": "deposit", "dep_amount": dep_amt, "amount": unique_amount,
                "expiry": expiry_time, "order_id": order_id, "msg_id": None
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
            "⏳ <b>Valid for:</b> 5:00 minutes"
        )
        try:
            await query.message.delete()
            sent_msg = await context.bot.send_photo(
                chat_id=user.id, photo=qr_url, caption=dep_text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Home", callback_data="home")]]),
                parse_mode="HTML"
            )
            with data_lock:
                pending_orders = get_pending_orders()
                if str(user.id) in pending_orders:
                    pending_orders[str(user.id)]["msg_id"] = sent_msg.message_id
                    set_pending_orders(pending_orders)
        except Exception as e:
            print(f"Error: {e}")

    elif data == "profile":
        prof_text = (
            "👤 <b>RESELLER PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📛 <b>Name:</b> {user.full_name}\n"
            f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
            f"💼 <b>Wallet Balance:</b> <code>₹{get_user_balance(user.id):.2f}</code>\n"
            "👑 <b>Status:</b> Phanthom Android + iOS Store 🟢\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        try: await query.message.edit_text(prof_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        except:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=prof_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "history":
        hist_str = "\n".join([f"• {h}" for h in get_user_history(user.id)[-10:]])
        hist_text = (
            "📊 <b>TRANSACTION HISTORY</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 <b>Wallet Balance:</b> <code>₹{get_user_balance(user.id):.2f}</code>\n\n"
            f"<b>Recent Activity:</b>\n{hist_str}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        try: await query.message.edit_text(hist_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        except:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=hist_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "referral":
        ref_text = (
            "👥 <b>REFERRAL PROGRAM</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Invite your friends and earn rewards!</i>\n\n"
            "🔗 <b>Your Referral Link:</b>\n"
            f"<code>https://t.me/{context.bot.username}?start=ref_{user.id}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        try: await query.message.edit_text(ref_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        except:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=ref_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data in ["share", "support"]:
        texts = {
            "share": f"🌐 <b>SHARE OUR BOT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\nInvite your friends to Phanthom Android + iOS Store:\n👉 https://t.me/{context.bot.username}",
            "support": f"🆘 <b>HELP LINE SUPPORT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\nNeed assistance?\n💬 Contact Owner: <b>{ADMIN_USERNAME}</b>"
        }
        keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
        try: await query.message.edit_text(texts[data], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        except:
            try:
                await query.message.delete()
            except:
                pass
            await context.bot.send_message(chat_id=user.id, text=texts[data], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

def main():
    global BOT_APPLICATION, BOT_LOOP
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
    app_bot.add_handler(CommandHandler("stock", admin_stock))
    app_bot.add_handler(CommandHandler("addkey", admin_addkey))
    app_bot.add_handler(CommandHandler("broadcast", admin_broadcast))
    app_bot.add_handler(CommandHandler("promo", promo_command))
    app_bot.add_handler(CommandHandler("applypromo", apply_promo))
    
    async def post_init(application):
        asyncio.create_task(check_qr_expiry_background(application))
        
    app_bot.post_init = post_init
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
