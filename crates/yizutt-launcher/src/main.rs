use std::env;
use std::ffi::OsString;
use std::path::Path;
use std::process::{Command, Stdio};

fn main() {
    let code = run();
    std::process::exit(code);
}

fn run() -> i32 {
    let exe = match env::current_exe() {
        Ok(path) => path,
        Err(error) => {
            eprintln!("yizutt: cannot resolve executable path: {error}");
            return 1;
        }
    };
    let bin_dir = exe.parent().unwrap_or_else(|| Path::new("."));
    let package_root = bin_dir
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .to_path_buf();
    let python_root = package_root.join("python");
    let runtime_bin = bin_dir.join(executable_name("yizutt-runtime"));

    let python = match env::var_os("YIZUTT_PYTHON") {
        Some(value) => value,
        None => match find_python() {
            Some(value) => value,
            None => {
                eprintln!("yizutt: Python 3.11+ is required. Set YIZUTT_PYTHON=/path/to/python.");
                return 127;
            }
        },
    };

    let mut command = Command::new(&python);
    command.arg("-m").arg("yizutt_agi.cli");
    command.args(env::args_os().skip(1));
    command.env("PYTHONPATH", prepend_pythonpath(&python_root));
    set_default_env(
        &mut command,
        "YIZUTT_PROJECT_ROOT",
        package_root.as_os_str().to_os_string(),
    );
    set_default_env(
        &mut command,
        "RUNTIME_BIN",
        runtime_bin.as_os_str().to_os_string(),
    );
    set_default_env(
        &mut command,
        "YIZUTT_RUNTIME_BIN",
        runtime_bin.as_os_str().to_os_string(),
    );
    set_default_env(&mut command, "BUILD", OsString::from("0"));
    set_default_env(&mut command, "YIZUTT_PYTHON", python);

    match command.status() {
        Ok(status) => status.code().unwrap_or(1),
        Err(error) => {
            eprintln!("yizutt: failed to start Python CLI: {error}");
            127
        }
    }
}

fn executable_name(name: &str) -> String {
    if cfg!(windows) {
        format!("{name}.exe")
    } else {
        name.to_string()
    }
}

fn find_python() -> Option<OsString> {
    for candidate in ["python3", "python"] {
        let status = Command::new(candidate)
            .arg("--version")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        if status.map(|value| value.success()).unwrap_or(false) {
            return Some(OsString::from(candidate));
        }
    }
    None
}

fn prepend_pythonpath(path: &Path) -> OsString {
    let mut paths = vec![path.to_path_buf()];
    if let Some(existing) = env::var_os("PYTHONPATH") {
        paths.extend(env::split_paths(&existing));
    }
    env::join_paths(paths).unwrap_or_else(|_| path.as_os_str().to_os_string())
}

fn set_default_env(command: &mut Command, name: &str, value: OsString) {
    if env::var_os(name).is_none() {
        command.env(name, value);
    }
}
