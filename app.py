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

st.set_page_config(page_title="Audiobook Cloud", page_icon="☁️", layout="wide")

VOZES = {
    "Francisca (Padrão - Fem)": "pt-BR-FranciscaNeural",
    "Antonio (Padrão - Masc)": "pt-BR-AntonioNeural",
    "Thalita (Jovem - Fem)": "pt-BR-ThalitaNeural",
    "Brenda (Clara - Fem)": "pt-BR-BrendaNeural",
    "Donato (Profunda - Masc)": "pt-BR-DonatoNeural",
    "Fabio (Madura - Masc)": "pt-BR-FabioNeural"
}

# ====================== EXTRAÇÃO ======================
def extrair_texto(arquivo):
    if arquivo.name.lower().endswith('.pdf'):
        reader = PdfReader(arquivo)
        textos = [p.extract_text() for p in reader.pages if p.extract_text()]
        return "\n".join(textos)
    
    else:  # EPUB
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as tmp:
                tmp.write(arquivo.getvalue())
                tmp_path = tmp.name
            
            livro = epub.read_epub(tmp_path)
            texto = ""
            for item in livro.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                texto += soup.get_text(separator="\n") + "\n"
            
            os.unlink(tmp_path)
            return texto.strip()
        except Exception as e:
            st.error(f"Erro ao ler EPUB: {e}")
            return ""

# ====================== DIVISÃO ======================
def dividir_inteligente(texto):
    if not texto:
        return [], "vazio"
    
    # Tentativa 1: Sumário
    sumario = extrair_sumario(texto)
    capitulos = dividir_por_sumario(texto, sumario)
    if len(capitulos) >= 3:
        return capitulos, "sumario"
    
    # Tentativa 2: Padrão "Capítulo X"
    capitulos = dividir_capitulos(texto)
    if len(capitulos) >= 2:
        return capitulos, "capitulos"
    
    # Fallback: divisão por tamanho
    return dividir_por_tamanho(texto), "tamanho"

def extrair_sumario(texto):
    linhas = [linha.strip() for linha in texto.split('\n') if linha.strip()]
    sumario = []
    encontrou = False
    for linha in linhas:
        if re.search(r'sum[áa]rio|índice|conteúdo', linha, re.IGNORECASE):
            encontrou = True
            continue
        if encontrou:
            if len(linha) > 100 or len(sumario) > 80:
                break
            if 4 < len(linha) < 70:
                sumario.append(linha)
    return sumario

def dividir_por_sumario(texto, sumario):
    if len(sumario) < 3:
        return []
    texto_lower = texto.lower()
    posicoes = []
    for item in sumario:
        pos = texto_lower.find(item.lower())
        if pos != -1:
            posicoes.append((pos, item))
    posicoes.sort()
    
    capitulos = []
    for i in range(len(posicoes)):
        inicio = posicoes[i][0]
        titulo = posicoes[i][1]
        fim = posicoes[i+1][0] if i+1 < len(posicoes) else len(texto)
        conteudo = texto[inicio:fim].strip()
        if len(conteudo) > 300:
            capitulos.append((titulo, conteudo))
    return capitulos

def dividir_capitulos(texto):
    texto = texto.replace('\r', '\n')
    partes = re.split(r'\n\s*(Cap[ií]tulo\s+\d+[^\n]*|PARTE\s+\d+[^\n]*)\s*\n', texto, flags=re.IGNORECASE)
    capitulos = []
    if len(partes) > 2:
        for i in range(1, len(partes), 2):
            titulo = partes[i].strip()
            conteudo = partes[i+1] if i+1 < len(partes) else ""
            if len(conteudo.strip()) > 400:
                capitulos.append((titulo, conteudo.strip()))
    return capitulos

def dividir_por_tamanho(texto, tamanho=3500):
    capitulos = []
    inicio = 0
    i = 1
    while inicio < len(texto):
        fim = inicio + tamanho
        bloco = texto[inicio:fim]
        # Tenta cortar em ponto final
        ultimo_ponto = bloco.rfind('.')
        if ultimo_ponto > 1000:
            fim = inicio + ultimo_ponto + 1
            bloco = texto[inicio:fim]
        capitulos.append((f"Parte {i:02d}", bloco))
        inicio = fim
        i += 1
    return capitulos

