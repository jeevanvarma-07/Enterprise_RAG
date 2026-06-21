# Groq API Setup Guide

This guide will help you generate an API key and choose the best model for your Enterprise RAG system.

## 1. Get Your API Key
1.  **Go to the Groq Console:**
    Navigate to [https://console.groq.com/keys](https://console.groq.com/keys).
2.  **Login/Sign Up:**
    Log in using your GitHub or Google account.
3.  **Create API Key:**
    Click on the **"Create API Key"** button.
4.  **Name Your Key:**
    Give it a recognizable name (e.g., `Enterprise_RAG_App`).
5.  **Copy the Key:**
    **IMPORTANT:** Copy the key immediately (starts with `gsk_`). You won't be able to see it again.

## 2. Configure the Application
1.  Open `e:\Enterprise_RAG\app.py`.
2.  Find the line `GROQ_API_KEY = "past_your_key_here"` near the top of the file.
3.  Paste your copied key inside the quotes.

## 3. Recommended Models
Groq offers several models. For this application, we recommend:

### **Best Balance (Recommended)**
- **Model ID:** `llama-3.3-70b-versatile`
- **Why:** State-of-the-art reasoning, excellent instruction following, and highly efficient on Groq LPU. Ideal for Enterprise RAG.

### **Fastest / Lower Resource**
- **Model ID:** `llama-3.1-8b-instant`
- **Why:** Extremely fast response times, perfect for quick summaries or simple Q&A.

### **To Change the Model:**
In `app.py`, search for `model="llama-3.3-70b-versatile"` and replace it with your chosen model ID.
