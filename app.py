import streamlit as st
import asyncio
import edge_tts
import os
import re
import zipfile
import io
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from gtts import gTTS
from mutagen.id3 import ID3, TIT2, TPE1, TRCK, TYER
from mutagen.mp3 import MP3

# --- CONFIGURAÇÕES E CONSTANTES ---
VOICES = {
    "Francisca (Feminina)": "pt-BR-FranciscaNeural",
    "Antonio (Masculino)": "pt-BR-AntonioNeural",
    "Brenda (Feminina)": "pt-BR-BrendaNeural",
    "Donato (Masculino)": "pt-BR-DonatoNeural",
    "Fabio (Masculino)": "pt-BR-FabioNeural"
}

# --- FUNÇÕES DE EXTRAÇÃO ---

def extract_text_pdf(file):
    reader = PdfReader(file)
    text = ""
    for page in reader.pages:
        content = page.extract_text()
        if content:
            text += content + "\n"
    return text

def extract_text_epub(file):
    with open("temp.epub", "wb") as f:
        f.write(file.getbuffer())
    
    try:
        book = epub.read_epub("temp.epub")
        chapters = []
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            chapters.append(soup.get_text())
        return "\n".join(chapters)
    finally:
        if os.path.exists("temp.epub"):
            os.remove("temp.epub")

# --- DIVISÃO DE CAPÍTULOS (LOGICA CORRIGIDA) ---

def split_text(text):
    # Regex corrigido: a flag (?i) movida para o início global ou removida em favor de re.IGNORECASE
    # Isso resolve o erro 'global flags not at the start'
    pattern = r'^\s*(?:Capítulo|Chapter|Parte|Part)\s+(?:[IVXLCDM]+|\d+)'
    
    # Encontra as posições onde os capítulos começam
    matches = list(re.finditer(pattern, text, flags=re.MULTILINE | re.IGNORECASE))
    
    if len(matches) > 1:
        method = "Padrões de Texto (Capítulos/Partes)"
        chapters = []
        for i in range(len(matches)):
            start = matches[i].start()
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            
            title = matches[i].group().strip()
            content = text[start:end].strip()
            
            if content:
                chapters.append({"title": title, "content": content})
        
        # Se por algum motivo a divisão resultou em algo vazio, ignora
        if chapters:
            return chapters, method

    # Fallback: Divisão por blocos de caracteres
    method = "Fallback (Blocos de 3000 caracteres)"
    chunks = []
    max_chars = 3000
    curr_idx = 0
    while curr_idx < len(text):
        end_idx = curr_idx + max_chars
        if end_idx < len(text):
            last_period = text.rfind('.', curr_idx, end_idx)
            if last_period != -1 and last_period > curr_idx + 1000:
                end_idx = last_period + 1
        
        chunk = text[curr_idx:end_idx].strip()
        if chunk:
            chunks.append({"title": f"Parte {len(chunks)+1}", "content": chunk})
        curr_idx = end_idx
        
    return chunks, method

# --- MOTOR DE ÁUDIO ---

async def generate_edge_tts(text, voice, filename):
    # O edge-tts tem limites de caracteres por requisição, dividimos internamente
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def generate_audio_segment(text, voice, filename, title_tag, author_tag, track_num, year_tag):
    retries = 3
    success = False
    
    # Limpeza básica de texto para evitar erros no TTS
    text = text.replace('\xa0', ' ').strip()
    
    if not text:
        return False

    for attempt in range(retries):
        try:
            # Tenta Edge-TTS (Neural)
            asyncio.run(generate_edge_tts(text, voice, filename))
            if os.path.exists(filename) and os.path.getsize(filename) > 0:
                success = True
                break
        except Exception:
            if attempt == retries - 1:
                try:
                    # Fallback final: gTTS
                    tts = gTTS(text=text[:5000], lang='pt') # gTTS tem limite de caracteres
                    tts.save(filename)
                    success = True
                except:
                    success = False
    
    if success:
        try:
            audio = MP3(filename, ID3=ID3)
            try: audio.add_tags()
            except: pass
            audio.tags.add(TIT2(encoding=3, text=title_tag))
            audio.tags.add(TPE1(encoding=3, text=author_tag))
            audio.tags.add(TRCK(encoding=3, text=str(track_num)))
            if year_tag: audio.tags.add(TYER(encoding=3, text=str(year_tag)))
            audio.save()
        except: pass
        return True
    return False

# --- INTERFACE ---

st.set_page_config(page_title="Audiobook Maker", layout="wide")
st.title("📚 PDF/EPUB to Audiobook")

with st.sidebar:
    st.header("Configurações")
    uploaded_file = st.file_uploader("Upload do livro", type=["pdf", "epub"])
    selected_voice = st.selectbox("Voz", list(VOICES.keys()))
    book_title = st.text_input("Título", "Meu Livro")
    book_author = st.text_input("Autor", "Desconhecido")
    book_year = st.text_input("Ano", "2024")

if uploaded_file:
    with st.spinner("Lendo arquivo..."):
        try:
            if uploaded_file.name.lower().endswith(".pdf"):
                full_text = extract_text_pdf(uploaded_file)
            else:
                full_text = extract_text_epub(uploaded_file)
            
            if not full_text.strip():
                st.error("Não foi possível extrair texto do arquivo.")
                st.stop()
                
            chapters, method = split_text(full_text)
            
            st.info(f"Método de detecção: {method} | Capítulos: {len(chapters)}")
            
            if st.button("▶️ Gerar Áudio"):
                progress = st.progress(0)
                status = st.empty()
                
                if not os.path.exists("temp_audio"):
                    os.makedirs("temp_audio")
                
                files = []
                for i, cap in enumerate(chapters):
                    fname = f"temp_audio/{i+1:03d}.mp3"
                    status.text(f"Processando: {cap['title']}")
                    
                    ok = generate_audio_segment(
                        cap['content'], VOICES[selected_voice], fname,
                        f"{book_title} - {cap['title']}", book_author, i+1, book_year
                    )
                    
                    if ok: files.append(fname)
                    progress.progress((i + 1) / len(chapters))
                
                if files:
                    zip_path = "audiobook.zip"
                    with zipfile.ZipFile(zip_path, 'w') as zipf:
                        for f in files:
                            zipf.write(f, os.path.basename(f))
                            os.remove(f)
                    
                    st.success("Pronto!")
                    with open(zip_path, "rb") as f:
                        st.download_button("📥 Baixar ZIP", f, file_name=f"{book_title}.zip")
                    os.remove(zip_path)
                    os.rmdir("temp_audio")
        except Exception as e:
            st.error(f"Ocorreu um erro: {e}")
