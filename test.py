import pyodbc
import os
from openai import OpenAI
from difflib import get_close_matches

# ========================
# Configurações de conexão SQL Server
# ========================
SERVER = r"localhost"  # ou "localhost\SQLEXPRESS"
DATABASE = "BahIAna"

def conectar_banco():
    try:
        conn = pyodbc.connect(
            r'DRIVER={ODBC Driver 17 for SQL Server};'
            f'SERVER={SERVER};'
            f'DATABASE={DATABASE};'
            'Trusted_Connection=yes;'
        )
        return conn
    except Exception as e:
        print("❌ Erro ao conectar no banco:", e)
        return None

# ========================
# Configuração da API OpenAI
# ========================
API_KEY = ""
if not API_KEY:
    raise ValueError("❌ Defina a variável de ambiente OPENAI_API_KEY")
client = OpenAI(api_key=API_KEY)

# ========================
# Funções auxiliares
# ========================
def interpretar_pergunta_chatgpt(pergunta, disciplinas_cadastradas):
    """
    Usa o ChatGPT para entender o que o usuário quer:
    - disciplina (se houver)
    - data (pode ser 'hoje', 'amanhã', 'segunda', '10/10', etc.)
    - hora (ex: 'agora', '19h', 'manhã')
    - sala ou pavilhão (ex: 'sala 203', 'Pavilhão D')
    - intenção (ex: 'consultar aula', 'consultar ocupação de sala')
    """
    prompt = f"""
Você é um assistente de reservas de aulas.
Analise a pergunta abaixo e retorne um JSON com o formato:
{{
  "intencao": "consultar_aula" ou "consultar_sala",
  "disciplina": "<disciplina ou vazio>",
  "data": "<data ou palavra como 'hoje', 'amanhã', 'terça'>",
  "hora": "<hora ou período como 'manhã', 'tarde', 'agora'>",
  "sala": "<número da sala ou vazio>",
  "pavilhao": "<nome do pavilhão ou vazio>"
}}

Pergunta: "{pergunta}"

As disciplinas disponíveis são: {', '.join(disciplinas_cadastradas)}.
Responda **apenas o JSON** sem explicações.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        import json
        data = json.loads(response.choices[0].message.content)
        return data
    except Exception as e:
        print("❌ Erro ao interpretar pergunta:", e)
        return None
    """
    Usa ChatGPT para extrair a disciplina mencionada na pergunta do usuário.
    Corrige erros de digitação e sugere a disciplina mais próxima.
    """
    prompt = f"""
Você é um assistente que ajuda alunos a encontrar aulas. 
Analise a seguinte pergunta do usuário e extraia **apenas o nome da disciplina**:

"{pergunta}"

As disciplinas disponíveis são: {', '.join(disciplinas_cadastradas)}.

- Se houver erro de digitação, retorne a disciplina mais próxima.
- Retorne somente o nome da disciplina, sem explicações.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        disciplina = response.choices[0].message.content.strip()
        return disciplina
    except Exception as e:
        print("❌ Erro ao chamar ChatGPT:", e)
        return None

from datetime import datetime, timedelta
import re

def normalizar_data_hora(data_str, hora_str):
    hoje = datetime.now()

    # Normalizar data
    data_str = (data_str or "").lower().strip()
    if data_str in ["", "hoje"]:
        data = hoje.date()
    elif data_str == "amanhã":
        data = hoje.date() + timedelta(days=1)
    elif re.match(r"\d{1,2}/\d{1,2}", data_str):  # ex: 10/10
        dia, mes = map(int, data_str.split('/'))
        ano = hoje.year
        data = datetime(ano, mes, dia).date()
    else:
        data = hoje.date()

    # Normalizar hora
    hora_str = (hora_str or "").lower().strip()
    if hora_str in ["", "agora"]:
        hora_inicial = hoje.time()
        hora_final = (hoje + timedelta(hours=1)).time()
    elif "manhã" in hora_str:
        hora_inicial, hora_final = (8, 0), (12, 0)
    elif "tarde" in hora_str:
        hora_inicial, hora_final = (13, 0), (18, 0)
    elif "noite" in hora_str:
        hora_inicial, hora_final = (18, 0), (22, 0)
    elif re.match(r"\d{1,2}h", hora_str):
        h = int(hora_str.replace("h", ""))
        hora_inicial, hora_final = (h, 0), (h+1, 0)
    else:
        hora_inicial, hora_final = (7, 0), (23, 0)

    return data, hora_inicial, hora_final

def buscar_aula_flexivel(info):
    conn = conectar_banco()
    if not conn:
        return "❌ Desculpe, não consegui acessar o banco de dados."
    cursor = conn.cursor()

    data, hora_ini, hora_fim = normalizar_data_hora(info.get("data"), info.get("hora"))
    params = []
    query = """
        SELECT disciplina, campus, pavilhao, sala, data_aula, hora_inicio, hora_fim
        FROM ReservasAulas
        WHERE status='Confirmada'
    """

    # Filtros dinâmicos
    if info.get("disciplina"):
        query += " AND disciplina LIKE ?"
        params.append(f"%{info['disciplina']}%")
    if info.get("sala"):
        query += " AND sala LIKE ?"
        params.append(f"%{info['sala']}%")
    if info.get("pavilhao"):
        query += " AND pavilhao LIKE ?"
        params.append(f"%{info['pavilhao']}%")
    query += " AND CAST(data_aula AS date) = ?"
    params.append(data)

    cursor.execute(query, params)
    resultados = cursor.fetchall()
    conn.close()

    if not resultados:
        return "⚠️ Nenhuma aula encontrada para os critérios informados."

    resposta = []
    for r in resultados:
        disciplina, campus, pav, sala, data_aula, h_ini, h_fim = r
        resposta.append(f"📘 {disciplina} — {campus}, {pav}, sala {sala}, "
                        f"{h_ini.strftime('%H:%M')}–{h_fim.strftime('%H:%M')} em {data_aula.strftime('%d/%m')}")

    return "\n".join(resposta)

# ========================
# Chat interativo
# ========================
def chat():
    print("🤖 Olá! Eu sou seu assistente de aulas.")
    print("Pergunte sobre qualquer aula confirmada. (Digite 'sair' para encerrar)\n")

    # Pega todas as disciplinas disponíveis
    conn = conectar_banco()
    if not conn:
        print("❌ Não foi possível conectar ao banco de dados. Encerrando.")
        return

    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT disciplina FROM ReservasAulas WHERE status='Confirmada'")
    disciplinas_cadastradas = [row[0] for row in cursor.fetchall()]
    conn.close()

    while True:
        pergunta = input("Você: ").strip()
        if pergunta.lower() in ["sair", "exit", "quit"]:
            print("🤖 Até mais! Boa sorte com suas aulas.")
            break

        info = interpretar_pergunta_chatgpt(pergunta, disciplinas_cadastradas)
        if not info:
            print("🤖 Desculpe, não entendi sua pergunta.\n")
            continue

        resposta = buscar_aula_flexivel(info)
        print("🤖", resposta, "\n")

# ========================
# Execução
# ========================
if __name__ == "__main__":
    chat()
