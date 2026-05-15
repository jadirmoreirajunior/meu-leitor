import streamlit as st
import asyncio
import edge_tts
import os
import zipfile
import io
import tempfile
import shutil
import re
import unicodedata
from pathlib import Path
from datetime import datetime
from collections import Counter
import pdfplumber
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
import time

# ============================================
# CONFIGURAÇÃO INICIAL
# ============================================

st.set_page_config(
    page_title="AudioBook AI - Transforme Texto em Voz",
    page_icon="🎧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================
# CSS MINIMAL (MAIS LEVE E SEGURO)
# ============================================

st.markdown("""
<style>
    .app-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 15px;
        margin-bottom: 2rem;
    }
    .app-header h1 {
        color: white;
        font-size: 2rem;
        font-weight: 700;
        margin: 0;
    }
    .app-header p {
        color: rgba(255,255,255,0.9);
        font-size: 1.1rem;
        margin-top: 0.5rem;
    }
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 0.7rem 1.5rem;
        border-radius: 10px;
        font-weight: 600;
        width: 100%;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
    }
    .success-box {
        background: #d4edda;
        padding: 1rem;
        border-radius: 10px;
        border: 1px solid #c3e6cb;
        color: #155724;
    }
    .info-box {
        background: #e8eaf6;
        padding: 1rem;
        border-radius: 10px;
        border: 1px solid #c5cae9;
    }
</style>
""", unsafe_allow_html=True)

# ============================================
# DIRETÓRIO TEMPORÁRIO
# ============================================

TEMP_DIR = Path(tempfile.mkdtemp())

# ============================================
# VOZES
# ============================================

AVAILABLE_VOICES = {
    "🇧🇷 Português Brasileiro": {
        "Alessio - Voz Fluida (Multilingual)": "it-IT-AlessioNeural",
        "Elsa - Voz Narrativa (Multilingual)": "it-IT-ElsaNeural",
        "Giuseppe - Voz Sóbria (Multilingual": "it-IT-GiuseppeNeural",
        "Isabella - Voz Clara (Multilingual)": "it-IT-IsabellaNeural",
        "Antonio - Voz Profissional (Brasileiro)": "pt-BR-AntonioNeural",
        "Francisca - Voz Natural (Brasileira)": "pt-BR-FranciscaNeural",
        "Brenda - Voz Expressiva (Brasileira)": "pt-BR-BrendaNeural"
    }
}

# ============================================
# CORREÇÕES TEXTUAIS
# ============================================

def fix_hyphenation(text):
    """Corrige palavras hifenizadas: cava-\nlo -> cavalo"""
    # Corrige hífen + quebra de linha
    text = re.sub(r'(\w+)-\n(\w+)', r'\1\2', text)
    # Corrige hífen + espaço
    text = re.sub(r'(\w+)-\s+(\w+)', r'\1\2', text)
    return text

def fix_common_mistakes(text):
    """Corrige palavras grudadas comuns"""
    fixes = {
        'cavalodado': 'cavalo dado',
        'burrode carga': 'burro de carga',
        'péde cabra': 'pé de cabra',
        'guardachuva': 'guarda chuva',
        'girassol': 'gira sol',
        'passatempo': 'passa tempo',
    }
    for wrong, correct in fixes.items():
        text = text.replace(wrong, correct)
    return text

def remove_headers_footers(pages_text):
    """
    Remove cabeçalhos/rodapés que aparecem em múltiplas páginas
    Versão segura sem st.write() dentro de cached function
    """
    if not pages_text or len(pages_text) < 3:
        return '\n\n'.join(pages_text) if pages_text else ""
    
    # Coleta todas as linhas
    all_lines = []
    for page in pages_text:
        lines = [line.strip() for line in page.split('\n') if line.strip()]
        all_lines.extend(lines)
    
    # Conta frequência
    line_counts = Counter(all_lines)
    total_pages = len(pages_text)
    threshold = max(3, total_pages * 0.7)
    
    # Identifica ruído
    noise = set()
    for line, count in line_counts.items():
        if count >= threshold and len(line) < 150:
            noise.add(line)
        if re.match(r'^\d{1,4}$', line) and count >= 2:
            noise.add(line)
        if re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}$', line):
            noise.add(line)
    
    # Limpa páginas
    cleaned_pages = []
    for page in pages_text:
        lines = page.split('\n')
        clean = []
        for line in lines:
            stripped = line.strip()
            if stripped in noise:
                continue
            if re.match(r'^\d+$', stripped):
                continue
            if stripped:
                clean.append(stripped)
        if clean:
            cleaned_pages.append('\n'.join(clean))
    
    result = '\n\n'.join(cleaned_pages)
    return result

