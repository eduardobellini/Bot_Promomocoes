import requests
import time
from bs4 import BeautifulSoup
from telegram import Bot

TOKEN = "8633387104:AAGvRAQHJ_umx4d-l4EmeKJWTpQmRqT65Sc"
CHAT_ID = "6960388628"

bot = Bot(token=TOKEN)

placas = ["RTX", "GTX", "RX"]

def enviar(nome, preco, link, loja):
    mensagem = f"""
🔥 Promoção encontrada

🏪 Loja: {loja}
🎮 Produto: {nome}
💰 Preço: {preco}

🔗 {link}
"""
    bot.send_message(chat_id=CHAT_ID, text=mensagem)

# KABUM
def kabum():
    url = "https://www.kabum.com.br/hardware/placa-de-video-vga"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    produtos = soup.find_all("span", class_="nameCard")

    for p in produtos:
        nome = p.text

        if any(x in nome for x in placas):
            enviar(nome, "ver site", url, "Kabum")

# MERCADO LIVRE
def mercado_livre():
    url = "https://lista.mercadolivre.com.br/placa-de-video"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    produtos = soup.select(".ui-search-item__title")

    for p in produtos:
        nome = p.text

        if any(x in nome for x in placas):
            enviar(nome, "ver site", url, "Mercado Livre")

# AMAZON
def amazon():
    url = "https://www.amazon.com.br/s?k=placa+de+video"
    r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")

    produtos = soup.select("h2 span")

    for p in produtos:
        nome = p.text

        if any(x in nome for x in placas):
            enviar(nome, "ver site", url, "Amazon")

# MAGAZINE LUIZA
def magalu():
    url = "https://www.magazineluiza.com.br/busca/placa-de-video/"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    produtos = soup.find_all("h2")

    for p in produtos:
        nome = p.text

        if any(x in nome for x in placas):
            enviar(nome, "ver site", url, "Magazine Luiza")

# SHOPEE
def shopee():
    url = "https://shopee.com.br/search?keyword=placa%20de%20video"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    produtos = soup.find_all("div")

    for p in produtos:
        nome = p.text

        if any(x in nome for x in placas):
            enviar(nome, "ver site", url, "Shopee")

# ALIEXPRESS
def aliexpress():
    url = "https://www.aliexpress.com/wholesale?SearchText=gpu"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    produtos = soup.find_all("h1")

    for p in produtos:
        nome = p.text

        if any(x in nome for x in placas):
            enviar(nome, "ver site", url, "AliExpress")

def executar():
    kabum()
    mercado_livre()
    amazon()
    magalu()
    shopee()
    aliexpress()

while True:
    try:
        print("Procurando promoções...")
        executar()

    except Exception as e:
        print("Erro:", e)

    time.sleep(600)