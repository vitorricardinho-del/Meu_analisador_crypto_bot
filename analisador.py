import requests
import pandas as pd

# ⚠️ COLE AQUI AS SUAS CHAVES DO TELEGRAM
TOKEN_TELEGRAM = "8208992176:AAE9DvaosgaH6Yyx0xUaui5J0jYJ6U8VIGI"
CHAT_ID_TELEGRAM = "8336469634"

def enviar_mensagem_telegram(mensagem):
    """Envia uma notificação formatada direto para o seu Telegram"""
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {
        "chat_id": CHAT_ID_TELEGRAM,
        "text": mensagem,
        "parse_mode": "Markdown"  # Permite usar negrito (*text*) e emojis de forma limpa
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("🚀 Notificação enviada para o Telegram com sucesso!")
        else:
            print(f"❌ Erro ao enviar para o Telegram: {response.text}")
    except Exception as e:
        print(f"Erro de conexão com o Telegram: {e}")

def buscar_dados_binance(symbol="BANANAS31USDT", interval="1h", limit=50):
    """Busca o histórico de velas na API da Binance"""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        response = requests.get(url, params=params)
        df = pd.DataFrame(response.json(), columns=[
            'tempo_abertura', 'abertura', 'maximo', 'minimo', 'fechamento', 
            'volume', 'tempo_fechamento', 'volume_moeda_cotacao', 
            'numero_trades', 'volume_compra_ativo', 'volume_compra_cotacao', 'ignore'
        ])
        df['fechamento'] = df['fechamento'].astype(float)
        df['volume'] = df['volume'].astype(float)
        return df
    except Exception as e:
        print(f"Erro Binance: {e}")
        return None

def disparar_analise_automatica(moeda="BANANAS31USDT"):
    """Executa a lógica matemática e monta o relatório para o Telegram"""
    print(f"🔄 Analisando {moeda}...")
    df = buscar_dados_binance(moeda)
    
    if df is not None:
        # Calcula Médias 9 e 21
        df['MA_9'] = df['fechamento'].rolling(window=9).mean()
        df['MA_21'] = df['fechamento'].rolling(window=21).mean()
        df['MA_Volume'] = df['volume'].rolling(window=20).mean()
        
        vela_atual = df.iloc[-2]
        vela_anterior = df.iloc[-3]
        
        preco_atual = vela_atual['fechamento']
        volume_atual = vela_atual['volume']
        volume_medio = vela_atual['MA_Volume']
        
        # Lógica dos Cruzamentos
        cruzou_para_alta = (vela_anterior['MA_9'] <= vela_anterior['MA_21']) and (vela_atual['MA_9'] > vela_atual['MA_21'])
        cruzou_para_baixa = (vela_anterior['MA_9'] >= vela_anterior['MA_21']) and (vela_atual['MA_9'] < vela_atual['MA_21'])
        volume_forte = volume_atual > volume_medio
        
        # Montagem do Texto em Markdown (Visual Limpo)
        mensagem = f"🤖 *RELATÓRIO DE TENDÊNCIA*\n"
        mensagem += f"📊 *Ativo:* {moeda}\n"
        mensagem += f"💵 *Preço:* {preco_atual}\n"
        mensagem += f"🔊 *Volume:* {'Acima da Média 🔥' if volume_forte else 'Normal ⏳'}\n"
        mensagem += f"---------------------------------------\n"
        
        if cruzou_para_alta:
            mensagem += f"🚨 *STATUS:* 🚀 *SINAL DE ALTA DETECTADO!*\n"
            mensagem += f"A média rápida cruzou para cima da lenta. Tendência revertendo para alta."
            enviar_mensagem_telegram(mensagem)
        elif cruzou_para_baixa:
            mensagem += f"🚨 *STATUS:* 📉 *SINAL DE BAIXA DETECTADO!*\n"
            mensagem += f"A média rápida cruzou para baixo. Atenção com a queda."
            enviar_mensagem_telegram(mensagem)
        else:
            # APENAS PARA TESTE: Vamos forçar o envio para ver se o Telegram está conectado!
            mensagem += f"⏳ *STATUS:* Tendência mantida.\n"
            if vela_atual['MA_9'] > vela_atual['MA_21']:
                mensagem += f"O preço segue estável em *TENDÊNCIA DE ALTA* 📈"
            else:
                mensagem += f"O preço segue estável em *TENDÊNCIA DE BAIXA* 📉"
            
            print("🔄 Forçando envio de teste para o Telegram...")
            enviar_mensagem_telegram(mensagem)

if __name__ == "__main__":
    # Teste inicial rodando para BANANAS31USDT
    disparar_analise_automatica()