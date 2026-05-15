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
# CSS PERSONALIZADO - DESIGN PREMIUM
# ============================================

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    * {
        font-family: 'Inter', sans-serif;
    }
    
    .app-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2.5rem;
        border-radius: 20px;
        margin-bottom: 2rem;
        box-shadow: 0 15px 35px rgba(102, 126, 234, 0.25);
        position: relative;
        overflow: hidden;
    }
    
    .app-header::before {
        content: '';
        position: absolute;
        top: -50%;
        right: -50%;
        width: 100%;
        height: 100%;
        background: rgba(255,255,255,0.1);
        transform: rotate(45deg);
    }
    
    .app-header h1 {
        color: white;
        font-size: 2.5rem;
        font-weight: 700;
        margin: 0;
        position: relative;
        z-index: 1;
    }
    
    .app-header p {
        color: rgba(255,255,255,0.9);
        font-size: 1.2rem;
        margin-top: 0.5rem;
        position: relative;
        z-index: 1;
    }
    
    .feature-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 1rem;
        margin: 1.5rem 0;
    }
    
    .feature-card {
        background: white;
        padding: 1.5rem;
        border-radius: 15px;
        border: 1px solid #e8e8e8;
        text-align: center;
        transition: all 0.3s ease;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
    
    .feature-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 10px 25px rgba(0,0,0,0.1);
        border-color: #667eea;
    }
    
    .feature-icon {
        font-size: 2.5rem;
        margin-bottom: 0.5rem;
    }
    
    .feature-card h3 {
        color: #333;
        font-size: 1.1rem;
        margin: 0.5rem 0;
    }
    
    .feature-card p {
        color: #666;
        font-size: 0.9rem;
        margin: 0;
    }
    
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 0.8rem 2rem;
        border-radius: 12px;
        font-weight: 600;
        font-size: 1rem;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
        width: 100%;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(102, 126, 234, 0.5);
    }
    
    .stButton > button:active {
        transform: translateY(0);
    }
    
    .test-button > button {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        box-shadow: 0 4px 15px rgba(17, 153, 142, 0.3);
    }
    
    .test-button > button:hover {
        box-shadow: 0 8px 25px rgba(17, 153, 142, 0.5);
    }
    
    .success-message {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        padding: 1.5rem;
        border-radius: 15px;
        color: white;
        margin: 1rem 0;
    }
    
    .info-message {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 15px;
        color: white;
        margin: 1rem 0;
    }
    
    .footer {
        text-align: center;
        padding: 2rem;
        color: #999;
        font-size: 0.9rem;
    }
    
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    @media (max-width: 768px) {
        .app-header h1 {
            font-size: 1.8rem;
        }
        .app-header p {
            font-size: 1rem;
        }
    }
