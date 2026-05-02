import streamlit as st
import asyncio
import edge_tts
import os
import re
import zipfile
import io
import shutil
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from gtts import gTTS
from mutagen.id3 import ID3, TIT2, TPE1, TRCK, TYER
from mutagen.mp3 import MP3

# Suporte a Word
try:
    import docx
    WORD_SUPPORT = True
except ImportError:
    WORD_SUPPORT = False

# --- CONFIGURAÇÃO DE IDENTIDADE ---
APP_NAME = "Narrador.AI"
ICON_URL = "https://jadirmoreirajunior.github.io/meu-leitor/narrador.ai.png"

st.set_page_config(page_title=APP_NAME, page_icon=ICON_URL, layout="wide")

# 1. INICIALIZAÇÃO DA MEMÓRIA PERSISTENTE
if "zip_buffer" not in st.session_state: st.session_state.zip_buffer = None
if "book_ready" not in st.session_state: st.session_state.book_ready = False
if "chapters_generated" not in st.session_state: st.session_state.chapters_generated = []
if "temp_chapters" not in st.session_state: st.session_state.temp_chapters = []

VOICES = {
    "Francisca (Feminina - BR)": "pt-BR-FranciscaNeural",
    "Antonio (Masculino - BR)": "pt-BR-AntonioNeural",
    "Andrew (Multilingue)": "en-US-AndrewMultilingualNeural",
    "Brian (Multilingue)": "en-US-BrianMultilingualNeural",
    "Ava (Multilingue)": "en-US-AvaMultilingualNeural",
    "Emma (Multilingue)": "en-US-EmmaMultilingualNeural",
    "Brenda (Feminina - BR)": "pt-BR-BrendaNeural",
    "Donato (Masculino - BR)": "pt-BR-DonatoNeural",
    "Fabio (Masculino - BR)": "pt-BR-FabioNeural"
}

st.markdown(f"""
    <style>
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        header {{ background-color: rgba(0,0,0,0); height: 3rem; }}
        .header-container {{ display: flex; align-items: center; gap: 15px; margin-bottom: 10px; }}
        .header-logo {{ width: 70px; border-radius: 12px; }}
        .header-text h1 {{ margin: 0; font-size: 1.6rem; }}
        .header-text p {{ margin: 0; font-size: 0.9rem; color: gray; }}
        .main .block-container {{ max-width: 900px; padding-top: 1rem; padding-bottom: 2rem; }}
        .stButton>button {{ width: 100%; border-radius: 20px; height: 3em; background-color: #0e1117; color: white; border: 1px solid #30363d; font-weight: bold; }}
        .stButton>button:hover {{ border-color: #f0ad4e; color: #f0ad4e; }}
    </style>
    """, unsafe_allow_html=True)

# --- MOTORES DE EXTRAÇÃO ---

def split_text_logic(text):
    if not text or len(text) < 10: return []
    pattern = r'^\s*(?:Capítulo|Chapter|Parte|Part)\s+(?:[IVXLCDM]+|\d+)'
    matches = list(re.finditer(pattern, text, flags=re.MULTILINE | re.IGNORECASE))
    if len(matches) > 2:
        chapters = []
        for i in range(len(matches)):
            start = matches[i].start()
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            chapters.append({"title": matches[i].group().strip(), "content": text[start:end].strip()})
        return chapters
    
    chunks = []
    max_chars = 5000
    curr_idx = 0
    while curr_idx < len(text):
        end_idx = curr_idx + max_chars
        if end_idx < len(text):
            last_p = text.rfind('.', curr_idx, end_idx)
            if last_p != -1 and last_p > curr_idx + 2000: end_idx = last_p + 1
        chunk = text[curr_idx:end_idx].strip()
        if chunk: chunks.append({"title": f"Parte {len(chunks)+1:03d}", "content": chunk})
        curr_idx = end_idx
    return chunks

def extract_safe_epub(file):
    with open("temp.epub", "wb") as f: f.write(file.getbuffer())
    all_text = ""
    try:
        book = epub.read_epub("temp.epub")
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            for tag in soup(['img', 'svg', 'style', 'script']): tag.decompose()
            all_text += soup.get_text(separator="\n") + "\n"
        return split_text_logic(all_text)
    except: return []

# --- INTERFACE ---

st.markdown(f"""<div class="header-container"><img src="{ICON_URL}" class="header-logo"><div class="header-text"><h1>{APP_NAME}</h1><p>Audiobooks neurais para PDF, EPUB, DOCX e TXT</p></div></div>""", unsafe_allow_html=True)

st.write("---")
input_method = st.radio("Método de Entrada:", ["Arquivo", "Texto Manual"], horizontal=True)

