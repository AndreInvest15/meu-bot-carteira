import telebot
import requests
from apscheduler.schedulers.background import BackgroundScheduler
import sqlite3
import os
import threading
from flask import Flask
from datetime import datetime

TOKEN = os.environ.get("TOKEN")  # ← o Render vai pegar automaticamente
bot = telebot.TeleBot(TOKEN)
user_id = None

# Banco de dados
conn = sqlite3.connect('carteira.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS carteira (ticker TEXT PRIMARY KEY, tipo TEXT, quantidade REAL, preco_medio REAL, preco_alvo REAL)''')
c.execute('''CREATE TABLE IF NOT EXISTS ultimos_div (ticker TEXT PRIMARY KEY, ultima_data TEXT)''')
conn.commit()

# ======================= FLASK PARA RENDER =======================
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot de carteira está online 24h!"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# ======================= COMANDOS DO BOT =======================
@bot.message_handler(commands=['start'])
def start(message):
    global user_id
    user_id = message.chat.id
    bot.reply_to(message, "✅ Bot online 24h no Render!\nComandos:\n/add TICKER qtd preco_medio preco_alvo\n/carteira\n/alertas")

@bot.message_handler(commands=['add'])
def add(message):
    try:
        _, ticker, qtd, pmedio, palvo = message.text.split()
        qtd = float(qtd); pmedio = float(pmedio); palvo = float(palvo)
        ticker = ticker.upper().replace('.SA', '')
        tipo = "FII" if "11" in ticker else "AÇÃO"
        c.execute("INSERT OR REPLACE INTO carteira VALUES (?,?,?,?,?)", (ticker, tipo, qtd, pmedio, palvo))
        conn.commit()
        bot.reply_to(message, f"✅ {ticker} adicionado!")
    except:
        bot.reply_to(message, "❌ Use: /add TICKER quantidade preco_medio preco_alvo")

@bot.message_handler(commands=['carteira'])
def ver_carteira(message):
    c.execute("SELECT * FROM carteira")
    rows = c.fetchall()
    if not rows:
        bot.reply_to(message, "Carteira vazia!")
        return
    texto = "📊 Sua Carteira (brapi.dev):\n\n"
    valor_total = 0
    for row in rows:
        ticker = row[0]
        try:
            r = requests.get(f"https://brapi.dev/api/quote/{ticker}?fundamental=true&dividends=true", timeout=10)
            data = r.json()['results'][0]
            preco = data.get('regularMarketPrice') or data.get('lastPrice', 0)
            pvp = data.get('priceToBookValue', 0)
            dy = data.get('dividendYield', 0) * 100
            valor = preco * row[2]
            valor_total += valor
            lucro = (preco - row[3]) * row[2]
            texto += f"{ticker} ({row[1]}): {row[2]:.0f} cotas @ R${preco:.2f}\n"
            texto += f"Valor: R${valor:.2f} | Lucro: R${lucro:.2f}\n"
            texto += f"P/VP: {pvp:.2f} | DY: {dy:.1f}%\nAlvo compra: R${row[4]:.2f}\n\n"
        except:
            texto += f"{ticker}: Erro ao buscar preço\n\n"
    texto += f"💰 Valor total: R${valor_total:.2f}"
    bot.reply_to(message, texto)

@bot.message_handler(commands=['alertas'])
def alertas(message):
    bot.reply_to(message, "✅ Monitoramento 24h ativado no Render!")

def checar_tudo():
    if user_id is None: return
    c.execute("SELECT * FROM carteira")
    for row in c.fetchall():
        ticker = row[0]
        preco_alvo = row[4]
        try:
            r = requests.get(f"https://brapi.dev/api/quote/{ticker}?dividends=true", timeout=10)
            data = r.json()['results'][0]
            preco = data.get('regularMarketPrice') or data.get('lastPrice', 0)

            if preco > 0 and preco <= preco_alvo:
                bot.send_message(user_id, f"🚨 HORA DE COMPRAR!\n{ticker} está baixo!\nPreço atual: R${preco:.2f} (alvo: R${preco_alvo:.2f})")

            if "11" in ticker and 'dividendsData' in data:
                divs = data['dividendsData'].get('cashDividends', [])
                if divs:
                    ultima = max(divs, key=lambda x: x.get('date', ''))['date'][:10]
                    c.execute("SELECT ultima_data FROM ultimos_div WHERE ticker=?", (ticker,))
                    salvo = c.fetchone()
                    if not salvo or salvo[0] != ultima:
                        c.execute("INSERT OR REPLACE INTO ultimos_div VALUES (?,?)", (ticker, ultima))
                        conn.commit()
                        bot.send_message(user_id, f"📄 NOVO RELATÓRIO GERENCIAL!\n{ticker} pagou dividendo em {ultima}\nVerifique na gestora!")
        except:
            pass

# ======================= INICIAR TUDO =======================
scheduler = BackgroundScheduler()
scheduler.add_job(checar_tudo, 'interval', hours=1)
scheduler.start()

print("🤖 Bot Render 24h rodando...")

# Roda o Flask em segundo plano + o bot
threading.Thread(target=run_flask, daemon=True).start()
bot.infinity_polling()