</style>
""", unsafe_allow_html=True)

# ============================================
# CONFIGURAÇÕES E CONSTANTES
# ============================================

TEMP_DIR = Path(tempfile.mkdtemp())

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
# INTELIGÊNCIA TEXTUAL - CORREÇÕES AVANÇADAS
# ============================================

class TextCleaner:
    """
    Classe especializada em limpar e corrigir textos extraídos de PDF/EPUB
    """
    
    @staticmethod
    def fix_hyphenation(text: str) -> str:
        """
        Corrige palavras hifenizadas no final de linha
        Ex: 'cava-\nlo' -> 'cavalo'
            'guarda-\nchuva' -> 'guardachuva'
        """
        # Padrão: palavra seguida de hífen e quebra de linha
        # Ex: cava-\nlo
        pattern = r'(\w+)-\n(\w+)'
        fixed = re.sub(pattern, r'\1\2', text)
        
        # Padrão: palavra com hífen e espaço
        # Ex: cava- lo
        pattern2 = r'(\w+)-\s+(\w+)'
        fixed = re.sub(pattern2, r'\1\2', fixed)
        
        # Se houve correção, loga
        if fixed != text:
            corrections = len(re.findall(pattern, text)) + len(re.findall(pattern2, text))
            st.info(f"🔧 {corrections} palavras hifenizadas foram corrigidas automaticamente")
        
        return fixed
    
    @staticmethod
    def fix_merged_words(text: str) -> str:
        """
        Tenta identificar palavras grudadas usando dicionário de palavras comuns
        Ex: 'cavalodado' -> 'cavalo dado'
        """
        # Lista de palavras curtas comuns que podem estar grudadas
        common_words = {
            'o', 'a', 'os', 'as', 'um', 'uma', 'uns', 'umas',
            'de', 'do', 'da', 'dos', 'das', 'no', 'na', 'nos', 'nas',
            'e', 'ou', 'se', 'não', 'mas', 'que', 'com', 'sem', 'por',
            'para', 'pra', 'em', 'ao', 'aos', 'à', 'às', 'pelo', 'pela'
        }
        
        # Padrões de correção conhecidos
        common_fixes = {
            'cavalodado': 'cavalo dado',
            'burrode carga': 'burro de carga',
            'péde cabra': 'pé de cabra',
            'couvedeflor': 'couve de flor',
            'guardachuva': 'guarda chuva',
            'girassol': 'gira sol',
            'passatempo': 'passa tempo',
            'malmequer': 'mal me quer',
        }
        
        # Aplica correções conhecidas
        for wrong, correct in common_fixes.items():
            text = text.replace(wrong, correct)
        
        return text
    
    @staticmethod
    def remove_headers_footers(pages_text: list) -> str:
        """
        Remove cabeçalhos e rodapés repetidos entre páginas
        """
        if not pages_text:
            return ""
        
        # Coleta todas as linhas de todas as páginas
        all_lines = []
        for page in pages_text:
            lines = [line.strip() for line in page.split('\n') if line.strip()]
            all_lines.extend(lines)
        
        # Conta frequência de cada linha
        line_counts = Counter(all_lines)
        total_pages = len(pages_text)
        
        # Linhas que aparecem em mais de 70% das páginas são cabeçalho/rodapé
        threshold = max(3, total_pages * 0.7)
        
        # Identifica padrões de ruído
        noise_patterns = set()
        
        for line, count in line_counts.items():
            # Remove linhas que aparecem em quase todas as páginas
            if count >= threshold and len(line) < 150:
                noise_patterns.add(line)
            
            # Remove números de página isolados
            if re.match(r'^\d{1,4}$', line) and count >= 2:
                noise_patterns.add(line)
            
            # Remove linhas de data
            if re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}$', line) and count >= 2:
                noise_patterns.add(line)
        
        # Limpa cada página
        cleaned_pages = []
        for page in pages_text:
            lines = page.split('\n')
            cleaned_lines = []
            
            for line in lines:
                clean_line = line.strip()
                
                # Pula linhas de ruído
                if clean_line in noise_patterns:
                    continue
                
                # Pula linhas que são apenas números
                if re.match(r'^\d+$', clean_line):
                    continue
                
                cleaned_lines.append(clean_line)
            
            if cleaned_lines:
                cleaned_pages.append('\n'.join(cleaned_lines))
        
        noise_removed = len(noise_patterns)
        if noise_removed > 0:
            st.info(f"🧹 {noise_removed} padrões de cabeçalho/rodapé identificados e removidos")
        
        return '\n\n'.join(cleaned_pages)

# ============================================
# FUNÇÕES UTILITÁRIAS
# ============================================

def clean_filename(filename: str) -> str:
    """Limpa nome de arquivo removendo caracteres especiais"""
    filename = unicodedata.normalize('NFKD', filename).encode('ASCII', 'ignore').decode('ASCII')
    filename = re.sub(r'[^\w\s-]', '', filename)
    filename = re.sub(r'[-\s]+', '_', filename)
    return filename.strip('_')[:100]

def format_time(seconds: float) -> str:
    """Formata tempo em formato legível"""
    if seconds < 60:
        return f"{seconds:.0f} segundos"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f} minutos"
    else:
        hours = seconds / 3600
        return f"{hours:.1f} horas"

def full_text_cleanup(text: str) -> str:
    """
    Pipeline completo de limpeza textual
    """
    # 1. Corrige hifenização
    text = TextCleaner.fix_hyphenation(text)
    
    # 2. Corrige palavras grudadas
    text = TextCleaner.fix_merged_words(text)
    
    # 3. Normaliza espaços múltiplos
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    
    # 4. Remove espaços no início e fim
    text = text.strip()
    
    # 5. Garante quebra de parágrafo adequada
    # Se uma linha termina com ponto final, exclamação ou interrogação,
    # e a próxima começa com maiúscula, mantém como novo parágrafo
    text = re.sub(r'([.!?])\n([A-ZÁÉÍÓÚÂÊÔÃÕÇ])', r'\1\n\n\2', text)
    
    # 6. Remove linhas vazias excessivas
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    
    return text

def split_text_smart(text: str, max_chars: int = 4000) -> list:
    """
    Divide texto em partes inteligentes respeitando:
    - Parágrafos
    - Frases completas (não corta no meio)
    - Tamanho máximo por parte
    """
    if len(text) <= max_chars:
        return [{"title": "Completo", "content": text}]
    
    parts = []
    current_part = ""
    part_number = 1
    
    # Divide por parágrafos
    paragraphs = text.split('\n\n')
    
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        
        # Se o parágrafo sozinho já é maior que o máximo
        if len(paragraph) > max_chars:
            # Se já temos conteúdo acumulado, salva
            if current_part:
                parts.append({
                    "title": f"Parte {part_number}",
                    "content": current_part.strip()
                })
                part_number += 1
                current_part = ""
            
            # Divide o parágrafo longo em frases
            sentences = re.split(r'(?<=[.!?])\s+', paragraph)
            for sentence in sentences:
                if len(current_part) + len(sentence) > max_chars and current_part:
                    parts.append({
                        "title": f"Parte {part_number}",
                        "content": current_part.strip()
                    })
                    part_number += 1
                    current_part = sentence
                else:
                    current_part += (' ' if current_part else '') + sentence
            
            continue
        
        # Se adicionar este parágrafo exceder o limite
        if len(current_part) + len(paragraph) > max_chars and current_part:
            parts.append({
                "title": f"Parte {part_number}",
                "content": current_part.strip()
            })
            part_number += 1
            current_part = paragraph
        else:
            current_part += ('\n\n' if current_part else '') + paragraph
    
    # Adiciona última parte
    if current_part.strip():
        parts.append({
            "title": f"Parte {part_number}",
            "content": current_part.strip()
        })
    
    return parts

# ============================================
# FUNÇÕES DE EXTRAÇÃO DE TEXTO
# ============================================

@st.cache_data(ttl=3600, max_entries=10)
def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extrai texto de PDF com limpeza inteligente de:
    - Cabeçalhos e rodapés
    - Números de página
    - Palavras hifenizadas
    """
    pages_text = []
    
    temp_file = TEMP_DIR / f"temp_{int(time.time())}.pdf"
    temp_file.write_bytes(file_bytes)
    
    try:
        with pdfplumber.open(temp_file) as pdf:
            total_pages = len(pdf.pages)
            
            for i, page in enumerate(pdf.pages):
                try:
                    text = page.extract_text()
                    if text and text.strip():
                        pages_text.append(text.strip())
                except:
                    continue
                
                # Log a cada 50 páginas
                if (i + 1) % 50 == 0:
                    st.write(f"📄 Processando página {i+1} de {total_pages}...")
            
            st.write(f"✅ {total_pages} páginas extraídas")
    finally:
        if temp_file.exists():
            temp_file.unlink()
    
    if not pages_text:
        return ""
    
    # Aplica limpeza de cabeçalhos/rodapés
    text = TextCleaner.remove_headers_footers(pages_text)
    
    # Aplica pipeline completo de limpeza
    text = full_text_cleanup(text)
    
    return text

