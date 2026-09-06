use std::env;
use std::fs;
use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").expect("missing manifest directory"));
    let default_backend = manifest_dir
        .join("binaries")
        .join("fincli-backend-x86_64-pc-windows-msvc.exe");
    let source = env::var_os("FINCLI_BACKEND_BINARY").map(PathBuf::from).unwrap_or(default_backend);
    let output = PathBuf::from(env::var_os("OUT_DIR").expect("missing cargo output directory")).join("fincli-backend.exe");
    println!("cargo:rerun-if-env-changed=FINCLI_BACKEND_BINARY");
    println!("cargo:rerun-if-changed={}", source.display());
    if source.is_file() {
        fs::copy(&source, &output).expect("failed to stage embedded FinCLI backend");
    } else if env::var("PROFILE").as_deref() == Ok("release") {
        panic!("embedded backend not found at {}; run scripts/build_desktop_backend.ps1 first", source.display());
    } else {
        fs::write(&output, &[] as &[u8]).expect("failed to create development backend placeholder");
    }
    println!("cargo:rustc-env=FINCLI_BACKEND_PATH={}", output.display());
    tauri_build::build();
}
