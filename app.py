import streamlit as st
import asyncio
import edge_tts
import os
import zipfile
import io
import tempfile
import re
import unicodedata
from pathlib import Path
from datetime import datetime
import pdfplumber
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
import time

st.set_page_config(page_title="AudioBook AI", page_icon="🎧", layout="wide")

st.markdown("""
<style>
.stButton > button {
    background: linear-gradient(135deg, #667eea, #764ba2);
    color: white;
    border: none;
    padding: 0.7rem 1.5rem;
    border-radius: 10px;
    font-weight: 600;
    width: 100%;
}
</style>
""", unsafe_allow_html=True)

TEMP_DIR = Path(tempfile.mkdtemp())

VOICES = {
    "Antonio (Português)": "pt-BR-AntonioNeural",
    "Francisca (Português)": "pt-BR-FranciscaNeural",
    "Alessio (Italiano Multilíngue)": "it-IT-AlessioMultilingualNeural",
    "Andrew (Inglês Multilíngue)": "en-US-AndrewMultilingualNeural",
    "Emma (Inglês Multilíngue)": "en-US-EmmaMultilingualNeural",
}

def clean_text(text):
    """Limpeza básica de texto"""
    # Corrige hifenização
    text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
    text = re.sub(r'(\w+)-\s+(\w+)', r'\1\2', text)
    # Remove caracteres estranhos
    text = re.sub(r'[^\w\sáéíóúâêôãõçàèìòùäëïöüñÁÉÍÓÚÂÊÔÃÕÇÀÈÌÒÙÄËÏÖÜÑ.,!?;:()\-\'\"\n]', ' ', text, flags=re.UNICODE)
    text = ' '.join(text.split())
    return text

def remove_headers_footers(pages):
    """Remove cabeçalhos/rodapés repetidos"""
    if len(pages) < 3:
        return '\n\n'.join(pages)
    
    # Conta linhas repetidas
    all_lines = []
    for page in pages:
        for line in page.split('\n'):
            line = line.strip()
            if line:
                all_lines.append(line)
    
    from collections import Counter
    counts = Counter(all_lines)
    threshold = len(pages) * 0.7
    
    # Identifica ruído
    noise = set()
    for line, count in counts.items():
        if count >= threshold and len(line) < 150:
            noise.add(line)
        if re.match(r'^\d+$', line) and count >= 2:
            noise.add(line)
    
    # Limpa
    clean = []
    for page in pages:
        lines = [l.strip() for l in page.split('\n') if l.strip() and l.strip() not in noise]
        if lines:
            clean.append('\n'.join(lines))
    
    return '\n\n'.join(clean)

def split_text(text, max_chars=4000):
    """Divide texto em partes"""
    if len(text) <= max_chars:
        return [{"title": "Parte 1", "content": text}]
    
    parts = []
    paragraphs = text.split('\n\n')
    current = ""
    n = 1
    
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(current) + len(p) > max_chars and current:
            parts.append({"title": f"Parte {n}", "content": current.strip()})
            n += 1
            current = p
        else:
            current += ('\n\n' if current else '') + p
    
    if current.strip():
        parts.append({"title": f"Parte {n}", "content": current.strip()})
    
    return parts

def extract_pdf(file_bytes):
    """Extrai PDF"""
    pages = []
    tmp = TEMP_DIR / "tmp.pdf"
    tmp.write_bytes(file_bytes)
    
    try:
        with pdfplumber.open(tmp) as pdf:
            for page in pdf.pages:
                try:
                    t = page.extract_text()
                    if t and t.strip():
                        pages.append(t.strip())
                except:
                    pass
    finally:
        if tmp.exists():
            tmp.unlink()
    
    text = remove_headers_footers(pages)
    return clean_text(text)

def extract_epub(file_bytes):
    """Extrai EPUB"""
    parts = []
    tmp = TEMP_DIR / "tmp.epub"
    tmp.write_bytes(file_bytes)
    
    try:
        book = epub.read_epub(tmp)
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            try:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                for s in soup(["script", "style"]):
                    s.decompose()
                t = soup.get_text()
                lines = [l.strip() for l in t.split('\n') if l.strip()]
                if lines:
                    parts.append('\n'.join(lines))
            except:
                pass
    finally:
        if tmp.exists():
            tmp.unlink()
    
    return clean_text('\n\n'.join(parts))

def extract_txt(file_bytes):
    """Extrai TXT"""
    for enc in ['utf-8', 'latin-1', 'cp1252']:
        try:
            return clean_text(file_bytes.decode(enc))
        except:
            pass
    return clean_text(file_bytes.decode('utf-8', errors='replace'))

