import axios from 'axios';

/**
 * Central backend client.
 *
 * The base URL is resolved at runtime so the SAME frontend build works in dev
 * (Vite dev server → local FastAPI) and inside the packaged desktop app, where
 * the Tauri shell starts the backend on a free port and injects it as a global.
 *
 * Resolution order:
 *   1. window.__RAG_API_BASE__   — injected by the packaged desktop app
 *   2. import.meta.env.VITE_API_BASE_URL — set in frontend/.env for custom dev
 *   3. http://localhost:8000     — default dev backend
 */
declare global {
  interface Window {
    __RAG_API_BASE__?: string;
  }
}

export const API_BASE_URL: string = (
  window.__RAG_API_BASE__ ||
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  'http://localhost:8000'
).replace(/\/$/, '');

const api = axios.create({ baseURL: API_BASE_URL });

export default api;