@st.cache_data(ttl=3600, max_entries=10)
def extract_text_from_epub(file_bytes: bytes) -> str:
    """Extrai texto de EPUB com limpeza inteligente"""
    text_parts = []
    
    temp_file = TEMP_DIR / f"temp_{int(time.time())}.epub"
    temp_file.write_bytes(file_bytes)
    
    try:
        book = epub.read_epub(temp_file)
        
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            try:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                for script in soup(["script", "style"]):
                    script.decompose()
                text = soup.get_text()
                
                lines = []
                for line in text.split('\n'):
                    line = line.strip()
                    if line:
                        lines.append(line)
                
                if lines:
                    text_parts.append('\n'.join(lines))
            except:
                continue
    finally:
        if temp_file.exists():
            temp_file.unlink()
    
    text = '\n\n'.join(text_parts)
    
    # Aplica pipeline de limpeza
    text = full_text_cleanup(text)
    
    return text

def extract_text_from_txt(file_bytes: bytes) -> str:
    """Extrai texto de TXT com detecção de encoding"""
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    
    for encoding in encodings:
        try:
            text = file_bytes.decode(encoding)
            if text.strip():
                return full_text_cleanup(text)
        except:
            continue
    
    text = file_bytes.decode('utf-8', errors='replace')
    return full_text_cleanup(text)

