import telebot
import requests
import yfinance as yf
from apscheduler.schedulers.background import BackgroundScheduler
import sqlite3
import os
import threading
from flask import Flask

TOKEN = os.environ.get("TOKEN")
bot = telebot.TeleBot(TOKEN)
user_id = None

conn = sqlite3.connect('carteira.db', check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS carteira (ticker TEXT PRIMARY KEY, tipo TEXT, quantidade REAL, preco_medio REAL, preco_alvo REAL)''')
c.execute('''CREATE TABLE IF NOT EXISTS ultimos_div (ticker TEXT PRIMARY KEY, ultima_data TEXT)''')
conn.commit()

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Bot de carteira online 24h no Render (com fallback yfinance)!"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

@bot.message_handler(commands=['start'])
def start(message):
    global user_id
    user_id = message.chat.id
    bot.reply_to(message, "✅ Bot atualizado com fallback yfinance!\nAgora funciona com TODOS os tickers (incluindo GARE11)")

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
    texto = "📊 Sua Carteira (brapi + yfinance fallback):\n\n"
    valor_total = 0
    for row in rows:
        ticker = row[0]
        source = "brapi"
        try:
            # Tenta brapi primeiro
            r = requests.get(f"https://brapi.dev/api/quote/{ticker}?fundamental=true&dividends=true", timeout=8)
            data = r.json()['results'][0]
            preco = data.get('regularMarketPrice') or data.get('lastPrice', 0)
            pvp = data.get('priceToBookValue', 0)
            dy = data.get('dividendYield', 0) * 100
        except:
            # Fallback yfinance
            source = "yfinance"
            try:
                info = yf.Ticker(ticker + ".SA").info
                preco = info.get('regularMarketPrice') or info.get('currentPrice', 0)
                pvp = info.get('priceToBook', 0)
                dy = info.get('dividendYield', 0) * 100 if info.get('dividendYield') else 0
            except:
                preco = 0
                pvp = dy = 0

        if preco > 0:
            valor = preco * row[2]
            valor_total += valor
            lucro = (preco - row[3]) * row[2]
            texto += f"{ticker} ({row[1]}): {row[2]:.0f} cotas @ R${preco:.2f} ({source})\n"
            texto += f"Valor: R${valor:.2f} | Lucro: R${lucro:.2f}\n"
            texto += f"P/VP: {pvp:.2f} | DY: {dy:.1f}%\nAlvo compra: R${row[4]:.2f}\n\n"
        else:
            texto += f"{ticker}: Erro em ambas as fontes\n\n"
    texto += f"💰 Valor total da carteira: R${valor_total:.2f}"
    bot.reply_to(message, texto)

@bot.message_handler(commands=['alertas'])
def alertas(message):
    bot.reply_to(message, "✅ Monitoramento 24h ativado (brapi + yfinance)!")

def checar_tudo():
    if user_id is None: return
    c.execute("SELECT * FROM carteira")
    for row in c.fetchall():
        ticker = row[0]
        preco_alvo = row[4]
        try:
            # Tenta brapi
            r = requests.get(f"https://brapi.dev/api/quote/{ticker}?dividends=true", timeout=8)
            data = r.json()['results'][0]
            preco = data.get('regularMarketPrice') or data.get('lastPrice', 0)
            divs_data = data.get('dividendsData', {}).get('cashDividends', [])
        except:
            # Fallback yfinance
            try:
                yf_ticker = yf.Ticker(ticker + ".SA")
                preco = yf_ticker.info.get('regularMarketPrice') or yf_ticker.info.get('currentPrice', 0)
                divs_data = yf_ticker.dividends
            except:
                continue

        if preco > 0 and preco <= preco_alvo:
            bot.send_message(user_id, f"🚨 HORA DE COMPRAR!\n{ticker} está baixo!\nPreço atual: R${preco:.2f} (alvo: R${preco_alvo:.2f})")

        if "11" in ticker and len(divs_data) > 0:
            if isinstance(divs_data, list):  # brapi
                ultima = max(divs_data, key=lambda x: x.get('date', ''))['date'][:10]
            else:  # yfinance
                ultima = divs_data.index[-1].strftime('%Y-%m-%d')
            c.execute("SELECT ultima_data FROM ultimos_div WHERE ticker=?", (ticker,))
            salvo = c.fetchone()
            if not salvo or salvo[0] != ultima:
                c.execute("INSERT OR REPLACE INTO ultimos_div VALUES (?,?)", (ticker, ultima))
                conn.commit()
                bot.send_message(user_id, f"📄 NOVO RELATÓRIO GERENCIAL!\n{ticker} pagou dividendo em {ultima}\nVerifique na gestora!")

scheduler = BackgroundScheduler()
scheduler.add_job(checar_tudo, 'interval', hours=1)
scheduler.start()

print("🤖 Bot com fallback yfinance rodando...")
threading.Thread(target=run_flask, daemon=True).start()
bot.infinity_polling()