def full_cleanup(text):
    """Pipeline completo de limpeza textual"""
    if not text:
        return ""
    
    # 1. Corrige hifenização
    text = fix_hyphenation(text)
    
    # 2. Corrige palavras grudadas
    text = fix_common_mistakes(text)
    
    # 3. Normaliza espaços
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    
    # 4. Remove espaços extras
    text = text.strip()
    
    return text

# ============================================
# DIVISÃO DE TEXTO
# ============================================

def split_text_smart(text, max_chars=4000):
    """Divide texto em partes inteligentes"""
    if len(text) <= max_chars:
        return [{"title": "Completo", "content": text}]
    
    parts = []
    current = ""
    part_num = 1
    
    # Divide por parágrafos
    paragraphs = text.split('\n\n')
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # Se o parágrafo é muito longo, divide por frases
        if len(para) > max_chars:
            if current:
                parts.append({"title": f"Parte {part_num}", "content": current.strip()})
                part_num += 1
                current = ""
            
            sentences = re.split(r'(?<=[.!?])\s+', para)
            for sent in sentences:
                if len(current) + len(sent) > max_chars and current:
                    parts.append({"title": f"Parte {part_num}", "content": current.strip()})
                    part_num += 1
                    current = sent
                else:
                    current += (' ' if current else '') + sent
            continue
        
        if len(current) + len(para) > max_chars and current:
            parts.append({"title": f"Parte {part_num}", "content": current.strip()})
            part_num += 1
            current = para
        else:
            current += ('\n\n' if current else '') + para
    
    if current.strip():
        parts.append({"title": f"Parte {part_num}", "content": current.strip()})
    
    return parts

# ============================================
# EXTRAÇÃO DE TEXTO (SEM CACHE PARA EVITAR ERROS)
# ============================================

def extract_text_from_pdf(file_bytes):
    """Extrai texto de PDF"""
    pages_text = []
    
    temp_file = TEMP_DIR / "temp.pdf"
    temp_file.write_bytes(file_bytes)
    
    try:
        with pdfplumber.open(temp_file) as pdf:
            for page in pdf.pages:
                try:
                    text = page.extract_text()
                    if text and text.strip():
                        pages_text.append(text.strip())
                except:
                    continue
    finally:
        if temp_file.exists():
            temp_file.unlink()
    
    if not pages_text:
        return ""
    
    # Remove cabeçalhos/rodapés
    text = remove_headers_footers(pages_text)
    
    # Limpeza completa
    text = full_cleanup(text)
    
    return text

def extract_text_from_epub(file_bytes):
    """Extrai texto de EPUB"""
    text_parts = []
    
    temp_file = TEMP_DIR / "temp.epub"
    temp_file.write_bytes(file_bytes)
    
    try:
        book = epub.read_epub(temp_file)
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            try:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                for script in soup(["script", "style"]):
                    script.decompose()
                text = soup.get_text()
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                if lines:
                    text_parts.append('\n'.join(lines))
            except:
                continue
    finally:
        if temp_file.exists():
            temp_file.unlink()
    
    text = '\n\n'.join(text_parts)
    return full_cleanup(text)

def extract_text_from_txt(file_bytes):
    """Extrai texto de TXT"""
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    
    for encoding in encodings:
        try:
            text = file_bytes.decode(encoding)
            if text.strip():
                return full_cleanup(text)
        except:
            continue
    
    text = file_bytes.decode('utf-8', errors='replace')
    return full_cleanup(text)

