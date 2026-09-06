#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use serde::Serialize;
use tauri::{Manager, State};

const BACKEND_BYTES: &[u8] = include_bytes!(env!("FINCLI_BACKEND_PATH"));

struct DesktopState {
    token: String,
    port: u16,
    data_dir: PathBuf,
    child: Mutex<Option<Child>>,
    runtime_path: Mutex<Option<PathBuf>>,
    error: Mutex<Option<String>>,
    log_path: PathBuf,
    stopping: AtomicBool,
    generation: AtomicU64,
}

#[derive(Serialize)]
struct DesktopStatus {
    url: String,
    status: String,
    backend_error: Option<String>,
    data_dir: String,
    log_path: String,
}

#[tauri::command]
fn desktop_url(state: State<'_, DesktopState>) -> String {
    format!("http://127.0.0.1:{}", state.port)
}

#[tauri::command]
fn desktop_session(state: State<'_, DesktopState>) -> String {
    state.token.clone()
}

#[tauri::command]
fn desktop_error(state: State<'_, DesktopState>) -> String {
    let message = state
        .error
        .lock()
        .ok()
        .and_then(|error| error.clone())
        .unwrap_or_else(|| "The local backend did not become ready.".to_string());
    format!("{message}\n\nLog: {}", state.log_path.display())
}

#[tauri::command]
fn desktop_status(state: State<'_, DesktopState>) -> DesktopStatus {
    let backend_error = state.error.lock().ok().and_then(|error| error.clone());
    let running = state.child.lock().map(|child| child.is_some()).unwrap_or(false);
    DesktopStatus {
        url: format!("http://127.0.0.1:{}", state.port),
        status: if backend_error.is_some() {
            "error"
        } else if running {
            "running"
        } else {
            "starting"
        }
        .to_string(),
        backend_error,
        data_dir: state.data_dir.display().to_string(),
        log_path: state.log_path.display().to_string(),
    }
}

fn default_data_dir() -> PathBuf {
    std::env::var_os("LOCALAPPDATA")
        .or_else(|| std::env::var_os("APPDATA"))
        .map(PathBuf::from)
        .map(|base| base.join("FinCLI"))
        .or_else(|| std::env::current_dir().ok().map(|base| base.join("FinCLIData")))
        .unwrap_or_else(|| PathBuf::from("FinCLIData"))
}

fn default_log_path(data_dir: &PathBuf) -> PathBuf {
    data_dir.join("logs").join("backend.log")
}

fn append_log(path: &PathBuf, bytes: &[u8]) {
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = file.write_all(bytes);
        let _ = file.write_all(b"\n");
    }
}

fn pick_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|address| address.port())
        .unwrap_or(19850)
}

fn extract_backend(token: &str) -> Result<PathBuf, String> {
    if BACKEND_BYTES.is_empty() {
        return Err("FinCLI backend payload is missing. Rebuild the release with the embedded backend.".to_string());
    }
    let directory = std::env::temp_dir().join("FinCLI").join(format!("backend-{token}"));
    fs::create_dir_all(&directory).map_err(|error| format!("Unable to prepare temporary backend: {error}"))?;
    let path = directory.join("fincli-backend.exe");
    let mut file = File::create(&path).map_err(|error| format!("Unable to extract FinCLI backend: {error}"))?;
    file.write_all(BACKEND_BYTES)
        .map_err(|error| format!("Unable to write FinCLI backend: {error}"))?;
    Ok(path)
}

fn pipe_to_log<R: Read + Send + 'static>(reader: R, path: PathBuf) {
    thread::spawn(move || {
        let mut reader = BufReader::new(reader);
        let mut line = Vec::new();
        loop {
            line.clear();
            match reader.read_until(b'\n', &mut line) {
                Ok(0) => break,
                Ok(_) => append_log(&path, &line),
                Err(error) => {
                    append_log(&path, format!("Backend output error: {error}").as_bytes());
                    break;
                }
            }
        }
    });
}

fn cleanup_runtime(path: Option<PathBuf>) {
    if let Some(path) = path {
        if let Some(parent) = path.parent() {
            let _ = fs::remove_dir_all(parent);
        }
    }
}

fn terminate_process_tree(child: &mut Child) {
    #[cfg(windows)]
    {
        let pid = child.id().to_string();
        let _ = Command::new("taskkill")
            .args(["/PID", &pid, "/T", "/F"])
            .status();
    }
    #[cfg(not(windows))]
    {
        let _ = child.kill();
    }
    let _ = child.wait();
}

