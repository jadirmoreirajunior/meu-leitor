import streamlit as st
import asyncio
import edge_tts
import os
import zipfile
import io
import re
import pypdf
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import uuid
import time

# --- 🎨 CONFIGURAÇÃO VISUAL & TEMA ---
st.set_page_config(
    page_title="Narrador.NEXT",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# CSS para deixar bonito (Dark Mode Nativo)
st.markdown("""
<style>
    /* Tema Escuro Profissional */
    .stApp {
        background-color: #0e1117;
    }
    div[data-testid="stSidebar"] {
        background-color: #1a1f29;
        border-right: 1px solid #2d3748;
    }
    .stTextArea textarea {
        background-color: #1a1f29;
        color: #e2e8f0;
        border: 1px solid #2d3748;
        border-radius: 8px;
    }
    /* Cards dos capítulos */
    div[data-testid="stVerticalBlock"] > div:has(> div > div > p > audio) {
        background-color: #1a1f29;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #2d3748;
        margin-bottom: 10px;
    }
    /* Botões */
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
</style>
""", unsafe_allow_html=True)

# --- 🧠 CONSTANTES E ESTADO ---
VOICES = {
    "🇧🇷 Antonio (Masculino, Padrão)": "pt-BR-AntonioNeural",
    "🇧🇷 Francisca (Feminino, Suave)": "pt-BR-FranciscaNeural",
    "🇧🇷 Brenda (Feminino, Jovem)": "pt-BR-BrendaNeural",
    "🇧🇷 Donato (Masculino, Autoridade)": "pt-BR-DonatoNeural",
    "🇺🇸 Andrew (Inglês, Natural)": "en-US-AndrewMultilingualNeural",
    "🇺🇸 Emma (Inglês, Doce)": "en-US-EmmaMultilingualNeural",
}

if 'chapters' not in st.session_state:
    st.session_state.chapters = []
if 'audio_files' not in st.session_state:
    st.session_state.audio_files = {} # { "Capítulo 1": "path/to/file.mp3" }
if 'app_ready' not in st.session_state:
    st.session_state.app_ready = False

# --- 🛠️ FUNÇÕES DE BACKEND (O CÉREBRO) ---

def clean_text(text):
    """Limpa o texto de ruídos comuns de PDF/OCR."""
    # Remove cabeçalhos/rodapés repetitivos (heurística simples)
    lines = text.split('\n')
    cleaned = [line for line in lines if len(line) > 20 and not re.match(r'^\s*\d+\s*$', line)]
    return '\n'.join(cleaned)

def split_into_chapters(text):
    """Divide o texto em capítulos inteligentemente."""
    # Padrão regex para "Capítulo 1", "Capítulo I", "1. Título", etc.
    pattern = r'(?:(?:^|\n)(?:Capítulo|Chapter|CAPÍTULO)\s+[IVXLCDM0-9]+.*?(?=\n(?:Capítulo|Chapter|CAPÍTULO)|$))'
    
    chapters = re.split(pattern, text, flags=re.IGNORECASE)
    titles = re.findall(pattern, text, flags=re.IGNORECASE)
    
    # Se não achar capítulos, divide por tamanho (fallback seguro)
    if len(chapters) <= 1:
        chunk_size = 6000 # Caracteres por arquivo (aprox 5-6 min)
        chapters = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
        titles = [f"Parte {i+1}" for i in range(len(chapters))]
        # Ajusta o primeiro item se a regex pegou lixo
        if not titles[0].strip(): 
            titles[0] = "Introdução"
            chapters[0] = chapters[0] + chapters[1]
            chapters.pop(1)
            titles.pop(1)

    # Limpa títulos
    titles = [t.strip().replace('\n', ' ') for t in titles]
    
    result = []
    for i, content in enumerate(chapters):
        if not content.strip(): continue
        title = titles[i] if i < len(titles) else f"Parte {i+1}"
        result.append({"id": str(uuid.uuid4()), "title": title, "content": content.strip()})
    
    return result

def add_ssml_pauses(text):
    """Adiciona pausas SSML para deixar a narração natural."""
    # Substitui 2 ou mais quebras de linha por uma pausa média
    text = re.sub(r'\n{2,}', '<break time="400ms"/>', text)
    # Substitui 1 quebra de linha por um espaço (evita que junte palavras)
    text = text.replace('\n', ' ')
    return text

async def generate_audio(chapter_id, title, content, voice_key, rate_delta=0):
    """Gera o áudio de um único capítulo."""
    communicate = edge_tts.Communicate(content, voice_key, rate=f"+{rate_delta}%")
    filename = f"temp_{chapter_id}.mp3"
    await communicate.save(filename)
    return filename, title

# --- 📂 EXTRATORES DE ARQUIVO ---

def extract_pdf(file):
    text = ""
    reader = pypdf.PdfReader(file)
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def extract_epub(file):
    book = epub.read_epub(file)
    text = ""
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        text += soup.get_text() + "\n"
    return text

def extract_mobi(file):
    # MOBI é complicado. A melhor lib é a 'kindle', mas não é padrão.
    # Vamos tentar usar ebooklib mesmo, às vezes funciona se for convertido.
    # Se falhar, avisamos o usuário.
    try:
        book = epub.read_epub(file)
        text = ""
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            text += soup.get_text() + "\n"
        return text
    except:
        return None

# --- 🖼️ INTERFACE GRÁFICA (UI) ---

def render_sidebar():
    with st.sidebar:
        st.title("& Configurações")
        
        voice = st.selectbox("🎙️ Escolha a Voz", list(VOICES.keys()), index=0)
        rate = st.slider("⚡ Velocidade da Fala", -20, 20, 0, help="0 é normal. Negativo é mais lento.")
        
        st.markdown("---")
        
        uploaded_file = st.file_uploader("📂 Carregar Livro", type=["pdf", "epub", "mobi", "txt"])
        
        if uploaded_file:
            st.info(f"Arquivo: `{uploaded_file.name}`")
            if st.button("🧹 Processar Texto", use_container_width=True):
                with st.spinner("Lendo arquivo e detectando capítulos..."):
                    raw_text = ""
                    try:
                        if uploaded_file.name.endswith(".pdf"):
                            raw_text = extract_pdf(uploaded_file)
                        elif uploaded_file.name.endswith(".epub"):
                            raw_text = extract_epub(uploaded_file)
                        elif uploaded_file.name.endswith(".mobi"):
                            raw_text = extract_mobi(uploaded_file)
                            if not raw_text:
                                st.error("Formato MOBI não suportado nativamente. Tente converter para EPUB.")
                        else:
                            raw_text = uploaded_file.getvalue().decode("utf-8")
                        
                        cleaned = clean_text(raw_text)
                        st.session_state.chapters = split_into_chapters(cleaned)
                        st.session_state.audio_files = {} # Limpa áudios antigos
                        st.success(f"✅ {len(st.session_state.chapters)} partes encontradas!")
                    except Exception as e:
                        st.error(f"Erro ao ler arquivo: {e}")

        st.markdown("---")
        if st.button("🔄 Reiniciar Tudo"):
            st.session_state.chapters = []
            st.session_state.audio_files = {}
            st.rerun()

def render_main_content():
    st.title("🎙️ Narrador.NEXT")
    st.markdown("Carregue um livro, edite se precisar, e gere seu audiobook capítulo por capítulo.")

    if not st.session_state.chapters:
        st.info("👈 Carregue um arquivo na barra lateral para começar.")
        # Dica visual
        with st.expander("💡 Como usar"):
            st.write("1. Arraste um PDF, EPUB ou TXT para a barra lateral.")
            st.write("2. O app vai separar o livro em capítulos automaticamente.")
            st.write("3. Você pode editar o texto de cada capítulo clicando nele.")
            st.write("4. Clique em 'Gerar Áudio' para ouvir e baixar.")
        return

    # Layout: Lista de Capítulos (Esquerda) | Editor/Player (Direita)
    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("📑 Capítulos")
        
        # Container com scroll para os capítulos
        with st.container(height=600):
            for i, chap in enumerate(st.session_state.chapters):
                is_generated = chap['id'] in st.session_state.audio_files
                
                with st.container():
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.write(f"**{chap['title']}**")
                    with c2:
                        if is_generated:
                            st.caption("✅ Pronto")
                        else:
                            st.caption("⏳ Pendente")
                    
                    # Botão de ação rápida
                    if st.button(f"▶️ Gerar" if not is_generated else "🔁 Refazer", key=f"btn_{chap['id']}", use_container_width=True):
                        with st.spinner(f"Gerando {chap['title']}..."):
                            # Adiciona SSML
                            ssml_content = add_ssml_pauses(chap['content'])
                            voice_key = VOICES[st.session_state.get('voice', list(VOICES.keys())[0])]
                            rate = st.session_state.get('rate', 0)
                            
                            filename, title = asyncio.run(generate_audio(chap['id'], chap['title'], ssml_content, voice_key, rate))
                            st.session_state.audio_files[chap['id']] = filename
                            st.toast(f"Áudio de '{chap['title']}' gerado!", icon="🎧")
                            st.rerun()

    with col2:
        st.subheader("✍️ Editor & Player")
        
        # Seleciona qual capítulo editar
        chapter_titles = [c['title'] for c in st.session_state.chapters]
        selected_title = st.selectbox("Selecione para editar:", chapter_titles)
        
        # Encontra o capítulo selecionado
        current_chap = next(c for c in st.session_state.chapters if c['title'] == selected_title)
        
        # Área de texto editável
        new_content = st.text_area("Edite o texto aqui:", value=current_chap['content'], height=300, key=f"edit_{current_chap['id']}")
        
        # Atualiza o conteúdo na memória se mudar
        if new_content != current_chap['content']:
            current_chap['content'] = new_content
            # Remove o áudio antigo se o texto mudou
            if current_chap['id'] in st.session_state.audio_files:
                del st.session_state.audio_files[current_chap['id']]

        st.markdown("---")
        
        # Player de Áudio
        if current_chap['id'] in st.session_state.audio_files:
            audio_path = st.session_state.audio_files[current_chap['id']]
            st.audio(audio_path, format="audio/mp3")
            
            # Botão de download individual
            with open(audio_path, "rb") as f:
                st.download_button(
                    label=f"📥 Baixar {current_chap['title']}",
                    data=f,
                    file_name=f"{current_chap['title']}.mp3",
                    mime="audio/mp3"
                )
        else:
            st.warning("Este capítulo ainda não tem áudio. Gere usando o botão na lista à esquerda.")

    # --- RODAPÉ: DOWNLOAD ZIP ---
    if st.session_state.audio_files:
        st.markdown("---")
        st.subheader("📦 Pacote Completo")
        
        col_zip1, col_zip2 = st.columns([3, 1])
        with col_zip2:
            if st.button("💾 BAIXAR TUDO (ZIP)", use_container_width=True):
                with st.spinner("Compactando arquivos..."):
                    mem_zip = io.BytesIO()
                    with zipfile.ZipFile(mem_zip, mode="w") as zf:
                        for cid, fpath in st.session_state.audio_files.items():
                            chap_title = next(c['title'] for c in st.session_state.chapters if c['id'] == cid)
                            clean_name = re.sub(r'[\\/*?:"<>|]', "", chap_title)
                            zf.write(fpath, arcname=f"{clean_name}.mp3")
                    
                    st.download_button(
                        label="Clique aqui para salvar o ZIP",
                        data=mem_zip.getvalue(),
                        file_name="meu_audiobook.zip",
                        mime="application/zip",
                        use_container_width=True
                    )
                    st.toast("ZIP pronto para download!", icon="📦")

# --- 🚀 EXECUÇÃO PRINCIPAL ---
def main():
    # Recupera estado da sidebar se existir
    if 'voice' in st.session_state:
         pass # O estado persiste automaticamente no Streamlit
    
    render_sidebar()
    render_main_content()
    
    # Limpeza de arquivos temporários ao fechar (opcional, mas bom)
    # Nota: Streamlit Cloud limpa a cada deploy, localmente pode acumular.
    # Para produção real, usar tempfile seria melhor.

if __name__ == "__main__":
    main()