# ============================================
# TTS - CONVERSÃO TEXTO PARA FALA
# ============================================

async def text_to_speech(text, voice, output_path):
    """Converte texto em fala"""
    try:
        # Limita tamanho
        if len(text) > 5000:
            text = text[:5000]
        
        # Limpa caracteres problemáticos
        text = re.sub(r'[^\w\sáéíóúâêôãõçàèìòùäëïöüñÁÉÍÓÚÂÊÔÃÕÇÀÈÌÒÙÄËÏÖÜÑ.,!?;:()\-—\'\"\n]', ' ', text, flags=re.UNICODE)
        text = ' '.join(text.split())
        
        if not text.strip():
            return False
        
        communicator = edge_tts.Communicate(text, voice)
        await communicator.save(output_path)
        
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1024
    
    except Exception:
        return False

def run_tts(text, voice, output_path):
    """Wrapper síncrono para TTS"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(text_to_speech(text, voice, output_path))
        loop.close()
        return result
    except:
        return False

def clean_filename(filename):
    """Limpa nome de arquivo"""
    filename = unicodedata.normalize('NFKD', filename).encode('ASCII', 'ignore').decode('ASCII')
    filename = re.sub(r'[^\w\s-]', '', filename)
    filename = re.sub(r'[-\s]+', '_', filename)
    return filename.strip('_')[:80]

def format_time(seconds):
    """Formata tempo"""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}min"
    else:
        return f"{seconds/3600:.1f}h"

# ============================================
# INTERFACE PRINCIPAL
# ============================================

def main():
    # Inicializa sessão
    for key in ['processed_text', 'text_parts', 'audio_files']:
        if key not in st.session_state:
            st.session_state[key] = None if key != 'audio_files' else []
    
    # Header
    st.markdown("""
    <div class="app-header">
        <h1>🎧 AudioBook AI</h1>
        <p>Transforme qualquer texto em audiobook profissional com inteligência textual</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Layout
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown("### 📁 Fonte do Texto")
        
        input_method = st.radio(
            "Método de entrada:",
            ["📤 Upload de Arquivo", "✍️ Digitar/colar Texto"]
        )
        
        st.markdown("---")
        
        uploaded_file = None
        manual_text = ""
        
        if input_method == "📤 Upload de Arquivo":
            uploaded_file = st.file_uploader(
                "Selecione o arquivo",
                type=['pdf', 'epub', 'txt']
            )
            
            if uploaded_file:
                file_size = len(uploaded_file.getvalue()) / (1024 * 1024)
                st.info(f"📄 {uploaded_file.name} • {file_size:.1f} MB")
                
                if st.button("📖 Processar Arquivo", use_container_width=True):
                    with st.spinner("Extraindo e limpando texto..."):
                        try:
                            if uploaded_file.name.endswith('.pdf'):
                                text = extract_text_from_pdf(uploaded_file.getvalue())
                            elif uploaded_file.name.endswith('.epub'):
                                text = extract_text_from_epub(uploaded_file.getvalue())
                            elif uploaded_file.name.endswith('.txt'):
                                text = extract_text_from_txt(uploaded_file.getvalue())
                            else:
                                st.error("Formato não suportado")
                                return
                            
                            if not text or len(text.strip()) < 50:
                                st.error("Texto insuficiente extraído")
                                return
                            
                            st.session_state.processed_text = text
                            st.session_state.text_parts = split_text_smart(text)
                            st.session_state.audio_files = []
                            
                            st.success(f"✅ {len(text):,} caracteres extraídos")
                            
                        except Exception as e:
                            st.error(f"Erro: {str(e)[:200]}")
        else:
            manual_text = st.text_area(
                "Digite ou cole seu texto:",
                height=200,
                placeholder="Seu texto aqui..."
            )
            
            if manual_text and len(manual_text.strip()) >= 50:
                if st.button("📝 Processar Texto", use_container_width=True):
                    text = full_cleanup(manual_text)
                    st.session_state.processed_text = text
                    st.session_state.text_parts = split_text_smart(text)
                    st.session_state.audio_files = []
                    st.success(f"✅ {len(text):,} caracteres")
        
        st.markdown("---")
        st.markdown("### 🎤 Voz")
        
        voice_category = st.selectbox("Categoria:", list(AVAILABLE_VOICES.keys()))
        voice_name = st.selectbox("Voz:", list(AVAILABLE_VOICES[voice_category].keys()))
        voice_id = AVAILABLE_VOICES[voice_category][voice_name]
        
        if st.button("🔊 Testar Voz", use_container_width=True):
            with st.spinner("Testando..."):
                test_file = TEMP_DIR / "test.mp3"
                if run_tts("Olá! Esta é a voz selecionada para seu audiobook.", voice_id, str(test_file)):
                    st.audio(str(test_file))
                    st.success("✅ Voz ok!")
                else:
                    st.error("Erro no teste")
        
        st.markdown("---")
        if st.button("🗑️ Limpar Tudo", use_container_width=True):
            st.session_state.processed_text = None
            st.session_state.text_parts = None
            st.session_state.audio_files = []
            if TEMP_DIR.exists():
                shutil.rmtree(TEMP_DIR)
            TEMP_DIR.mkdir()
            st.rerun()
    
    with col2:
        if not st.session_state.processed_text:
            st.markdown("### 👋 Bem-vindo!")
            st.markdown("""
            <div class="info-box">
            <h4>🧠 Recursos inteligentes:</h4>
            <ul>
                <li>✅ Correção de hifenização (cava-\\nlo → cavalo)</li>
                <li>✅ Remoção de cabeçalhos/rodapés</li>
                <li>✅ Remoção de números de página</li>
                <li>✅ Correção de palavras grudadas</li>
            </ul>
            </div>
            """, unsafe_allow_html=True)
        else:
            text = st.session_state.processed_text
            parts = st.session_state.text_parts
            
            # Stats
            c1, c2, c3 = st.columns(3)
            c1.metric("📝 Caracteres", f"{len(text):,}")
            c2.metric("📚 Palavras", f"{len(text.split()):,}")
            c3.metric("📑 Partes", len(parts))
            
            # Preview
            with st.expander("👁️ Preview do texto limpo"):
                st.text(text[:3000] + ("..." if len(text) > 3000 else ""))
            
            # Narração
            st.markdown("---")
            if st.button("🎙️ Gerar Audiobook", use_container_width=True, type="primary"):
                output_dir = TEMP_DIR / "output"
                output_dir.mkdir(exist_ok=True)
                
                # Limpa
                for f in output_dir.glob("*.mp3"):
                    f.unlink()
                
                st.session_state.audio_files = []
                progress = st.progress(0)
                status = st.empty()
                
                total = len(parts)
                for i, part in enumerate(parts):
                    progress.progress((i+1)/total)
                    status.info(f"🎙️ {part['title']} ({i+1}/{total})")
                    
                    fname = f"{i+1:03d}_{clean_filename(part['title'])}.mp3"
                    out = output_dir / fname
                    
                    if run_tts(part['content'], voice_id, str(out)):
                        st.session_state.audio_files.append(out)
                    else:
                        status.warning(f"⚠️ Falha em: {part['title']}")
                    
                    time.sleep(0.3)
                
                progress.progress(1.0)
                
                if st.session_state.audio_files:
                    status.markdown(f"""
                    <div class="success-box">
                    ✅ {len(st.session_state.audio_files)}/{total} partes geradas!
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    status.error("Nenhum arquivo gerado")
            
            # Download
            if st.session_state.audio_files:
                st.markdown("---")
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for f in st.session_state.audio_files:
                        zf.write(f, f.name)
                
                st.download_button(
                    f"📥 Baixar ZIP ({len(st.session_state.audio_files)} arquivos)",
                    zip_buf.getvalue(),
                    f"audiobook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                    "application/zip",
                    use_container_width=True
                )
                
                # Preview
                with st.expander("🎵 Preview"):
                    for f in st.session_state.audio_files:
                        st.audio(str(f))

if __name__ == "__main__":
    main()
