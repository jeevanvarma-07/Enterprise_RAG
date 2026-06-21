# Enterprise RAG System

An enterprise-grade **Retrieval Augmented Generation (RAG)** system that allows organizations to upload documents and query them intelligently using large language models.

---

## 🚀 Features

- **Multi-format ingestion** — PDF, Excel/CSV, TXT, and Images (OCR)
- **Batch upload** — Upload 300+ files simultaneously with live progress bar
- **Advanced Retrieval** — Multi-Query Retrieval + Reciprocal Rank Fusion (RRF) + MMR
- **Conversation History** — History-aware follow-up question understanding
- **Vector Store Management** — View, selectively delete, or export the FAISS index
- **Markdown responses** — Structured, ChatGPT-quality answers with bullet points and headers
- **Model selection** — Switch between Llama 3.1 8B, Llama 3.3 70B, and Mixtral 8x7B

---

## 🏗️ Architecture

```
frontend/          ← React + Vite + TypeScript + Tailwind CSS
backend/
  main.py          ← FastAPI application with all REST endpoints
  services/
    document_processing.py  ← PDF/Excel/Image text extraction
    indexing.py             ← FAISS vector store management
    generation.py           ← Multi-Query + MMR + RRF + Chat History RAG pipeline
  uploads/         ← Uploaded source documents
  vector_store/    ← FAISS index + metadata.json
```

---

## ⚙️ Setup

### Backend
```bash
cd backend
python -m venv venv
.\venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Create `backend/.env`:
```
GROQ_API_KEY=your_groq_api_key_here
```

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/upload` | Upload and index documents |
| POST | `/api/chat` | Query with conversation history |
| GET | `/api/index/status` | Index status and chunk count |
| GET | `/api/index/documents` | List all indexed files |
| DELETE | `/api/index/documents/{filename}` | Delete a specific file |
| POST | `/api/index/documents/batch-delete` | Delete multiple files |
| DELETE | `/api/index/clear` | Clear the entire index |
| GET | `/api/index/export` | Download FAISS index as ZIP |

---

## 🧠 RAG Pipeline

```
User Query
    │
    ├── History-aware query rewriting (chat context)
    │
    └── Multi-Query Generation (3 query variations)
             │
             ├── Query 1 ──▶ MMR Retrieval ──▶ [docs]
             ├── Query 2 ──▶ MMR Retrieval ──▶ [docs]
             └── Query 3 ──▶ MMR Retrieval ──▶ [docs]
                                    │
                            Reciprocal Rank Fusion
                                    │
                              Top-6 diverse chunks
                                    │
                              Groq LLM (Llama/Mixtral)
                                    │
                            Markdown-formatted Answer
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React, Vite, TypeScript, Tailwind CSS, Framer Motion |
| Backend | FastAPI, Uvicorn, Python 3.9+ |
| Embeddings | HuggingFace `all-MiniLM-L6-v2` |
| Vector DB | FAISS (local), upgradeable to Pinecone |
| LLM | Groq API (Llama 3.1, Llama 3.3, Mixtral) |
| Document Parsing | PyPDF2, pandas, pytesseract, easyocr |
