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
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

app = Flask(__name__)

data_lock = Lock()
BOT_TOKEN = "8950060993:AAHGnbt7SjJ944okecPKK_Y10HFGQ3MLj0s"
ADMIN_CHAT_ID = 8380823727
ADMIN_USERNAME = "@Momshad_00"
FAMPAY_UPI = "islam-momshad.khan@fam"

KEY_FILE = "keys_stock.json"
USER_FILE = "users_db.json"
ORDERS_FILE = "pending_orders.json"
QR_EXPIRY_SECONDS = 300  # 5 Minutes

def save_json_file_safely(filename, data):
    with data_lock:
        try:
            temp_file = filename + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, filename)
        except Exception as e:
            print(f"Error saving {filename} safely: {e}")

def load_json_file(filename, default_val):
    with data_lock:
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading {filename}: {e}")
    return default_val

def get_pending_orders():
    return load_json_file(ORDERS_FILE, {})

def set_pending_orders(orders):
    save_json_file_safely(ORDERS_FILE, orders)

def load_keys():
    stock = load_json_file(KEY_FILE, {})
    if not stock:
        default_stock = {
            "phanthom_1_hour": ["PHTM-1HR-AAAA-1111", "PHTM-1734-B61A-0BF0"],
            "phanthom_3_hour": ["PHTM-3HR-CCCC-3333"],
            "phanthom_6_hour": ["PHTM-6HR-DDDD-4444"],
            "phanthom_12_hour": ["PHTM-12HR-EEEE-5555"],
            "phanthom_1_day": ["PHTM-1DAY-FFFF-6666"],
            "phanthom_3_days": ["PHTM-3DAY-GGGG-7777"],
            "phanthom_7_days": ["PHTM-7DAY-HHHH-8888"],
            "phanthom_30_days": ["PHTM-30DAY-2000-9999", "PHTM-30DAY-VIP-8888"]
        }
        save_json_file_safely(KEY_FILE, default_stock)
        return default_stock
    return stock

def save_keys(stock_data):
    save_json_file_safely(KEY_FILE, stock_data)

def load_users():
    return load_json_file(USER_FILE, {})

def save_users(users_data):
    save_json_file_safely(USER_FILE, users_data)

def get_user_balance(user_id):
    users = load_users()
    str_uid = str(user_id)
    if str_uid not in users:
        users[str_uid] = {"balance": 0.0, "purchases": 0, "history": []}
        save_users(users)
    return users[str_uid].get("balance", 0.0)

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
        return "PHTM-DEFAULT-KEY-9999"

def get_product_price(plan):
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
    return prices.get(plan, 20.0)

# Initialize Telegram Application
application = Application.builder().token(BOT_TOKEN).read_timeout(10).write_timeout(10).build()
bot_loop = None

@app.route("/")
def home():
    return "X Panel Store Webhook Bot Gateway is running!"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    try:
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, application.bot)
        if bot_loop and bot_loop.is_running():
            asyncio.run_coroutine_threadsafe(application.process_update(update), bot_loop)
    except Exception as e:
        print(f"Error processing webhook update: {e}")
        traceback.print_exc()
    return "OK", 200

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
                if eu in pending_orders:
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
                if uid in pending_orders:
                    del pending_orders[uid]

            set_pending_orders(pending_orders)

        if target_user_id and order_type:
            if order_type == "deposit":
                dep_amount = matched_data["dep_amount"]
                update_user_balance(target_user_id, dep_amount, f"Deposit Added: +₹{dep_amount:.2f}")
                if bot_loop and bot_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        send_deposit_success(target_user_id, dep_amount),
                        bot_loop
                    )
                return {"status": "success", "message": "Balance deposited successfully!"}, 200
            
            elif order_type == "product":
                plan = matched_data["plan"]
                order_id = matched_data.get("order_id", "ORD997673")
                user_name = matched_data.get("user_name", "User")
                username = matched_data.get("username", "None")
                
                assigned_key = get_key_from_stock(plan)
                update_user_balance(target_user_id, 0.0, f"Purchased Phanthom ({plan}): Key {assigned_key}")
                
                if bot_loop and bot_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        send_key_to_user(target_user_id, assigned_key, plan, order_id, matched_amount, user_name, username),
                        bot_loop
                    )
                return {"status": "success", "message": "Key delivered automatically!"}, 200
        else:
            return {"status": "not_found", "message": "No active pending order found."}, 404
            
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "message": str(e)}, 500