# ============================================
# FUNÇÃO DE NARRAÇÃO (TTS)
# ============================================

async def text_to_speech(text: str, voice: str, output_path: str) -> bool:
    """
    Converte texto em fala usando Edge TTS
    Com retry automático em caso de falha
    """
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            # Limita tamanho do texto
            if len(text) > 5000:
                text = text[:5000]
            
            # Limpa caracteres problemáticos mantendo pontuação
            text = re.sub(r'[^\w\sáéíóúâêôãõçàèìòùäëïöüñÁÉÍÓÚÂÊÔÃÕÇÀÈÌÒÙÄËÏÖÜÑ.,!?;:()\-—\'\"\n]', ' ', text, flags=re.UNICODE)
            text = ' '.join(text.split())
            
            if not text.strip():
                return False
            
            # Cria comunicador
            communicator = edge_tts.Communicate(text, voice)
            
            # Salva áudio
            await communicator.save(output_path)
            
            # Verifica se o arquivo foi criado
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                return True
            
        except Exception as e:
            if attempt < max_retries - 1:
                # Espera um pouco antes de tentar novamente
                await asyncio.sleep(2)
                continue
            else:
                st.error(f"Erro na narração após {max_retries} tentativas: {str(e)[:200]}")
                return False
    
    return False

def run_async_tts(text: str, voice: str, output_path: str) -> bool:
    """Executa TTS de forma síncrona"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            text_to_speech(text, voice, output_path)
        )
        loop.close()
        return result
    except Exception as e:
        st.error(f"Erro ao executar TTS: {str(e)[:200]}")
        return False

# ============================================
# INTERFACE DO USUÁRIO
# ============================================

def main():
    # Inicializa estado da sessão
    if 'processed_text' not in st.session_state:
        st.session_state.processed_text = None
    if 'text_parts' not in st.session_state:
        st.session_state.text_parts = None
    if 'audio_files' not in st.session_state:
        st.session_state.audio_files = []
    if 'narration_stopped' not in st.session_state:
        st.session_state.narration_stopped = False
    
    # ============================================
    # HEADER
    # ============================================
    
    st.markdown("""
    <div class="app-header">
        <h1>🎧 AudioBook AI</h1>
        <p>Transforme qualquer texto em audiobook profissional com inteligência textual avançada</p>
    </div>
    """, unsafe_allow_html=True)
    
    # ============================================
    # LAYOUT PRINCIPAL
    # ============================================
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown("### 📁 Fonte do Texto")
        
        input_method = st.radio(
            "Como deseja fornecer o texto?",
            ["📤 Upload de Arquivo", "✍️ Digitar/colar Texto"],
            help="Escolha entre fazer upload de um arquivo ou digitar o texto manualmente"
        )
        
        st.markdown("---")
        
        if input_method == "📤 Upload de Arquivo":
            uploaded_file = st.file_uploader(
                "Selecione o arquivo",
                type=['pdf', 'epub', 'txt'],
                help="Formatos aceitos: PDF, EPUB e TXT"
            )
            
            if uploaded_file:
                file_size = len(uploaded_file.getvalue()) / (1024 * 1024)
                st.info(f"""
                **Arquivo:** {uploaded_file.name}  
                **Tamanho:** {file_size:.1f} MB
                """)
                
                if st.button("📖 Processar Arquivo", use_container_width=True):
                    with st.spinner("Extraindo e limpando texto com inteligência artificial..."):
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
                                st.error("Não foi possível extrair texto suficiente do arquivo")
                                return
                            
                            st.session_state.processed_text = text
                            st.session_state.text_parts = split_text_smart(text)
                            st.session_state.audio_files = []
                            st.session_state.narration_stopped = False
                            
                            st.success(f"✅ Texto extraído e limpo: {len(text):,} caracteres")
                            
                        except Exception as e:
                            st.error(f"Erro ao processar arquivo: {str(e)[:300]}")
                            return
        else:
            manual_text = st.text_area(
                "Digite ou cole seu texto",
                height=200,
                placeholder="Cole aqui o texto que deseja transformar em audiobook...",
                help="Mínimo de 50 caracteres"
            )
            
            if manual_text and len(manual_text.strip()) >= 50:
                if st.button("📝 Processar Texto", use_container_width=True):
                    # Aplica limpeza também no texto manual
                    cleaned_text = full_text_cleanup(manual_text)
                    st.session_state.processed_text = cleaned_text
                    st.session_state.text_parts = split_text_smart(cleaned_text)
                    st.session_state.audio_files = []
                    st.session_state.narration_stopped = False
                    st.success(f"✅ Texto processado: {len(cleaned_text):,} caracteres")
        
        st.markdown("---")
        st.markdown("### 🎤 Configurações de Voz")
        
        voice_category = st.selectbox(
            "Categoria de Voz",
            list(AVAILABLE_VOICES.keys()),
            help="Escolha o idioma/categoria da voz"
        )
        
        voice_name = st.selectbox(
            "Voz",
            list(AVAILABLE_VOICES[voice_category].keys()),
            help="Escolha a voz específica para narração"
        )
        
        voice_id = AVAILABLE_VOICES[voice_category][voice_name]
        
        st.markdown('<div class="test-button">', unsafe_allow_html=True)
        if st.button("🔊 Testar Voz Selecionada", use_container_width=True):
            with st.spinner("Gerando teste de voz..."):
                test_text = "Olá! Esta é uma demonstração da voz selecionada. As palavras hifenizadas e cabeçalhos serão corrigidos automaticamente."
                test_file = TEMP_DIR / "voice_test.mp3"
                
                if run_async_tts(test_text, voice_id, str(test_file)):
                    st.audio(str(test_file))
                    st.success("✅ Voz testada com sucesso!")
                else:
                    st.error("Erro ao testar voz. Verifique sua conexão com a internet.")
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown("---")
        if st.button("🗑️ Limpar Tudo e Recomeçar", use_container_width=True):
            st.session_state.processed_text = None
            st.session_state.text_parts = None
            st.session_state.audio_files = []
            st.session_state.narration_stopped = False
            if TEMP_DIR.exists():
                shutil.rmtree(TEMP_DIR)
            TEMP_DIR.mkdir()
            st.rerun()
    
    with col2:
        if not st.session_state.processed_text:
            st.markdown("### 👋 Bem-vindo ao AudioBook AI!")
            
            st.markdown("""
            <div class="feature-grid">
                <div class="feature-card">
                    <div class="feature-icon">🧠</div>
                    <h3>IA Textual</h3>
                    <p>Corrige hifenização e palavras grudadas</p>
                </div>
                <div class="feature-card">
                    <div class="feature-icon">🧹</div>
                    <h3>Limpeza Inteligente</h3>
                    <p>Remove cabeçalhos e rodapés</p>
                </div>
                <div class="feature-card">
                    <div class="feature-icon">🎤</div>
                    <h3>Vozes Neurais</h3>
                    <p>+10 vozes premium</p>
                </div>
                <div class="feature-card">
                    <div class="feature-icon">📄</div>
                    <h3>Múltiplos Formatos</h3>
                    <p>PDF, EPUB e TXT</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("""
            <div class="info-message">
                <h4>🚀 Novidades desta versão:</h4>
                <ul>
                    <li>✅ Correção automática de palavras hifenizadas (cava-\\nlo → cavalo)</li>
                    <li>✅ Remoção inteligente de cabeçalhos e rodapés</li>
                    <li>✅ Eliminação de números de página</li>
                    <li>✅ Narração com retry automático (não para no meio)</li>
                    <li>✅ Divisão inteligente por frases e parágrafos</li>
                </ul>
            </div>
            """, unsafe_allow_html=True)
        
        else:
            text = st.session_state.processed_text
            parts = st.session_state.text_parts
            
            st.markdown("### 📊 Estatísticas do Texto")
            
            stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
            
            with stat_col1:
                st.metric("📝 Caracteres", f"{len(text):,}")
            
            with stat_col2:
                word_count = len(text.split())
                st.metric("📚 Palavras", f"{word_count:,}")
            
            with stat_col3:
                part_count = len(parts)
                st.metric("📑 Partes", part_count)
            
            with stat_col4:
                estimated_time = len(text) / 1000 * 0.4
                st.metric("⏱️ Tempo Est.", format_time(estimated_time))
            
            # Preview do texto
            with st.expander("👁️ Visualizar Texto Extraído (após limpeza)", expanded=False):
                preview = text[:2000] + "..." if len(text) > 2000 else text
                st.text_area("Conteúdo:", preview, height=200, disabled=True)
            
            # Lista de partes
            if len(parts) > 1:
                with st.expander(f"📋 Ver {len(parts)} Partes para Narração", expanded=False):
                    for i, part in enumerate(parts, 1):
                        preview_part = part['content'][:100] + "..."
                        st.write(f"**{i}. {part['title']}** - {len(part['content']):,} caracteres")
                        st.caption(f"Início: {preview_part}")
            
            st.markdown("---")
            st.markdown("### 🎬 Gerar Audiobook")
            
            if st.button("🎙️ Iniciar Narração", use_container_width=True, type="primary"):
                output_dir = TEMP_DIR / "audiobook_output"
                output_dir.mkdir(exist_ok=True)
                
                # Limpa arquivos anteriores
                for old_file in output_dir.glob("*.mp3"):
                    try:
                        old_file.unlink()
                    except:
                        pass
                
                st.session_state.audio_files = []
                st.session_state.narration_stopped = False
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                part_status = st.empty()
                
                total_parts = len(parts)
                success_count = 0
                fail_count = 0
                
                for i, part in enumerate(parts):
                    # Verifica se foi interrompido
                    if st.session_state.narration_stopped:
                        break
                    
                    progress = (i + 1) / total_parts
                    progress_bar.progress(progress)
                    
                    status_text.info(f"🎙️ Narrando {part['title']}... ({i+1}/{total_parts})")
                    
                    filename = f"{i+1:03d}_{clean_filename(part['title'])}.mp3"
                    output_file = output_dir / filename
                    
                    start_time = time.time()
                    success = run_async_tts(part['content'], voice_id, str(output_file))
                    elapsed = time.time() - start_time
                    
                    if success:
                        st.session_state.audio_files.append(output_file)
                        success_count += 1
                        part_status.success(f"✅ {part['title']} concluído em {elapsed:.1f}s")
                    else:
                        fail_count += 1
                        part_status.error(f"❌ Falha ao narrar {part['title']}")
                        
                        # Pergunta se quer continuar
                        if i < total_parts - 1:
                            col_continue, col_stop = st.columns(2)
                            with col_continue:
                                if st.button("▶️ Continuar mesmo assim", key=f"continue_{i}"):
                                    continue
                            with col_stop:
                                if st.button("⏹️ Parar narração", key=f"stop_{i}"):
                                    st.session_state.narration_stopped = True
                                    break
                    
                    # Pequena pausa entre partes
                    time.sleep(0.3)
                
                progress_bar.progress(1.0)
                
                if st.session_state.audio_files:
                    status_text.markdown(f"""
                    <div class="success-message">
                        <h4>✅ Audiobook Gerado!</h4>
                        <p>📁 {success_count} de {total_parts} partes narradas com sucesso<br>
                        {'⚠️ ' + str(fail_count) + ' falhas' if fail_count > 0 else ''}</p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    status_text.error("❌ Nenhum arquivo de áudio foi gerado")
            
            # Mostra arquivos gerados
            if st.session_state.audio_files:
                st.markdown("---")
                st.markdown("### 📥 Download e Preview")
                
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for audio_file in st.session_state.audio_files:
                        zf.write(audio_file, audio_file.name)
                
                col_download, col_space = st.columns([2, 1])
                with col_download:
                    st.download_button(
                        label=f"📥 Baixar Audiobook Completo ({len(st.session_state.audio_files)} arquivos)",
                        data=zip_buffer.getvalue(),
                        file_name=f"audiobook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                        mime="application/zip",
                        use_container_width=True
                    )
                
                st.markdown("#### 🎵 Preview dos Arquivos")
                
                for audio_file in st.session_state.audio_files:
                    with st.expander(f"🎧 {audio_file.name}", expanded=False):
                        st.audio(str(audio_file))
    
    st.markdown("---")
    st.markdown("""
    <div class="footer">
        <p>🎧 AudioBook AI v2.0 | Tecnologia Microsoft Edge TTS | Com inteligência textual avançada</p>
        <p>✨ Correção de hifenização • Remoção de cabeçalhos • Narração robusta</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
