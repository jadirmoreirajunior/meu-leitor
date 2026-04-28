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
    # Salva temporariamente para o ebooklib ler
    with open("temp.epub", "wb") as f:
        f.write(file.getbuffer())
    
    book = epub.read_epub("temp.epub")
    chapters = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        chapters.append(soup.get_text())
    
    os.remove("temp.epub")
    return "\n".join(chapters)

# --- DIVISÃO DE CAPÍTULOS ---

def split_text(text):
    # Prioridade 2: Padrões de Capítulos (Regex)
    patterns = [
        r'(?i)^\s*(Capítulo|Chapter|Parte|Part)\s+\d+',
        r'(?i)^\s*(Capítulo|Chapter|Parte|Part)\s+[IVXLCDM]+'
    ]
    
    combined_pattern = "|".join(patterns)
    segments = re.split(combined_pattern, text, flags=re.MULTILINE)
    titles = re.findall(combined_pattern, text, flags=re.MULTILINE)

    if len(titles) > 1:
        method = "Padrões de Texto (Capítulos/Partes)"
        chapters = []
        for i in range(len(titles)):
            content = segments[i+1] if i+1 < len(segments) else ""
            chapters.append({"title": titles[i].strip() + f" {i+1}", "content": content})
        return chapters, method

    # Fallback: Divisão por blocos de caracteres
    method = "Fallback (Blocos de 3000 caracteres)"
    chunks = []
    max_chars = 3000
    curr_idx = 0
    while curr_idx < len(text):
        end_idx = curr_idx + max_chars
        if end_idx < len(text):
            # Tenta não cortar no meio da frase
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
    # Divide em partes menores para o edge-tts não falhar
    max_chunk = 1500
    text_parts = [text[i:i+max_chunk] for i in range(0, len(text), max_chunk)]
    
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

def generate_audio_segment(text, voice, filename, title_tag, author_tag, track_num, year_tag):
    retries = 3
    success = False
    
    for attempt in range(retries):
        try:
            # Tenta Edge-TTS
            asyncio.run(generate_edge_tts(text, voice, filename))
            success = True
            break
        except Exception as e:
            if attempt == retries - 1:
                # Fallback definitivo: gTTS
                try:
                    tts = gTTS(text=text, lang='pt')
                    tts.save(filename)
                    success = True
                except:
                    success = False
            else:
                continue

    if success and os.path.exists(filename):
        # Inserir Metadados
        try:
            audio = MP3(filename, ID3=ID3)
            try:
                audio.add_tags()
            except:
                pass
            audio.tags.add(TIT2(encoding=3, text=title_tag))
            audio.tags.add(TPE1(encoding=3, text=author_tag))
            audio.tags.add(TRCK(encoding=3, text=str(track_num)))
            if year_tag:
                audio.tags.add(TYER(encoding=3, text=str(year_tag)))
            audio.save()
        except:
            pass # Falha nos metadados não impede o app
        return True
    return False

# --- INTERFACE STREAMLIT ---

st.set_page_config(page_title="PDF to Audiobook Pro", layout="wide")

st.title("📚 PDF/EPUB to Audiobook")
st.markdown("Transforme seus livros em áudio usando IA de voz neural.")

with st.sidebar:
    st.header("Configurações")
    uploaded_file = st.file_uploader("Escolha o arquivo", type=["pdf", "epub"])
    selected_voice_label = st.selectbox("Selecione a Voz", list(VOICES.keys()))
    voice_id = VOICES[selected_voice_label]
    
    title = st.text_input("Título do Livro", "Meu Audiobook")
    author = st.text_input("Autor", "Desconhecido")
    year = st.text_input("Ano", "")

if uploaded_file:
    # Extração de texto
    with st.spinner("Extraindo texto do arquivo..."):
        if uploaded_file.name.endswith(".pdf"):
            full_text = extract_text_pdf(uploaded_file)
        else:
            full_text = extract_text_epub(uploaded_file)

    if full_text.strip():
        chapters, method = split_text(full_text)
        
        col1, col2 = st.columns(2)
        col1.metric("Capítulos Detectados", len(chapters))
        col2.metric("Método de Divisão", method.split(' ')[0])
        
        with st.expander("Ver prévia dos capítulos"):
            for i, cap in enumerate(chapters[:5]):
                st.write(f"**{cap['title']}**: {cap['content'][:100]}...")

        if st.button("🚀 Iniciar Geração de Áudio"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            generated_files = []
            
            # Criar pasta temporária
            if not os.path.exists("output_audio"):
                os.makedirs("output_audio")

            for i, cap in enumerate(chapters):
                track_no = i + 1
                filename = f"output_audio/{track_no:03d}.mp3"
                status_text.text(f"Gerando capítulo {track_no}/{len(chapters)}: {cap['title']}")
                
                # O conteúdo não pode estar vazio
                clean_content = cap['content'].strip()
                if not clean_content:
                    clean_content = "Capítulo sem conteúdo detectado."

                res = generate_audio_segment(
                    clean_content, 
                    voice_id, 
                    filename, 
                    f"{title} - {cap['title']}", 
                    author, 
                    track_no, 
                    year
                )
                
                if res:
                    generated_files.append(filename)
                
                progress_bar.progress((i + 1) / len(chapters))

            if generated_files:
                # Criar ZIP
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zf:
                    for f in generated_files:
                        zf.write(f, os.path.basename(f))
                        os.remove(f) # Limpa arquivo individual
                
                st.success("✅ Audiobook gerado com sucesso!")
                st.download_button(
                    label="📥 Baixar Audiobook (.ZIP)",
                    data=zip_buffer.getvalue(),
                    file_name=f"{title.replace(' ', '_')}.zip",
                    mime="application/zip"
                )
                
                # Limpar pasta
                os.rmdir("output_audio")
            else:
                st.error("Erro crítico: Nenhum arquivo de áudio foi gerado.")
    else:
        st.error("Não foi possível extrair texto deste arquivo.")
else:
    st.info("Aguardando upload de arquivo PDF ou EPUB para começar.")
