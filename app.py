import streamlit as st
import asyncio
import edge_tts
import os
import re
import zipfile
from PyPDF2 import PdfReader
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
from gtts import gTTS
from mutagen.id3 import ID3, TIT2, TPE1, TRCK, TYER
from mutagen.mp3 import MP3

# --- CONFIGURAÇÕES ---
VOICES = {
    "Francisca (Feminina)": "pt-BR-FranciscaNeural",
    "Antonio (Masculino)": "pt-BR-AntonioNeural",
    "Brenda (Feminina)": "pt-BR-BrendaNeural",
    "Donato (Masculino)": "pt-BR-DonatoNeural",
    "Fabio (Masculino)": "pt-BR-FabioNeural"
}

# --- FIX ASYNCIO (ESSENCIAL) ---
def run_async_task(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(coro)
    loop.close()

# --- EXTRAÇÃO ---

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

        # 🔥 TENTA USAR TOC PRIMEIRO
        toc_chapters = split_epub_by_toc(book)

        if len(toc_chapters) > 2:
            return toc_chapters, "TOC (sumário do EPUB)"

        # fallback: texto completo
        texts = []
        for item in book.get_items():
            if item.get_type() == ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), 'html.parser')

                for tag in soup(['img', 'svg']):
                    tag.decompose()

                text = soup.get_text(separator="\n")
                if text.strip():
                    texts.append(text)

        full_text = "\n\n".join(texts)

        return full_text, "Texto bruto EPUB"

    finally:
        if os.path.exists("temp.epub"):
            os.remove("temp.epub")

def generate_preview(text, voice):
    preview_file = "preview.mp3"
    sample = text[:500] if len(text) > 500 else text

    try:
        run_async_task(generate_edge_tts(sample, voice, preview_file))
        return preview_file
    except:
        try:
            tts = gTTS(text=sample, lang='pt')
            tts.save(preview_file)
            return preview_file
        except:
            return None

def flatten_toc(toc):
    for item in toc:
        if isinstance(item, tuple):
            yield item[0]
            yield from flatten_toc(item[1])
        else:
            yield item


def split_epub_by_toc(book):
    chapters = []

    try:
        for item in flatten_toc(book.toc):
            try:
                title = item.title
                content_item = book.get_item_with_href(item.href)

                if not content_item:
                    continue

                soup = BeautifulSoup(content_item.get_content(), 'html.parser')

                # remove imagens
                for tag in soup(['img', 'svg']):
                    tag.decompose()

                text = soup.get_text(separator="\n")

                if text.strip() and len(text) > 300:
                    chapters.append({
                        "title": title.strip(),
                        "content": text.strip()
                    })
            except:
                continue
    except:
        return []

    return chapters

# --- DIVISÃO DE TEXTO EM CAPÍTULOS ---

def split_text(text):
    pattern = r'^\s*(?:Capítulo|Chapter|Parte|Part)\s+(?:[IVXLCDM]+|\d+)'
    matches = list(re.finditer(pattern, text, flags=re.MULTILINE | re.IGNORECASE))

    if len(matches) > 2:
        chapters = []
        for i in range(len(matches)):
            start = matches[i].start()
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            title = matches[i].group().strip()
            content = text[start:end].strip()

            if len(content) > 500:
                chapters.append({"title": title, "content": content})

        if len(chapters) > 1:
            return chapters, "Regex (capítulos detectados)"

    # 🔥 fallback final
    return [{"title": "Livro Completo", "content": text}], "Arquivo único"

# --- DIVISÃO PARA TTS (CRÍTICO) ---

def split_for_tts(text, max_chars=2000):
    parts = []
    while len(text) > max_chars:
        split_index = text.rfind('.', 0, max_chars)
        if split_index == -1:
            split_index = max_chars
        parts.append(text[:split_index + 1])
        text = text[split_index + 1:]
    if text:
        parts.append(text)
    return parts

# --- EDGE TTS ---

async def generate_edge_tts(text, voice, filename):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

