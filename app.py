import streamlit as st
import os
import re
import asyncio
import edge_tts
import zipfile
import io
from PyPDF2 import PdfReader
from ebooklib import epub
import ebooklib
from bs4 import BeautifulSoup
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TYER, TRCK
import tempfile

st.set_page_config(page_title="Audiobook Cloud", page_icon="☁️")

VOZES = {
    "Francisca (Padrão - Fem)": "pt-BR-FranciscaNeural",
    "Antonio (Padrão - Masc)": "pt-BR-AntonioNeural",
    "Thalita (Jovem - Fem)": "pt-BR-ThalitaNeural",
    "Brenda (Clara - Fem)": "pt-BR-BrendaNeural",
    "Donato (Profunda - Masc)": "pt-BR-DonatoNeural",
    "Fabio (Madura - Masc)": "pt-BR-FabioNeural"
}

# ---------------- EXTRAÇÃO DE TEXTO ---------------- #
def extrair_texto(arquivo):
    if arquivo.name.endswith('.pdf'):
        reader = PdfReader(arquivo)
        textos = []
        for p in reader.pages:
            t = p.extract_text()
            if t:
                textos.append(t)
        return "\n".join(textos)
    else:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as tmp:
            tmp.write(arquivo.getvalue())
            tmp_path = tmp.name

        livro = epub.read_epub(tmp_path)
        texto = ""

        for item in livro.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            texto += soup.get_text(separator='\n') + "\n"

        os.unlink(tmp_path)
        return texto


# ---------------- SUMÁRIO ---------------- #
def extrair_sumario(texto):
    linhas = texto.split('\n')
    sumario = []
    encontrou = False

    for linha in linhas:
        linha = linha.strip()

        if re.search(r'sum[áa]rio|índice', linha, re.IGNORECASE):
            encontrou = True
            continue

        if encontrou:
            if len(linha) > 80:
                break
            if not linha:
                continue
            if 3 < len(linha) < 60:
                sumario.append(linha)
            if len(sumario) > 100:
                break

    return sumario


# ---------------- DIVISÃO POR SUMÁRIO ---------------- #
def dividir_por_sumario(texto, sumario):
    capitulos = []
    texto_lower = texto.lower()

    posicoes = []

    for item in sumario:
        pos = texto_lower.find(item.lower())
        if pos != -1:
            posicoes.append((pos, item))

    posicoes.sort()

    if len(posicoes) < 3:
        return []

    for i in range(len(posicoes)):
        inicio = posicoes[i][0]
        titulo = posicoes[i][1]

        fim = posicoes[i+1][0] if i+1 < len(posicoes) else len(texto)

        conteudo = texto[inicio:fim].strip()

        if len(conteudo) > 200:
            capitulos.append((titulo, conteudo))

    return capitulos


# ---------------- FALLBACK ---------------- #
def dividir_capitulos(texto):
    texto = texto.replace('\r', '\n')

    partes = re.split(r'\n\s*(Cap[ií]tulo\s+\d+|PARTE\s+\d+)\s*\n', texto)

    capitulos = []

    if len(partes) > 2:
        for i in range(1, len(partes), 2):
            titulo = partes[i]
            conteudo = partes[i+1] if i+1 < len(partes) else ""
            if len(conteudo) > 300:
                capitulos.append((titulo, conteudo))
    else:
        # divisão por tamanho
        tamanho = 3000
        inicio = 0
        i = 1
        while inicio < len(texto):
            fim = inicio + tamanho
            bloco = texto[inicio:fim]
            capitulos.append((f"Parte {i}", bloco))
            inicio = fim
            i += 1

    return capitulos


# ---------------- ESCOLHA ---------------- #
def dividir_inteligente(texto):
    sumario = extrair_sumario(texto)

    capitulos = dividir_por_sumario(texto, sumario)
    if capitulos:
        return capitulos, "sumario"

    capitulos = dividir_capitulos(texto)
    return capitulos, "fallback"


# 🔥 DIVISÃO PARA TTS (ESSENCIAL)
def dividir_texto_tts(texto, max_chars=1500):
    partes = []
    inicio = 0

    while inicio < len(texto):
        fim = inicio + max_chars
        trecho = texto[inicio:fim]

        ultimo_ponto = trecho.rfind('.')
        if ultimo_ponto != -1:
            fim = inicio + ultimo_ponto + 1

        partes.append(texto[inicio:fim])
        inicio = fim

    return partes


# ---------------- GERAÇÃO ---------------- #
async def gerar_zip(texto, voz, titulo, autor, ano):
    capitulos, metodo = dividir_inteligente(texto)

    st.write(f"📚 Método: {metodo} | Capítulos: {len(capitulos)}")

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        barra = st.progress(0)

        for i, (tit, cont) in enumerate(capitulos, 1):
            num = f"{i:03d}"

            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                caminho = tmp.name

            partes = dividir_texto_tts(f"{tit}. {cont}")

            with open(caminho, "wb") as f:
                for parte in partes:
                    for tentativa in range(3):
                        try:
                            communicate = edge_tts.Communicate(parte, VOZES[voz])
                            stream = communicate.stream()

                            async for chunk in stream:
                                if chunk["type"] == "audio":
                                    f.write(chunk["data"])

                            break
                        except Exception as e:
                            if tentativa == 2:
                                st.error(f"Erro no capítulo {num}")
                            await asyncio.sleep(1)

            if os.path.exists(caminho) and os.path.getsize(caminho) > 0:
                zip_file.write(caminho, f"{num}.mp3")

            os.unlink(caminho)
            barra.progress(i / len(capitulos))

    zip_buffer.seek(0)
    return zip_buffer


# ---------------- UI ---------------- #
st.title("☁️ Audiobook Cloud")

arquivo = st.file_uploader("Livro", type=["pdf", "epub"])
voz = st.selectbox("Voz", list(VOZES.keys()))
titulo = st.text_input("Título")
autor = st.text_input("Autor")

if st.button("Gerar"):
    if arquivo and titulo and autor:
        texto = extrair_texto(arquivo)

        st.info("Processando...")

        zip_data = asyncio.run(gerar_zip(texto, voz, titulo, autor, ""))

        st.download_button("Baixar ZIP", zip_data.getvalue(), "audiobook.zip")
