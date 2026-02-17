import streamlit as st
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os
import pickle
import time
from groq import Groq

# Page Config
st.set_page_config(page_title="Enterprise AI RAG System", layout="wide", page_icon="🏢")

# Custom CSS for "Enterprise" look
st.markdown("""
<style>
    .reportview-container {
        background: #0e1117;
    }
    .main-header {
        font-family: 'Helvetica Neue', sans-serif;
        font-weight: 700;
        color: #FAFAFA;
    }
    .metric-card {
        background-color: #262730;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# Session State Initialization
if "index" not in st.session_state:
    st.session_state.index = None
if "chunks" not in st.session_state:
    st.session_state.chunks = []
if "model" not in st.session_state:
    st.session_state.model = SentenceTransformer('all-MiniLM-L6-v2')

# Sidebar for Configuration & System Stats
with st.sidebar:
    st.image("https://img.icons8.com/cloud/100/000000/network.png", width=50) 
    st.markdown("<h2 style='text-align: left;'>System Control</h2>", unsafe_allow_html=True)
    
    # API Key Handling
    api_key = None
    if "GROQ_API_KEY" in st.secrets:
        api_key = st.secrets["GROQ_API_KEY"]
        st.success("Authenticated (Secrets) 🔒")
    else:
        st.error("⚠️ API Key Not Found")
        st.info("Please set `GROQ_API_KEY` in `.streamlit/secrets.toml`")
    
    st.divider()
    
    # System Architecture Dashboard
    st.markdown("### 🛠️ System Internals")
    with st.expander("Architecture Details", expanded=True):
        st.markdown("**Orchestrator:** Streamlit")
        st.markdown("**Embedding Model:** all-MiniLM-L6-v2")
        st.markdown("**Vector DB:** FAISS (Facebook AI Search)")
        st.markdown("**Inference Engine:** Groq LPU (Llama 3)")
        
    st.divider()
    
    # Index Management
    st.markdown("### 💾 Knowledge Base")
    if st.button("Save Index State"):
        if st.session_state.index and st.session_state.chunks:
            try:
                faiss.write_index(st.session_state.index, "index.faiss")
                with open("chunks.pkl", "wb") as f:
                    pickle.dump(st.session_state.chunks, f)
                st.success("State Snapshot Saved ✅")
            except Exception as e:
                st.error(f"Snapshot Failed: {e}")
        else:
            st.warning("No Active Index")
            
    if st.button("Load Index State"):
        start_time = time.time()
        try:
            if os.path.exists("index.faiss") and os.path.exists("chunks.pkl"):
                st.session_state.index = faiss.read_index("index.faiss")
                with open("chunks.pkl", "rb") as f:
                    st.session_state.chunks = pickle.load(f)
                
                load_time = time.time() - start_time
                st.success(f"Index Loaded in {load_time:.4f}s")
                st.markdown(f"**Indexed Documents:** {len(st.session_state.chunks)} text chunks")
                st.markdown(f"**Vector Dimensions:** {st.session_state.index.d}")
            else:
                st.error("Snapshot Not Found")
        except Exception as e:
            st.error(f"Load Failed: {e}")

# Main Content
st.markdown("<h1 class='main-header' style='text-align: center;'>Enterprise RAG Analytics Platform</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #a1a1aa;'>High-Performance Retrieval Augmented Generation System</p>", unsafe_allow_html=True)

# Tabs for Mode
tab1, tab2 = st.tabs(["📄 Document Ingestion", "💬 Interactive Query"])

with tab1:
    st.markdown("### Batch Data Processing")
    uploaded_files = st.file_uploader("Upload Corporate Assets (PDF)", type="pdf", accept_multiple_files=True)

    if uploaded_files:
        if st.button("Initialize Processing Pipeline"):
            try:
                all_text = ""
                progress_bar = st.progress(0)
                status_box = st.empty()
                log_container = st.container()
                
                with log_container:
                    st.markdown("#### Execution Logs")
                    log_text = st.empty()
                    logs = []

                    def update_logs(message):
                        logs.append(f"[{time.strftime('%H:%M:%S')}] {message}")
                        log_text.code("\n".join(logs[-10:]), language="bash") # Show last 10 logs

                    update_logs("INFO: User initiated batch processing.")
                    total_files = len(uploaded_files)
                    
                    for i, uploaded_file in enumerate(uploaded_files):
                        update_logs(f"INFO: Parsing binary PDF stream: {uploaded_file.name}")
                        start_parse = time.time()
                        reader = PdfReader(uploaded_file)
                        file_text = ""
                        for page in reader.pages:
                            file_text += page.extract_text() + "\n"
                        all_text += file_text
                        parse_time = time.time() - start_parse
                        update_logs(f"SUCCESS: Extracted {len(file_text)} chars in {parse_time:.3f}s")
                        progress_bar.progress((i + 1) / total_files)
                
                if all_text.strip() == "":
                    st.warning("Stream Parse Error: No text content detected.")
                else:
                    update_logs("INFO: Initializing Recursive Character Text Splitter...")
                    # Split text into chunks
                    chunks = []
                    current_chunk = ""
                    words = all_text.split()
                    
                    for word in words:
                        if len(current_chunk) + len(word) + 1 > 1000: 
                             chunks.append(current_chunk.strip())
                             current_chunk = word
                        else:
                            if current_chunk:
                                current_chunk += " " + word
                            else:
                                current_chunk = word
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    
                    update_logs(f"INFO: Generated {len(chunks)} semantic text chunks.")
                    update_logs("INFO: Loading Transformer Model: all-MiniLM-L6-v2...")
                    
                    # Generate embeddings
                    start_embed = time.time()
                    embeddings = st.session_state.model.encode(chunks)
                    embed_time = time.time() - start_embed
                    update_logs(f"SUCCESS: Vectorized {len(chunks)} chunks in {embed_time:.2f}s.")
                    
                    # Create FAISS index
                    update_logs("INFO: Building FAISS Flat L2 Index...")
                    dimension = embeddings.shape[1]
                    index = faiss.IndexFlatIP(dimension)
                    faiss.normalize_L2(embeddings)
                    index.add(embeddings)
                    
                    st.session_state.index = index
                    st.session_state.chunks = chunks
                    
                    update_logs(f"SUCCESS: Pipeline Complete. Index Size: {index.ntotal} vectors.")
                    status_box.success("Data Ingestion Pipeline Executed Automatically.")
                    
            except Exception as e:
                st.error(f"Pipeline Critical Failure: {e}")

with tab2:
    st.markdown("### Real-time Knowledge Retrieval")
    question = st.text_input("Input Query:", placeholder="e.g., What are the key financial risks outlined in Q3?")

    if question:
        if not api_key:
            st.error("Authentication Error: Missing API Key.")
        elif st.session_state.index is None:
            st.warning("Index Error: No Knowledge Base Loaded.")
        else:
            with st.spinner("Executing Semantic Search & LLM Inference..."):
                t0 = time.time()
                
                # Retrieval
                query_emb = st.session_state.model.encode([question])
                faiss.normalize_L2(query_emb)
                distances, indices = st.session_state.index.search(query_emb, 5) 
                retrieved_chunks = [st.session_state.chunks[i] for i in indices[0]]
                retrieved_scores = distances[0]
                
                t1 = time.time()
                retrieval_time = (t1 - t0) * 1000
                
                context = "\n".join(retrieved_chunks)
                
                # Generation
                try:
                    client = Groq(api_key=api_key)
                    
                    completion = client.chat.completions.create(
                        messages=[
                            {
                                "role": "system", 
                                "content": "You are a specialized enterprise assistant. Answer based strictly on the provided context."
                            },
                            {
                                "role": "user", 
                                "content": f"Context:\n{context}\n\nQuestion: {question}"
                            }
                        ],
                        model="llama-3.3-70b-versatile",
                        temperature=0.0,
                    )
                    
                    t2 = time.time()
                    inference_time = (t2 - t1) * 1000
                    total_time = (t2 - t0) * 1000
                    
                    answer = completion.choices[0].message.content
                    
                    # Display Results
                    st.markdown("#### Model Response")
                    st.write(answer)
                    
                    st.divider()
                    
                    # Technical Metrics Section
                    st.markdown("#### ⚙️ Inference Telemetry")
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.metric("Total Latency", f"{total_time:.0f} ms")
                    with c2:
                        st.metric("Retrieval Time", f"{retrieval_time:.0f} ms")
                    with c3:
                        st.metric("Inference Time", f"{inference_time:.0f} ms")
                    
                    with st.expander("🔍 Vector Search Analysis (Explainability)"):
                        for i, (chunk, score) in enumerate(zip(retrieved_chunks, retrieved_scores)):
                            st.markdown(f"**Chunk {i+1}** (Similarity: `{score:.4f}`)")
                            st.text(chunk[:200] + "...")
                            st.markdown("---")
                            
                except Exception as e:
                    st.error(f"API Gateway Error: {e}")