fn start_backend(app: tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<DesktopState>();
    let generation = state.generation.fetch_add(1, Ordering::SeqCst) + 1;
    state.stopping.store(false, Ordering::SeqCst);
    if let Ok(mut error) = state.error.lock() {
        *error = None;
    }
    fs::create_dir_all(&state.data_dir).map_err(|error| format!("Unable to create FinCLI data folder: {error}"))?;
    append_log(&state.log_path, b"Starting embedded FinCLI backend...");
    let backend_path = extract_backend(&state.token)?;
    let port = state.port.to_string();
    let mut command = Command::new(&backend_path);
    command
        .args(["--desktop", "--host", "127.0.0.1", "--port", &port])
        .env("FINCLI_DESKTOP", "1")
        .env("FINCLI_DESKTOP_TOKEN", &state.token)
        .env("FINCLI_DATA_DIR", &state.data_dir)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = command
        .spawn()
        .map_err(|error| format!("Unable to start embedded FinCLI backend: {error}"))?;
    if let Some(stdout) = child.stdout.take() {
        pipe_to_log(stdout, state.log_path.clone());
    }
    if let Some(stderr) = child.stderr.take() {
        pipe_to_log(stderr, state.log_path.clone());
    }
    if let Ok(mut path) = state.runtime_path.lock() {
        *path = Some(backend_path);
    }
    *state.child.lock().map_err(|_| "Backend state lock failed".to_string())? = Some(child);

    let app_handle = app.clone();
    thread::spawn(move || loop {
        if app_handle
            .state::<DesktopState>()
            .generation
            .load(Ordering::SeqCst)
            != generation
        {
            return;
        }
        let result = {
            let state = app_handle.state::<DesktopState>();
            let mut child = match state.child.lock() {
                Ok(child) => child,
                Err(_) => return,
            };
            if state.generation.load(Ordering::SeqCst) != generation {
                return;
            }
            match child.as_mut() {
                Some(child) => child.try_wait(),
                None => return,
            }
        };
        match result {
            Ok(Some(status)) => {
                let state = app_handle.state::<DesktopState>();
                if state.generation.load(Ordering::SeqCst) != generation {
                    return;
                }
                if !state.stopping.load(Ordering::SeqCst) && !status.success() {
                    if let Ok(mut error) = state.error.lock() {
                        *error = Some(format!("The FinCLI backend exited with status {status}."));
                    }
                }
                if let Ok(mut child) = state.child.lock() {
                    child.take();
                }
                let path = state.runtime_path.lock().ok().and_then(|mut path| path.take());
                cleanup_runtime(path);
                return;
            }
            Ok(None) => thread::sleep(Duration::from_millis(200)),
            Err(error) => {
                let state = app_handle.state::<DesktopState>();
                if state.generation.load(Ordering::SeqCst) != generation {
                    return;
                }
                if let Ok(mut detail) = state.error.lock() {
                    *detail = Some(format!("Unable to monitor the FinCLI backend: {error}"));
                }
                return;
            }
        }
    });
    Ok(())
}

fn stop_backend(app: &tauri::AppHandle) {
    let state = app.state::<DesktopState>();
    state.generation.fetch_add(1, Ordering::SeqCst);
    state.stopping.store(true, Ordering::SeqCst);
    if let Ok(mut child_state) = state.child.lock() {
        if let Some(mut child) = child_state.take() {
            terminate_process_tree(&mut child);
        }
    }
    let path = state.runtime_path.lock().ok().and_then(|mut path| path.take());
    cleanup_runtime(path);
}

#[tauri::command]
fn desktop_restart(app: tauri::AppHandle) -> Result<(), String> {
    stop_backend(&app);
    start_backend(app)
}

pub fn run() {
    let data_dir = std::env::var_os("FINCLI_DATA_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(default_data_dir);
    let state = DesktopState {
        token: uuid::Uuid::new_v4().to_string(),
        port: pick_port(),
        log_path: default_log_path(&data_dir),
        data_dir,
        child: Mutex::new(None),
        runtime_path: Mutex::new(None),
        error: Mutex::new(None),
        stopping: AtomicBool::new(false),
        generation: AtomicU64::new(0),
    };

    tauri::Builder::default()
        .manage(state)
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .invoke_handler(tauri::generate_handler![desktop_url, desktop_session, desktop_error, desktop_status, desktop_restart])
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if let Err(error) = start_backend(handle.clone()) {
                    if let Ok(mut state) = handle.state::<DesktopState>().error.lock() {
                        *state = Some(error);
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building FinCLI desktop")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                stop_backend(app);
            }
        });
}

fn main() {
    run();
}
