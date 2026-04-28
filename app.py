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

# ---------------- LIMPEZA DE TEXTO ---------------- #
def limpar_texto(t):
    # Remove caracteres especiais invisíveis e espaços excessivos
    t = t.replace('\xa0', ' ').replace('\u200b', '').replace('\r', '\n')
    t = re.sub(r'\n+', '\n', t)
    return t.strip()

# ---------------- EXTRAÇÃO DE TEXTO ---------------- #
def extrair_texto(arquivo):
    texto = ""
    if arquivo.name.endswith('.pdf'):
        reader = PdfReader(arquivo)
        textos = []
        for p in reader.pages:
            t = p.extract_text()
            if t: textos.append(t)
        texto = "\n".join(textos)
    else:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as tmp:
            tmp.write(arquivo.getvalue())
            tmp_path = tmp.name
        
        livro = epub.read_epub(tmp_path)
        for item in livro.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            texto += soup.get_text(separator=' ') + "\n"
        
        os.unlink(tmp_path)
    
    return limpar_texto(texto)

# ---------------- SUMÁRIO E DIVISÃO ---------------- #
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
            if len(linha) > 80: break
            if not linha: continue
            if 3 < len(linha) < 60: sumario.append(linha)
            if len(sumario) > 100: break
    return sumario

def dividir_por_sumario(texto, sumario):
    capitulos = []
    texto_lower = texto.lower()
    posicoes = []
    for item in sumario:
        pos = texto_lower.find(item.lower())
        if pos != -1: posicoes.append((pos, item))
    
    posicoes.sort()
    if len(posicoes) < 3: return []

    for i in range(len(posicoes)):
        inicio = posicoes[i][0]
        titulo = posicoes[i][1]
        fim = posicoes[i+1][0] if i+1 < len(posicoes) else len(texto)
        conteudo = texto[inicio:fim].strip()
        if len(conteudo) > 100:
            capitulos.append((titulo, conteudo))
    return capitulos

def dividir_capitulos_fallback(texto):
    partes = re.split(r'\n\s*(Cap[ií]tulo\s+\d+|PARTE\s+\d+)\s*\n', texto, flags=re.IGNORECASE)
    capitulos = []
    if len(partes) > 2:
        for i in range(1, len(partes), 2):
            titulo = partes[i]
            conteudo = partes[i+1] if i+1 < len(partes) else ""
            if len(conteudo.strip()) > 100:
                capitulos.append((titulo, conteudo.strip()))
    else:
        tamanho = 4000
        inicio = 0
        while inicio < len(texto):
            fim = inicio + tamanho
            capitulos.append((f"Parte {len(capitulos)+1}", texto[inicio:fim]))
            inicio = fim
    return capitulos

def dividir_inteligente(texto):
    sumario = extrair_sumario(texto)
    capitulos = dividir_por_sumario(texto, sumario)
    if capitulos: return capitulos, "sumario"
    return dividir_capitulos_fallback(texto), "fallback"

def dividir_texto_tts(texto, max_chars=2500):
    partes = []
    while len(texto) > 0:
        if len(texto) <= max_chars:
            partes.append(texto)
            break
        corte = texto.rfind('.', 0, max_chars)
        if corte == -1: corte = max_chars
        partes.append(texto[:corte+1])
        texto = texto[corte+1:].strip()
    return [p for p in partes if p.strip()]

# ---------------- GERAÇÃO ---------------- #
async def gerar_audiobook(texto, voz_key, titulo_livro):
    capitulos, metodo = dividir_inteligente(texto)
    st.write(f"📚 Método: {metodo} | Capítulos: {len(capitulos)}")
    
    zip_buffer = io.BytesIO()
    voz_id = VOZES[voz_key]

    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        barra = st.progress(0)
        status_text = st.empty()

        for i, (tit, cont) in enumerate(capitulos, 1):
            num = f"{i:03d}"
            status_text.text(f"Convertendo: {tit}")
            
            partes = dividir_texto_tts(f"{tit}. {cont}")
            cap_buffer = io.BytesIO()

            sucesso_capitulo = False
            for parte in partes:
                for tentativa in range(3):
                    try:
                        communicate = edge_tts.Communicate(parte, voz_id)
                        async for chunk in communicate.stream():
                            if chunk["type"] == "audio":
                                cap_buffer.write(chunk["data"])
                        sucesso_capitulo = True
                        break
                    except Exception:
                        if tentativa == 2:
                            st.warning(f"Aviso: Falha parcial no capítulo {num}")
                        await asyncio.sleep(1)

            if sucesso_capitulo and cap_buffer.tell() > 0:
                cap_buffer.seek(0)
                zip_file.writestr(f"{num}.mp3", cap_buffer.read())
            
            barra.progress(i / len(capitulos))
        
        status_text.text("✅ Processamento concluído!")
    
    zip_buffer.seek(0)
    return zip_buffer

# ---------------- UI ---------------- #
st.title("☁️ Audiobook Cloud")

col1, col2 = st.columns(2)
with col1:
    arquivo = st.file_uploader("Upload Livro (PDF/EPUB)", type=["pdf", "epub"])
    voz = st.selectbox("Voz Narradora", list(VOZES.keys()))
with col2:
    titulo = st.text_input("Título do Livro")
    autor = st.text_input("Autor")

if st.button("Gerar Audiobook"):
    if not (arquivo and titulo and autor):
        st.error("Preencha todos os campos e envie o arquivo.")
    else:
        with st.spinner("Extraindo texto e preparando capítulos..."):
            texto_completo = extrair_texto(arquivo)
            
            # Criar um novo loop para evitar erros de nested loops no Streamlit
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            zip_data = loop.run_until_complete(gerar_audiobook(texto_completo, voz, titulo))

            st.download_button(
                label="📥 Baixar Audiobook (ZIP)",
                data=zip_data,
                file_name=f"{titulo}.zip",
                mime="application/zip"
            )
