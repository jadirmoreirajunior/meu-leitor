import streamlit as st
import asyncio
import edge_tts
import os
import zipfile
import io
import shutil
import re
from collections import Counter
import pdfplumber
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Narrador.AI Pro", page_icon="🎧", layout="wide")

OUTPUT_DIR = "audiobook_pro_out"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

VOICES = {
    "Antonio (Masculino)": "pt-BR-AntonioNeural",
    "Francisca (Feminina)": "pt-BR-FranciscaNeural",
    "Brenda (Feminina)": "pt-BR-BrendaNeural",
    "Donato (Masculino)": "pt-BR-DonatoNeural",
    "Thalita (Feminina)": "pt-BR-ThalitaNeural",
    "Andrew (Multilingue)": "en-US-AndrewMultilingualNeural",
    "Emma (Multilingue)": "en-US-EmmaMultilingualNeural"
}

# --- INTELIGÊNCIA DE LIMPEZA (HEURÍSTICA) ---

def clean_professional_text(pages):
    """
    Recebe uma lista de textos (um por página) e remove ruídos sistemáticos.
    """
    if not pages:
        return ""

    # 1. Identificar Cabeçalhos e Rodapés (Textos que se repetem em > 80% das páginas)
    all_lines = []
    for page in pages:
        all_lines.extend([line.strip() for line in page.split('\n') if line.strip()])
    
    line_counts = Counter(all_lines)
    threshold = len(pages) * 0.8
    repeated_noise = {line for line, count in line_counts.items() if count > threshold and not line.isdigit()}

    cleaned_pages = []
    for page in pages:
        page_lines = page.split('\n')
        final_page_lines = []
        
        for line in page_lines:
            clean_line = line.strip()
            
            # Filtro 1: Remove se for ruído repetido (cabeçalho/rodapé)
            if clean_line in repeated_noise:
                continue
            
            # Filtro 2: Remove se for apenas números (paginação)
            if re.match(r'^\d+$', clean_line):
                continue
                
            # Filtro 3: Remove linhas de "código" ou lixo de formatação (muitos símbolos, poucas vogais)
            if len(clean_line) > 0:
                special_chars = len(re.findall(r'[^a-zA-Z0-9\sà-úÀ-Ú]', clean_line))
                if special_chars / len(clean_line) > 0.3 and len(clean_line) < 20:
                    continue
            
            if clean_line:
                final_page_lines.append(clean_line)
        
        cleaned_pages.append(" ".join(final_page_lines))

    # Junta tudo e limpa espaços múltiplos
    full_text = " ".join(cleaned_pages)
    full_text = re.sub(r'\s+', ' ', full_text)
    return full_text

# --- EXTRAÇÃO ---

def extract_content(file):
    pages_content = []
    if file.name.endswith(".pdf"):
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_content.append(text)
    elif file.name.endswith(".epub"):
        with open("temp.epub", "wb") as f:
            f.write(file.getbuffer())
        book = epub.read_epub("temp.epub")
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            pages_content.append(soup.get_text())
        os.remove("temp.epub")
    else:
        return file.getvalue().decode("utf-8")
    
    return clean_professional_text(pages_content)

# --- TTS E UI ---

with st.sidebar:
    st.title("🎙️ Narrador.AI Pro")
    uploaded_file = st.file_uploader("Arquivo", type=["pdf", "epub", "txt"])
    voice_key = st.selectbox("Voz", list(VOICES.keys()))
    chunk_size = st.slider("Tamanho de cada bloco (caracteres)", 2000, 5000, 4000)
    
    if st.button("🗑️ Resetar Sistema"):
        shutil.rmtree(OUTPUT_DIR)
        os.makedirs(OUTPUT_DIR)
        st.rerun()

st.header("Estúdio de Gravação Inteligente")

if uploaded_file:
    if 'processed_text' not in st.session_state or st.session_state.get('last_file') != uploaded_file.name:
        with st.spinner("Aplicando IA de limpeza no texto..."):
            text = extract_content(uploaded_file)
            st.session_state.processed_text = text
            st.session_state.last_file = uploaded_file.name

    text = st.session_state.processed_text

    if text:
        # Divide o texto limpo em partes para o TTS
        words = text.split()
        chunks = []
        current_chunk = []
        curr_len = 0
        for w in words:
            if curr_len + len(w) < chunk_size:
                current_chunk.append(w)
                curr_len += len(w) + 1
            else:
                chunks.append(" ".join(current_chunk))
                current_chunk = [w]
                curr_len = len(w)
        if current_chunk: chunks.append(" ".join(current_chunk))

        st.success(f"Texto limpo com sucesso! {len(chunks)} partes prontas para narração.")
        
        with st.expander("🔍 Visualizar Texto Limpo (Verifique se há ruídos)"):
            st.write(text[:2000] + "...")

        if st.button("🎬 Iniciar Narração Profissional", use_container_width=True):
            bar = st.progress(0)
            status = st.empty()
            
            for i, segment in enumerate(chunks):
                idx = i + 1
                fname = f"Parte_{idx:03d}.mp3"
                path = os.path.join(OUTPUT_DIR, fname)
                
                status.info(f"Gravando parte {idx} de {len(chunks)}...")
                
                # Executa o TTS de forma isolada para evitar crash no navegador
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(edge_tts.Communicate(segment, VOICES[voice_key]).save(path))
                loop.close()
                
                bar.progress(idx / len(chunks))
            
            status.success("✨ Audiobook Gerado!")

            # Zip e Download
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for f in sorted(os.listdir(OUTPUT_DIR)):
                    z.write(os.path.join(OUTPUT_DIR, f), f)
            
            st.download_button("📥 Baixar Pack Completo (.ZIP)", buf.getvalue(), "audiobook.zip", "application/zip", use_container_width=True)

else:
    st.info("Aguardando upload para higienização do texto.")
