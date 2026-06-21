@echo off
title Enterprise RAG - Viva Startup
color 0A
echo.
echo  ==========================================
echo    Enterprise RAG System - Starting...
echo  ==========================================
echo.

echo [1/2] Starting Backend (FastAPI)...
start "Backend - FastAPI" cmd /k "cd /d %~dp0backend && .\venv\Scripts\activate && uvicorn main:app --reload --port 8000"

timeout /t 5 /nobreak >nul

echo [2/2] Starting Frontend (React)...
start "Frontend - React" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 5 /nobreak >nul

echo.
echo  ==========================================
echo   Both servers starting!
echo   Open browser at: http://localhost:5173
echo  ==========================================
echo.

start "" "http://localhost:5173"

pause
