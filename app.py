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
from pathlib import Path
from typing import List, Dict, Optional
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
    
    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 1rem;
        margin: 1rem 0;
    }
    
    .stat-card {
        background: rgba(255, 255, 255, 0.2);
        backdrop-filter: blur(10px);
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
        border: 1px solid rgba(255, 255, 255, 0.3);
    }
    
    .stat-number {
        font-size: 2rem;
        font-weight: bold;
        color: white;
    }
    
    .stat-label {
        font-size: 0.9rem;
        color: rgba(255, 255, 255, 0.9);
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
    
    .chapter-list {
        max-height: 400px;
        overflow-y: auto;
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 10px;
    }
    
    .success-message {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# --- DIRETÓRIOS E CONFIGURAÇÕES ---
OUTPUT_DIR = Path("audiobook_pro_out")
OUTPUT_DIR.mkdir(exist_ok=True)

TEMP_DIR = Path(tempfile.mkdtemp())

# --- VOZES EXPANDIDAS (CORRIGIDAS) ---
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

# --- CONFIGURAÇÕES DE ÁUDIO CORRIGIDAS ---
# Os valores agora estão no formato correto para edge-tts
AUDIO_SETTINGS = {
    "Velocidade": {
        "Muito Lenta (0.5x)": "-50%",
        "Lenta (0.75x)": "-25%",
        "Normal (1.0x)": "+0%",
        "Rápida (1.25x)": "+25%",
        "Muito Rápida (1.5x)": "+50%"
    },
    "Tom": {
        "Mais Grave (-20Hz)": "-20Hz",
        "Levemente Grave (-10Hz)": "-10Hz",
        "Normal (0Hz)": "+0Hz",
        "Levemente Agudo (+10Hz)": "+10Hz",
        "Mais Agudo (+20Hz)": "+20Hz"
    }
}

# --- FUNÇÕES DE UTILIDADE ---
def normalize_filename(text: str) -> str:
    """Normaliza nomes de arquivo removendo acentos e caracteres especiais"""
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    text = re.sub(r'[^\w\s-]', '', text).strip()
    text = re.sub(r'[-\s]+', '_', text)
    return text[:100]

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

# --- CLASSE DE PROCESSAMENTO DE TEXTO ---
class TextProcessor:
    @staticmethod
    def clean_professional_text(pages: List[str]) -> str:
        """Limpeza profissional de texto"""
        if not pages:
            return ""
        
        all_lines = []
        for page in pages:
            all_lines.extend([line.strip() for line in page.split('\n') if line.strip()])
        
        line_counts = Counter(all_lines)
        total_pages = len(pages)
        
        # Remove cabeçalhos/rodapés repetidos
        threshold = total_pages * 0.7
        repeated_noise = {line for line, count in line_counts.items() 
                         if count > threshold and len(line) < 100 and not line.isdigit()}
        
        # Remove números de página
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
                
                if clean_line in noise_patterns:
                    continue
                
                if re.match(r'https?://', clean_line):
                    continue
                
                if re.match(r'^[ivxlcdm]{1,5}[\.\)]?\s*$', clean_line.lower()):
                    continue
                
                if not clean_line:
                    consecutive_empty += 1
                    if consecutive_empty > 2:
                        continue
                else:
                    consecutive_empty = 0
                
                if clean_line:
                    final_page_lines.append(clean_line)
            
            if final_page_lines:
                cleaned_text_list.append("\n".join(final_page_lines))
        
        return "\n\n".join(cleaned_text_list)
    
    @staticmethod
    def detect_chapters(text: str) -> List[Dict]:
        """Detecção inteligente de capítulos"""
        # Padrões de capítulo
        patterns = [
            r'\n\s*(?:Capítulo|Chapter|CAPÍTULO|CAPITULO)\s+(\d+|[IVXLCDM]+)\b',
            r'\n\s*(?:Parte|Part|PARTE)\s+(\d+|[IVXLCDM]+)\b',
            r'\n\s*(\d+)\s*\n\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]',
            r'\n\s*([IVXLCDM]+)\s*\n',
        ]
        
        all_matches = []
        for pattern in patterns:
            matches = list(re.finditer(pattern, text))
            all_matches.extend(matches)
        
        if len(all_matches) >= 2:
            all_matches.sort(key=lambda x: x.start())
            unique_matches = []
            last_pos = -1000
            
            for match in all_matches:
                if match.start() - last_pos > 100:
                    unique_matches.append(match)
                    last_pos = match.start()
            
            chapters = []
            for i, match in enumerate(unique_matches):
                start = match.start()
                end = unique_matches[i+1].start() if i+1 < len(unique_matches) else len(text)
                
                title = match.group(0).strip()
                content = text[start:end].strip()
                
                if len(content) > 50:
                    chapters.append({
                        "title": title,
                        "content": content,
                        "position": i + 1
                    })
            
            if len(chapters) >= 3:
                return chapters
        
        return TextProcessor.split_by_size(text)
    
    @staticmethod
    def split_by_size(text: str, max_chars: int = 4000) -> List[Dict]:
        """Divide texto em partes de tamanho similar"""
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

# --- CLASSE DE EXTRAÇÃO DE DOCUMENTOS ---
class DocumentExtractor:
    @staticmethod
    def extract_from_pdf(file) -> List[str]:
        """Extração de PDF"""
        pages_content = []
        
        try:
            with pdfplumber.open(file) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages_content.append(text)
        except Exception as e:
            st.error(f"Erro ao extrair PDF: {str(e)}")
            return []
        
        return pages_content
    
    @staticmethod
    def extract_from_epub(file) -> List[str]:
        """Extração de EPUB"""
        pages_content = []
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.epub') as tmp_file:
            tmp_file.write(file.getbuffer())
            tmp_path = tmp_file.name
        
        try:
            book = epub.read_epub(tmp_path)
            items = list(book.get_items_of_type(ITEM_DOCUMENT))
            
            for item in items:
                try:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    for script in soup(["script", "style"]):
                        script.decompose()
                    text = soup.get_text()
                    if text.strip():
                        pages_content.append(text)
                except:
                    continue
        except Exception as e:
            st.error(f"Erro ao extrair EPUB: {str(e)}")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        
        return pages_content
    
    @staticmethod
    def extract_from_txt(file) -> str:
        """Extração de TXT com detecção de encoding"""
        content = file.getvalue()
        
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            try:
                return content.decode(encoding)
            except:
                continue
        
        return content.decode('utf-8', errors='replace')

# --- FUNÇÃO PRINCIPAL DE NARRAÇÃO ---
async def narrate_text(text: str, voice_id: str, rate: str, pitch: str, output_path: str):
    """Função assíncrona para narração com parâmetros corretos"""
    try:
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice_id,
            rate=rate,
            pitch=pitch
        )
        await communicate.save(output_path)
        return True
    except Exception as e:
        st.error(f"Erro na narração: {str(e)}")
        return False

def run_narration(text: str, voice_id: str, rate: str, pitch: str, output_path: str):
    """Wrapper síncrono para narração assíncrona"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            narrate_text(text, voice_id, rate, pitch, output_path)
        )
        return result
    finally:
        loop.close()

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

    # Sidebar
    with st.sidebar:
        st.markdown("### 📁 Upload de Arquivo")
        
        input_method = st.radio(
            "Método de entrada",
            ["📄 Arquivo", "✍️ Texto Manual"],
            key="input_method",
            help="Escolha como deseja fornecer o texto"
        )
        
        if input_method == "📄 Arquivo":
            uploaded_file = st.file_uploader(
                "Selecione o documento",
                type=["pdf", "epub", "txt"],
                help="Formatos suportados: PDF, EPUB, TXT"
            )
            manual_text = ""
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
        
        with st.expander("⚙️ Configurações Avançadas de Áudio"):
            speed = st.select_slider(
                "Velocidade de Narração",
                options=list(AUDIO_SETTINGS["Velocidade"].keys()),
                value="Normal (1.0x)"
            )
            
            pitch = st.select_slider(
                "Tom de Voz",
                options=list(AUDIO_SETTINGS["Tom"].keys()),
                value="Normal (0Hz)"
            )
            
            st.info("💡 Ajuste a velocidade e tom para personalizar a narração")
        
        # Preview de voz (agora com tratamento de erro)
        if st.button("🔊 Testar Voz", use_container_width=True):
            if st.session_state.get('preview_generated', False):
                preview_path = TEMP_DIR / "preview.mp3"
                if preview_path.exists():
                    st.audio(str(preview_path))
            else:
                with st.spinner("Gerando preview..."):
                    try:
                        preview_text = "Olá! Esta é uma demonstração da voz selecionada para seu audiobook."
                        preview_path = TEMP_DIR / "preview.mp3"
                        
                        success = run_narration(
                            preview_text,
                            VOICES[language_category][voice_name],
                            AUDIO_SETTINGS["Velocidade"][speed],
                            AUDIO_SETTINGS["Tom"][pitch],
                            str(preview_path)
                        )
                        
                        if success and preview_path.exists():
                            st.audio(str(preview_path))
                            st.session_state.preview_generated = True
                        else:
                            st.error("Falha ao gerar preview. Verifique a conexão com a internet.")
                    except Exception as e:
                        st.error(f"Erro ao gerar preview: {str(e)}")
        
        st.markdown("---")
        
        if st.button("🗑️ Resetar Sistema", use_container_width=True):
            if OUTPUT_DIR.exists():
                shutil.rmtree(OUTPUT_DIR)
            OUTPUT_DIR.mkdir()
            if TEMP_DIR.exists():
                shutil.rmtree(TEMP_DIR)
            TEMP_DIR.mkdir()
            st.session_state.clear()
            st.rerun()

    # Área principal
    st.markdown("### 📚 Processamento do Documento")
    
    # Verifica se tem conteúdo para processar
    has_content = False
    current_file = None
    
    if input_method == "📄 Arquivo" and uploaded_file:
        has_content = True
        current_file = uploaded_file
    elif input_method == "✍️ Texto Manual" and len(manual_text.strip()) > 50:
        has_content = True
        # Cria um arquivo virtual para processamento uniforme
        current_file = io.BytesIO(manual_text.encode('utf-8'))
        current_file.name = "texto_manual.txt"
    
    if has_content:
        # Processamento do arquivo
        if 'processed_chunks' not in st.session_state or \
           st.session_state.get('last_file') != current_file.name:
            
            with st.spinner("🔍 Analisando documento..."):
                try:
                    # Extrai conteúdo baseado no tipo de arquivo
                    if current_file.name.endswith('.pdf'):
                        pages = DocumentExtractor.extract_from_pdf(current_file)
                        full_text = TextProcessor.clean_professional_text(pages)
                    elif current_file.name.endswith('.epub'):
                        pages = DocumentExtractor.extract_from_epub(current_file)
                        full_text = TextProcessor.clean_professional_text(pages)
                    elif current_file.name.endswith('.txt') or current_file.name == "texto_manual.txt":
                        full_text = DocumentExtractor.extract_from_txt(current_file)
                    else:
                        st.error("❌ Formato não suportado")
                        return
                    
                    if full_text and len(full_text) > 50:
                        st.session_state.processed_chunks = TextProcessor.detect_chapters(full_text)
                        st.session_state.last_file = current_file.name
                        st.session_state.full_text = full_text
                    else:
                        st.error("❌ Não foi possível extrair texto suficiente do documento")
                        return
                except Exception as e:
                    st.error(f"Erro no processamento: {str(e)}")
                    return
        
        chunks = st.session_state.get('processed_chunks', [])
        
        if chunks:
            # Métricas
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📄 Partes/Capítulos", len(chunks))
            with col2:
                total_chars = sum(len(c['content']) for c in chunks)
                st.metric("📝 Caracteres Totais", f"{total_chars:,}")
            with col3:
                estimated_time = total_chars / 1000 * 0.5  # 0.5 min por 1000 caracteres
                st.metric("⏱️ Tempo Estimado", f"{estimated_time:.1f} min")
            with col4:
                avg_chars = total_chars / len(chunks) if chunks else 0
                st.metric("📊 Média por Parte", f"{avg_chars:.0f} chars")
            
            # Estrutura detectada
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
            if st.button("🎬 Iniciar Narração Profissional", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                start_time = time.time()
                
                for i, chunk in enumerate(chunks):
                    progress = (i + 1) / len(chunks)
                    progress_bar.progress(progress)
                    
                    elapsed = time.time() - start_time
                    remaining = (elapsed / (i + 1)) * (len(chunks) - i - 1) if i > 0 else 0
                    
                    status_text.markdown(f"""
                    🎙️ **Narrando:** {chunk['title']}  
                    ⏱️ **Progresso:** {i+1}/{len(chunks)} - Tempo restante: {format_duration(remaining)}
                    """)
                    
                    # Narra o chunk
                    clean_name = normalize_filename(chunk['title'])
                    fname = f"{i+1:03d}_{clean_name}.mp3"
                    path = OUTPUT_DIR / fname
                    
                    try:
                        success = run_narration(
                            chunk['content'],
                            VOICES[language_category][voice_name],
                            AUDIO_SETTINGS["Velocidade"][speed],
                            AUDIO_SETTINGS["Tom"][pitch],
                            str(path)
                        )
                        
                        if not success:
                            st.error(f"Falha ao narrar: {chunk['title']}")
                    except Exception as e:
                        st.error(f"Erro ao narrar {chunk['title']}: {str(e)}")
                
                progress_bar.progress(1.0)
                total_time = time.time() - start_time
                
                # Verifica se arquivos foram gerados
                mp3_files = list(OUTPUT_DIR.glob("*.mp3"))
                
                if mp3_files:
                    status_text.markdown(f"""
                    <div class="success-message">
                    ✅ **Narração concluída com sucesso!**  
                    ⏱️ Tempo total: {format_duration(total_time)}  
                    📁 {len(mp3_files)} arquivos gerados
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Cria ZIP para download
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                        for file_path in sorted(OUTPUT_DIR.glob("*.mp3")):
                            zf.write(file_path, file_path.name)
                    
                    # Botão de download
                    st.download_button(
                        "📥 Baixar Audiobook Completo (ZIP)",
                        zip_buffer.getvalue(),
                        f"audiobook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                        "application/zip",
                        use_container_width=True
                    )
                    
                    # Preview dos arquivos
                    st.markdown("### 🎵 Preview dos Arquivos Gerados")
                    selected_file = st.selectbox(
                        "Selecione o capítulo para preview:",
                        sorted(mp3_files),
                        format_func=lambda x: x.name
                    )
                    if selected_file:
                        st.audio(str(selected_file))
                else:
                    status_text.error("❌ Nenhum arquivo foi gerado. Verifique sua conexão com a internet.")
    else:
        st.info("👆 Faça o upload de um arquivo ou digite um texto manualmente para começar")
        
        # Cards de instrução
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("""
            <div class="feature-card">
            <h3>📄 Upload de Arquivos</h3>
            <p>Suporta PDF, EPUB e TXT. Arraste e solte ou clique para selecionar.</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown("""
            <div class="feature-card">
            <h3>✍️ Texto Manual</h3>
            <p>Digite ou cole qualquer texto para converter em áudio instantaneamente.</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown("""
            <div class="feature-card">
            <h3>🎤 Vozes Premium</h3>
            <p>20+ vozes neurais em 5 idiomas com qualidade profissional.</p>
            </div>
            """, unsafe_allow_html=True)

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
