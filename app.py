import streamlit as st
import asyncio
import edge_tts
import os
import zipfile
import io
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
import re
import unicodedata
from typing import List, Dict, Optional
import pdfplumber
from ebooklib import epub, ITEM_DOCUMENT
from bs4 import BeautifulSoup

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
    /* Import Google Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    /* Tema Global */
    * {
        font-family: 'Inter', sans-serif;
    }
    
    /* Header Principal */
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
    
    /* Cards de Features */
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
    
    /* Botões */
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
    
    /* Botão de teste de voz */
    .test-button > button {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        box-shadow: 0 4px 15px rgba(17, 153, 142, 0.3);
    }
    
    .test-button > button:hover {
        box-shadow: 0 8px 25px rgba(17, 153, 142, 0.5);
    }
    
    /* Área de Upload */
    .upload-area {
        border: 2px dashed #667eea;
        border-radius: 15px;
        padding: 2rem;
        text-align: center;
        background: #f8f9ff;
        transition: all 0.3s ease;
    }
    
    .upload-area:hover {
        background: #f0f1ff;
        border-color: #764ba2;
    }
    
    /* Cards de Estatísticas */
    .stat-container {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 1rem;
        margin: 1rem 0;
    }
    
    .stat-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 1.5rem;
        border-radius: 15px;
        text-align: center;
    }
    
    .stat-value {
        font-size: 2rem;
        font-weight: 700;
        color: #667eea;
    }
    
    .stat-label {
        font-size: 0.9rem;
        color: #666;
        margin-top: 0.25rem;
    }
    
    /* Player de Áudio */
    .audio-player-container {
        background: #f8f9fa;
        padding: 1.5rem;
        border-radius: 15px;
        border: 1px solid #e8e8e8;
        margin: 1rem 0;
    }
    
    /* Mensagens */
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
    
    /* Rodapé */
    .footer {
        text-align: center;
        padding: 2rem;
        color: #999;
        font-size: 0.9rem;
    }
    
    /* Esconder elementos padrão */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Responsividade */
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

# Diretório temporário para arquivos
TEMP_DIR = Path(tempfile.mkdtemp())

# Vozes disponíveis (validadas e testadas)
AVAILABLE_VOICES = {
    "🇧🇷 Português Brasileiro": {
        "Antonio - Voz Masculina Profissional": "pt-BR-AntonioNeural",
        "Francisca - Voz Feminina Natural": "pt-BR-FranciscaNeural",
        "Brenda - Voz Feminina Jovem": "pt-BR-BrendaNeural",
        "Donato - Voz Masculina Madura": "pt-BR-DonatoNeural",
        "Thalita - Voz Feminina Suave": "pt-BR-ThalitaNeural"
    },
    "🌍 Vozes Multilíngue": {
        "Alessio - Italiano (Multilíngue)": "it-IT-AlessioMultilingualNeural",
        "Andrew - Inglês Americano (Multilíngue)": "en-US-AndrewMultilingualNeural",
        "Emma - Inglês Americano (Multilíngue)": "en-US-EmmaMultilingualNeural",
        "Ava - Inglês Americano (Multilíngue)": "en-US-AvaMultilingualNeural"
    },
    "🇺🇸 Inglês": {
        "Jenny - Voz Feminina Americana": "en-US-JennyNeural",
        "Guy - Voz Masculina Americana": "en-US-GuyNeural"
    }
}

# ============================================
# FUNÇÕES UTILITÁRIAS
# ============================================

def clean_filename(filename: str) -> str:
    """Limpa nome de arquivo removendo caracteres especiais"""
    # Remove acentos
    filename = unicodedata.normalize('NFKD', filename).encode('ASCII', 'ignore').decode('ASCII')
    # Remove caracteres não permitidos
    filename = re.sub(r'[^\w\s-]', '', filename)
    # Substitui espaços por underscore
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

def split_text_smart(text: str, max_chars: int = 4000) -> List[Dict]:
    """Divide texto em partes inteligentes respeitando parágrafos"""
    if len(text) <= max_chars:
        return [{"title": "Completo", "content": text}]
    
    # Divide por parágrafos
    paragraphs = text.split('\n\n')
    parts = []
    current_part = ""
    part_number = 1
    
    for paragraph in paragraphs:
        # Se adicionar este parágrafo exceder o limite
        if len(current_part) + len(paragraph) > max_chars and current_part:
            parts.append({
                "title": f"Parte {part_number}",
                "content": current_part.strip()
            })
            current_part = paragraph
            part_number += 1
        else:
            if current_part:
                current_part += '\n\n' + paragraph
            else:
                current_part = paragraph
    
    # Adiciona última parte
    if current_part:
        parts.append({
            "title": f"Parte {part_number}",
            "content": current_part.strip()
        })
    
    return parts