async def check_qr_expiry_background():
    while True:
        await asyncio.sleep(10)
        try:
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
                    print(f"Error expiring QR message: {e}")
        except Exception as e:
            print(f"Error in background expiry loop: {e}")

async def send_deposit_success(user_id, amount):
    try:
        msg = (
            "🎉 <b>DEPOSIT SUCCESSFUL & CREDITED!</b> 🎉\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Added to Wallet:</b> <code>₹{amount:.2f}</code>\n"
            f"💼 <b>Current Balance:</b> <code>₹{get_user_balance(user_id):.2f}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🚀 <i>You can now buy panel instantly using your wallet balance with 1-click!</i>"
        )
        await application.bot.send_message(chat_id=int(user_id), text=msg, parse_mode="HTML")
    except Exception as e:
        print(f"Error in send_deposit_success: {e}")

async def send_key_to_user(user_id, panel_key, plan, order_id, paid_amount, user_name, username):
    try:
        plan_display = plan.replace('_', ' ').title()
        success_msg = (
            "🎉 <b>PAYMENT SUCCESSFUL</b> 🎉\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Thank you for your purchase!</i>\n\n"
            "📋 <b>Order Details</b>\n"
            f"— 🆔 <b>ID:</b> <code>{order_id}</code>\n"
            f"— 📦 <b>Product:</b> Phanthom Android + IOS ({plan_display})\n"
            f"— 🔢 <b>Quantity:</b> 1\n"
            f"— 💳 <b>Method:</b> 📲 UPI Payment\n"
            f"— 💵 <b>Paid:</b> ₹{paid_amount:.2f} INR\n\n"
            "🔑 <b>Your Key</b>\n"
            f"<code>{panel_key}</code>\n\n"
            "💡 <i>Tap the key above to copy. Enjoy your game!</i>"
        )
        await application.bot.send_message(chat_id=int(user_id), text=success_msg, parse_mode="HTML")
        
        admin_alert = (
            "🔔 <b>SECURE AUTO-SALE SUCCESSFUL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Name:</b> {user_name}\n"
            f"🔗 <b>Username:</b> {username}\n"
            f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
            f"📦 <b>Product:</b> Phanthom Android + IOS ({plan_display})\n"
            f"🔑 <b>Key Delivered:</b> <code>{panel_key}</code>\n"
            f"💵 <b>Price Paid:</b> ₹{paid_amount:.2f}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await application.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=admin_alert, parse_mode="HTML")
    except Exception as e:
        print(f"Error in send_key_to_user: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        balance = get_user_balance(user.id)
        
        keyboard = [
            [InlineKeyboardButton("🔥 Phanthom Android + IOS", callback_data="shop_phanthom")],
            [InlineKeyboardButton("💰 Deposit Balance", callback_data="deposit_menu"), InlineKeyboardButton("📊 All History", callback_data="history")],
            [InlineKeyboardButton("👤 Reseller Profile", callback_data="profile"), InlineKeyboardButton("👥 Referral", callback_data="referral")],
            [InlineKeyboardButton("🌐 Share Friends", callback_data="share"), InlineKeyboardButton("🆘 Help Line Support", callback_data="support")],
            [InlineKeyboardButton("📂 File Channel", url="https://t.me/File99channel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        welcome_text = (
            "⚡ <b>WELCOME TO X PANEL STORE</b> ⚡\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👋 Hello <b>{user.first_name}</b>!\n\n"
            "👑 <b>Official Phanthom Android + IOS Hub</b>\n"
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
            except Exception:
                pass
            await context.bot.send_message(chat_id=user.id, text=welcome_text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        print(f"Error in start handler: {e}")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        if user.id != int(ADMIN_CHAT_ID):
            await update.message.reply_text("❌ You are not authorized to use broadcast.")
            return
        
        if not context.args:
            await update.message.reply_text("⚠️ Please provide a message to broadcast. Usage:\n`/broadcast Your message here`", parse_mode="Markdown")
            return
            
        broadcast_msg = " ".join(context.args)
        users = load_users()
        success_count = 0
        fail_count = 0
        
        status_msg = await update.message.reply_text("🚀 Broadcast started... Please wait.")
        
        for uid_str in users.keys():
            try:
                await context.bot.send_message(chat_id=int(uid_str), text=f"📢 <b>ANNOUNCEMENT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n{broadcast_msg}", parse_mode="HTML")
                success_count += 1
                await asyncio.sleep(0.05)
            except Exception:
                fail_count += 1
                
        await status_msg.edit_text(
            f"✅ <b>Broadcast Completed!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>Total Users:</b> {len(users)}\n"
            f"🟢 <b>Successful:</b> {success_count}\n"
            f"🔴 <b>Failed:</b> {fail_count}",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Error in broadcast: {e}")

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        if user.id != int(ADMIN_CHAT_ID):
            await update.message.reply_text("❌ Unauthorized.")
            return
            
        with open(KEY_FILE, "rb") as f1, open(USER_FILE, "rb") as f2:
            await context.bot.send_document(chat_id=user.id, document=f1, caption="📦 Keys Stock Backup")
            await context.bot.send_document(chat_id=user.id, document=f2, caption="👥 Users Database Backup")
    except Exception as e:
        await update.message.reply_text(f"❌ Backup failed: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        try:
            await query.answer()
        except Exception:
            pass
            
        data = query.data
        user = update.effective_user
        get_user_balance(user.id) # register user
        
        if data == "shop_phanthom":
            keyboard = [
                [InlineKeyboardButton("⚡ 1 Hour (₹20)", callback_data="buy_1_hour"), InlineKeyboardButton("⚡ 3 Hour (₹50)", callback_data="buy_3_hour")],
                [InlineKeyboardButton("🔥 6 Hour (₹80)", callback_data="buy_6_hour"), InlineKeyboardButton("🔥 12 Hour (₹100)", callback_data="buy_12_hour")],
                [InlineKeyboardButton("💎 1 Day (₹150)", callback_data="buy_1_day"), InlineKeyboardButton("💎 3 Days (₹300)", callback_data="buy_3_days")],
                [InlineKeyboardButton("👑 7 Days (₹600)", callback_data="buy_7_days"), InlineKeyboardButton("🏆 30 Days (₹2000)", callback_data="buy_30_days")],
                [InlineKeyboardButton("« Back to Home", callback_data="home")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            header_text = "🔥 <b>Phanthom Android + IOS Panel</b> 🔥\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select your duration plan below:</i>"
            try:
                await query.message.edit_text(header_text, reply_markup=reply_markup, parse_mode="HTML")
            except Exception:
                try:
                    await query.message.delete()
                except Exception:
                    pass
                await context.bot.send_message(chat_id=user.id, text=header_text, reply_markup=reply_markup, parse_mode="HTML")
            
        elif data == "home":
            await start(update, context)
            
        elif data.startswith("buy_"):
            plan = data.replace("buy_", "")
            base_price = get_product_price(plan)
            balance = get_user_balance(user.id)
            
            if balance >= base_price:
                keyboard = [
                    [InlineKeyboardButton("💳 Pay via Wallet (1-Click)", callback_data=f"walletpay_{plan}")],
                    [InlineKeyboardButton("📲 Pay via UPI QR", callback_data=f"upipay_{plan}")],
                    [InlineKeyboardButton("« Back to Shop", callback_data="shop_phanthom")]
                ]
                try:
                    await query.message.edit_text(
                        f"💳 <b>CHECKOUT OPTIONS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📦 <b>Product:</b> Phanthom Android + IOS ({plan.replace('_', ' ').title()})\n"
                        f"💰 <b>Price:</b> <code>₹{base_price:.2f}</code>\n"
                        f"💼 <b>Wallet Balance:</b> <code>₹{balance:.2f}</code> (Sufficient!)\n\n"
                        f"<i>Choose your payment method:</i>",
                        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
                    )
                except Exception:
                    try:
                        await query.message.delete()
                    except Exception:
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
                        "type": "product", "plan": plan,
                        "amount": unique_amount, "expiry": expiry_time, "order_id": order_id,
                        "msg_id": None, "user_name": user.full_name, "username": f"@{user.username}" if user.username else "None"
                    }
                    set_pending_orders(pending_orders)
                
                upi_link = f"upi://pay?pa={FAMPAY_UPI}&pn=Momshad%20Khan&am={unique_amount:.2f}&cu=INR"
                qr_url = f"https://quickchart.io/qr?text={quote(upi_link)}&size=300&margin=2&format=png"
                checkout_text = (
                    "💳 <b>UNIVERSAL UPI CHECKOUT</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📦 <b>Product:</b> Phanthom Android + IOS ({plan.replace('_', ' ').title()})\n"
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
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Shop", callback_data="shop_phanthom")]]),
                        parse_mode="HTML"
                    )
                    with data_lock:
                        pending_orders = get_pending_orders()
                        if str(user.id) in pending_orders:
                            pending_orders[str(user.id)]["msg_id"] = sent_msg.message_id
                            set_pending_orders(pending_orders)
                except Exception as e:
                    print(f"Error sending QR photo: {e}")

        elif data.startswith("walletpay_"):
            plan = data.replace("walletpay_", "")
            base_price = get_product_price(plan)
            if get_user_balance(user.id) >= base_price:
                update_user_balance(user.id, -base_price, f"Wallet Purchase Phanthom ({plan}): -₹{base_price:.2f}")
                assigned_key = get_key_from_stock(plan)
                plan_display = plan.replace('_', ' ').title()
                success_msg = (
                    "🎉 <b>1-CLICK PURCHASE SUCCESSFUL!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📦 <b>Product:</b> Phanthom Android + IOS ({plan_display})\n"
                    f"🔑 <b>License Key:</b> <code>{assigned_key}</code>\n"
                    f"💼 <b>Remaining Balance:</b> <code>₹{get_user_balance(user.id):.2f}</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n🚀 <i>Enjoy your game!</i>"
                )
                try:
                    await query.message.edit_text(success_msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Home", callback_data="home")]]), parse_mode="HTML")
                except Exception:
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
                        f"📦 <b>Product:</b> Phanthom Android + IOS ({plan_display})\n"
                        f"🔑 <b>Key Delivered:</b> <code>{assigned_key}</code>\n"
                        f"💵 <b>Price Paid:</b> ₹{base_price:.2f}\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                    )
                    await context.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=admin_alert, parse_mode="HTML")
                except Exception as e:
                    print(f"Error sending admin wallet alert: {e}")
            else:
                await query.message.reply_text("❌ Insufficient balance!")

        elif data.startswith("upipay_"):
            plan = data.replace("upipay_", "")
            base_price = get_product_price(plan)
            expiry_time = time.time() + QR_EXPIRY_SECONDS
            order_id = f"ORD{random.randint(100000, 999999)}"
            with data_lock:
                pending_orders = get_pending_orders()
                while True:
                    unique_amount = base_price + (random.randint(1, 99) * 0.01)
                    if not any(abs(o["amount"] - unique_amount) < 0.001 for o in pending_orders.values()):
                        break
                pending_orders[str(user.id)] = {
                    "type": "product", "plan": plan,
                    "amount": unique_amount, "expiry": expiry_time, "order_id": order_id,
                    "msg_id": None, "user_name": user.full_name, "username": f"@{user.username}" if user.username else "None"
                }
                set_pending_orders(pending_orders)
            
            upi_link = f"upi://pay?pa={FAMPAY_UPI}&pn=Momshad%20Khan&am={unique_amount:.2f}&cu=INR"
            qr_url = f"https://quickchart.io/qr?text={quote(upi_link)}&size=300&margin=2&format=png"
            checkout_text = (
                "💳 <b>UNIVERSAL UPI CHECKOUT</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Product:</b> Phanthom Android + IOS ({plan.replace('_', ' ').title()})\n"
                f"💰 <b>Amount:</b> ₹{unique_amount:.2f} INR\n"
                f"🔒 <b>Order:</b> {order_id}\n"
                f"⏱️ <b>UPI ID:</b> {FAMPAY_UPI}\n"
                "⏳ <b>Valid for:</b> 5:00 minutes"
            )
            try:
                await query.message.delete()
                sent_msg = await context.bot.send_photo(
                    chat_id=user.id, photo=qr_url, caption=checkout_text,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back to Shop", callback_data="shop_phanthom")]]),
                    parse_mode="HTML"
                )
                with data_lock:
                    pending_orders = get_pending_orders()
                    if str(user.id) in pending_orders:
                        pending_orders[str(user.id)]["msg_id"] = sent_msg.message_id
                        set_pending_orders(pending_orders)
            except Exception as e:
                print(f"Error sending upipay QR: {e}")

        elif data == "deposit_menu":
            keyboard = [
                [InlineKeyboardButton("➕ Add ₹50", callback_data="dep_50"), InlineKeyboardButton("➕ Add ₹100", callback_data="dep_100")],
                [InlineKeyboardButton("➕ Add ₹200", callback_data="dep_200"), InlineKeyboardButton("➕ Add ₹500", callback_data="dep_500")],
                [InlineKeyboardButton("« Back to Home", callback_data="home")]
            ]
            try:
                await query.message.edit_text("💰 <b>DEPOSIT BALANCE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Select amount to add to wallet:</i>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            except Exception:
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
                print(f"Error sending deposit QR: {e}")

        elif data == "profile":
            prof_text = (
                "👤 <b>RESELLER PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📛 <b>Name:</b> {user.full_name}\n"
                f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
                f"💼 <b>Wallet Balance:</b> <code>₹{get_user_balance(user.id):.2f}</code>\n"
                "👑 <b>Status:</b> X Panel Store 🟢\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
            try:
                await query.message.edit_text(prof_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            except Exception:
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
            try:
                await query.message.edit_text(hist_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            except Exception:
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
            try:
                await query.message.edit_text(ref_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            except Exception:
                try:
                    await query.message.delete()
                except:
                    pass
                await context.bot.send_message(chat_id=user.id, text=ref_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

        elif data in ["share", "support"]:
            texts = {
                "share": f"🌐 <b>SHARE OUR BOT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\nInvite your friends to X Panel Store:\n👉 https://t.me/{context.bot.username}",
                "support": f"🆘 <b>HELP LINE SUPPORT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\nNeed assistance?\n💬 Contact Owner: <b>{ADMIN_USERNAME}</b>"
            }
            keyboard = [[InlineKeyboardButton("« Back to Home", callback_data="home")]]
            try:
                await query.message.edit_text(texts[data], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            except Exception:
                try:
                    await query.message.delete()
                except:
                    pass
                await context.bot.send_message(chat_id=user.id, text=texts[data], reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    except Exception as e:
        print(f"Error in button_handler: {e}")

async def init_telegram_bot():
    global bot_loop
    bot_loop = asyncio.get_running_loop()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("backup", backup_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    await application.initialize()
    await application.start()

    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        webhook_url = f"{render_url.rstrip('/')}/{BOT_TOKEN}"
        await application.bot.set_webhook(url=webhook_url)
        print(f"Webhook successfully set to: {webhook_url}")
    else:
        print("RENDER_EXTERNAL_URL not found. Webhook URL needs to be set manually if needed.")

    asyncio.create_task(check_qr_expiry_background())

def run_bot_in_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_telegram_bot())
    loop.run_forever()

if __name__ == "__main__":
    t = Thread(target=run_bot_in_thread, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, use_reloader=False)
