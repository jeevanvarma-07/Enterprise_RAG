//! Enterprise RAG desktop shell.
//!
//! Responsibilities of the Rust side:
//!   1. Pick a free localhost port for the backend.
//!   2. Resolve a per-user data directory and pass it to the backend so all
//!      uploads / vector store / settings live outside the install dir.
//!   3. Spawn the frozen FastAPI backend as a Tauri **sidecar** with
//!      RAG_HOST / RAG_PORT / RAG_DATA_DIR / RAG_CORS_ORIGINS in its env.
//!   4. Health-check `GET /api/health` until the backend is ready.
//!   5. Create the webview, injecting `window.__RAG_API_BASE__` so the SAME
//!      frontend build that runs in dev also talks to the sidecar here.
//!   6. Tear the backend down when the app exits.
//!
//! The frontend never hardcodes a port; see `frontend/src/api.ts`.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Handle to the running backend child, so we can kill it on exit.
///
/// We keep the child's PID separately because the frozen sidecar is a **one-file**
/// PyInstaller exe: its bootloader process re-spawns the real uvicorn server as a
/// *grandchild*. `CommandChild::kill()` only reaps the direct bootloader, leaving
/// the server orphaned (holding its port + ~285 MB). We therefore tear down the
/// whole process tree by PID on exit (see `terminate_backend`).
struct BackendProcess {
    child: Arc<Mutex<Option<CommandChild>>>,
    pid: u32,
}

/// Tear down the backend and every process it spawned.
///
/// On Windows the one-file sidecar spawns a grandchild, so we `taskkill /T`
/// the live tree by PID; `CommandChild::kill()` is kept as the cross-platform
/// path (and a fallback). Best-effort — never panics on shutdown.
fn terminate_backend(child: Option<CommandChild>, pid: u32) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let _ = std::process::Command::new("taskkill")
            .args(["/F", "/T", "/PID", &pid.to_string()])
            .creation_flags(CREATE_NO_WINDOW)
            .output();
    }
    #[cfg(not(windows))]
    let _ = pid;

    if let Some(c) = child {
        let _ = c.kill();
    }
}

/// Ask the OS for a free TCP port by binding to :0 and reading it back.
fn find_free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8000)
}

/// Minimal blocking HTTP GET that returns true iff the response status is 200.
/// Avoids pulling in a full HTTP client crate just for a readiness probe.
fn http_ok(host: &str, port: u16, path: &str) -> bool {
    let addr = format!("{host}:{port}");
    let Ok(mut stream) = TcpStream::connect_timeout(
        &match addr.parse() {
            Ok(a) => a,
            Err(_) => return false,
        },
        Duration::from_millis(800),
    ) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
    let req = format!(
        "GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }
    let mut buf = [0u8; 256];
    match stream.read(&mut buf) {
        Ok(n) if n > 0 => {
            let head = String::from_utf8_lossy(&buf[..n]);
            head.contains("200")
        }
        _ => false,
    }
}

/// Poll the health endpoint until it answers 200 or we time out.
fn wait_for_backend(host: &str, port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if http_ok(host, port, "/api/health") {
            return true;
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let host = "127.0.0.1".to_string();
            let port = find_free_port();
            let api_base = format!("http://{host}:{port}");

            // Per-user data dir: <app_data>/EnterpriseRAG. The backend reads
            // RAG_DATA_DIR (see backend/config.py) and puts uploads, the FAISS
            // store, settings.json and rag.db there — never in Program Files.
            let data_dir = app
                .path()
                .app_data_dir()
                .map(|p| p.join("data"))
                .unwrap_or_else(|_| std::env::temp_dir().join("EnterpriseRAG"));
            let _ = std::fs::create_dir_all(&data_dir);
            let data_dir_str = data_dir.to_string_lossy().to_string();

            // CORS: the Tauri webview origin must be allowed by the backend.
            let cors = "tauri://localhost,http://tauri.localhost,http://localhost".to_string();

            // ── Spawn the backend sidecar ───────────────────────────────
            // "rag-backend" matches the externalBin name in tauri.conf.json;
            // Tauri resolves the platform-specific binary (target-triple
            // suffix) automatically.
            let sidecar = app
                .shell()
                .sidecar("rag-backend")
                .expect("failed to create `rag-backend` sidecar command")
                .env("RAG_HOST", host.clone())
                .env("RAG_PORT", port.to_string())
                .env("RAG_DATA_DIR", data_dir_str.clone())
                .env("RAG_CORS_ORIGINS", cors);

            let (mut rx, child) = sidecar.spawn().expect("failed to spawn backend sidecar");

            // Stash the child (and its PID) so we can kill the whole backend
            // process tree on window close / app exit.
            let backend_pid = child.pid();
            app.manage(BackendProcess {
                child: Arc::new(Mutex::new(Some(child))),
                pid: backend_pid,
            });

            // Drain sidecar stdout/stderr to the shell's console for debugging.
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            print!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            eprint!("[backend] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[backend] terminated: {payload:?}");
                        }
                        _ => {}
                    }
                }
            });

            // ── Wait for readiness, then build the window ───────────────
            // Health-check on a background thread so the OS event loop stays
            // responsive; build the webview once the backend answers.
            let handle = app.handle().clone();
            let host_for_wait = host.clone();
            std::thread::spawn(move || {
                let ready = wait_for_backend(&host_for_wait, port, Duration::from_secs(60));
                if !ready {
                    eprintln!("[shell] backend did not become healthy in 60s");
                }

                // The init script runs before any page JS, so api.ts sees the
                // resolved base URL on first load.
                let init = format!("window.__RAG_API_BASE__ = \"{api_base}\";");

                let res = WebviewWindowBuilder::new(
                    &handle,
                    "main",
                    WebviewUrl::App("index.html".into()),
                )
                .title("Enterprise RAG")
                .inner_size(1280.0, 840.0)
                .min_inner_size(900.0, 600.0)
                .initialization_script(&init)
                .build();

                if let Err(e) = res {
                    eprintln!("[shell] failed to create window: {e}");
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            // Kill the backend (and its whole tree) when the window is closing.
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                if let Some(state) = window.app_handle().try_state::<BackendProcess>() {
                    let child = state.child.lock().ok().and_then(|mut g| g.take());
                    terminate_backend(child, state.pid);
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building the Enterprise RAG application")
        .run(|app_handle, event| {
            // Final safety net: kill the backend tree on full app exit.
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<BackendProcess>() {
                    let child = state.child.lock().ok().and_then(|mut g| g.take());
                    terminate_backend(child, state.pid);
                }
            }
        });
}