async def tts(text, voice, path):
    """Texto para fala"""
    try:
        text = text[:5000]
        c = edge_tts.Communicate(text, voice)
        await c.save(path)
        return os.path.exists(path) and os.path.getsize(path) > 1024
    except:
        return False

def run_tts(text, voice, path):
    """Wrapper síncrono"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        r = loop.run_until_complete(tts(text, voice, path))
        loop.close()
        return r
    except:
        return False

def safe_filename(name):
    """Nome de arquivo seguro"""
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ASCII')
    name = re.sub(r'[^\w\s-]', '', name).strip()
    name = re.sub(r'[-\s]+', '_', name)
    return name[:80]

# ========== INTERFACE ==========

st.title("🎧 AudioBook AI")
st.write("Transforme texto em audiobook com inteligência textual")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("📁 Entrada")
    
    method = st.radio("Método:", ["Upload de Arquivo", "Texto Manual"])
    
    if method == "Upload de Arquivo":
        file = st.file_uploader("Arquivo:", type=['pdf', 'epub', 'txt'])
        if file:
            st.info(f"📄 {file.name} ({len(file.getvalue())/1024/1024:.1f} MB)")
            if st.button("📖 Processar", use_container_width=True):
                with st.spinner("Processando..."):
                    try:
                        if file.name.endswith('.pdf'):
                            txt = extract_pdf(file.getvalue())
                        elif file.name.endswith('.epub'):
                            txt = extract_epub(file.getvalue())
                        else:
                            txt = extract_txt(file.getvalue())
                        
                        if txt and len(txt) > 50:
                            st.session_state.text = txt
                            st.session_state.parts = split_text(txt)
                            st.session_state.audio = []
                            st.success(f"✅ {len(txt):,} caracteres")
                        else:
                            st.error("Texto insuficiente")
                    except Exception as e:
                        st.error(f"Erro: {e}")
    else:
        txt = st.text_area("Texto:", height=200)
        if txt and len(txt.strip()) >= 50:
            if st.button("📝 Processar", use_container_width=True):
                st.session_state.text = clean_text(txt)
                st.session_state.parts = split_text(st.session_state.text)
                st.session_state.audio = []
                st.success(f"✅ {len(st.session_state.text):,} caracteres")
    
    st.subheader("🎤 Voz")
    voice_name = st.selectbox("Selecione:", list(VOICES.keys()))
    voice_id = VOICES[voice_name]
    
    if st.button("🔊 Testar", use_container_width=True):
        with st.spinner("..."):
            test_file = TEMP_DIR / "test.mp3"
            if run_tts("Olá, esta é a voz selecionada.", voice_id, str(test_file)):
                st.audio(str(test_file))
    
    if st.button("🗑️ Limpar", use_container_width=True):
        st.session_state.text = None
        st.session_state.parts = None
        st.session_state.audio = []
        import shutil
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir()
        st.rerun()

with col2:
    if 'text' not in st.session_state or not st.session_state.text:
        st.info("👈 Faça upload de um arquivo ou digite texto para começar")
    else:
        txt = st.session_state.text
        parts = st.session_state.parts
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Caracteres", f"{len(txt):,}")
        c2.metric("Palavras", f"{len(txt.split()):,}")
        c3.metric("Partes", len(parts))
        
        with st.expander("Preview"):
            st.text(txt[:2000] + ("..." if len(txt) > 2000 else ""))
        
        if st.button("🎙️ Gerar Audiobook", use_container_width=True, type="primary"):
            out_dir = TEMP_DIR / "out"
            out_dir.mkdir(exist_ok=True)
            
            for f in out_dir.glob("*.mp3"):
                f.unlink()
            
            st.session_state.audio = []
            bar = st.progress(0)
            msg = st.empty()
            
            for i, part in enumerate(parts):
                bar.progress((i+1)/len(parts))
                msg.info(f"🎙️ {part['title']} ({i+1}/{len(parts)})")
                
                fname = f"{i+1:03d}_{safe_filename(part['title'])}.mp3"
                out = out_dir / fname
                
                if run_tts(part['content'], voice_id, str(out)):
                    st.session_state.audio.append(out)
                time.sleep(0.3)
            
            bar.progress(1.0)
            if st.session_state.audio:
                msg.success(f"✅ {len(st.session_state.audio)}/{len(parts)} partes geradas!")
        
        if st.session_state.get('audio'):
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for f in st.session_state.audio:
                    zf.write(f, f.name)
            
            st.download_button(
                f"📥 Baixar ZIP ({len(st.session_state.audio)} arquivos)",
                zip_buf.getvalue(),
                f"audiobook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                "application/zip",
                use_container_width=True
            )
            
            with st.expander("🎵 Preview"):
                for f in st.session_state.audio:
                    st.audio(str(f))
