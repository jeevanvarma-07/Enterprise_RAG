# Deployment Guide

## 1. Push to GitHub
I have already initialized a git repository for you. Now you need to push it to GitHub.

1.  **Create a New Repository on GitHub**
    *   Go to [github.com/new](https://github.com/new).
    *   Name it `Enterprise_RAG`.
    *   **Public or Private:** Choose according to your preference (Private is safer for enterprise data, but Public is fine since we secured your key).
    *   **Do NOT** check "Initialize with README", .gitignore, or license.
    *   Click **Create repository**.

2.  **Push your code**
    Copy the commands under **"…or push an existing repository from the command line"** and run them in your terminal. They will look like this:
    ```bash
    git remote add origin https://github.com/YOUR_USERNAME/Enterprise_RAG.git
    git branch -M main
    git add .
    git commit -m "Initial commit"
    git push -u origin main
    ```

## 2. Deploy to Streamlit Cloud
1.  **Go to Streamlit Cloud**
    *   Visit [share.streamlit.io](https://share.streamlit.io/).
    *   Click **New app**.

2.  **Connect to GitHub**
    *   Select your `Enterprise_RAG` repository.
    *   **Main file path:** `app.py`.
    *   Click **Deploy!**.

## 3. Configure Secrets (CRITICAL)
Your app will fail to start initially because the API key is missing from the cloud environment.

1.  On your deployed app dashboard, click **Manage app** (bottom right) or the **Settings** menu.
2.  Go to **Secrets**.
3.  Paste the contents of your local `.streamlit/secrets.toml` file:
    ```toml
    GROQ_API_KEY = "gsk_..."
    ```
4.  Click **Save**. The app will automatically restart and work perfectly!