# ============================================
# FUNÇÕES DE EXTRAÇÃO DE TEXTO
# ============================================

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extrai texto de arquivo PDF"""
    text_parts = []
    
    # Cria arquivo temporário
    temp_file = TEMP_DIR / "temp.pdf"
    temp_file.write_bytes(file_bytes)
    
    try:
        with pdfplumber.open(temp_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    # Limpa texto da página
                    text = text.strip()
                    if text:
                        text_parts.append(text)
    finally:
        # Remove arquivo temporário
        if temp_file.exists():
            temp_file.unlink()
    
    return '\n\n'.join(text_parts)

def extract_text_from_epub(file_bytes: bytes) -> str:
    """Extrai texto de arquivo EPUB"""
    text_parts = []
    
    # Cria arquivo temporário
    temp_file = TEMP_DIR / "temp.epub"
    temp_file.write_bytes(file_bytes)
    
    try:
        book = epub.read_epub(temp_file)
        
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            try:
                # Parse HTML
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                
                # Remove scripts e estilos
                for script in soup(["script", "style"]):
                    script.decompose()
                
                # Extrai texto
                text = soup.get_text()
                
                # Limpa texto
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
        # Remove arquivo temporário
        if temp_file.exists():
            temp_file.unlink()
    
    return '\n\n'.join(text_parts)

def extract_text_from_txt(file_bytes: bytes) -> str:
    """Extrai texto de arquivo TXT com detecção de encoding"""
    # Tenta diferentes encodings
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    
    for encoding in encodings:
        try:
            text = file_bytes.decode(encoding)
            if text.strip():
                return text
        except:
            continue
    
    # Fallback com substituição de caracteres
    return file_bytes.decode('utf-8', errors='replace')

# ============================================
# FUNÇÃO DE NARRAÇÃO (TTS)
# ============================================

async def text_to_speech(text: str, voice: str, output_path: str) -> bool:
    """Converte texto em fala usando Edge TTS"""
    try:
        # Limita tamanho do texto para evitar erros
        if len(text) > 5000:
            text = text[:5000]
        
        # Cria comunicador
        communicator = edge_tts.Communicate(text, voice)
        
        # Salva áudio
        await communicator.save(output_path)
        
        # Verifica se o arquivo foi criado
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    
    except Exception as e:
        st.error(f"Erro na narração: {str(e)}")
        return False

def run_async_tts(text: str, voice: str, output_path: str) -> bool:
    """Executa TTS de forma síncrona (para Streamlit)"""
    try:
        # Cria novo event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Executa
        result = loop.run_until_complete(
            text_to_speech(text, voice, output_path)
        )
        
        # Fecha loop
        loop.close()
        
        return result
    except Exception as e:
        st.error(f"Erro ao executar TTS: {str(e)}")
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
    
    # ============================================
    # HEADER
    # ============================================
    
    st.markdown("""
    <div class="app-header">
        <h1>🎧 AudioBook AI</h1>
        <p>Transforme qualquer texto em audiobook profissional com vozes neurais de última geração</p>
    </div>
    """, unsafe_allow_html=True)
    
    # ============================================
    # LAYOUT PRINCIPAL (2 COLUNAS)
    # ============================================
    
    col1, col2 = st.columns([1, 2])
    
    # ============================================
    # COLUNA 1 - CONFIGURAÇÕES
    # ============================================
    
    with col1:
        st.markdown("### 📁 Fonte do Texto")
        
        # Seleção do método de entrada
        input_method = st.radio(
            "Como deseja fornecer o texto?",
            ["📤 Upload de Arquivo", "✍️ Digitar/colar Texto"],
            help="Escolha entre fazer upload de um arquivo ou digitar o texto manualmente"
        )
        
        st.markdown("---")
        
        if input_method == "📤 Upload de Arquivo":
            # Upload de arquivo
            uploaded_file = st.file_uploader(
                "Selecione o arquivo",
                type=['pdf', 'epub', 'txt'],
                help="Formatos aceitos: PDF, EPUB e TXT"
            )
            
            if uploaded_file:
                # Informações do arquivo
                file_size = len(uploaded_file.getvalue()) / (1024 * 1024)
                st.info(f"""
                **Arquivo:** {uploaded_file.name}  
                **Tamanho:** {file_size:.1f} MB
                """)
                
                # Botão para processar
                if st.button("📖 Processar Arquivo", use_container_width=True):
                    with st.spinner("Extraindo texto do arquivo..."):
                        try:
                            # Extrai texto baseado no tipo
                            if uploaded_file.name.endswith('.pdf'):
                                text = extract_text_from_pdf(uploaded_file.getvalue())
                            elif uploaded_file.name.endswith('.epub'):
                                text = extract_text_from_epub(uploaded_file.getvalue())
                            elif uploaded_file.name.endswith('.txt'):
                                text = extract_text_from_txt(uploaded_file.getvalue())
                            else:
                                st.error("Formato não suportado")
                                return
                            
                            # Verifica se extraiu algo
                            if not text or len(text.strip()) < 50:
                                st.error("Não foi possível extrair texto suficiente do arquivo")
                                return
                            
                            # Armazena na sessão
                            st.session_state.processed_text = text
                            st.session_state.text_parts = split_text_smart(text)
                            
                            st.success(f"✅ Texto extraído: {len(text):,} caracteres")
                            
                        except Exception as e:
                            st.error(f"Erro ao processar arquivo: {str(e)}")
                            return
        else:
            # Entrada manual de texto
            manual_text = st.text_area(
                "Digite ou cole seu texto",
                height=200,
                placeholder="Cole aqui o texto que deseja transformar em audiobook...",
                help="Mínimo de 50 caracteres"
            )
            
            if manual_text and len(manual_text.strip()) >= 50:
                if st.button("📝 Processar Texto", use_container_width=True):
                    st.session_state.processed_text = manual_text
                    st.session_state.text_parts = split_text_smart(manual_text)
                    st.success(f"✅ Texto processado: {len(manual_text):,} caracteres")
        
        # Configurações de voz
        st.markdown("---")
        st.markdown("### 🎤 Configurações de Voz")
        
        # Seleção de categoria
        voice_category = st.selectbox(
            "Categoria de Voz",
            list(AVAILABLE_VOICES.keys()),
            help="Escolha o idioma/categoria da voz"
        )
        
        # Seleção de voz específica
        voice_name = st.selectbox(
            "Voz",
            list(AVAILABLE_VOICES[voice_category].keys()),
            help="Escolha a voz específica para narração"
        )
        
        voice_id = AVAILABLE_VOICES[voice_category][voice_name]
        
        # Botão de teste de voz
        st.markdown('<div class="test-button">', unsafe_allow_html=True)
        if st.button("🔊 Testar Voz Selecionada", use_container_width=True):
            with st.spinner("Gerando teste de voz..."):
                test_text = "Olá! Esta é uma demonstração da voz selecionada para o seu audiobook."
                test_file = TEMP_DIR / "voice_test.mp3"
                
                if run_async_tts(test_text, voice_id, str(test_file)):
                    st.audio(str(test_file))
                    st.success("✅ Voz testada com sucesso!")
                else:
                    st.error("Erro ao testar voz. Verifique sua conexão com a internet.")
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Botão de reset
        st.markdown("---")
        if st.button("🗑️ Limpar Tudo e Recomeçar", use_container_width=True):
            # Limpa sessão
            st.session_state.processed_text = None
            st.session_state.text_parts = None
            st.session_state.audio_files = []
            
            # Limpa diretório temporário
            if TEMP_DIR.exists():
                shutil.rmtree(TEMP_DIR)
            TEMP_DIR.mkdir()
            
            st.rerun()
    
    # ============================================
    # COLUNA 2 - VISUALIZAÇÃO E PROCESSAMENTO
    # ============================================
    
    with col2:
        # Se não tem texto processado, mostra welcome
        if not st.session_state.processed_text:
            st.markdown("### 👋 Bem-vindo ao AudioBook AI!")
            
            # Grid de features
            st.markdown("""
            <div class="feature-grid">
                <div class="feature-card">
                    <div class="feature-icon">📄</div>
                    <h3>Múltiplos Formatos</h3>
                    <p>PDF, EPUB e TXT</p>
                </div>
                <div class="feature-card">
                    <div class="feature-icon">🎤</div>
                    <h3>Vozes Neurais</h3>
                    <p>+10 vozes premium</p>
                </div>
                <div class="feature-card">
                    <div class="feature-icon">🌍</div>
                    <h3>Multilíngue</h3>
                    <p>Português, Inglês, Italiano</p>
                </div>
                <div class="feature-card">
                    <div class="feature-icon">⚡</div>
                    <h3>Rápido</h3>
                    <p>Processamento otimizado</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Instruções
            st.markdown("""
            <div class="info-message">
                <h4>🚀 Como começar:</h4>
                <ol>
                    <li>Escolha como fornecer o texto (upload ou digitação)</li>
                    <li>Selecione a voz desejada</li>
                    <li>Teste a voz para confirmar</li>
                    <li>Clique em "Gerar Audiobook"</li>
                    <li>Faça o download dos arquivos</li>
                </ol>
            </div>
            """, unsafe_allow_html=True)
        
        else:
            # Mostra informações do texto processado
            text = st.session_state.processed_text
            parts = st.session_state.text_parts
            
            # Estatísticas
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
                estimated_time = len(text) / 1000 * 0.5
                st.metric("⏱️ Tempo Est.", format_time(estimated_time))
            
            # Preview do texto
            with st.expander("👁️ Visualizar Texto Extraído", expanded=False):
                preview = text[:1000] + "..." if len(text) > 1000 else text
                st.text_area("Conteúdo:", preview, height=200, disabled=True)
            
            # Lista de partes
            if len(parts) > 1:
                with st.expander(f"📋 Ver {len(parts)} Partes", expanded=False):
                    for i, part in enumerate(parts, 1):
                        st.write(f"**{i}. {part['title']}** - {len(part['content']):,} caracteres")
            
            # Botão de gerar audiobook
            st.markdown("---")
            st.markdown("### 🎬 Gerar Audiobook")
            
            if st.button("🎙️ Iniciar Narração", use_container_width=True, type="primary"):
                # Prepara diretório de saída
                output_dir = TEMP_DIR / "audiobook_output"
                output_dir.mkdir(exist_ok=True)
                
                # Limpa arquivos anteriores
                st.session_state.audio_files = []
                
                # Barra de progresso
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                # Processa cada parte
                for i, part in enumerate(parts):
                    # Atualiza progresso
                    progress = (i + 1) / len(parts)
                    progress_bar.progress(progress)
                    status_text.info(f"🎙️ Narrando {part['title']}... ({i+1}/{len(parts)})")
                    
                    # Gera nome do arquivo
                    filename = f"{i+1:03d}_{clean_filename(part['title'])}.mp3"
                    output_file = output_dir / filename
                    
                    # Converte para áudio
                    success = run_async_tts(part['content'], voice_id, str(output_file))
                    
                    if success:
                        st.session_state.audio_files.append(output_file)
                    else:
                        status_text.error(f"❌ Erro ao narrar {part['title']}")
                        break
                
                # Finaliza
                progress_bar.progress(1.0)
                
                if st.session_state.audio_files:
                    status_text.markdown("""
                    <div class="success-message">
                        <h4>✅ Audiobook Gerado com Sucesso!</h4>
                        <p>Seu audiobook está pronto para download.</p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    status_text.error("❌ Nenhum arquivo de áudio foi gerado")
            
            # Mostra arquivos gerados e opções de download
            if st.session_state.audio_files:
                st.markdown("---")
                st.markdown("### 📥 Download e Preview")
                
                # Criar ZIP com todos os arquivos
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for audio_file in st.session_state.audio_files:
                        zf.write(audio_file, audio_file.name)
                
                # Botão de download
                col_download, col_space = st.columns([2, 1])
                with col_download:
                    st.download_button(
                        label="📥 Baixar Audiobook Completo (ZIP)",
                        data=zip_buffer.getvalue(),
                        file_name=f"audiobook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                        mime="application/zip",
                        use_container_width=True
                    )
                
                # Preview individual
                st.markdown("#### 🎵 Preview dos Arquivos")
                
                for audio_file in st.session_state.audio_files:
                    with st.expander(f"🎧 {audio_file.name}", expanded=False):
                        st.audio(str(audio_file))
    
    # ============================================
    # RODAPÉ
    # ============================================
    
    st.markdown("---")
    st.markdown("""
    <div class="footer">
        <p>🎧 AudioBook AI v1.0 | Tecnologia Microsoft Edge TTS | Desenvolvido com Streamlit</p>
        <p>Transformando texto em voz de forma simples e profissional</p>
    </div>
    """, unsafe_allow_html=True)

# ============================================
# EXECUÇÃO
# ============================================

if __name__ == "__main__":
    main()
