import requests
import pandas as pd
import telebot
import os
import time
import schedule
import threading



#CONFIGURAÇÃO DOS TOKENS (Usa variáveis de ambiente no Railway ou o padrão local)
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM")
CHAT_ID_TELEGRAM = os.getenv("CHAT_ID_TELEGRAM")

# Inicializa o bot do Telegram para escuta de comandos
bot = telebot.TeleBot(TOKEN_TELEGRAM)

# VARIÁVEIS GLOBAIS DE CONTROLE DO AGENDAMENTO AUTOMÁTICO
moeda_automatica = "BANANAS31USDT"
tempo_automatico = "1h"
alerta_ativo = False

# 🧠 VARIÁVEL GLOBAL DE MEMÓRIA PARA PAGINAÇÃO DAS QUEDAS
moedas_ja_mostradas = []


def buscar_dados_binance(symbol, interval="1h", limit=50):
    """Busca o histórico de velas na API da Binance"""
    url = "https://api3.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        response = requests.get(url, params=params)
        if response.status_code == 400:
            return None
            
        df = pd.DataFrame(response.json(), columns=[
            'tempo_abertura', 'abertura', 'maximo', 'minimo', 'fechamento', 
            'volume', 'tempo_fechamento', 'volume_moeda_cotacao', 
            'numero_trades', 'volume_compra_ativo', 'volume_compra_cotacao', 'ignore'
        ])
        df['fechamento'] = df['fechamento'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        print(f"Erro Binance Klines: {e}")
        return None

def buscar_forca_livro_ofertas(symbol):
    """Acessa a profundidade de mercado da Binance e calcula a porcentagem de força"""
    url = "https://api.binance.com/api/v3/depth"
    params = {"symbol": symbol, "limit": 20}
    try:
        response = requests.get(url, params=params)
        if response.status_code != 200:
            return 50.0, 50.0
            
        dados = response.json()
        total_compras = sum(float(ordem[1]) for ordem in dados['bids'])
        total_vendas = sum(float(ordem[1]) for ordem in dados['asks'])
        total_geral = total_compras + total_vendas
        
        if total_geral == 0:
            return 50.0, 50.0
            
        porcentagem_compra = (total_compras / total_geral) * 100
        porcentagem_venda = (total_vendas / total_geral) * 100
        
        return porcentagem_compra, porcentagem_venda
    except Exception as e:
        print(f"Erro ao buscar Livro de Ofertas: {e}")
        return 50.0, 50.0

def obter_maiores_quedas_24h(resetar_memoria=False):
    """Varre a Binance e filtra RIGOROSAMENTE apenas criptomoedas grandes e populares em queda com paginação"""
    global moedas_ja_mostradas
    
    if resetar_memoria:
        moedas_ja_mostradas = []
        
    url = "https://api1.binance.com/api/v3/ticker/24hr"
    try:
        response = requests.get(url)
        if response.status_code != 200:
            return "❌ Erro ao conectar com o painel de tickers da Binance."
            
        dados = response.json()
        df = pd.DataFrame(dados)
        
        # 1. Filtra apenas pares em USDT
        df = df[df['symbol'].str.endswith('USDT')]
        
        # 2. Converte colunas para números para podermos filtrar com precisão matemática
        df['priceChangePercent'] = df['priceChangePercent'].astype(float)
        df['lastPrice'] = df['lastPrice'].astype(float)
        df['quoteVolume'] = df['quoteVolume'].astype(float)  # Volume medido em DÓLARES (USDT)
        
        # 🛡️ FILTRO DE POPULARIDADE: Só aceita moedas com mais de 50 MILHÕES de dólares movimentados nas últimas 24h!
        df = df[df['quoteVolume'] >= 50000000.0]
        
        # 3. LISTA NEGRA: Remove stablecoins, moedas fiduciárias e tokens de alavancagem falsos
        ignorar = 'UP|DOWN|BEAR|BULL|USDC|BUSD|EUR|BRL|GBP|FDUSD|TUSD|DAI|USDE'
        df = df[~df['symbol'].str.contains(ignorar)]
        
        # 🛡️ FILTRO DE MEMÓRIA: Remove da tabela as moedas que o usuário já viu nesta sessão
        if len(moedas_ja_mostradas) > 0:
            df = df[~df['symbol'].isin(moedas_ja_mostradas)]
        
        # 4. Ordena do menor para o maior (as maiores quedas reais no topo)
        df_quedas = df.sort_values(by='priceChangePercent', ascending=True).head(5)
        
        if df_quedas.empty:
            return "⏳ Você já viu todas as moedas populares em queda no momento! Digite `/perdedores` para resetar a lista."
            
        inicio_ranking = len(moedas_ja_mostradas) + 1
        mensagem = f"📉 *QUEDAS EM CRIPTOS POPULARES (Posições {inicio_ranking} a {inicio_ranking + len(df_quedas) - 1})*\n"
        mensagem += "Filtrado apenas por moedas de alta relevância (Volume > $50M):\n"
        mensagem += "---------------------------------------\n"
        
        for i, (index, linha) in enumerate(df_quedas.iterrows()):
            moeda_nome = linha['symbol'].replace('USDT', '')
            vol_milhoes = linha['quoteVolume'] / 1000000
            
            # Alimenta a memória global com a moeda mostrada
            moedas_ja_mostradas.append(linha['symbol'])
            
            mensagem += f"🔹 *{moeda_nome}/USDT*\n"
            mensagem += f"🔻 Variação: `{linha['priceChangePercent']:.2f}%`\n"
            mensagem += f"💵 Preço: `{linha['lastPrice']}`\n"
            mensagem += f"🔊 Vol 24h: `${vol_milhoes:.1f}M`\n"
            mensagem += "---------------------------------------\n"
            
        mensagem += "👉 _Quer ver mais outras 5? Digite_ /mais\n"
        mensagem += "👉 _Quer resetar e voltar pro Top 1? Digite_ /perdedores"
        return mensagem
    except Exception as e:
        print(f"Erro ao buscar maiores quedas: {e}")
        return "❌ Ocorreu um erro interno ao processar a lista de quedas."

def gerar_relatorio_tendencia(moeda, tempo_grafico, eh_automatico=False):
    """Executa a lógica matemática e RETORNA a string do relatório formatada"""
    print(f"🔄 Analisando {moeda} no gráfico de {tempo_grafico}...")
    df = buscar_dados_binance(moeda, interval=tempo_grafico)
    
    if df is None:
        return f"❌ *Erro:* O ativo `{moeda}` não foi encontrado na Binance. Verifique o código!"
        
    porcentagem_compra, porcentagem_venda = buscar_forca_livro_ofertas(moeda)
    
    df['MA_9'] = df['fechamento'].rolling(window=9).mean()
    df['MA_21'] = df['fechamento'].rolling(window=21).mean()
    df['MA_Volume'] = df['volume'].rolling(window=20).mean()
    
    vela_atual = df.iloc[-2]
    vela_anterior = df.iloc[-3]
    
    preco_atual = vela_atual['fechamento']
    volume_forte = vela_atual['volume'] > vela_atual['MA_Volume']
    
    titulo = "🚨 *ALERTA AUTOMÁTICO DE ROTINA*" if eh_automatico else "🤖 *RELATÓRIO DE TENDÊNCIA*"
    
    mensagem = f"{titulo}\n"
    mensagem += f"📊 *Ativo:* {moeda}\n"
    mensagem += f"⏱️ *Gráfico:* {tempo_grafico}\n"
    mensagem += f"💵 *Preço:* {preco_atual}\n"
    mensagem += f"🔊 *Volume:* {'Acima da Média 🔥' if volume_forte else 'Normal ⏳'}\n"
    mensagem += f"---------------------------------------\n"
    mensagem += f"⚔️ *Força do Livro de Ofertas:*\n"
    mensagem += f"🟢 Compradores: {porcentagem_compra:.1f}%\n"
    mensagem += f"🔴 Vendedores: {porcentagem_venda:.1f}%\n"
    
    if porcentagem_compra > 55.0:
        mensagem += f"👉 _Pressão de COMPRA dominante no momento! 🔥_\n"
    elif porcentagem_venda > 55.0:
        mensagem += f"👉 _Pressão de VENDA dominante no momento! ⚠️_\n"
    else:
        mensagem += f"👉 _Disputa equilibrada no book de ordens. ⏳_\n"
        
    mensagem += f"---------------------------------------\n"
    
    cruzou_para_alta = (vela_anterior['MA_9'] <= vela_anterior['MA_21']) and (vela_atual['MA_9'] > vela_atual['MA_21'])
    cruzou_para_baixa = (vela_anterior['MA_9'] >= vela_anterior['MA_21']) and (vela_atual['MA_9'] < vela_atual['MA_21'])
    
    if cruzou_para_alta:
        mensagem += f"🚨 *STATUS:* 🚀 *SINAL DE ALTA DETECTADO!*\nA média rápida (9) cruzou para cima da lenta (21)."
    elif cruzou_para_baixa:
        mensagem += f"🚨 *STATUS:* 📉 *SINAL DE BAIXA DETECTADO!*\nA média rápida (9) cruzou para baixo da lenta (21)."
    else:
        mensagem += f"⏳ *STATUS:* Tendência histórica estável.\n"
        if vela_atual['MA_9'] > vela_atual['MA_21']:
            mensagem += f"O preço segue trabalhando em *TENDÊNCIA DE ALTA* 📈"
        else:
            mensagem += f"O preço segue trabalhando em *TENDENSIA DE BAIXA* 📉"
            
    return mensagem

def enviar_alerta_agendado():
    global alerta_ativo, moeda_automatica, tempo_automatico
    if alerta_ativo:
        print(f"⏰ Cronômetro acionado! Disparando alerta de {moeda_automatica}...")
        relatorio = gerar_relatorio_tendencia(moeda_automatica, tempo_automatico, eh_automatico=True)
        bot.send_message(CHAT_ID_TELEGRAM, relatorio, parse_mode="Markdown")

def extrair_parametros(texto_mensagem):
    partes = texto_mensagem.split()
    moeda = "BANANAS31"
    tempo = "1h"
    if len(partes) > 1: moeda = partes[1].upper()
    if len(partes) > 2: tempo = partes[2].lower()
    if tempo in ["1", "4"]: tempo = f"{tempo}h"
    if not moeda.endswith("USDT"): moeda = f"{moeda}USDT"
    return moeda, tempo

# =====================================================================
# 🤖 SEÇÃO DE COMANDOS INTERATIVOS DO TELEGRAM
# =====================================================================

@bot.message_handler(commands=['perdedores', 'baixas'])
def responder_maiores_quedas(message):
    bot.reply_to(message, "🔍 Buscando o topo da lista de quedas populares... Aguarde.")
    ranking = obter_maiores_quedas_24h(resetar_memoria=True)
    bot.send_message(message.chat.id, ranking, parse_mode="Markdown")

@bot.message_handler(commands=['mais', 'proximas'])
def responder_proximas_quedas(message):
    bot.reply_to(message, "⏭️ Pulando as moedas que você já viu e buscando as próximas da fila...")
    ranking = obter_maiores_quedas_24h(resetar_memoria=False)
    bot.send_message(message.chat.id, ranking, parse_mode="Markdown")

@bot.message_handler(commands=['alertas'])
def activar_alertas_automaticos(message):
    global moeda_automatica, tempo_automatico, alerta_ativo
    moeda_automatica, tempo_automatico = extrair_parametros(message.text)
    
    if tempo_automatico not in ["1h", "4h"]:
        bot.reply_to(message, "⚠️ Tempos permitidos para alertas: `1h` ou `4h`.", parse_mode="Markdown")
        return

    df_teste = buscar_dados_binance(moeda_automatica, interval=tempo_automatico)
    if df_teste is None:
        bot.reply_to(message, f"❌ Erro: O ativo `{moeda_automatica}` não existe na Binance. Agendamento cancelado.")
        return

    schedule.clear()
    if tempo_automatico == "1h":
        schedule.every().hour.at(":00").do(enviar_alerta_agendado)
    elif tempo_automatico == "4h":
        schedule.every(4).hours.do(enviar_alerta_agendado)

    alerta_ativo = True
    resposta = (
        f"🔔 *Alertas Automáticos Ligados!*\n\n"
        f"A partir de agora, vou monitorar *{moeda_automatica}* em `{tempo_automatico}` "
        f"e te enviar o relatório em toda virada de vela no gráfico!"
    )
    bot.reply_to(message, resposta, parse_mode="Markdown")

@bot.message_handler(commands=['parar'])
def parar_alertas(message):
    global alerta_ativo
    alerta_ativo = False
    schedule.clear()
    bot.reply_to(message, "🔕 *Alertas automáticos desligados.*", parse_mode="Markdown")

@bot.message_handler(commands=['status'])
def responder_status_rapido(message):
    moeda, tempo = extrair_parametros(message.text)
    if tempo not in ["1h", "4h"]:
        bot.reply_to(message, "⚠️ Tempos permitidos: `1h` ou `4h`.", parse_mode="Markdown")
        return

    df = buscar_dados_binance(moeda, interval=tempo)
    if df is None:
        bot.reply_to(message, f"❌ Erro: O ativo `{moeda}` não existe na API da Binance.")
        return

    df['MA_9'] = df['fechamento'].rolling(window=9).mean()
    df['MA_21'] = df['fechamento'].rolling(window=21).mean()
    
    vela_atual = df.iloc[-2]
    preco = vela_atual['fechamento']
    tendencia = "ALTA 📈" if vela_atual['MA_9'] > vela_atual['MA_21'] else "BAIXA 📉"
    
    resposta = f"📊 *{moeda}:* Gráfico `{tempo}`\n📌 Tendência atual: *{tendencia}*\n💵 Preço: {preco}"
    bot.reply_to(message, resposta, parse_mode="Markdown")

@bot.message_handler(commands=['analisar'])
def responder_analise_detalhada(message):
    moeda, tempo = extrair_parametros(message.text)
    if tempo not in ["1h", "4h"]:
        bot.reply_to(message, "⚠️ Tempos permitidos: `1h` ou `4h`.", parse_mode="Markdown")
        return

    bot.reply_to(message, f"🔄 Processando indicadores e livro de ordens de *{moeda}* em `{tempo}`...", parse_mode="Markdown")
    relatorio = gerar_relatorio_tendencia(moeda, tempo)
    bot.send_message(message.chat.id, relatorio, parse_mode="Markdown")

@bot.message_handler(commands=['help', 'ajuda'])
def enviar_ajuda(message):
    menu = (
        "🤖 *Painel de Controle Total do Robô:*\n\n"
        "⚡ *ATALHO RÁPIDO (Basta digitar o nome):*\n"
        "👉 `xrp` ou `sol` - Analisa direto o ativo no gráfico de 1h!\n\n"
        "🔥 *RADAR DE MERCADO PAGINADO (Oportunidades):*\n"
        "👉 `/perdedores` - Traz as top 1 a 5 maiores quedas reais (reseta a lista)\n"
        "👉 `/mais` - Descarta as que você já viu e traz as próximas 5 moedas da fila!\n\n"
        "📢 *ALERTAS AUTOMÁTICOS (O robô envia sozinho):*\n"
        "👉 `/alertas sol 1h` - Ativa relatórios de hora em hora\n"
        "👉 `/parar` - Desliga os envios agendados\n\n"
        "🔍 *CONSULTAS MANUAIS:*\n"
        "👉 `/status xrp 4h` - Resumo rápido da tendência em 4h\n"
        "👉 `/analisar doge 1h` - Relatório completo com Livro de Ofertas"
    )
    bot.reply_to(message, menu, parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def tratar_texto_direto(message):
    texto = message.text.strip().upper()
    if len(texto.split()) > 1: return
    moeda_teste = texto if texto.endswith("USDT") else f"{texto}USDT"
    df_teste = buscar_dados_binance(moeda_teste, interval="1h")
    if df_teste is not None:
        bot.reply_to(message, f"⚡ *Atalho Detectado!* Processando relatório de *{moeda_teste}* (1h)...", parse_mode="Markdown")
        relatorio = gerar_relatorio_tendencia(moeda_teste, "1h")
        bot.send_message(message.chat.id, relatorio, parse_mode="Markdown")

def rodar_cronometro():
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    print("🚀 Inicializando motor e agendador de tarefas...")
    t = threading.Thread(target=rodar_cronometro)
    t.daemon = True
    t.start()
    
    print("🤖 O Bot está online no Telegram com suporte à paginação dinâmica de moedas populares!")
    bot.infinity_polling()