# --- GERAÇÃO DE ÁUDIO ---

def generate_audio_segment(text, voice, filename, title_tag, author_tag, track_num, year_tag):
    text = text.replace('\xa0', ' ').strip()
    if not text:
        return False

    try:
        parts = split_for_tts(text)
        temp_files = []

        for idx, part in enumerate(parts):
            temp_file = f"{filename}_{idx}.mp3"
            run_async_task(generate_edge_tts(part, voice, temp_file))
            temp_files.append(temp_file)

        # junta os arquivos
        with open(filename, 'wb') as final_audio:
            for tf in temp_files:
                with open(tf, 'rb') as f:
                    final_audio.write(f.read())
                os.remove(tf)

    except Exception:
        # fallback gTTS
        try:
            tts = gTTS(text=text[:3000], lang='pt')
            tts.save(filename)
        except:
            return False

    # metadata
    try:
        audio = MP3(filename, ID3=ID3)
        try: audio.add_tags()
        except: pass
        audio.tags.add(TIT2(encoding=3, text=title_tag))
        audio.tags.add(TPE1(encoding=3, text=author_tag))
        audio.tags.add(TRCK(encoding=3, text=str(track_num)))
        if year_tag:
            audio.tags.add(TYER(encoding=3, text=str(year_tag)))
        audio.save()
    except:
        pass

    return True

# --- INTERFACE ---

st.set_page_config(page_title="Audiobook Maker", layout="wide")
st.title("📚 PDF/EPUB → Audiobook")

with st.sidebar:
    st.header("Configurações")
    uploaded_file = st.file_uploader("Upload", type=["pdf", "epub"])
    selected_voice = st.selectbox("Voz", list(VOICES.keys()))
    book_title = st.text_input("Título", "Meu Livro")
    book_author = st.text_input("Autor", "Desconhecido")
    book_year = st.text_input("Ano", "2024")

if uploaded_file:
    with st.spinner("Lendo arquivo..."):
if uploaded_file.name.lower().endswith(".pdf"):
    text = extract_text_pdf(uploaded_file)
    chapters, method = split_text(text)

else:
    result, method = extract_text_epub(uploaded_file)

    # 🔥 se já veio pronto do TOC
    if isinstance(result, list):
        chapters = result
    else:
        chapters, method2 = split_text(result)
        method = f"{method} + {method2}"

    if not text.strip():
        st.error("Erro ao extrair texto.")
        st.stop()

    chapters, method = split_text(text)
    st.info(f"{method} | {len(chapters)} partes")

    if st.button("Gerar Áudio"):
        progress = st.progress(0)
        status = st.empty()

        os.makedirs("temp_audio", exist_ok=True)

        files = []

        for i, cap in enumerate(chapters):
            fname = f"temp_audio/{i+1:03d}.mp3"
            status.text(f"Processando: {cap['title']}")

            ok = generate_audio_segment(
                cap['content'],
                VOICES[selected_voice],
                fname,
                f"{book_title} - {cap['title']}",
                book_author,
                i+1,
                book_year
            )

            if ok:
                files.append(fname)

            progress.progress((i + 1) / len(chapters))

        if files:
            zip_path = "audiobook.zip"
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for f in files:
                    zipf.write(f, os.path.basename(f))
                    os.remove(f)

            with open(zip_path, "rb") as f:
                st.download_button("📥 Baixar ZIP", f, file_name=f"{book_title}.zip")

            os.remove(zip_path)
            os.rmdir("temp_audio")

            st.success("Concluído!")

if st.button("🔊 Ouvir prévia da voz"):
    sample_text = "Olá! Esta é uma demonstração da voz selecionada para o seu audiobook."
    preview = generate_preview(sample_text, VOICES[selected_voice])

    if preview:
        audio_file = open(preview, 'rb')
        st.audio(audio_file.read(), format="audio/mp3")
        os.remove(preview)
    else:
        st.error("Erro ao gerar prévia")
