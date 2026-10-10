use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

fn python_executable(project_dir: &Path) -> PathBuf {
    if let Ok(path) = std::env::var("RICIFIER_PYTHON") {
        return PathBuf::from(path);
    }
    let venv_python = project_dir.join(".venv").join("bin").join("python");
    if venv_python.is_file() {
        return venv_python;
    }
    PathBuf::from("python3")
}

fn project_dir() -> Result<&'static Path, String> {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .ok_or_else(|| "Could not find the project directory".to_string())
}

fn temp_input(bytes: Vec<u8>) -> Result<PathBuf, String> {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| format!("Could not create temporary input name: {error}"))?
        .as_nanos();
    let path = std::env::temp_dir().join(format!("ricifier-input-{stamp}"));
    fs::write(&path, bytes).map_err(|error| format!("Could not save selected input: {error}"))?;
    Ok(path)
}

fn backend_error(output: &std::process::Output, project: &Path) -> String {
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    if stderr.contains("ModuleNotFoundError: No module named 'google'") {
        return format!(
            "{stderr}\n\nInstall dependencies with: {} -m pip install -r backend/requirements.txt",
            python_executable(project).display()
        );
    }
    stderr
}

#[tauri::command]
async fn generate_configs(
    input_bytes: Vec<u8>,
    input_kind: String,
    apps: Vec<String>,
    gemini_configs: bool,
) -> Result<String, String> {
    let project = project_dir()?.to_path_buf();
    tauri::async_runtime::spawn_blocking(move || {
        const VALID_APPS: [&str; 5] = ["kitty", "i3", "polybar", "rofi", "picom"];
        if input_bytes.is_empty() {
            return Err("Choose a wallpaper image or mood.json first.".to_string());
        }
        if input_kind != "image" && input_kind != "json" {
            return Err("The input must be an image or JSON file.".to_string());
        }
        if apps.is_empty() || apps.iter().any(|app| !VALID_APPS.contains(&app.as_str())) {
            return Err("Select at least one supported application.".to_string());
        }
        let input_design = if input_kind == "json" {
            Some(
                serde_json::from_slice::<Value>(&input_bytes)
                    .map_err(|error| format!("Selected mood.json is invalid: {error}"))?,
            )
        } else {
            None
        };

        let script = project.join("backend").join("test_ml_model.py");
        let output_dir = project.join("output");
        let input_path = temp_input(input_bytes)?;
        let mut command = Command::new(python_executable(&project));
        command.current_dir(&project).arg(&script);
        if input_kind == "json" {
            command.arg("--mood-json");
        }
        command
            .arg(&input_path)
            .arg("--out")
            .arg(&output_dir)
            .arg("--apps")
            .args(&apps);
        if gemini_configs {
            command.arg("--gemini-configs");
        }

        let result = command.output();
        let _ = fs::remove_file(&input_path);
        let output = result.map_err(|error| {
            format!(
                "Could not start the Python backend. Install backend/requirements.txt or set \
                 RICIFIER_PYTHON: {error}"
            )
        })?;
        if !output.status.success() {
            return Err(backend_error(&output, &project));
        }

        let design_path = output_dir.join("mood.json");
        let design = if design_path.is_file() {
            serde_json::from_str::<Value>(
                &fs::read_to_string(&design_path)
                    .map_err(|error| format!("Could not read generated mood.json: {error}"))?,
            )
            .map_err(|error| format!("Generated mood.json is invalid: {error}"))?
        } else {
            input_design.unwrap_or_else(|| json!({}))
        };

        let mut files = Vec::new();
        for app in apps {
            let config_name = match app.as_str() {
                "kitty" => "kitty.conf",
                "i3" => "config",
                "polybar" => "config.ini",
                "rofi" => "config.rasi",
                "picom" => "picom.conf",
                _ => unreachable!(),
            };
            let path = output_dir.join(&app).join(config_name);
            let text = fs::read_to_string(&path)
                .map_err(|error| format!("Could not read generated {app} config: {error}"))?;
            files.push(json!({
                "app": app,
                "file": path.to_string_lossy(),
                "text": text
            }));
        }

        Ok(json!({ "design": design, "files": files }).to_string())
    })
    .await
    .map_err(|error| format!("Generation worker failed: {error}"))?
}

#[tauri::command]
async fn explain_parameter(
    app: String,
    line: String,
    line_number: usize,
    design: String,
) -> Result<String, String> {
    let project = project_dir()?.to_path_buf();
    tauri::async_runtime::spawn_blocking(move || {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|error| format!("Could not create request name: {error}"))?
            .as_nanos();
        let payload_path = std::env::temp_dir().join(format!("ricifier-explain-{stamp}.json"));
        let payload = json!({
            "app": app,
            "line": line,
            "line_number": line_number,
            "design": serde_json::from_str::<Value>(&design)
                .map_err(|error| format!("Invalid design data: {error}"))?
        });
        fs::write(&payload_path, payload.to_string())
            .map_err(|error| format!("Could not save explanation request: {error}"))?;

        let output = Command::new(python_executable(&project))
            .current_dir(&project)
            .arg(project.join("backend").join("explain_parameter.py"))
            .arg(&payload_path)
            .output()
            .map_err(|error| format!("Could not start the explanation request: {error}"))?;
        let _ = fs::remove_file(&payload_path);
        if !output.status.success() {
            return Err(backend_error(&output, &project));
        }
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
    })
    .await
    .map_err(|error| format!("Explanation worker failed: {error}"))?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![generate_configs, explain_parameter])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