c1, c2, c3 = st.columns([2, 1, 1.5])
with c1: book_title = st.text_input("Título", "Meu Audiobook")
with c2: book_year = st.text_input("Ano", "")
with c3: voice_label = st.selectbox("Voz", list(VOICES.keys()))
book_author = st.text_input("Autor", "Narrador.AI")

# Processamento de Entrada
if input_method == "Arquivo":
    uploaded_file = st.file_uploader("Upload", type=["pdf", "epub", "docx", "txt"])
    if uploaded_file:
        if st.button("📄 PROCESSAR ARQUIVO"):
            with st.status("Extraindo texto...", expanded=False) as s:
                if uploaded_file.name.endswith(".pdf"):
                    raw = "\n".join([p.extract_text() for p in PdfReader(uploaded_file).pages])
                    st.session_state.temp_chapters = split_text_logic(raw)
                elif uploaded_file.name.endswith(".epub"):
                    st.session_state.temp_chapters = extract_safe_epub(uploaded_file)
                elif uploaded_file.name.endswith(".docx") and WORD_SUPPORT:
                    raw = "\n".join([p.text for p in docx.Document(uploaded_file).paragraphs])
                    st.session_state.temp_chapters = split_text_logic(raw)
                elif uploaded_file.name.endswith(".txt"):
                    st.session_state.temp_chapters = split_text_logic(uploaded_file.getvalue().decode("utf-8", errors="ignore"))
                s.update(label="Conteúdo extraído com sucesso!", state="complete")
else:
    m_text = st.text_area("Texto:", height=250)
    if st.button("✍️ CAPTURAR TEXTO DIGITADO"):
        st.session_state.temp_chapters = split_text_logic(m_text)
        st.success("Texto capturado!")

# Botões de Utilidade
st.write("")
col_u1, col_u2 = st.columns(2)
with col_u1:
    if st.button("▶️ Ouvir Prévia"):
        asyncio.run(edge_tts.Communicate("Teste.", VOICES[voice_label]).save("preview.mp3"))
        st.audio("preview.mp3")
with col_u2:
    if st.button("🗑️ Limpar Tudo"):
        st.session_state.temp_chapters = []
        st.session_state.chapters_generated = []
        st.session_state.zip_buffer = None
        st.session_state.book_ready = False
        if os.path.exists("out"): shutil.rmtree("out")
        st.rerun()

# --- ÁREA DE GERAÇÃO (PROTEGIDA) ---
# Usamos session_state diretamente aqui para que o botão não dependa do clique anterior
if st.session_state.temp_chapters:
    st.divider()
    st.info(f"✅ {len(st.session_state.temp_chapters)} partes identificadas. Motor pronto.")
    
    if st.button("🚀 INICIAR GERAÇÃO DE ÁUDIO"):
        st.session_state.chapters_generated = []
        progress = st.progress(0)
        
        with st.status("Narrando partes...", expanded=True) as status_gen:
            if not os.path.exists("out"): os.makedirs("out")
            for i, cap in enumerate(st.session_state.temp_chapters):
                track = i + 1
                fname = f"out/{track:03d}.mp3"
                status_gen.write(f"🎙️ Gerando: {cap['title']}")
                
                # Motor TTS
                asyncio.run(edge_tts.Communicate(cap['content'], VOICES[voice_label]).save(fname))
                
                # Tags MP3
                audio = MP3(fname, ID3=ID3)
                try: audio.add_tags()
                except: pass
                audio.tags.add(TIT2(encoding=3, text=f"{book_title} - {cap['title']}"))
                audio.tags.add(TPE1(encoding=3, text=book_author))
                audio.tags.add(TRCK(encoding=3, text=str(track)))
                if book_year: audio.tags.add(TYER(encoding=3, text=str(book_year)))
                audio.save()
                
                with open(fname, "rb") as f:
                    st.session_state.chapters_generated.append({"title": cap['title'], "data": f.read(), "track": track})
                progress.progress(track / len(st.session_state.temp_chapters))
            status_gen.update(label="Narração concluída!", state="complete")
        
        # Gerar ZIP
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zf:
            for item in st.session_state.chapters_generated:
                zf.writestr(f"{item['track']:03d}.mp3", item['data'])
        st.session_state.zip_buffer = buffer.getvalue()
        st.session_state.book_ready = True

# Área de Downloads
if st.session_state.chapters_generated:
    st.write("---")
    st.subheader("📥 Capítulos individuais")
    for item in st.session_state.chapters_generated:
        with st.expander(f"Parte {item['track']}: {item['title']}"):
            st.download_button("Baixar MP3", item["data"], f"{item['track']:03d}.mp3", key=f"dl_{item['track']}")

if st.session_state.book_ready:
    st.divider()
    st.download_button("📥 BAIXAR LIVRO COMPLETO (.ZIP)", st.session_state.zip_buffer, f"{book_title.replace(' ', '_')}.zip")
