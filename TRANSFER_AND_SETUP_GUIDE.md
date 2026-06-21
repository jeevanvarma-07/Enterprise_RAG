# 📦 Enterprise RAG — Complete Transfer & Setup Guide

> **This guide is written for someone who has NEVER set up this project before.**
> Follow every step in order. Do NOT skip any step.

---

## 📁 PART 1: WHAT TO COPY TO YOUR PENDRIVE

Copy the **entire `Enterprise_RAG` folder** to your pendrive — BUT exclude these two heavy folders to save space and time (they will be recreated on the new laptop):

| Folder to EXCLUDE (don't copy) | Why |
|---|---|
| `Enterprise_RAG\backend\venv\` | Python virtual environment — must be recreated |
| `Enterprise_RAG\frontend\node_modules\` | Node packages — must be reinstalled |

### ✅ Everything else MUST be copied, especially:
- `Enterprise_RAG\backend\` (all .py files, requirements.txt, .env, uploads/, vector_store/)
- `Enterprise_RAG\frontend\` (all src/ files, package.json, vite.config.ts, tsconfig files etc.)
- `Enterprise_RAG\.env`
- `Enterprise_RAG\START_PROJECT.bat`
- `Enterprise_RAG\requirements.txt`

> **TIP:** If you already uploaded documents to the system, make sure to copy:
> - `Enterprise_RAG\backend\uploads\` (your uploaded files)
> - `Enterprise_RAG\backend\vector_store\` (your indexed data — very important!)

---

## 💻 PART 2: WHAT TO INSTALL ON THE NEW LAPTOP (One-time setup)

### Step 1 — Install Python 3.11

1. Go to: https://www.python.org/downloads/release/python-3119/
2. Download **"Windows installer (64-bit)"**
3. Run the installer
4. ⚠️ **VERY IMPORTANT**: On the first screen, check the box that says **"Add Python to PATH"** before clicking Install
5. Click **"Install Now"**
6. After install, open Command Prompt and verify:
   ```
   python --version
   ```
   You should see: `Python 3.11.x`

---

### Step 2 — Install Node.js (v20 LTS)

1. Go to: https://nodejs.org/en/download
2. Download the **LTS version** (Windows Installer .msi)
3. Run the installer, click Next through all steps (defaults are fine)
4. After install, open Command Prompt and verify:
   ```
   node --version
   npm --version
   ```
   You should see version numbers for both.

---

### Step 3 — Copy the Project Folder from Pendrive

1. Plug in your pendrive
2. Copy the `Enterprise_RAG` folder to: `C:\Enterprise_RAG`
3. Final path should be: `C:\Enterprise_RAG\` (not `C:\Enterprise_RAG\Enterprise_RAG\`)

---

## ⚙️ PART 3: SETTING UP THE BACKEND (Python)

Open **Command Prompt** (search "cmd" in Start menu). Then run these commands **one by one**:

### Step 4 — Go to the backend folder
```cmd
cd C:\Enterprise_RAG\backend
```

### Step 5 — Create a Python virtual environment
```cmd
python -m venv venv
```
Wait for it to finish. A new `venv` folder will appear.

### Step 6 — Activate the virtual environment
```cmd
venv\Scripts\activate
```
You should now see `(venv)` at the start of your command prompt line. If you do NOT see this, stop and check Step 1 again.

### Step 7 — Install all Python packages
```cmd
pip install -r requirements.txt
```
⏳ This will take **5–15 minutes** depending on internet speed. Wait for it to finish completely.

> **If you see an error about `easyocr` or `pytesseract`**, that is okay — those are optional OCR features. The core system will still work.

### Step 8 — Verify backend installation
```cmd
uvicorn main:app --reload --port 8000
```
If you see output like:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```
✅ **Backend is working!** Press `Ctrl+C` to stop it for now.

---

## 🎨 PART 4: SETTING UP THE FRONTEND (React)

Open a **new Command Prompt window** and run these commands **one by one**:

### Step 9 — Go to the frontend folder
```cmd
cd C:\Enterprise_RAG\frontend
```

### Step 10 — Install all Node packages
```cmd
npm install
```
⏳ This will take **2–5 minutes**. Wait for it to finish completely.

### Step 11 — Verify frontend setup
```cmd
npm run dev
```
If you see:
```
  VITE v7.x.x  ready in xxx ms
  ➜  Local:   http://localhost:5173/
```
✅ **Frontend is working!** Press `Ctrl+C` to stop it for now.

---

## 🔑 PART 5: VERIFY THE API KEY (.env FILE)

### Step 12 — Check the .env file

Open `C:\Enterprise_RAG\backend\.env` in Notepad and confirm it contains:

```
PROJECT_NAME="Enterprise RAG System"
GROQ_API_KEY="your_groq_api_key_here"
```

> ⚠️ Get a free key at https://console.groq.com/keys and paste it into `backend/.env`.
> **Never commit a real key or paste it into documentation** — keep it only in your local
> (gitignored) `.env` file.

---

## 🚀 PART 6: RUNNING THE PROJECT (Every time after setup)

### Option A — Use the one-click launcher (Easiest)

After completing the setup above, every time you want to run the project:

1. Go to `C:\Enterprise_RAG\`
2. Double-click **`START_PROJECT.bat`**
3. Two command windows will open automatically (one for backend, one for frontend)
4. Wait about 10 seconds, then your browser will open at: **http://localhost:5173**

> ⚠️ **If `START_PROJECT.bat` doesn't work** because the project folder is not in `C:\`:
> Right-click `START_PROJECT.bat` → Edit → The file uses `%~dp0` so it should work from any location automatically.

---

### Option B — Run manually (if .bat file fails)

**Terminal 1 — Start Backend:**
```cmd
cd C:\Enterprise_RAG\backend
venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

**Terminal 2 — Start Frontend:**
```cmd
cd C:\Enterprise_RAG\frontend
npm run dev
```

Then open browser at: **http://localhost:5173**

---

## 🔧 PART 7: TROUBLESHOOTING COMMON ERRORS

### ❌ Error: `'python' is not recognized`
- **Fix**: Python was not added to PATH during installation. Uninstall Python and reinstall, making sure to check "Add Python to PATH" on the first screen.

### ❌ Error: `'npm' is not recognized`
- **Fix**: Node.js was not installed correctly. Reinstall Node.js and restart Command Prompt.

### ❌ Error: `venv\Scripts\activate` gives an error about execution policy
- **Fix**: Open PowerShell as Administrator and run:
  ```powershell
  Set-ExecutionPolicy RemoteSigned
  ```
  Then press `Y` and Enter. Try activating again.

### ❌ Backend starts but frontend shows "Network Error" or can't connect
- **Fix**: Make sure BOTH the backend and frontend are running at the same time. Backend must be running on port 8000 and frontend at port 5173.

### ❌ Error: `pip install` fails for a package
- **Fix**: Run this first, then retry:
  ```cmd
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  ```

### ❌ Error: Port 8000 already in use
- **Fix**: Open Task Manager, find any Python process and end it. Then restart the backend.

### ❌ Error: Port 5173 already in use
- **Fix**: Open Task Manager, find any Node.js process and end it. Then restart the frontend.

### ❌ The uploaded documents or chat history are gone on the new laptop
- **Reason**: You forgot to copy `backend\uploads\` and `backend\vector_store\` from the old machine.
- **Fix**: Copy those two folders from your pendrive/old machine to `C:\Enterprise_RAG\backend\`.

---

## 📋 QUICK CHECKLIST — Before You Start

- [ ] Python 3.11 installed with "Add to PATH" checked
- [ ] Node.js LTS installed
- [ ] Project folder copied to `C:\Enterprise_RAG\` (not nested deeper)
- [ ] `backend\venv` recreated with `python -m venv venv`
- [ ] `pip install -r requirements.txt` completed in `backend\venv`
- [ ] `npm install` completed in `frontend\`
- [ ] `backend\.env` file has the GROQ API key
- [ ] Both backend (port 8000) and frontend (port 5173) are running

---

## 📊 SYSTEM REQUIREMENTS

| Component | Minimum | Recommended |
|---|---|---|
| RAM | 8 GB | 16 GB |
| Storage | 10 GB free | 20 GB free |
| OS | Windows 10 64-bit | Windows 10/11 64-bit |
| Internet | Required for setup | Required for AI responses |
| Processor | Intel i3 | Intel i5 or better |

> ⚠️ **Note for 8GB RAM laptops**: The system will work, but processing large documents (50+ pages) may be slow. OCR features (image-based PDFs) require more RAM and may crash. Stick to text-based PDFs and spreadsheets for best results.

---

*Guide created for Enterprise RAG System v2.0.0*