# ====================== TTS ======================
async def gerar_audio(texto, voz, caminho):
    partes = []
    inicio = 0
    max_chars = 1400
    while inicio < len(texto):
        fim = inicio + max_chars
        trecho = texto[inicio:fim]
        ultimo_ponto = trecho.rfind('.')
        if ultimo_ponto > 200:
            fim = inicio + ultimo_ponto + 1
        partes.append(texto[inicio:fim])
        inicio = fim

    with open(caminho, "wb") as f:
        for parte in partes:
            for tentativa in range(4):
                try:
                    communicate = edge_tts.Communicate(parte, VOZES[voz])
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            f.write(chunk["data"])
                    break
                except Exception as e:
                    if tentativa == 3:
                        raise e
                    await asyncio.sleep(1.2)

# ====================== GERAÇÃO PRINCIPAL ======================
async def gerar_zip(texto, voz, titulo_livro, autor):
    capitulos, metodo = dividir_inteligente(texto)
    
    st.write(f"📚 **Método:** {metodo} | **Capítulos:** {len(capitulos)}")
    
    if not capitulos:
        st.error("Não foi possível dividir o livro em capítulos.")
        return None

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        barra = st.progress(0, text="Gerando áudio...")
        
        for i, (tit, cont) in enumerate(capitulos, 1):
            num = f"{i:03d}"
            titulo_cap = f"{tit}".strip()[:100]
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                caminho = tmp.name
            
            try:
                conteudo_com_titulo = f"{titulo_cap}. {cont}"
                await gerar_audio(conteudo_com_titulo, voz, caminho)
                
                if os.path.exists(caminho) and os.path.getsize(caminho) > 500:
                    zip_file.write(caminho, f"{num} - {titulo_cap}.mp3")
                else:
                    st.warning(f"⚠️ Capítulo {num} gerado com tamanho muito pequeno.")
            except Exception as e:
                st.error(f"❌ Falha no capítulo {num}: {e}")
            finally:
                if os.path.exists(caminho):
                    os.unlink(caminho)
            
            barra.progress(i / len(capitulos), text=f"Convertendo capítulo {num}/{len(capitulos)}...")
    
    zip_buffer.seek(0)
    return zip_buffer

# ====================== INTERFACE ======================
st.title("☁️ Audiobook Cloud")

col1, col2 = st.columns([1, 1])

with col1:
    arquivo = st.file_uploader("Upload Livro (PDF/EPUB)", type=["pdf", "epub"], help="Penso Logo Insisto - Marcio Krauss")
    
with col2:
    voz = st.selectbox("Voz Narradora", list(VOZES.keys()), index=4)  # Donato por padrão
    
titulo = st.text_input("Título do Livro", value="Penso logo insisto")
autor = st.text_input("Autor", value="Marcio Krauss")

if st.button("🚀 Gerar Audiobook", type="primary"):
    if not arquivo:
        st.error("Por favor, faça upload do livro.")
    elif not titulo or not autor:
        st.error("Título e Autor são obrigatórios.")
    else:
        with st.spinner("Extraindo texto do livro..."):
            texto = extrair_texto(arquivo)
        
        if len(texto) < 500:
            st.error("Texto extraído muito curto. O arquivo pode estar corrompido ou protegido.")
        else:
            st.success(f"✅ Texto extraído com sucesso! ({len(texto):,} caracteres)")
            
            zip_data = asyncio.run(gerar_zip(texto, voz, titulo, autor))
            
            if zip_data:
                st.download_button(
                    label="📥 Baixar Audiobook ZIP",
                    data=zip_data.getvalue(),
                    file_name=f"{titulo.replace(' ', '_')}.zip",
                    mime="application/zip",
                    use_container_width=True
                )

st.caption("Powered by edge-tts + Streamlit")
