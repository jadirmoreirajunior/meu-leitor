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

# --- INTELIGÊNCIA DE LIMPEZA E DIVISÃO ---

def clean_professional_text(pages):
    if not pages: return ""
    
    all_lines = []
    for page in pages:
        all_lines.extend([line.strip() for line in page.split('\n') if line.strip()])
    
    line_counts = Counter(all_lines)
    threshold = len(pages) * 0.8
    repeated_noise = {line for line, count in line_counts.items() if count > threshold and not line.isdigit()}

    cleaned_text_list = []
    for page in pages:
        page_lines = page.split('\n')
        final_page_lines = []
        for line in page_lines:
            clean_line = line.strip()
            if clean_line in repeated_noise or re.match(r'^\d+$', clean_line):
                continue
            if clean_line:
                final_page_lines.append(clean_line)
        cleaned_text_list.append("\n".join(final_page_lines))
    
    return "\n".join(cleaned_text_list)

def split_by_chapters(text):
    """Tenta dividir por capítulos, caso contrário, divide por blocos de texto."""
    # Regex para identificar "Capítulo X", "CAPÍTULO X" ou apenas o número romano/cardinal no início da linha
    chapter_pattern = r'\n(?:Capítulo|Chapter|CAPÍTULO|CAPITULO)\s+\d+|\n[IVXLCDM]+\b'
    
    # Encontra as posições dos capítulos
    chapters = re.split(chapter_pattern, text)
    titles = re.findall(chapter_pattern, text)
    
    # Se encontrou mais de 2 capítulos, usa essa divisão
    if len(chapters) > 2:
        final_chunks = []
        for i, content in enumerate(chapters):
            if len(content.strip()) > 50:
                title = titles[i-1].strip() if i > 0 else "Introdução"
                final_chunks.append({"title": title, "content": content.strip()})
        return final_chunks
    
    # Caso contrário, divide por blocos de 5000 caracteres (sem cortar frases)
    st.warning("Capítulos não detectados automaticamente. Dividindo por partes lógicas.")
    paragraphs = text.split('\n\n')
    chunks = []
    current_chunk = ""
    for p in paragraphs:
        if len(current_chunk) + len(p) < 5000:
            current_chunk += p + "\n\n"
        else:
            chunks.append({"title": f"Parte {len(chunks)+1}", "content": current_chunk.strip()})
            current_chunk = p + "\n\n"
    if current_chunk:
        chunks.append({"title": f"Parte {len(chunks)+1}", "content": current_chunk.strip()})
    return chunks

# --- EXTRAÇÃO ---

def extract_content(file):
    pages_content = []
    try:
        if file.name.endswith(".pdf"):
            with pdfplumber.open(file) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text: pages_content.append(text)
        elif file.name.endswith(".epub"):
            # Modo seguro para EPUB
            temp_path = f"temp_{os.getpid()}.epub"
            with open(temp_path, "wb") as f:
                f.write(file.getbuffer())
            book = epub.read_epub(temp_path)
            for item in book.get_items_of_type(ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                pages_content.append(soup.get_text())
            if os.path.exists(temp_path):
                os.remove(temp_path)
        else:
            return file.getvalue().decode("utf-8")
    except Exception as e:
        st.error(f"Erro na extração: {e}")
        return ""
    
    return clean_professional_text(pages_content)

# --- UI ---

with st.sidebar:
    st.title("🎙️ Narrador.AI Pro")
    uploaded_file = st.file_uploader("Arquivo", type=["pdf", "epub", "txt"])
    voice_key = st.selectbox("Voz", list(VOICES.keys()))
    
    if st.button("🗑️ Resetar Sistema"):
        if os.path.exists(OUTPUT_DIR):
            shutil.rmtree(OUTPUT_DIR)
            os.makedirs(OUTPUT_DIR)
        st.rerun()

st.header("Estúdio de Gravação Inteligente")

if uploaded_file:
    # Evita re-processar o arquivo se ele não mudou
    if 'processed_chunks' not in st.session_state or st.session_state.get('last_file') != uploaded_file.name:
        with st.spinner("Analisando estrutura do livro e limpando ruídos..."):
            full_text = extract_content(uploaded_file)
            if full_text:
                st.session_state.processed_chunks = split_by_chapters(full_text)
                st.session_state.last_file = uploaded_file.name
            else:
                st.error("Falha ao extrair texto.")

    chunks = st.session_state.get('processed_chunks', [])

    if chunks:
        st.success(f"Sucesso! {len(chunks)} capítulos/partes identificados.")
        
        # Lista os capítulos identificados para o usuário ver
        with st.expander("📋 Ver Estrutura Detectada"):
            for c in chunks:
                st.write(f"- {c['title']} ({len(c['content'])} caracteres)")

        if st.button("🎬 Iniciar Narração Profissional", use_container_width=True):
            bar = st.progress(0)
            status = st.empty()
            
            for i, chunk in enumerate(chunks):
                idx = i + 1
                # Nome do arquivo agora inclui o título do capítulo (limpo)
                clean_title = re.sub(r'[^\w\s-]', '', chunk['title']).strip().replace(' ', '_')
                fname = f"{idx:03d}_{clean_title}.mp3"
                path = os.path.join(OUTPUT_DIR, fname)
                
                status.info(f"Narrando: {chunk['title']}...")
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(edge_tts.Communicate(chunk['content'], VOICES[voice_key]).save(path))
                loop.close()
                
                bar.progress(idx / len(chunks))
            
            status.success("✨ Gravação Concluída!")

            # Zip e Download
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for f in sorted(os.listdir(OUTPUT_DIR)):
                    if f.endswith(".mp3"):
                        z.write(os.path.join(OUTPUT_DIR, f), f)
            
            st.download_button("📥 Baixar Audiobook Completo (.ZIP)", buf.getvalue(), "audiobook.zip", "application/zip", use_container_width=True)
else:
    st.info("Aguardando upload para iniciar a análise.")
