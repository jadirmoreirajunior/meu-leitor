import streamlit as st
import asyncio
import edge_tts
import os
import zipfile
import io
import shutil
import re
import tempfile
import unicodedata
from collections import Counter
from datetime import datetime
import pdfplumber
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup
import base64
from pathlib import Path
import json
from typing import List, Dict, Optional, Tuple
import threading
from concurrent.futures import ThreadPoolExecutor
import time

# --- CONFIGURAÇÃO PROFISSIONAL ---
st.set_page_config(
    page_title="Narrador.AI Pro | Estúdio de Audiobook Inteligente",
    page_icon="🎧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS PROFISSIONAL ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    * {
        font-family: 'Inter', sans-serif;
    }
    
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 20px;
        color: white;
        margin-bottom: 2rem;
        box-shadow: 0 10px 30px rgba(102, 126, 234, 0.3);
    }
    
    .feature-card {
        background: white;
        padding: 1.5rem;
        border-radius: 15px;
        border: 1px solid #e0e0e0;
        margin: 1rem 0;
        transition: transform 0.3s, box-shadow 0.3s;
    }
    
    .feature-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 15px 30px rgba(0,0,0,0.1);
    }
    
    .voice-selector {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 10px;
        border: 2px solid #667eea;
    }
    
    .progress-container {
        background: #f0f2f6;
        border-radius: 10px;
        padding: 1rem;
    }
    
    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 1rem;
        margin: 1rem 0;
    }
    
    .stat-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
    }
    
    .stat-number {
        font-size: 2rem;
        font-weight: bold;
        color: #667eea;
    }
    
    .stat-label {
        font-size: 0.9rem;
        color: #666;
        margin-top: 0.5rem;
    }
    
    div[data-testid="stToolbar"] {
        display: none;
    }
    
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        border-radius: 10px;
        font-weight: 600;
        transition: all 0.3s;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
    }
    
    .custom-audio {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
    }
    
    .text-input-custom {
        border: 2px solid #667eea;
        border-radius: 10px;
        padding: 1rem;
    }
    
    .chapter-list {
        max-height: 400px;
        overflow-y: auto;
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

# --- DIRETÓRIOS E CONFIGURAÇÕES ---
OUTPUT_DIR = Path("audiobook_pro_out")
OUTPUT_DIR.mkdir(exist_ok=True)

TEMP_DIR = Path(tempfile.mkdtemp())

# --- VOZES EXPANDIDAS ---
VOICES = {
    "🇧🇷 Português": {
        "Antonio (Masculino - Neutro)": "pt-BR-AntonioNeural",
        "Francisca (Feminina - Natural)": "pt-BR-FranciscaNeural",
        "Brenda (Feminina - Jovem)": "pt-BR-BrendaNeural",
        "Donato (Masculino - Maduro)": "pt-BR-DonatoNeural",
        "Thalita (Feminina - Profissional)": "pt-BR-ThalitaNeural",
        "Julio (Masculino - Formal)": "pt-BR-JulioNeural",
        "Nicolau (Masculino - Casual)": "pt-BR-NicolauNeural",
        "Leticia (Feminina - Suave)": "pt-BR-LeticiaNeural",
        "Yara (Feminina - Expressiva)": "pt-BR-YaraNeural",
        "Valeria (Feminina - Elegante)": "pt-BR-ValeriaNeural"
    },
    "🌍 Multilíngue": {
        "Alessio (Multilíngue - Italiano)": "it-IT-AlessioMultilingualNeural",
        "Andrew (Multilíngue - Inglês)": "en-US-AndrewMultilingualNeural",
        "Emma (Multilíngue - Inglês)": "en-US-EmmaMultilingualNeural",
        "Brian (Multilíngue - Inglês)": "en-US-BrianMultilingualNeural",
        "Ava (Multilíngue - Inglês)": "en-US-AvaMultilingualNeural",
        "Florian (Multilíngue - Francês)": "fr-FR-FlorianMultilingualNeural",
        "Serena (Multilíngue - Italiano)": "it-IT-SerenaMultilingualNeural"
    },
    "🇺🇸 Inglês": {
        "Jenny (Feminina - US)": "en-US-JennyNeural",
        "Guy (Masculino - US)": "en-US-GuyNeural",
        "Aria (Feminina - US)": "en-US-AriaNeural",
        "Davis (Masculino - US)": "en-US-DavisNeural"
    },
    "🇪🇸 Espanhol": {
        "Alvaro (Masculino - Espanha)": "es-ES-AlvaroNeural",
        "Elvira (Feminina - Espanha)": "es-ES-ElviraNeural"
    }
}

# --- CONFIGURAÇÕES DE ÁUDIO ---
AUDIO_SETTINGS = {
    "Velocidade": {
        "Muito Lenta (0.5x)": "-50%",
        "Lenta (0.75x)": "-25%",
        "Normal (1.0x)": "+0%",
        "Rápida (1.25x)": "+25%",
        "Muito Rápida (1.5x)": "+50%"
    },
    "Tom": {
        "Mais Grave (-20%)": "-20%",
        "Levemente Grave (-10%)": "-10%",
        "Normal": "+0%",
        "Levemente Agudo (+10%)": "+10%",
        "Mais Agudo (+20%)": "+20%"
    }
}

# --- FUNÇÕES DE UTILIDADE ---
def normalize_filename(text: str) -> str:
    """Normaliza nomes de arquivo removendo acentos e caracteres especiais"""
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    text = re.sub(r'[^\w\s-]', '', text).strip()
    text = re.sub(r'[-\s]+', '_', text)
    return text[:100]  # Limita tamanho

def get_audio_duration(audio_path: str) -> float:
    """Estima duração do áudio baseado no tamanho do arquivo"""
    try:
        size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        # Estimativa aproximada: 1MB ≈ 1 minuto para MP3 de qualidade média
        return size_mb * 60
    except:
        return 0

def format_duration(seconds: float) -> str:
    """Formata duração em formato legível"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}h {minutes}min {secs}s"
    elif minutes > 0:
        return f"{minutes}min {secs}s"
    else:
        return f"{secs}s"

# --- SISTEMA DE LOG ---
class ProcessingLog:
    def __init__(self):
        self.logs = []
        self.start_time = None
    
    def start(self):
        self.start_time = time.time()
        self.logs = []
    
    def add(self, message: str, level: str = "info"):
        timestamp = time.time() - self.start_time if self.start_time else 0
        self.logs.append({
            "timestamp": f"{timestamp:.1f}s",
            "message": message,
            "level": level
        })
    
    def get_stats(self) -> Dict:
        if not self.start_time:
            return {}
        elapsed = time.time() - self.start_time
        return {
            "total_time": format_duration(elapsed),
            "total_operations": len(self.logs),
            "errors": len([l for l in self.logs if l["level"] == "error"]),
            "warnings": len([l for l in self.logs if l["level"] == "warning"])
        }

processing_log = ProcessingLog()

# --- PROCESSAMENTO DE TEXTO AVANÇADO ---
class TextProcessor:
    @staticmethod
    def clean_professional_text(pages: List[str]) -> str:
        """Limpeza profissional de texto com múltiplas estratégias"""
        if not pages:
            return ""
        
        processing_log.add("Iniciando limpeza profissional de texto")
        
        all_lines = []
        for page in pages:
            all_lines.extend([line.strip() for line in page.split('\n') if line.strip()])
        
        # Detecta padrões de ruído
        line_counts = Counter(all_lines)
        total_pages = len(pages)
        
        # Remove cabeçalhos/rodapés repetidos
        threshold = total_pages * 0.7
        repeated_noise = {line for line, count in line_counts.items() 
                         if count > threshold and len(line) < 100 and not line.isdigit()}
        
        # Remove números de página isolados
        page_numbers = {line for line in all_lines 
                       if re.match(r'^\d{1,4}$', line) and line_counts[line] > 2}
        
        noise_patterns = repeated_noise.union(page_numbers)
        
        cleaned_text_list = []
        for page in pages:
            page_lines = page.split('\n')
            final_page_lines = []
            consecutive_empty = 0
            
            for line in page_lines:
                clean_line = line.strip()
                
                # Pula linhas de ruído
                if clean_line in noise_patterns:
                    continue
                
                # Pula URLs
                if re.match(r'https?://', clean_line):
                    continue
                
                # Pula linhas muito curtas que parecem numeração
                if re.match(r'^[ivxlcdm]{1,5}[\.\)]?\s*$', clean_line.lower()):
                    continue
                
                # Controle de linhas vazias consecutivas
                if not clean_line:
                    consecutive_empty += 1
                    if consecutive_empty > 2:  # Máximo 2 linhas vazias
                        continue
                else:
                    consecutive_empty = 0
                
                if clean_line:
                    final_page_lines.append(clean_line)
            
            if final_page_lines:
                cleaned_text_list.append("\n".join(final_page_lines))
        
        processing_log.add(f"Limpeza concluída: {len(all_lines)} linhas processadas")
        return "\n\n".join(cleaned_text_list)
    
    @staticmethod
    def detect_chapters(text: str) -> List[Dict]:
        """Detecção inteligente de capítulos com múltiplos padrões"""
        processing_log.add("Detectando estrutura de capítulos")
        
        # Padrões de capítulo
        patterns = [
            r'\n\s*(?:Capítulo|Chapter|CAPÍTULO|CAPITULO)\s+(\d+|[IVXLCDM]+)\b',
            r'\n\s*(?:Parte|Part|PARTE)\s+(\d+|[IVXLCDM]+)\b',
            r'\n\s*(\d+)\s*\n\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]',  # Número de capítulo simples
            r'\n\s*([IVXLCDM]+)\s*\n',  # Numeração romana
        ]
        
        all_matches = []
        for pattern in patterns:
            matches = list(re.finditer(pattern, text))
            all_matches.extend(matches)
        
        if len(all_matches) >= 2:
            # Ordena por posição e remove duplicatas próximas
            all_matches.sort(key=lambda x: x.start())
            unique_matches = []
            last_pos = -1000
            
            for match in all_matches:
                if match.start() - last_pos > 100:  # Evita duplicatas próximas
                    unique_matches.append(match)
                    last_pos = match.start()
            
            # Extrai conteúdo dos capítulos
            chapters = []
            for i, match in enumerate(unique_matches):
                start = match.start()
                end = unique_matches[i+1].start() if i+1 < len(unique_matches) else len(text)
                
                title = match.group(0).strip()
                content = text[start:end].strip()
                
                if len(content) > 50:  # Filtra capítulos muito curtos
                    chapters.append({
                        "title": title,
                        "content": content,
                        "position": i + 1
                    })
            
            if len(chapters) >= 3:
                processing_log.add(f"{len(chapters)} capítulos detectados")
                return chapters
        
        # Fallback: divisão por tamanho
        processing_log.add("Usando divisão por tamanho (capítulos não detectados)")
        return TextProcessor.split_by_size(text)
    
    @staticmethod
    def split_by_size(text: str, max_chars: int = 4000) -> List[Dict]:
        """Divide texto em partes de tamanho similar respeitando parágrafos"""
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = ""
        current_size = 0
        
        for para in paragraphs:
            para_size = len(para)
            
            if current_size + para_size > max_chars and current_chunk:
                chunks.append({
                    "title": f"Parte {len(chunks) + 1}",
                    "content": current_chunk.strip(),
                    "position": len(chunks) + 1
                })
                current_chunk = para
                current_size = para_size
            else:
                current_chunk += ("\n\n" if current_chunk else "") + para
                current_size += para_size
        
        if current_chunk:
            chunks.append({
                "title": f"Parte {len(chunks) + 1}",
                "content": current_chunk.strip(),
                "position": len(chunks) + 1
            })
        
        return chunks

# --- SISTEMA DE EXTRAÇÃO ---
class DocumentExtractor:
    @staticmethod
    def extract_from_pdf(file) -> List[str]:
        """Extração otimizada de PDF"""
        processing_log.add("Extraindo conteúdo do PDF")
        pages_content = []
        
        with pdfplumber.open(file) as pdf:
            total_pages = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    pages_content.append(text)
                if (i + 1) % 10 == 0:
                    processing_log.add(f"PDF: {i+1}/{total_pages} páginas processadas")
        
        processing_log.add(f"PDF extraído: {total_pages} páginas")
        return pages_content
    
    @staticmethod
    def extract_from_epub(file) -> List[str]:
        """Extração robusta de EPUB"""
        processing_log.add("Extraindo conteúdo do EPUB")
        pages_content = []
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.epub') as tmp_file:
            tmp_file.write(file.getbuffer())
            tmp_path = tmp_file.name
        
        try:
            book = epub.read_epub(tmp_path)
            items = list(book.get_items_of_type(ITEM_DOCUMENT))
            
            for i, item in enumerate(items):
                try:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    # Remove scripts e estilos
                    for script in soup(["script", "style"]):
                        script.decompose()
                    text = soup.get_text()
                    if text.strip():
                        pages_content.append(text)
                except:
                    continue
                
                if (i + 1) % 5 == 0:
                    processing_log.add(f"EPUB: {i+1}/{len(items)} seções processadas")
            
            processing_log.add(f"EPUB extraído: {len(pages_content)} seções com conteúdo")
        finally:
            os.unlink(tmp_path)
        
        return pages_content
    
    @staticmethod
    def extract_from_txt(file) -> str:
        """Extração de texto puro com detecção de encoding"""
        processing_log.add("Extraindo conteúdo do TXT")
        
        content = file.getvalue()
        # Tenta diferentes encodings
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            try:
                return content.decode(encoding)
            except:
                continue
        
        # Fallback
        processing_log.add("Usando encoding padrão com substituição de caracteres", "warning")
        return content.decode('utf-8', errors='replace')

# --- SISTEMA DE NARRAÇÃO ---
class Narrator:
    def __init__(self, voice_id: str, rate: str = "+0%", pitch: str = "+0%"):
        self.voice_id = voice_id
        self.rate = rate
        self.pitch = pitch
        self.log = []
    
    async def narrate_chunk(self, text: str, output_path: str, chunk_info: Dict) -> Dict:
        """Narra um chunk de texto com configurações personalizadas"""
        try:
            communicate = edge_tts.Communicate(
                text,
                self.voice_id,
                rate=self.rate,
                pitch=self.pitch
            )
            
            await communicate.save(output_path)
            
            # Estima duração
            duration = get_audio_duration(output_path)
            
            return {
                "success": True,
                "path": output_path,
                "title": chunk_info.get("title", "Unknown"),
                "duration": duration,
                "size_mb": os.path.getsize(output_path) / (1024 * 1024)
            }
        except Exception as e:
            return {
                "success": False,
                "title": chunk_info.get("title", "Unknown"),
                "error": str(e)
            }
    
    async def narrate_chapters(self, chapters: List[Dict], output_dir: str, 
                              progress_callback=None) -> List[Dict]:
        """Narra múltiplos capítulos com controle de progresso"""
        results = []
        
        for i, chapter in enumerate(chapters):
            if progress_callback:
                progress_callback(i + 1, len(chapters), chapter["title"])
            
            clean_name = normalize_filename(chapter["title"])
            filename = f"{i+1:03d}_{clean_name}.mp3"
            output_path = os.path.join(output_dir, filename)
            
            result = await self.narrate_chunk(chapter["content"], output_path, chapter)
            results.append(result)
            
            # Pequena pausa para evitar throttling
            await asyncio.sleep(0.5)
        
        return results

# --- INTERFACE PRINCIPAL ---
def main():
    # Header profissional
    st.markdown("""
    <div class="main-header">
        <h1>🎧 Narrador.AI Pro</h1>
        <p style="font-size: 1.2rem; opacity: 0.9;">
            Transforme seus documentos em audiobooks profissionais com vozes neurais de última geração
        </p>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-number">20+</div>
                <div class="stat-label">Vozes Neurais</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">5</div>
                <div class="stat-label">Idiomas</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">PDF/EPUB</div>
                <div class="stat-label">Formatos</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Sidebar profissional
    with st.sidebar:
        st.markdown("### 📁 Upload de Arquivo")
        
        col1, col2 = st.columns(2)
        with col1:
            input_method = st.radio(
                "Método de entrada",
                ["📄 Arquivo", "✍️ Texto Manual"],
                key="input_method"
            )
        
        if input_method == "📄 Arquivo":
            uploaded_file = st.file_uploader(
                "Selecione o documento",
                type=["pdf", "epub", "txt", "mobi"],
                help="Formatos suportados: PDF, EPUB, TXT, MOBI"
            )
        else:
            uploaded_file = None
            manual_text = st.text_area(
                "Cole ou digite seu texto aqui",
                height=200,
                placeholder="Digite ou cole o texto que deseja converter em áudio...",
                help="Mínimo de 50 caracteres para processamento"
            )
        
        st.markdown("---")
        st.markdown("### 🎤 Configurações de Voz")
        
        # Seletor de voz por categoria
        language_category = st.selectbox(
            "Idioma / Categoria",
            list(VOICES.keys()),
            help="Selecione a categoria de vozes"
        )
        
        voice_name = st.selectbox(
            "Voz Específica",
            list(VOICES[language_category].keys()),
            help="Escolha a voz neural para narração"
        )
        
        # Configurações avançadas de áudio
        with st.expander("⚙️ Configurações Avançadas de Áudio"):
            speed = st.select_slider(
                "Velocidade de Narração",
                options=list(AUDIO_SETTINGS["Velocidade"].keys()),
                value="Normal (1.0x)"
            )
            
            pitch = st.select_slider(
                "Tom de Voz",
                options=list(AUDIO_SETTINGS["Tom"].keys()),
                value="Normal"
            )
            
            st.info("💡 Ajuste a velocidade e tom para personalizar a narração")
        
        # Preview de voz
        if st.button("🔊 Testar Voz", use_container_width=True):
            with st.spinner("Gerando preview..."):
                preview_text = "Olá! Esta é uma demonstração da voz selecionada para seu audiobook."
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                preview_path = TEMP_DIR / "preview.mp3"
                loop.run_until_complete(
                    edge_tts.Communicate(
                        preview_text,
                        VOICES[language_category][voice_name],
                        rate=AUDIO_SETTINGS["Velocidade"][speed],
                        pitch=AUDIO_SETTINGS["Tom"][pitch]
                    ).save(str(preview_path))
                )
                loop.close()
                
                st.audio(str(preview_path))
        
        st.markdown("---")
        
        # Controles
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🗑️ Resetar", use_container_width=True):
                if OUTPUT_DIR.exists():
                    shutil.rmtree(OUTPUT_DIR)
                OUTPUT_DIR.mkdir()
                st.cache_data.clear()
                st.rerun()
        
        with col2:
            if st.button("ℹ️ Ajuda", use_container_width=True):
                st.info("""
                **Formatos Suportados:**
                - PDF (com extração de texto)
                - EPUB (e-books)
                - TXT (texto puro)
                - MOBI (em desenvolvimento)
                
                **Limitações:**
                - Máximo recomendado: 500 páginas
                - Tempo de processamento: ~2min/página
                """)

    # Área principal
    tab1, tab2, tab3 = st.tabs(["📚 Processamento", "📊 Estatísticas", "📝 Log"])
    
    with tab1:
        # Verifica se tem conteúdo para processar
        has_content = False
        
        if input_method == "📄 Arquivo" and uploaded_file:
            has_content = True
        elif input_method == "✍️ Texto Manual" and 'manual_text' in locals() and len(manual_text.strip()) > 50:
            has_content = True
            # Cria um "arquivo virtual" para processamento uniforme
            uploaded_file = io.BytesIO(manual_text.encode('utf-8'))
            uploaded_file.name = "texto_manual.txt"
        
        if has_content:
            # Inicializa estado se necessário
            if 'processed_chunks' not in st.session_state or \
               st.session_state.get('last_file') != uploaded_file.name:
                
                with st.spinner("🔍 Analisando documento..."):
                    processing_log.start()
                    
                    # Extrai conteúdo
                    if uploaded_file.name.endswith('.pdf'):
                        pages = DocumentExtractor.extract_from_pdf(uploaded_file)
                        full_text = TextProcessor.clean_professional_text(pages)
                    elif uploaded_file.name.endswith('.epub'):
                        pages = DocumentExtractor.extract_from_epub(uploaded_file)
                        full_text = TextProcessor.clean_professional_text(pages)
                    elif uploaded_file.name.endswith('.txt') or uploaded_file.name == "texto_manual.txt":
                        full_text = DocumentExtractor.extract_from_txt(uploaded_file)
                    else:
                        st.error("❌ Formato não suportado")
                        return
                    
                    if full_text and len(full_text) > 50:
                        st.session_state.processed_chunks = TextProcessor.detect_chapters(full_text)
                        st.session_state.last_file = uploaded_file.name
                        st.session_state.full_text = full_text
                        st.session_state.processing_log = processing_log
                    else:
                        st.error("❌ Não foi possível extrair texto suficiente do documento")
                        return
            
            chunks = st.session_state.get('processed_chunks', [])
            
            if chunks:
                # Métricas do documento
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("📄 Partes/Capítulos", len(chunks))
                with col2:
                    total_chars = sum(len(c['content']) for c in chunks)
                    st.metric("📝 Caracteres Totais", f"{total_chars:,}")
                with col3:
                    estimated_time = total_chars / 1000  # Estimativa aproximada
                    st.metric("⏱️ Tempo Estimado", f"{estimated_time:.0f} min")
                with col4:
                    avg_chars = total_chars / len(chunks) if chunks else 0
                    st.metric("📊 Média por Parte", f"{avg_chars:.0f} chars")
                
                # Preview da estrutura
                with st.expander("📋 Estrutura Detectada", expanded=True):
                    st.markdown('<div class="chapter-list">', unsafe_allow_html=True)
                    for i, chunk in enumerate(chunks, 1):
                        preview = chunk['content'][:200] + "..." if len(chunk['content']) > 200 else chunk['content']
                        st.markdown(f"""
                        **{i}. {chunk['title']}**  
                        📏 {len(chunk['content']):,} caracteres  
                        📝 *{preview}*  
                        ---
                        """)
                    st.markdown('</div>', unsafe_allow_html=True)
                
                # Botão de narração
                col1, col2 = st.columns([2, 1])
                with col1:
                    if st.button("🎬 Iniciar Narração Profissional", use_container_width=True):
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        time_text = st.empty()
                        
                        start_time = time.time()
                        
                        # Configura narrador
                        narrator = Narrator(
                            VOICES[language_category][voice_name],
                            AUDIO_SETTINGS["Velocidade"][speed],
                            AUDIO_SETTINGS["Tom"][pitch]
                        )
                        
                        # Narra capítulos
                        results = []
                        for i, chunk in enumerate(chunks):
                            progress = (i + 1) / len(chunks)
                            progress_bar.progress(progress)
                            
                            elapsed = time.time() - start_time
                            remaining = (elapsed / (i + 1)) * (len(chunks) - i - 1) if i > 0 else 0
                            
                            status_text.text(f"🎙️ Narrando: {chunk['title']}")
                            time_text.text(f"⏱️ Tempo restante estimado: {format_duration(remaining)}")
                            
                            # Narra o chunk
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            
                            clean_name = normalize_filename(chunk['title'])
                            fname = f"{i+1:03d}_{clean_name}.mp3"
                            path = OUTPUT_DIR / fname
                            
                            loop.run_until_complete(
                                narrator.narrate_chunk(
                                    chunk['content'],
                                    str(path),
                                    chunk
                                )
                            )
                            loop.close()
                            
                            if path.exists():
                                results.append({
                                    "title": chunk['title'],
                                    "path": str(path),
                                    "size": os.path.getsize(path)
                                })
                        
                        progress_bar.progress(1.0)
                        status_text.text("✅ Narração concluída!")
                        
                        total_time = time.time() - start_time
                        time_text.text(f"⏱️ Tempo total: {format_duration(total_time)}")
                        
                        st.session_state.narration_results = results
                        st.session_state.narration_complete = True
                
                # Download após narração
                if st.session_state.get('narration_complete'):
                    st.success("✨ Audiobook gerado com sucesso!")
                    
                    # Cria ZIP
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for file_path in OUTPUT_DIR.glob("*.mp3"):
                            zf.write(file_path, file_path.name)
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.download_button(
                            "📥 Baixar Audiobook Completo (ZIP)",
                            zip_buffer.getvalue(),
                            f"audiobook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                            "application/zip",
                            use_container_width=True
                        )
                    
                    with col2:
                        # Player individual
                        st.markdown("### 🎵 Preview dos Arquivos")
                        mp3_files = sorted(OUTPUT_DIR.glob("*.mp3"))
                        if mp3_files:
                            selected_file = st.selectbox(
                                "Selecione o capítulo para preview:",
                                mp3_files,
                                format_func=lambda x: x.name
                            )
                            if selected_file:
                                st.audio(str(selected_file))
    
    with tab2:
        if 'narration_results' in st.session_state:
            st.markdown("### 📊 Estatísticas da Narração")
            
            results = st.session_state.narration_results
            total_size = sum(r['size'] for r in results) / (1024 * 1024)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("🎵 Arquivos Gerados", len(results))
            with col2:
                st.metric("💾 Tamanho Total", f"{total_size:.1f} MB")
            with col3:
                if 'processing_log' in st.session_state:
                    stats = st.session_state.processing_log.get_stats()
                    st.metric("⚡ Tempo Processamento", stats.get('total_time', 'N/A'))
            
            # Tabela de arquivos
            st.markdown("### 📁 Arquivos Gerados")
            data = []
            for r in results:
                data.append({
                    "Título": r['title'],
                    "Tamanho": f"{r['size'] / (1024*1024):.2f} MB",
                    "Arquivo": os.path.basename(r['path'])
                })
            st.dataframe(data, use_container_width=True)
        else:
            st.info("As estatísticas aparecerão aqui após a narração")
    
    with tab3:
        st.markdown("### 📝 Log de Processamento")
        if 'processing_log' in st.session_state:
            for log in st.session_state.processing_log.logs:
                if log['level'] == 'error':
                    st.error(f"[{log['timestamp']}] {log['message']}")
                elif log['level'] == 'warning':
                    st.warning(f"[{log['timestamp']}] {log['message']}")
                else:
                    st.text(f"[{log['timestamp']}] {log['message']}")
        else:
            st.info("O log de processamento aparecerá aqui")

# --- RODAPÉ ---
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: #666; padding: 1rem;'>"
    "Narrador.AI Pro v2.0 | Desenvolvido com ❤️ usando Streamlit e Edge TTS | "
    "Tecnologia de Voz Neural Microsoft Azure"
    "</div>",
    unsafe_allow_html=True
)

if __name__ == "__main__":
    main()
