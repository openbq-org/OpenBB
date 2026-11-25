use crate::tauri_handlers::helpers::{
    EnvSystem, FileSystem, RealEnvSystem, RealFileSystem, get_environment_python_version_impl,
    get_environments_directory_impl, get_installation_directory_impl,
    save_environment_as_yaml_impl,
};
use crate::tauri_handlers::startup::INSTALLATION_STATE;
use crate::utils::process_monitor::{get_log_storage, register_process};
use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader};
use std::process::Stdio;
use tauri::Emitter;

// Helper function to remove ANSI escape sequences and handle carriage returns
fn clean_output_line(input: &str) -> String {
    let ansi_regex = regex::Regex::new(r"\x1B\[[0-9;]*[a-zA-Z]").unwrap();
    let without_ansi = ansi_regex.replace_all(input, "");

    // Handle backspaces by removing the character before it
    let mut processed = String::new();
    for c in without_ansi.chars() {
        if c == '\x08' {
            processed.pop();
        } else {
            processed.push(c);
        }
    }

    processed
        .rsplit('\r')
        .find(|s| !s.trim().is_empty())
        .unwrap_or("")
        .trim()
        .to_string()
}

// Helper function to run a command and log its output
fn run_command_with_logging(
    mut command: std::process::Command,
    process_id: &str,
    app_handle: &Option<tauri::AppHandle>,
) -> Result<(std::process::ExitStatus, Vec<String>, Vec<String>), String> {
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn command: {e}"))?;

    let stdout = child.stdout.take().ok_or("Failed to capture stdout")?;
    let stderr = child.stderr.take().ok_or("Failed to capture stderr")?;

    let process_id_clone = process_id.to_string();
    let app_handle_clone = app_handle.clone();
    let stdout_thread = std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        let mut lines = Vec::new();
        for line in reader.lines().map_while(Result::ok) {
            if let Some(handle) = &app_handle_clone {
                let clean_line = clean_output_line(&line);
                if !clean_line.is_empty() {
                    let _ = handle.emit(
                        "process-output",
                        serde_json::json!({
                            "processId": process_id_clone.clone(),
                            "output": clean_line,
                        }),
                    );
                }
            }
            lines.push(line);
        }
        lines
    });

    let process_id_clone2 = process_id.to_string();
    let stderr_handle = app_handle.clone();
    let stderr_thread = std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        let mut lines = Vec::new();
        for line in reader.lines().map_while(Result::ok) {
            if let Some(handle) = &stderr_handle {
                let clean_line = clean_output_line(&line);
                if !clean_line.is_empty() {
                    let _ = handle.emit(
                        "process-output",
                        serde_json::json!({
                            "processId": process_id_clone2.clone(),
                            "output": clean_line,
                        }),
                    );
                }
            }
            lines.push(line);
        }
        lines
    });

    let stdout_lines = stdout_thread.join().unwrap();
    let stderr_lines = stderr_thread.join().unwrap();

    let status = child
        .wait()
        .map_err(|e| format!("Failed to wait on child process: {e}"))?;

    Ok((status, stdout_lines, stderr_lines))
}

#[derive(Serialize, Deserialize, Debug)]
pub struct CondaEnvironment {
    pub name: String,
    #[serde(rename = "pythonVersion")]
    pub python_version: String,
    pub path: String,
}

#[cfg(windows)]
use std::os::windows::process::CommandExt;

pub async fn create_environment_impl<F: FileSystem, E: EnvSystem>(
    name: String,
    python_version: String,
    extensions: Vec<String>,
    process_id: String,
    app_handle: Option<tauri::AppHandle>,
    fs: &F,
    env_sys: &E,
) -> Result<bool, String> {
    use std::collections::HashMap;
    use std::path::Path;

    let log_storage = get_log_storage();
    register_process(&log_storage, &process_id);

    log::debug!("=== CREATING ENVIRONMENT: {name} ===");
    log::debug!("Python version: {python_version}");
    log::debug!("Extensions: {extensions:?}");

    // Ensure openbb-platform-api is included
    let mut all_extensions = extensions.clone();
    if !all_extensions.iter().any(|e| e == "openbb-platform-api") {
        all_extensions.push("openbb-platform-api".to_string());
        log::debug!("Added openbb-platform-api to extensions");
    }

    // We'll always include OpenBB regardless of whether it's in the extensions list
    let has_openbb_in_extensions = all_extensions.iter().any(|e| e.to_lowercase() == "openbb");
    if !has_openbb_in_extensions {
        all_extensions.push("openbb".to_string());
    }

    // Get the system settings file path
    let home_dir = env_sys
        .var("HOME")
        .or_else(|_| env_sys.var("USERPROFILE"))
        .map_err(|e| format!("Could not determine home directory: {e}"))?;

    let platform_dir = Path::new(&home_dir).join(".openbb_platform");
    let system_settings_path = platform_dir.join("system_settings.json");

    if !fs.exists(&system_settings_path) {
        return Err(
            "System settings file not found. Please complete installation first.".to_string(),
        );
    }

    // Read the system settings file
    let settings_content = fs
        .read_to_string(&system_settings_path)
        .map_err(|e| format!("Failed to read system settings: {e}"))?;

    let settings: serde_json::Value = serde_json::from_str(&settings_content)
        .map_err(|e| format!("Failed to parse system settings: {e}"))?; // Get the installation directory
    let install_dir = settings["install_settings"]["installation_directory"]
        .as_str()
        .ok_or_else(|| "Installation directory not found in system settings".to_string())?;

    log::debug!("Installation directory: {install_dir}");

    // Path to conda directory
    let conda_dir = Path::new(install_dir).join("conda");

    // Determine the conda executable path
    let conda_exe = if env_sys.consts_os() == "windows" {
        conda_dir.join("Scripts").join("conda.exe")
    } else {
        conda_dir.join("bin").join("conda")
    };

    if !fs.exists(&conda_exe) {
        return Err(format!(
            "Conda executable not found at: {}",
            conda_exe.display()
        ));
    } // Check if environment already exists and remove it if it does
    let env_path = conda_dir.join("envs").join(&name);
    if fs.exists(&env_path) {
        log::debug!("Environment '{name}' already exists, removing it first");

        let mut remove_command = env_sys.new_conda_command(&conda_exe, &conda_dir);
        remove_command.args(["env", "remove", "-n", &name, "-y"]);

        let (status, stdout_lines, stderr_lines) =
            run_command_with_logging(remove_command, &process_id, &app_handle)
                .map_err(|e| format!("Failed to remove existing environment: {e}"))?;

        if !status.success() {
            let stderr = stderr_lines.join("\n");
            let stdout = stdout_lines.join("\n");
            log::error!(
                "Failed to remove existing environment '{}': Exit code: {}",
                name,
                status
            );
            log::error!("STDOUT: {stdout}");
            log::error!("STDERR: {stderr}");

            return Err(format!(
                "Failed to remove existing environment '{}': Exit code: {}\nStdout: {}\nStderr: {}",
                name, status, stdout, stderr
            ));
        }
        log::debug!("Successfully removed existing environment '{name}'");
    }

    // Parse extensions into conda and pip packages
    let mut conda_packages = Vec::new();
    let mut pip_packages = Vec::new();
    let mut conda_channels_map: HashMap<String, Vec<String>> = HashMap::new();

    // Add default channels
    conda_channels_map.insert("defaults".to_string(), Vec::new());
    conda_channels_map.insert("conda-forge".to_string(), Vec::new());

    // Process extensions into their respective categories
    for ext in &all_extensions {
        if let Some(stripped) = ext.strip_prefix("conda:") {
            // Check if it includes channel information
            if let Some(second_colon) = stripped.find(':') {
                let channel = &stripped[..second_colon];
                let package = &stripped[(second_colon + 1)..];

                conda_packages.push(package.to_string());

                // Add channel and associate package with it
                conda_channels_map
                    .entry(channel.to_string())
                    .or_default()
                    .push(package.to_string());
            } else {
                // Default to conda-forge if no channel specified
                conda_packages.push(stripped.to_string());

                // Add to conda-forge channel
                conda_channels_map
                    .entry("conda-forge".to_string())
                    .or_default()
                    .push(stripped.to_string());
            }
        } else if ext.to_lowercase() != "openbb" {
            // Skip OpenBB here - we'll handle it separately
            pip_packages.push(ext.clone());
        }
    }

    // Ensure pip is in conda packages if we have pip packages
    if !pip_packages.is_empty() && !conda_packages.contains(&"pip".to_string()) {
        conda_packages.push("pip".to_string());
    } // First create environment with just Python
    log::debug!("Creating conda environment '{name}' with Python {python_version}");
    let mut create_command = env_sys.new_conda_command(&conda_exe, &conda_dir);
    create_command.args([
        "create",
        "-n",
        &name,
        &format!("python={python_version}"),
        "-y",
    ]);

    let (status, stdout_lines, stderr_lines) =
        run_command_with_logging(create_command, &process_id, &app_handle)
            .map_err(|e| format!("Failed to create environment: {e}"))?;

    if !status.success() {
        let stderr = stderr_lines.join("\n");
        let stdout = stdout_lines.join("\n");
        log::error!(
            "Failed to create environment '{}': Exit code: {}",
            name,
            status
        );
        log::error!("STDOUT: {stdout}");
        log::error!("STDERR: {stderr}");

        return Err(format!(
            "Failed to create environment '{}': Exit code: {}\nStdout: {}\nStderr: {}",
            name, status, stdout, stderr
        ));
    }
    log::debug!("Successfully created base environment '{name}'");

    use regex::Regex;
    let re_conda_unsatisfiable = Regex::new(r"UnsatisfiableError: The following specifications were found to be incompatible with the existing environment:\s*\n\s*-\s*(\S+)").unwrap();
    let re_conda_not_found = Regex::new(r"PackagesNotFoundError: The following packages are not available from current channels:\s*\n\s*-\s*(\S+)").unwrap();
    let re_pip_no_dist = Regex::new(r"No matching distribution found for ([\w-]+)").unwrap();

    loop {
        // Generate YAML file for the environment
        let yaml_path = save_environment_as_yaml_impl(
            &name,
            &python_version,
            &conda_packages,
            &pip_packages,
            &conda_channels_map,
            install_dir,
            fs,
            env_sys,
        )
        .await?;

        // Update environment from YAML
        log::debug!("Updating environment from YAML: {}", yaml_path.display());
        let mut update_command = env_sys.new_conda_command(&conda_exe, &conda_dir);
        update_command.args([
            "env",
            "update",
            "-n",
            &name,
            "-f",
            &yaml_path.to_string_lossy(),
            "--prune",
        ]);

        let (status, stdout_lines, stderr_lines) =
            run_command_with_logging(update_command, &process_id, &app_handle)
                .map_err(|e| format!("Failed to update environment: {e}"))?;

        if status.success() {
            log::debug!("Successfully updated environment '{name}' from YAML");
            break; // Success, exit loop
        }

        let stderr = stderr_lines.join("\n");
        let stdout = stdout_lines.join("\n");
        log::warn!(
            "Failed to update environment from YAML: Exit code: {}",
            status
        );
        log::warn!("STDOUT: {stdout}");
        log::warn!("STDERR: {stderr}");

        let failing_package = if let Some(caps) = re_conda_unsatisfiable.captures(&stderr) {
            caps.get(1).map(|m| m.as_str().to_string())
        } else if let Some(caps) = re_conda_not_found.captures(&stderr) {
            caps.get(1).map(|m| m.as_str().to_string())
        } else if let Some(caps) = re_pip_no_dist.captures(&stderr) {
            caps.get(1).map(|m| m.as_str().to_string())
        } else {
            None
        };

        if let Some(pkg_spec) = failing_package {
            // The package spec might have version info, like "numpy==1.2.3" or "numpy>=1.2".
            // We need to get the base package name.
            let pkg_name = pkg_spec.split(['=', '<', '>']).next().unwrap_or("").trim();

            if pkg_name.is_empty() {
                // Could not parse package name, abort
                return Err(format!(
                    "Failed to update environment from YAML and could not parse failing package name from: {pkg_spec}\nStdout: {stdout}\nStderr: {stderr}"
                ));
            }

            log::warn!("Found failing package: {pkg_name}. Removing it and retrying.");

            // Remove from conda and pip packages list
            let before_len = conda_packages.len() + pip_packages.len();
            conda_packages.retain(|p| !p.starts_with(pkg_name));
            pip_packages.retain(|p| !p.starts_with(pkg_name));
            let after_len = conda_packages.len() + pip_packages.len();

            if after_len == before_len {
                // We removed nothing, which means we'll loop forever. Abort.
                log::error!(
                    "Could not find package '{pkg_name}' in package lists to remove it. Aborting."
                );
                return Err(format!(
                    "Failed to update environment from YAML: Exit code: {}\nStdout: {}\nStderr: {}",
                    status, stdout, stderr
                ));
            }
            // Continue to next iteration of the loop
        } else {
            // Could not identify a specific failing package, so we fail for real.
            log::error!(
                "Failed to update environment and could not identify a specific failing package to remove."
            );
            return Err(format!(
                "Failed to update environment from YAML: Exit code: {}\nStdout: {}\nStderr: {}",
                status, stdout, stderr
            ));
        }
    }

    save_environment_as_yaml_impl(
        &name,
        &python_version,
        &conda_packages,
        &pip_packages,
        &conda_channels_map,
        install_dir,
        fs,
        env_sys,
    )
    .await?;

    Ok(true)
}

#[tauri::command]
pub async fn create_environment(
    name: String,
    python_version: String,
    extensions: Vec<String>,
    process_id: String,
    app_handle: tauri::AppHandle,
) -> Result<bool, String> {
    create_environment_impl(
        name,
        python_version,
        extensions,
        process_id,
        Some(app_handle),
        &RealFileSystem,
        &RealEnvSystem,
    )
    .await
}

pub async fn create_environment_from_requirements_impl<F: FileSystem, E: EnvSystem>(
    name: String,
    file_path: String,
    directory: String,
    process_id: String,
    app_handle: Option<tauri::AppHandle>,
    fs: &F,
    env_sys: &E,
) -> Result<bool, String> {
    use regex::Regex;
    use std::collections::HashMap;
    use std::path::Path;
    use toml::Value;

    log::debug!("Creating environment '{name}' from requirements file: {file_path}");

    // Verify the file exists
    let file_path = Path::new(&file_path);
    if !fs.exists(file_path) {
        return Err(format!(
            "Requirements file not found: {}",
            file_path.display()
        ));
    }

    // Determine the project directory (parent directory of the file)
    let project_dir = file_path
        .parent()
        .ok_or_else(|| "Could not determine project directory".to_string())?;

    // Determine file type
    let file_extension = file_path
        .extension()
        .and_then(|ext| ext.to_str())
        .unwrap_or("")
        .to_lowercase();

    let file_name = file_path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("")
        .to_string();

    let is_requirements = file_name == "requirements.txt" || file_extension == "txt";
    let is_pyproject = file_name == "pyproject.toml" || file_extension == "toml";
    let is_yaml = file_extension == "yaml" || file_extension == "yml";

    if !is_requirements && !is_pyproject && !is_yaml {
        return Err(format!(
            "Unsupported file type: {file_name}. Only requirements.txt, pyproject.toml, or YAML files are supported"
        ));
    }

    // Read the file content
    let file_content = fs
        .read_to_string(file_path)
        .map_err(|e| format!("Failed to read requirements file: {e}"))?;

    // Extract Python version and packages
    let mut python_version = String::new();
    let mut pip_packages: Vec<String> = Vec::new();
    let mut conda_packages: Vec<String> = Vec::new();
    let mut conda_channels: Vec<String> = vec!["defaults".to_string(), "conda-forge".to_string()];

    // Determine if this is a proper Python project that should be installed in development mode
    let mut is_installable_project = false;
    let mut project_name = String::new();
    let mut has_packages_definition = false;

    if is_pyproject {
        // Parse pyproject.toml
        match toml::from_str::<Value>(&file_content) {
            Ok(toml_value) => {
                // Check if it has package definitions in any format
                // First check PEP 621 format
                if let Some(project) = toml_value.get("project") {
                    // Check for project name
                    if let Some(name_val) = project.get("name")
                        && let Some(name_str) = name_val.as_str()
                    {
                        is_installable_project = true;
                        project_name = name_str.to_string();
                    }

                    // Extract Python version from project.requires-python
                    if let Some(requires_python) = project.get("requires-python")
                        && let Some(version_str) = requires_python.as_str()
                    {
                        // Extract version from constraints like ">=3.8,<3.11"
                        let re = Regex::new(r"([>=<~!]*)([0-9]+\.[0-9]+)").unwrap();
                        if let Some(captures) = re.captures(version_str)
                            && let Some(version_match) = captures.get(2)
                        {
                            python_version = version_match.as_str().to_string();
                        }
                    }

                    // Check for packages definition (key indicator for development install)
                    if let Some(packages) = project.get("packages")
                        && let Some(packages_array) = packages.as_array()
                        && !packages_array.is_empty()
                    {
                        has_packages_definition = true;
                        is_installable_project = true;

                        for pkg in packages_array {
                            if let Some(pkg_obj) = pkg.as_table()
                                && let Some(include) =
                                    pkg_obj.get("include").and_then(|i| i.as_str())
                            {
                                log::debug!("Found package module: {include}");
                            }
                        }
                    }

                    // Extract dependencies with version constraints
                    if let Some(dependencies) = project.get("dependencies")
                        && let Some(deps_array) = dependencies.as_array()
                    {
                        for dep in deps_array {
                            if let Some(dep_str) = dep.as_str() {
                                // Remove any environment markers but preserve version constraints
                                if let Some(pos) = dep_str.find(';') {
                                    let package_spec = dep_str[..pos].trim().to_string();
                                    pip_packages.push(package_spec);
                                } else {
                                    pip_packages.push(dep_str.to_string());
                                }
                            }
                        }
                    }
                }

                // Check Poetry format
                if let Some(tool) = toml_value.get("tool")
                    && let Some(poetry) = tool.get("poetry")
                {
                    // Check for project name
                    if let Some(name_val) = poetry.get("name")
                        && let Some(name_str) = name_val.as_str()
                    {
                        is_installable_project = true;
                        project_name = name_str.to_string();
                    }

                    // Check for packages definition in poetry format
                    if let Some(packages) = poetry.get("packages")
                        && let Some(packages_array) = packages.as_array()
                        && !packages_array.is_empty()
                    {
                        has_packages_definition = true;
                        is_installable_project = true;

                        for pkg in packages_array {
                            if let Some(pkg_obj) = pkg.as_table()
                                && let Some(include) =
                                    pkg_obj.get("include").and_then(|i| i.as_str())
                            {
                                log::debug!("Found Poetry package module: {include}");
                            }
                        }
                    }

                    // Extract dependencies
                    if let Some(dependencies) = poetry.get("dependencies")
                        && let Some(deps_table) = dependencies.as_table()
                    {
                        let re = Regex::new(r"^\s*([~=><^]+)").unwrap();
                        let py_re = Regex::new(r"([>=<~!]*)([0-9]+\.[0-9]+)").unwrap();
                        for (key, value) in deps_table {
                            if key != "python" {
                                match value {
                                    Value::String(version) => {
                                        // Format as package==version or package>=version etc.
                                        if version.trim() == "*" {
                                            pip_packages.push(key.clone());
                                        } else {
                                            // Extract the operator (==, >=, <=, etc.)
                                            let version_str =
                                                if let Some(captures) = re.captures(version) {
                                                    if let Some(operator) = captures.get(1) {
                                                        let op = operator.as_str();
                                                        let version_value =
                                                            version.trim_start_matches(op).trim();

                                                        // Handle caret notation (^) - compatible with version
                                                        if op.contains("^") {
                                                            // Parse the version to get the components
                                                            let components: Vec<&str> =
                                                                version_value.split('.').collect();
                                                            if components.len() >= 2 {
                                                                // For ^1.2.3, use >=1.2.3,<2.0.0
                                                                let major = components[0]
                                                                    .parse::<u32>()
                                                                    .unwrap_or(0);
                                                                format!(
                                                                    "{}>={},<{}.0.0",
                                                                    key,
                                                                    version_value,
                                                                    major + 1
                                                                )
                                                            } else {
                                                                // Fallback if version doesn't have enough components
                                                                format!("{key}>={version_value}")
                                                            }
                                                        }
                                                        // Handle tilde notation (~) - approximately equivalent to version
                                                        else if op.contains("~") {
                                                            // Parse the version to get the components
                                                            let components: Vec<&str> =
                                                                version_value.split('.').collect();
                                                            if components.len() >= 2 {
                                                                // For ~1.2.3, use >=1.2.3,<1.3.0
                                                                let major = components[0]
                                                                    .parse::<u32>()
                                                                    .unwrap_or(0);
                                                                let minor = components[1]
                                                                    .parse::<u32>()
                                                                    .unwrap_or(0);
                                                                format!(
                                                                    "{}>={},<{}.{}.0",
                                                                    key,
                                                                    version_value,
                                                                    major,
                                                                    minor + 1
                                                                )
                                                            } else {
                                                                // Fallback if version doesn't have enough components
                                                                format!("{key}>={version_value}")
                                                            }
                                                        }
                                                        // Standard comparison operators
                                                        else {
                                                            format!("{key}{op}{version_value}")
                                                        }
                                                    } else {
                                                        format!("{}=={}", key, version.trim())
                                                    }
                                                } else {
                                                    format!("{}=={}", key, version.trim())
                                                };
                                            pip_packages.push(version_str);
                                        }
                                    }
                                    Value::Table(version_table) => {
                                        // Handle complex version specs
                                        if let Some(version_str) =
                                            version_table.get("version").and_then(|v| v.as_str())
                                        {
                                            let version_spec = if let Some(captures) =
                                                re.captures(version_str)
                                            {
                                                if let Some(operator) = captures.get(1) {
                                                    let op = operator.as_str();
                                                    let version_value =
                                                        version_str.trim_start_matches(op).trim();

                                                    // Handle caret notation (^)
                                                    if op.contains("^") {
                                                        let components: Vec<&str> =
                                                            version_value.split('.').collect();
                                                        if components.len() >= 2 {
                                                            let major = components[0]
                                                                .parse::<u32>()
                                                                .unwrap_or(0);
                                                            format!(
                                                                "{}>={},<{}.0.0",
                                                                key,
                                                                version_value,
                                                                major + 1
                                                            )
                                                        } else {
                                                            format!("{key}>={version_value}")
                                                        }
                                                    }
                                                    // Handle tilde notation (~)
                                                    else if op.contains("~") {
                                                        let components: Vec<&str> =
                                                            version_value.split('.').collect();
                                                        if components.len() >= 2 {
                                                            let major = components[0]
                                                                .parse::<u32>()
                                                                .unwrap_or(0);
                                                            let minor = components[1]
                                                                .parse::<u32>()
                                                                .unwrap_or(0);
                                                            format!(
                                                                "{}>={},<{}.{}.0",
                                                                key,
                                                                version_value,
                                                                major,
                                                                minor + 1
                                                            )
                                                        } else {
                                                            format!("{key}>={version_value}")
                                                        }
                                                    }
                                                    // Standard comparison operators
                                                    else {
                                                        format!("{key}{op}{version_value}")
                                                    }
                                                } else {
                                                    format!("{}=={}", key, version_str.trim())
                                                }
                                            } else {
                                                format!("{}=={}", key, version_str.trim())
                                            };
                                            pip_packages.push(version_spec);
                                        }
                                    }
                                    _ => {
                                        // For other types, just use the package name
                                        pip_packages.push(key.clone());
                                    }
                                }
                            } else if let Some(python_value) =
                                deps_table.get("python").and_then(|v| v.as_str())
                            {
                                // Extract version from constraints like ">=3.8,<3.11"
                                if let Some(captures) = py_re.captures(python_value)
                                    && let Some(version_match) = captures.get(2)
                                {
                                    python_version = version_match.as_str().to_string();
                                }
                            }
                        }
                    }
                }

                // Check for setup.py as an alternative indicator
                if !is_installable_project && fs.exists(&project_dir.join("setup.py")) {
                    is_installable_project = true;
                    log::debug!(
                        "Found setup.py in project directory, will install in development mode"
                    );
                }

                // Look for src or package directories as another indicator
                if !is_installable_project {
                    if fs.exists(&project_dir.join("src")) && fs.is_dir(&project_dir.join("src")) {
                        is_installable_project = true;
                        log::debug!("Found src directory, assuming this is a Python project");
                    }

                    // Check for any Python files in the root directory
                    if let Ok(entries) = fs.read_dir(project_dir) {
                        for path in entries {
                            if let Some(ext) = path.extension()
                                && ext == "py"
                                && path.file_name() != Some(std::ffi::OsStr::new("setup.py"))
                            {
                                is_installable_project = true;
                                log::debug!("Found Python files in project directory");
                                break;
                            }
                        }
                    }
                }
            }
            Err(e) => return Err(format!("Failed to parse pyproject.toml: {e}")),
        }
    } else if is_requirements {
        // Parse requirements.txt
        let re = Regex::new(r"python\s*([>=<~!]*)([0-9]+\.[0-9]+(\.[0-9]+)?)").unwrap();
        let name_re = Regex::new(r#"name\s*=\s*['"]([^'"]+)['"]"#).unwrap();
        for line in file_content.lines() {
            let trimmed_line = line.trim();
            if trimmed_line.is_empty() || trimmed_line.starts_with('#') {
                continue;
            }

            // Check for Python version specification
            if trimmed_line.starts_with("python") || trimmed_line.starts_with("Python") {
                // Try to extract version with regex
                if let Some(captures) = re.captures(trimmed_line)
                    && let Some(version_match) = captures.get(2)
                {
                    let version = version_match.as_str();

                    // Take only major.minor part if full version provided
                    let version_parts: Vec<&str> = version.split('.').collect();
                    if version_parts.len() >= 2 {
                        python_version = format!("{}.{}", version_parts[0], version_parts[1]);
                    } else {
                        python_version = version.to_string();
                    }
                }
            } else {
                // Keep the entire package spec including version constraints
                // But remove any environment markers (after semicolon)
                if let Some(pos) = trimmed_line.find(';') {
                    let package_spec = trimmed_line[..pos].trim().to_string();
                    pip_packages.push(package_spec);
                } else {
                    pip_packages.push(trimmed_line.to_string());
                }
            }
        }

        // Check if this is possibly a Python project with a setup.py or pyproject.toml in the same directory
        if fs.exists(&project_dir.join("setup.py"))
            || fs.exists(&project_dir.join("pyproject.toml"))
        {
            is_installable_project = true;

            // Try to determine project name from setup.py if it exists
            if fs.exists(&project_dir.join("setup.py"))
                && let Ok(setup_content) = fs.read_to_string(&project_dir.join("setup.py"))
                && let Some(captures) = name_re.captures(&setup_content)
                && let Some(name_match) = captures.get(1)
            {
                project_name = name_match.as_str().to_string();
            }

            // Try to determine project name from pyproject.toml if exists
            if project_name.is_empty()
                && fs.exists(&project_dir.join("pyproject.toml"))
                && let Ok(pyproject_content) =
                    fs.read_to_string(&project_dir.join("pyproject.toml"))
                && let Ok(toml_value) = toml::from_str::<Value>(&pyproject_content)
            {
                // Check PEP 621 format
                if let Some(name) = toml_value
                    .get("project")
                    .and_then(|p| p.get("name"))
                    .and_then(|n| n.as_str())
                {
                    project_name = name.to_string();
                }
                // Check Poetry format
                else if let Some(name) = toml_value
                    .get("tool")
                    .and_then(|t| t.get("poetry"))
                    .and_then(|p| p.get("name"))
                    .and_then(|n| n.as_str())
                {
                    project_name = name.to_string();
                }

                // Check for packages definition which indicates development install
                if let Some(packages) = toml_value.get("project").and_then(|p| p.get("packages"))
                    && let Some(packages_array) = packages.as_array()
                    && !packages_array.is_empty()
                {
                    has_packages_definition = true;
                }

                if let Some(tool) = toml_value.get("tool")
                    && let Some(poetry) = tool.get("poetry")
                    && let Some(packages) = poetry.get("packages")
                    && let Some(packages_array) = packages.as_array()
                    && !packages_array.is_empty()
                {
                    has_packages_definition = true;
                }
            }
        }
    } else if is_yaml {
        let re = Regex::new(r"python[= ]([0-9]+\.[0-9]+)").unwrap();
        // Parse YAML file (conda env file format)
        match serde_yaml::from_str::<serde_yaml::Value>(&file_content) {
            Ok(yaml_value) => {
                // Extract channels
                if let Some(channels_val) = yaml_value.get("channels")
                    && let Some(channels_array) = channels_val.as_sequence()
                {
                    conda_channels.clear(); // Remove defaults if specified in the file
                    for channel in channels_array {
                        if let Some(channel_str) = channel.as_str() {
                            conda_channels.push(channel_str.to_string());
                        }
                    }
                }

                // Extract dependencies
                if let Some(deps_val) = yaml_value.get("dependencies")
                    && let Some(deps_array) = deps_val.as_sequence()
                {
                    for dep in deps_array {
                        if let Some(dep_str) = dep.as_str() {
                            // Check if it's Python spec
                            if dep_str.starts_with("python=") || dep_str.starts_with("python ") {
                                // Extract Python version
                                if let Some(captures) = re.captures(dep_str)
                                    && let Some(version_match) = captures.get(1)
                                {
                                    python_version = version_match.as_str().to_string();
                                }
                            } else if dep_str != "pip" {
                                // Add as conda package
                                conda_packages.push(dep_str.to_string());
                            }
                        } else if let Some(dep_map) = dep.as_mapping() {
                            // Check if it's pip dependencies
                            if let Some(pip_key) =
                                dep_map.get(serde_yaml::Value::String("pip".to_string()))
                                && let Some(pip_deps) = pip_key.as_sequence()
                            {
                                for pip_dep in pip_deps {
                                    if let Some(pip_dep_str) = pip_dep.as_str() {
                                        pip_packages.push(pip_dep_str.to_string());
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Err(e) => return Err(format!("Failed to parse YAML file: {e}")),
        }
    }

    // If no Python version specified, default to 3.12
    if python_version.is_empty() {
        python_version = "3.12".to_string();
        log::debug!("No Python version found in file, defaulting to {python_version}");
    } else {
        log::debug!("Detected Python version: {python_version}");
    }

    // Validate Python version is between 3.11 and 3.14 inclusive
    let python_major_minor: Vec<&str> = python_version.split('.').collect();
    if python_major_minor.len() >= 2 {
        let major: i32 = python_major_minor[0].parse().unwrap_or(3);
        let minor: i32 = python_major_minor[1].parse().unwrap_or(11);

        if major != 3 || !(11..=14).contains(&minor) {
            log::debug!("Python version {python_version} not supported. Using Python 3.12 instead");
            python_version = "3.12".to_string();
        }
    } else {
        log::debug!("Invalid Python version format: {python_version}. Using Python 3.12 instead");
        python_version = "3.12".to_string();
    }

    // Report if we found an installable project
    if is_installable_project {
        log::debug!(
            "Detected Python project: {}",
            if !project_name.is_empty() {
                &project_name
            } else {
                "unnamed project"
            }
        );
        if has_packages_definition {
            log::debug!("Found packages definition, will install in development mode");
        }
        log::debug!("Project directory: {}", project_dir.display());
    }

    // Ensure pip is in conda packages if we have pip packages
    if !pip_packages.is_empty() && !conda_packages.contains(&"pip".to_string()) {
        conda_packages.push("pip".to_string());
    }

    log::debug!(
        "Creating environment with Python {} and {} packages ({} conda, {} pip)",
        python_version,
        pip_packages.len() + conda_packages.len(),
        conda_packages.len(),
        pip_packages.len()
    );

    // Setup conda channels map for save_environment_as_yaml
    let mut conda_channels_map = HashMap::new();
    for channel in conda_channels {
        conda_channels_map.insert(channel, Vec::new());
    }

    let conda_dir = Path::new(&directory).join("conda");
    let conda_exe = if env_sys.consts_os() == "windows" {
        conda_dir.join("Scripts").join("conda.exe")
    } else {
        conda_dir.join("bin").join("conda")
    };

    if is_pyproject {
        let log_storage = get_log_storage();
        register_process(&log_storage, &process_id);

        // For TOML files, create a single script to create the environment and install dependencies
        let temp_dir = env_sys.temp_dir();
        let requirements_path = temp_dir.join(format!("reqs_{name}.txt"));
        let requirements_content = pip_packages.join("\n");
        fs.write(&requirements_path, &requirements_content)
            .map_err(|e| format!("Failed to write temporary requirements.txt: {e}"))?;

        let script_ext = if env_sys.consts_os() == "windows" {
            "bat"
        } else {
            "sh"
        };
        let script_path = temp_dir.join(format!("create_and_install_{name}.{script_ext}"));
        let script_content = if env_sys.consts_os() == "windows" {
            format!(
                r#"@echo off
setlocal
set "CONDA_ROOT={}"
set "CONDA_ENVS_PATH={}"
set "CONDA_PKGS_DIRS={}"
set "CONDARC={}"
set CONDA_DEFAULT_ENV=
set CONDA_PREFIX=
set CONDA_SHLVL=
set "PATH={};{};%PATH%"
echo "Removing existing environment (if any)..."
call "{}" env remove -n {} -y
echo "Creating environment..."
call "{}" create -n {} python={} pip -y
if errorlevel 1 exit /b 1
echo "Activating environment..."
call "{}" activate {}
if errorlevel 1 exit /b 1
echo "Installing packages..."
pip install -r "{}"
"#,
                conda_dir.to_string_lossy(),
                conda_dir.join("envs").to_string_lossy(),
                conda_dir.join("pkgs").to_string_lossy(),
                conda_dir.join(".condarc").to_string_lossy(),
                conda_dir.join("Scripts").to_string_lossy(),
                conda_dir.join("condabin").to_string_lossy(),
                conda_exe.to_string_lossy(),
                name,
                conda_exe.to_string_lossy(),
                name,
                python_version,
                conda_exe.to_string_lossy(),
                name,
                requirements_path.to_string_lossy()
            )
        } else {
            format!(
                r#"#!/bin/bash
export CONDA_ROOT="{}"
export CONDA_ENVS_PATH="{}"
export CONDA_PKGS_DIRS="{}"
export CONDARC="{}"
unset CONDA_DEFAULT_ENV
unset CONDA_PREFIX
unset CONDA_SHLVL
export PATH="{}:{}:$PATH"
echo "Removing existing environment (if any)..."
"{}" env remove -n {} -y
echo "Creating environment..."
"{}" create -n {} python={} pip -y
echo "Activating environment..."
source "{}" {}
echo "Installing packages..."
pip install -r "{}"
"#,
                conda_dir.to_string_lossy(),
                conda_dir.join("envs").to_string_lossy(),
                conda_dir.join("pkgs").to_string_lossy(),
                conda_dir.join(".condarc").to_string_lossy(),
                conda_dir.join("bin").to_string_lossy(),
                conda_dir.join("condabin").to_string_lossy(),
                conda_exe.to_string_lossy(),
                name,
                conda_exe.to_string_lossy(),
                name,
                python_version,
                conda_dir.join("bin").join("activate").to_string_lossy(),
                name,
                requirements_path.to_string_lossy()
            )
        };

        fs.write(&script_path, &script_content)
            .map_err(|e| format!("Failed to create installation script: {e}"))?;

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mut perms = fs
                .metadata(&script_path)
                .map_err(|e| format!("Failed to get script permissions: {e}"))?
                .permissions();
            perms.set_mode(0o755);
            fs.set_permissions(&script_path, perms)
                .map_err(|e| format!("Failed to set script permissions: {e}"))?;
        }

        let shell = if env_sys.consts_os() == "windows" {
            "cmd.exe"
        } else {
            "bash"
        };
        let shell_arg = if env_sys.consts_os() == "windows" {
            "/c"
        } else {
            "-c"
        };
        let mut command = env_sys.new_command(shell);
        command.arg(shell_arg).arg(&script_path);

        let (status, _, _) = run_command_with_logging(command, &process_id, &app_handle)
            .map_err(|e| format!("Failed to spawn installation process: {e}"))?;

        let _ = fs.remove_file(&requirements_path.to_string_lossy());
        let _ = fs.remove_file(&script_path.to_string_lossy());

        if !status.success() {
            return Err(format!(
                "Failed to create environment and install packages: Exit code: {}",
                status
            ));
        }
    } else {
        // For other file types, use the existing YAML-based creation method
        let env_path = conda_dir.join("envs").join(&name);
        if fs.exists(&env_path) {
            log::debug!("Environment '{name}' already exists, removing it first");

            let mut remove_command = env_sys.new_conda_command(&conda_exe, &conda_dir);
            let remove_output = remove_command
                .args(["env", "remove", "-n", &name, "-y"])
                .output()
                .map_err(|e| format!("Failed to remove existing environment: {e}"))?;

            if !remove_output.status.success() {
                log::warn!(
                    "'conda env remove' failed for '{name}', attempting forceful directory removal."
                );
                if let Err(e) = fs.remove_dir_all(std::path::Path::new(&env_path)) {
                    let stderr = String::from_utf8_lossy(&remove_output.stderr);
                    return Err(format!(
                        "Failed to remove environment '{name}' with conda (Stderr: {stderr}) and failed to forcefully remove directory (Error: {e})"
                    ));
                }
            }
        }
        let yaml_path = save_environment_as_yaml_impl(
            &name,
            &python_version,
            &conda_packages,
            &pip_packages,
            &conda_channels_map,
            &directory,
            fs,
            env_sys,
        )
        .await?;

        log::debug!(
            "Created environment specification at: {}",
            yaml_path.display()
        );

        log::debug!("Creating conda environment from YAML...");
        let mut env_create_command = env_sys.new_conda_command(&conda_exe, &conda_dir);

        let log_storage = get_log_storage();
        register_process(&log_storage, &process_id);

        env_create_command.args(["env", "create", "-f", &yaml_path.to_string_lossy(), "-y"]);

        let (status, _, _) = run_command_with_logging(env_create_command, &process_id, &app_handle)
            .map_err(|e| format!("Failed to spawn conda process: {e}"))?;

        if !status.success() {
            return Err(format!(
                "Failed to create environment from YAML: Exit code: {}",
                status
            ));
        }
    }

    log::debug!("Environment '{name}' created successfully");

    // If this is an installable Python project, install it in development mode
    if is_installable_project {
        log::debug!("Installing Python project in development mode");

        // Create a script to install the project in development mode
        let script_ext = if env_sys.consts_os() == "windows" {
            "bat"
        } else {
            "sh"
        };
        let dev_script_path = env_sys
            .temp_dir()
            .join(format!("install_project_dev.{script_ext}"));
        let dev_script_content = if env_sys.consts_os() == "windows" {
            format!(
                r#"@echo off
setlocal
set "CONDA_ROOT={}"
set "CONDA_ENVS_PATH={}"
set "CONDA_PKGS_DIRS={}"
set "CONDARC={}"
set CONDA_DEFAULT_ENV=
set CONDA_PREFIX=
set CONDA_SHLVL=
set "PATH={};{};%PATH%"
call "{}" activate {}
if errorlevel 1 exit /b 1
cd /d "{}"
pip install -e .
"#,
                conda_dir.to_string_lossy(),
                conda_dir.join("envs").to_string_lossy(),
                conda_dir.join("pkgs").to_string_lossy(),
                conda_dir.join(".condarc").to_string_lossy(),
                conda_dir.join("Scripts").to_string_lossy(),
                conda_dir.join("condabin").to_string_lossy(),
                conda_dir
                    .join("Scripts")
                    .join("conda.exe")
                    .to_string_lossy(),
                name,
                project_dir.to_string_lossy().replace("\\", "\\\\") // Escape backslashes for Windows
            )
        } else {
            format!(
                r#"#!/bin/bash
export CONDA_ROOT="{}"
export CONDA_ENVS_PATH="{}"
export CONDA_PKGS_DIRS="{}"
export CONDARC="{}"
unset CONDA_DEFAULT_ENV
unset CONDA_PREFIX
unset CONDA_SHLVL
export PATH="{}:{}:$PATH"
source "{}" {}
cd "{}"
pip install -e .
"#,
                conda_dir.to_string_lossy(),
                conda_dir.join("envs").to_string_lossy(),
                conda_dir.join("pkgs").to_string_lossy(),
                conda_dir.join(".condarc").to_string_lossy(),
                conda_dir.join("bin").to_string_lossy(),
                conda_dir.join("condabin").to_string_lossy(),
                conda_dir.join("bin").join("activate").to_string_lossy(),
                name,
                project_dir.to_string_lossy()
            )
        };
        let shell = if env_sys.consts_os() == "windows" {
            "cmd.exe"
        } else {
            "bash"
        };
        let shell_arg = if env_sys.consts_os() == "windows" {
            "/c"
        } else {
            "-c"
        }; // Write the script to a temporary file
        fs.write(&dev_script_path, &dev_script_content)
            .map_err(|e| format!("Failed to create project installation script: {e}"))?;

        // Make the script executable on Unix
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mut perms = fs
                .metadata(&dev_script_path)
                .map_err(|e| format!("Failed to get script permissions: {e}"))?
                .permissions();
            perms.set_mode(0o755);
            fs.set_permissions(&dev_script_path, perms)
                .map_err(|e| format!("Failed to set script permissions: {e}"))?;
        }

        // Execute the script
        let dev_output = env_sys
            .new_command(shell)
            .arg(shell_arg)
            .arg(&dev_script_path)
            .output()
            .map_err(|e| format!("Failed to execute project installation script: {e}"))?;

        // Clean up the temporary script
        let _ = fs.remove_file(&dev_script_path.to_string_lossy());

        // Report the result
        if dev_output.status.success() {
            log::debug!("Successfully installed project in development mode");
        } else {
            let stderr = String::from_utf8_lossy(&dev_output.stderr);
            let stdout = String::from_utf8_lossy(&dev_output.stdout);

            log::debug!(
                "Warning: Failed to install project in development mode: \nStdout: {stdout}\nStderr: {stderr}"
            );
        }
    }

    // Save the final YAML file for reference, especially for the TOML flow
    save_environment_as_yaml_impl(
        &name,
        &python_version,
        &conda_packages,
        &pip_packages,
        &conda_channels_map,
        &directory,
        fs,
        env_sys,
    )
    .await?;

    log::debug!("Environment creation completed successfully");
    Ok(true)
}

#[tauri::command]
pub async fn create_environment_from_requirements(
    name: String,
    file_path: String,
    directory: String,
    process_id: String,
    app_handle: tauri::AppHandle,
) -> Result<bool, String> {
    create_environment_from_requirements_impl(
        name,
        file_path,
        directory,
        process_id,
        Some(app_handle),
        &RealFileSystem,
        &RealEnvSystem,
    )
    .await
}

pub async fn select_requirements_file_impl<E: EnvSystem>(env_sys: &E) -> Result<String, String> {
    // Get user's home directory as the default
    let home_dir = env_sys
        .var("HOME")
        .or_else(|_| env_sys.var("USERPROFILE"))
        .unwrap_or_else(|_| "/".to_string());

    #[cfg(target_os = "macos")]
    {
        // AppleScript to open file picker with file type filtering
        let script = format!(
            r#"
            try
                tell application "System Events"
                    activate
                    set defaultFolder to POSIX file "{}"
                    set fileTypes to {{"txt", "toml", "yml", "yaml"}}
                    set filePath to POSIX path of (choose file default location defaultFolder with prompt "Select Requirements File" of type fileTypes)
                    return filePath
                end tell
            on error errMsg number errNum
                if errNum is -128 then
                    -- User canceled, return empty string
                    return ""
                else
                    -- Real error, return the error message with a prefix so we can detect it
                    return "ERROR: " & errMsg
                end if
            end try
            "#,
            home_dir.replace("\"", "\\\"")
        );

        // Execute the AppleScript and get the output
        let output = env_sys
            .new_command("osascript")
            .args(["-e", &script])
            .output()
            .map_err(|e| format!("Failed to execute AppleScript: {e}"))?;

        let path = String::from_utf8(output.stdout)
            .map_err(|_| "Invalid UTF-8 in file path".to_string())?
            .trim()
            .to_string();

        // Check for error prefix
        if let Some(matched) = path.strip_prefix("ERROR: ") {
            return Err(matched.to_string());
        }

        // Empty string means user canceled
        if path.is_empty() {
            return Ok(path);
        }

        Ok(path)
    }

    #[cfg(target_os = "windows")]
    {
        // PowerShell script for file picker on Windows with better cancel handling
        let script = format!(
            r#"
            Add-Type -AssemblyName System.Windows.Forms
            $dialog = New-Object System.Windows.Forms.OpenFileDialog
            $dialog.InitialDirectory = "{}"
            $dialog.Filter = "Requirements Files|*.txt;*.toml;*.yml;*.yaml|All Files|*.*"
            $dialog.Title = "Select Requirements File"
            $dialog.Multiselect = $false
            if ($dialog.ShowDialog() -eq 'OK') {{
                $dialog.FileName
            }} else {{
                "" # Return empty string on cancel
            }}
            "#,
            home_dir.replace("\"", "`\"") // Escape quotes for PowerShell
        );

        let mut powershell_cmd = env_sys.new_command("powershell");
        #[cfg(windows)]
        {
            powershell_cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let output = powershell_cmd
            .args(["-Command", &script])
            .output()
            .map_err(|e| format!("Failed to execute PowerShell: {e}"))?;

        // Get the output regardless of status
        let path = String::from_utf8(output.stdout)
            .map_err(|_| "Invalid UTF-8 in file path".to_string())?
            .trim()
            .to_string();

        // If the path is empty, user canceled
        Ok(path)
    }

    #[cfg(target_os = "linux")]
    {
        // Try different dialog tools commonly found on Linux systems in order of preference

        // First try zenity (common on GNOME and many distros)
        // Zenity returns non-zero exit code on cancel, so we need to check specifically for that
        let zenity_result = env_sys
            .new_command("zenity")
            .args([
                "--file-selection",
                "--title=Select Requirements File",
                &format!("--filename={}/", home_dir),
                "--file-filter=*.txt *.toml *.yml *.yaml",
            ])
            .output();

        if let Ok(output) = zenity_result {
            if output.status.success() {
                // Success means a file was selected
                let path = String::from_utf8(output.stdout)
                    .map_err(|_| "Invalid UTF-8 in file path".to_string())?
                    .trim()
                    .to_string();

                if !path.is_empty() {
                    return Ok(path);
                }
            } else if output.status.code() == Some(1) {
                // Exit code 1 in zenity typically means user canceled
                return Ok(String::new());
            }
        }

        // Try kdialog (KDE)
        // KDialog also returns non-zero exit code on cancel
        let kdialog_result = env_sys
            .new_command("kdialog")
            .args([
                "--getopenfilename",
                &home_dir,
                "*.txt *.toml *.yml *.yaml|Requirements Files",
            ])
            .output();

        if let Ok(output) = kdialog_result {
            if output.status.success() {
                let path = String::from_utf8(output.stdout)
                    .map_err(|_| "Invalid UTF-8 in file path".to_string())?
                    .trim()
                    .to_string();

                if !path.is_empty() {
                    return Ok(path);
                }
            } else {
                // User likely canceled
                return Ok(String::new());
            }
        }

        // Try xdg-open for other desktop environments
        let xdg_result = env_sys
            .new_command("python3")
            .args([
                "-c",
                r#"
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
dialog = Gtk.FileChooserDialog(
    title="Select Requirements File",
    action=Gtk.FileChooserAction.OPEN
)
dialog.set_default_response(Gtk.ResponseType.OK)
dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)

filter_text = Gtk.FileFilter()
filter_text.set_name("Requirements Files")
filter_text.add_pattern("*.txt")
filter_text.add_pattern("*.toml")
filter_text.add_pattern("*.yml")
filter_text.add_pattern("*.yaml")
dialog.add_filter(filter_text)

response = dialog.run()
if response == Gtk.ResponseType.OK:
    print(dialog.get_filename())
dialog.destroy()
                "#,
            ])
            .output();

        if let Ok(output) = xdg_result {
            let path = String::from_utf8(output.stdout)
                .map_err(|_| "Invalid UTF-8 in file path".to_string())?
                .trim()
                .to_string();

            if !path.is_empty() {
                return Ok(path);
            } else {
                // Empty output means no file selected or canceled
                return Ok(String::new());
            }
        }

        // If all GUI methods fail, fall back to a simple text input dialog
        let dialog_result = env_sys
            .new_command("dialog")
            .args([
                "--stdout",
                "--title",
                "Select Requirements File",
                "--inputbox",
                "Enter path to requirements file:",
                "10",
                "60",
                "",
            ])
            .output();

        if let Ok(output) = dialog_result {
            if output.status.success() {
                let path = String::from_utf8(output.stdout)
                    .map_err(|_| "Invalid UTF-8 in file path".to_string())?
                    .trim()
                    .to_string();

                if !path.is_empty() {
                    return Ok(path);
                }
            }
            // Dialog also returns non-zero exit code on cancel
            return Ok(String::new());
        }

        // If we've exhausted all options, just return empty string rather than error
        // This avoids showing an error when user might have just canceled
        return Ok(String::new());
    }

    #[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
    {
        // For other platforms, just return an empty string since we don't support them
        return Ok(String::new());
    }
}

#[tauri::command]
pub async fn select_requirements_file() -> Result<String, String> {
    select_requirements_file_impl(&RealEnvSystem).await
}

#[tauri::command]
pub async fn list_conda_environments_impl<F: FileSystem, E: EnvSystem>(
    directory: Option<String>,
    fs: &F,
    env_sys: &E,
) -> Result<Vec<CondaEnvironment>, String> {
    use std::path::Path;

    // Get the directory - either from parameter or from system settings
    let conda_dir = if let Some(dir) = directory {
        Path::new(&dir).join("conda")
    } else {
        // Get from system settings if not provided
        let home_dir = env_sys
            .var("HOME")
            .or_else(|_| env_sys.var("USERPROFILE"))
            .map_err(|e| format!("Could not determine home directory: {e}"))?;

        let platform_dir = Path::new(&home_dir).join(".openbb_platform");
        let system_settings_path = platform_dir.join("system_settings.json");

        if !fs.exists(&system_settings_path) {
            return Err(
                "System settings file not found. Please complete installation first.".to_string(),
            );
        }

        // Read the system settings file
        let settings_content = fs
            .read_to_string(&system_settings_path)
            .map_err(|e| format!("Failed to read system settings: {e}"))?;

        let settings: serde_json::Value = serde_json::from_str(&settings_content)
            .map_err(|e| format!("Failed to parse system settings: {e}"))?;

        // First check install_settings.installation_directory
        let install_dir = if let Some(install_settings) = settings.get("install_settings") {
            if let Some(dir) = install_settings.get("installation_directory") {
                dir.as_str()
            } else {
                None
            }
        } else {
            None
        };

        // Then check installation_directory at root
        let install_dir = install_dir.or_else(|| {
            settings
                .get("installation_directory")
                .and_then(|dir| dir.as_str())
        });

        let install_dir = install_dir
            .ok_or_else(|| "Installation directory not found in system settings".to_string())?;

        Path::new(install_dir).join("conda")
    };

    if !fs.exists(&conda_dir) {
        return Err(format!(
            "Conda installation not found at: {}",
            conda_dir.display()
        ));
    }
    log::debug!("Looking for environments in: {}", conda_dir.display());

    let mut environments = Vec::new();

    // Check environments directory
    let envs_dir = conda_dir.join("envs");
    if !fs.exists(&envs_dir) {
        log::warn!(
            "Environments directory not found at: {}",
            envs_dir.display()
        );
        return Ok(environments); // Return just base if no envs directory
    }

    log::debug!("Scanning environments directory: {}", envs_dir.display());

    // Get a list of actual environment directory names
    let mut actual_env_names = Vec::new();

    // Scan environments directory
    match fs.read_dir(&envs_dir) {
        Ok(entries) => {
            for path in entries {
                if path.is_dir()
                    && let Some(file_name) = path.file_name()
                    && let Some(name_str) = file_name.to_str()
                {
                    let name = name_str.to_string();
                    if name.starts_with('.') || name.is_empty() {
                        continue;
                    }
                    actual_env_names.push(name.clone());

                    match get_environment_python_version_impl(&path, fs, env_sys) {
                        Ok(python_version) => {
                            log::debug!("Found environment: {name} with Python {python_version}");
                            environments.push(CondaEnvironment {
                                name: name.clone(),
                                python_version,
                                path: path.to_string_lossy().to_string(),
                            });
                        }
                        Err(e) => {
                            log::warn!(
                                "Skipping directory '{name}' - not a valid Python environment: {e}"
                            );
                        }
                    }
                }
            }
        }
        Err(e) => return Err(format!("Failed to read environments directory: {e}")),
    }

    // Try to determine active environment from settings
    let home_dir = env_sys
        .var("HOME")
        .or_else(|_| env_sys.var("USERPROFILE"))
        .map_err(|e| format!("Could not determine home directory: {e}"))?;

    let platform_dir = Path::new(&home_dir).join(".openbb_platform");
    let system_settings_path = platform_dir.join("system_settings.json");

    // Now check if there are YAML files for environments that don't exist

    if let Ok(envs_dir) = get_environments_directory_impl(env_sys)
        && fs.exists(&envs_dir)
    {
        // Scan for YAML files
        if let Ok(entries) = fs.read_dir(&envs_dir) {
            for path in entries {
                // Check if it's a YAML file
                if fs.is_file(&path.to_string_lossy())
                    && path
                        .extension()
                        .is_some_and(|ext| ext == "yaml" || ext == "yml")
                    && let Some(file_stem) = path.file_stem()
                    && let Some(env_name) = file_stem.to_str()
                {
                    // Check if this environment actually exists
                    if !actual_env_names.contains(&env_name.to_string()) && env_name != "base" {
                        log::debug!(
                            "Found YAML file for non-existent environment '{env_name}', removing it"
                        );

                        // Delete the YAML file for non-existent environment
                        if let Err(e) = fs.remove_file(&path.to_string_lossy()) {
                            log::error!("Failed to delete YAML file {}: {}", path.display(), e);
                        }

                        // Also try to clean up in system_settings.json
                        if fs.exists(&system_settings_path)
                            && let Ok(settings_content) = fs.read_to_string(&system_settings_path)
                            && let Ok(mut settings) =
                                serde_json::from_str::<serde_json::Value>(&settings_content)
                            && let Some(envs) = settings
                                .get_mut("environments")
                                .and_then(|e| e.as_object_mut())
                        {
                            envs.remove(env_name);

                            // Write updated settings back
                            if let Ok(updated_settings) = serde_json::to_string_pretty(&settings)
                                && let Err(e) = fs.write(&system_settings_path, &updated_settings)
                            {
                                log::error!("Failed to update system settings: {e}");
                            }
                        }
                    }
                }
            }
        }
    }
    log::debug!("Found {} environments", environments.len());
    Ok(environments)
}

#[tauri::command]
pub async fn list_conda_environments(
    directory: Option<String>,
) -> Result<Vec<CondaEnvironment>, String> {
    list_conda_environments_impl(directory, &RealFileSystem, &RealEnvSystem).await
}

pub async fn get_environment_extensions_impl<F: FileSystem, E: EnvSystem>(
    name: String,
    fs: &F,
    env_sys: &E,
) -> Result<serde_json::Value, String> {
    use std::path::Path;

    let envs_dir = get_environments_directory_impl(env_sys)?;
    let yaml_path = envs_dir.join(format!("{name}.yaml"));

    if !yaml_path.exists() {
        // Try to check if there's a backup YAML in the system settings
        let home_dir = env_sys
            .var("HOME")
            .or_else(|_| env_sys.var("USERPROFILE"))
            .map_err(|e| format!("Could not determine home directory: {e}"))?;

        let platform_dir = Path::new(&home_dir).join(".openbb_platform");
        let system_settings_path = platform_dir.join("system_settings.json");

        // If no system settings either, return empty extensions
        if !fs.exists(&system_settings_path) {
            return Ok(serde_json::json!({ "extensions": [] }));
        }

        // Read the system settings as a fallback
        let settings_content = fs
            .read_to_string(&system_settings_path)
            .map_err(|e| format!("Failed to read system settings: {e}"))?;

        let settings: serde_json::Value = serde_json::from_str(&settings_content)
            .map_err(|e| format!("Failed to parse system settings: {e}"))?;

        // Return extensions from settings if they exist
        if let Some(env_obj) = settings.get("environments").and_then(|e| e.get(&name))
            && let Some(extensions) = env_obj.get("extensions")
        {
            return Ok(serde_json::json!({ "extensions": extensions }));
        }

        return Ok(serde_json::json!({ "extensions": [] }));
    }

    // From this point on, use conda list to get accurate package information
    // Path to conda
    let install_dir = get_installation_directory_impl(fs, env_sys)?;
    let conda_dir = Path::new(&install_dir).join("conda"); // Create a script to run conda list in the environment
    let script_ext = if env_sys.consts_os() == "windows" {
        "bat"
    } else {
        "sh"
    };
    let script_path = env_sys
        .temp_dir()
        .join(format!("conda_list_{name}.{script_ext}"));

    // Script content to activate environment and run conda list with JSON output
    let script_content = if env_sys.consts_os() == "windows" {
        format!(
            r#"@echo off
setlocal enabledelayedexpansion
set "CONDA_ROOT={}"
set "CONDA_ENVS_PATH={}"
set "CONDA_PKGS_DIRS={}"
set "CONDARC={}"
set CONDA_DEFAULT_ENV=
set CONDA_PREFIX=
set CONDA_SHLVL=
set "PATH={};{};%PATH%"

REM Initialize conda first
call "{}\Scripts\conda.bat" init cmd.exe >nul 2>&1

REM Use conda list with explicit environment
call "{}\condabin\conda.bat" list --name {} --json
"#,
            conda_dir.to_string_lossy(),
            conda_dir.join("envs").to_string_lossy(),
            conda_dir.join("pkgs").to_string_lossy(),
            conda_dir.join(".condarc").to_string_lossy(),
            conda_dir.join("Scripts").to_string_lossy(),
            conda_dir.join("condabin").to_string_lossy(),
            conda_dir.to_string_lossy(),
            conda_dir.to_string_lossy(),
            name
        )
    } else {
        format!(
            r#"#!/bin/bash
export CONDA_ROOT="{}"
export CONDA_ENVS_PATH="{}"
export CONDA_PKGS_DIRS="{}"
export CONDARC="{}"
unset CONDA_DEFAULT_ENV
unset CONDA_PREFIX
unset CONDA_SHLVL
export PATH="{}:{}:$PATH"
"{}" list --name {} --json
"#,
            conda_dir.to_string_lossy(),
            conda_dir.join("envs").to_string_lossy(),
            conda_dir.join("pkgs").to_string_lossy(),
            conda_dir.join(".condarc").to_string_lossy(),
            conda_dir.join("bin").to_string_lossy(),
            conda_dir.join("condabin").to_string_lossy(),
            conda_dir.join("bin").join("conda").to_string_lossy(),
            name
        )
    }; // Write the script to a file
    fs.write(&script_path, &script_content)
        .map_err(|e| format!("Failed to create conda list script: {e}"))?;

    // Make the script executable on Unix
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let perms_result = fs.metadata(&script_path).map(|m| m.permissions());
        if let Ok(mut perms) = perms_result {
            perms.set_mode(0o755);
            if let Err(e) = fs.set_permissions(&script_path, perms) {
                log::debug!("Warning: Failed to set script permissions: {e}");
            }
        }
    } // Execute conda command directly without scripts to prevent window opening
    let conda_exe = if env_sys.consts_os() == "windows" {
        conda_dir.join("Scripts").join("conda.exe")
    } else {
        conda_dir.join("bin").join("conda")
    };

    let mut conda_cmd = env_sys.new_conda_command(&conda_exe, &conda_dir);

    let output = conda_cmd
        .args(["list", "--name", &name, "--json"])
        .output()
        .map_err(|e| format!("Failed to execute conda list command: {e}"))?;

    // Get output regardless of success
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);

    log::debug!("Exit code: {:?}", output.status.code());
    if !stderr.is_empty() {
        log::warn!("STDERR:\n{stderr}");
    }

    // Clean up the script file
    let _ = fs.remove_file(&script_path.to_string_lossy());

    // Check if command was successful
    if !output.status.success() {
        return Err(format!("Failed to get package list: {stderr}\n{stdout}"));
    }

    // Parse the JSON output from conda list
    let stdout = String::from_utf8_lossy(&output.stdout);
    let packages: Vec<serde_json::Value> = serde_json::from_str(&stdout)
        .map_err(|e| format!("Failed to parse conda list output: {e}"))?;

    // Convert the packages to the expected extension format
    let mut extensions = Vec::new();

    for pkg in packages {
        // Skip Python, pip and setuptools
        let name = pkg["name"].as_str().unwrap_or("unknown");
        if name == "python" || name == "pip" || name == "setuptools" {
            continue;
        }

        let version = pkg["version"].as_str().unwrap_or("unknown");
        let channel = pkg["channel"].as_str().unwrap_or("unknown");

        // Determine install method based on channel
        let (install_method, package_name) = if channel == "pypi" {
            ("pip", name.to_string())
        } else {
            ("conda", format!("{}:{}", channel, name))
        };

        // Create the extension object
        let extension = serde_json::json!({
            "package": package_name,
            "version": version,
            "install_method": install_method,
            "channel": channel
        });

        extensions.push(extension);
    }

    // Sort extensions in the specified order:
    // 1. "openbb" first
    // 2. "openbb-core" second
    // 3. "openbb-platform-api" third
    // 4. Other openbb-* packages alphabetically
    // 5. All other packages alphabetically
    extensions.sort_by(|a, b| {
        let a_package = a["package"].as_str().unwrap_or("");
        let b_package = b["package"].as_str().unwrap_or("");

        if a_package == "openbb" && b_package != "openbb" {
            std::cmp::Ordering::Less
        } else if a_package != "openbb" && b_package == "openbb" {
            std::cmp::Ordering::Greater
        } else if a_package == "openbb-core" && b_package != "openbb-core" {
            if b_package == "openbb" {
                std::cmp::Ordering::Greater
            } else {
                std::cmp::Ordering::Less
            }
        } else if a_package != "openbb-core" && b_package == "openbb-core" {
            if a_package == "openbb" {
                std::cmp::Ordering::Less
            } else {
                std::cmp::Ordering::Greater
            }
        } else if a_package == "openbb-platform-api" && b_package != "openbb-platform-api" {
            if b_package == "openbb" || b_package == "openbb-core" {
                std::cmp::Ordering::Greater
            } else {
                std::cmp::Ordering::Less
            }
        } else if a_package != "openbb-platform-api" && b_package == "openbb-platform-api" {
            if a_package == "openbb" || a_package == "openbb-core" {
                std::cmp::Ordering::Less
            } else {
                std::cmp::Ordering::Greater
            }
        } else if a_package.starts_with("openbb-") && !b_package.starts_with("openbb-") {
            std::cmp::Ordering::Less
        } else if !a_package.starts_with("openbb-") && b_package.starts_with("openbb-") {
            std::cmp::Ordering::Greater
        } else {
            // Alphabetical sorting for everything else
            a_package.cmp(b_package)
        }
    });

    Ok(serde_json::json!({ "extensions": extensions }))
}

#[tauri::command]
pub async fn get_environment_extensions(name: String) -> Result<serde_json::Value, String> {
    get_environment_extensions_impl(name, &RealFileSystem, &RealEnvSystem).await
}

pub async fn remove_extension_impl<F: FileSystem, E: EnvSystem>(
    package: String,
    environment: String,
    directory: String,
    fs: &F,
    env_sys: &E,
) -> Result<bool, String> {
    use std::path::Path;
    log::debug!("Removing extension '{package}' from environment '{environment}'");

    // Determine removal method and package name from the identifier
    let (removal_method, package_name) = if let Some(index) = package.find(':') {
        ("conda", &package[(index + 1)..])
    } else {
        ("pip", package.as_str())
    };
    log::debug!("Using '{removal_method}' to remove '{package_name}'");

    // Use provided directory
    let conda_dir = Path::new(&directory).join("conda");

    // Get the Python executable path for the environment
    let env_python_path = if env_sys.consts_os() == "windows" {
        if environment == "base" {
            conda_dir.join("python.exe")
        } else {
            conda_dir.join("envs").join(&environment).join("python.exe")
        }
    } else if environment == "base" {
        conda_dir.join("bin").join("python")
    } else {
        conda_dir
            .join("envs")
            .join(&environment)
            .join("bin")
            .join("python")
    };

    if !fs.exists(&env_python_path) {
        return Err(format!("Environment '{environment}' does not exist"));
    }

    if removal_method == "conda" {
        // Use conda to remove the package
        let conda_exe = if env_sys.consts_os() == "windows" {
            conda_dir.join("Scripts").join("conda.exe")
        } else {
            conda_dir.join("bin").join("conda")
        };
        let conda_args = if environment == "base" {
            vec!["remove", package_name, "-y"]
        } else {
            vec!["remove", "-n", &environment, package_name, "-y"]
        };

        let mut conda_command = env_sys.new_conda_command(&conda_exe, &conda_dir);
        let conda_output = conda_command
            .args(&conda_args)
            .output()
            .map_err(|e| format!("Failed to remove extension with conda: {e}"))?;

        if conda_output.status.success() {
            log::debug!("Successfully removed extension '{package_name}' with conda");
        } else {
            let stderr = String::from_utf8_lossy(&conda_output.stderr);
            let stdout = String::from_utf8_lossy(&conda_output.stdout);
            return Err(format!(
                "Failed to remove extension '{package_name}' with conda: \nStdout: {stdout}\nStderr: {stderr}"
            ));
        }
    } else {
        // Use pip to remove the package
        let mut pip_command = env_sys.new_conda_command(&env_python_path, &conda_dir);
        let pip_output = pip_command
            .args(["-m", "pip", "uninstall", package_name, "-y"])
            .output()
            .map_err(|e| format!("Failed to remove extension with pip: {e}"))?;

        if pip_output.status.success() {
            log::debug!("Successfully removed extension '{package_name}' with pip");
        } else {
            let stderr = String::from_utf8_lossy(&pip_output.stderr);
            let stdout = String::from_utf8_lossy(&pip_output.stdout);
            return Err(format!(
                "Failed to remove extension '{package_name}' with pip: \nStdout: {stdout}\nStderr: {stderr}"
            ));
        }
    }

    // Always update the YAML file after a removal attempt.
    match get_environments_directory_impl(env_sys) {
        Ok(envs_dir) => {
            let yaml_path = envs_dir.join(format!("{environment}.yaml"));

            if fs.exists(&yaml_path) {
                log::debug!("Updating YAML file to remove package: {package_name}");

                // Read and parse the YAML file
                match fs.read_to_string(&yaml_path) {
                    Ok(yaml_content) => {
                        match serde_yaml::from_str::<serde_yaml::Value>(&yaml_content) {
                            Ok(mut yaml_value) => {
                                let mut updated = false;

                                if let Some(deps) = yaml_value
                                    .get_mut("dependencies")
                                    .and_then(|d| d.as_sequence_mut())
                                {
                                    if removal_method == "conda" {
                                        let original_len = deps.len();
                                        deps.retain(|dep| {
                                            if let Some(dep_str) = dep.as_str() {
                                                !dep_str.starts_with(package_name)
                                            } else {
                                                true
                                            }
                                        });
                                        if deps.len() < original_len {
                                            updated = true;
                                        }
                                    } else {
                                        // removal_method == "pip"
                                        for dep in deps.iter_mut() {
                                            if let Some(pip_map) = dep.as_mapping_mut()
                                                && let Some(pip_deps) = pip_map
                                                    .get_mut(serde_yaml::Value::String(
                                                        "pip".to_string(),
                                                    ))
                                                    .and_then(|p| p.as_sequence_mut())
                                            {
                                                let pip_original_len = pip_deps.len();
                                                pip_deps.retain(|pip_dep| {
                                                    if let Some(pip_dep_str) = pip_dep.as_str() {
                                                        let pip_dep_name = pip_dep_str
                                                            .split(['=', '<', '>'])
                                                            .next()
                                                            .unwrap_or("")
                                                            .trim();
                                                        pip_dep_name != package_name
                                                    } else {
                                                        true
                                                    }
                                                });
                                                if pip_deps.len() < pip_original_len {
                                                    updated = true;
                                                }
                                            }
                                        }
                                    }
                                }

                                // If we made changes, save the updated YAML
                                if updated {
                                    match serde_yaml::to_string(&yaml_value) {
                                        Ok(updated_yaml) => {
                                            if let Err(e) = fs.write(&yaml_path, &updated_yaml) {
                                                log::warn!("Failed to update YAML file: {e}");
                                            } else {
                                                log::debug!(
                                                    "Successfully updated YAML file after removing package"
                                                );
                                            }
                                        }
                                        Err(e) => {
                                            log::warn!("Failed to serialize updated YAML: {e}")
                                        }
                                    }
                                } else {
                                    log::debug!("Package not found in YAML file, no changes made.");
                                }
                            }
                            Err(e) => log::warn!("Failed to parse YAML file: {e}"),
                        }
                    }
                    Err(e) => log::warn!("Failed to read YAML file: {e}"),
                }
            } else {
                log::debug!("No YAML file found for environment, skipping update");
            }
        }
        Err(e) => log::warn!("Failed to get environments directory: {e}"),
    }
    Ok(true)
}

#[tauri::command]
pub async fn remove_extension(
    package: String,
    environment: String,
    directory: String,
) -> Result<bool, String> {
    remove_extension_impl(
        package,
        environment,
        directory,
        &RealFileSystem,
        &RealEnvSystem,
    )
    .await
}

pub async fn update_extension_impl<F: FileSystem, E: EnvSystem>(
    package: String,
    environment: String,
    directory: String,
    fs: &F,
    env_sys: &E,
) -> Result<bool, String> {
    use std::path::Path;

    log::debug!("Updating extension '{package}' in environment '{environment}'");

    // Use provided directory
    let conda_dir = Path::new(&directory).join("conda");

    // Get the Python executable path for the environment
    let env_python_path = if env_sys.consts_os() == "windows" {
        if environment == "base" {
            conda_dir.join("python.exe")
        } else {
            conda_dir.join("envs").join(&environment).join("python.exe")
        }
    } else if environment == "base" {
        conda_dir.join("bin").join("python")
    } else {
        conda_dir
            .join("envs")
            .join(&environment)
            .join("bin")
            .join("python")
    };

    if !fs.exists(&env_python_path) {
        return Err(format!("Environment '{environment}' does not exist"));
    }

    // First try to update with pip
    let mut pip_command = env_sys.new_conda_command(&env_python_path, &conda_dir);
    let pip_output = pip_command
        .args(["-m", "pip", "install", "--upgrade", &package])
        .output()
        .map_err(|e| format!("Failed to update extension with pip: {e}"))?;

    if pip_output.status.success() {
        log::debug!("Successfully updated extension '{package}' with pip");
        return Ok(true);
    }

    // If pip fails, try conda
    let conda_exe = if env_sys.consts_os() == "windows" {
        conda_dir.join("Scripts").join("conda.exe")
    } else {
        conda_dir.join("bin").join("conda")
    };
    let conda_args = if environment == "base" {
        vec!["install", &package, "-y"]
    } else {
        vec!["install", "-n", &environment, &package, "-y"]
    };

    let mut conda_command = env_sys.new_conda_command(&conda_exe, &conda_dir);
    let conda_output = conda_command
        .args(&conda_args)
        .output()
        .map_err(|e| format!("Failed to install extension with conda: {e}"))?;
    if conda_output.status.success() {
        log::debug!("Successfully updated extension '{package}' with conda");
        Ok(true)
    } else {
        let stderr = String::from_utf8_lossy(&conda_output.stderr);
        let stdout = String::from_utf8_lossy(&conda_output.stdout);
        Err(format!(
            "Failed to update extension '{package}': \nStdout: {stdout}\nStderr: {stderr}"
        ))
    }
}

#[tauri::command]
pub async fn update_extension(
    package: String,
    environment: String,
    directory: String,
) -> Result<bool, String> {
    update_extension_impl(
        package,
        environment,
        directory,
        &RealFileSystem,
        &RealEnvSystem,
    )
    .await
}

pub async fn install_extensions_impl<F: FileSystem, E: EnvSystem>(
    environment: String,
    extensions: Vec<String>,
    fs: &F,
    env_sys: &E,
) -> Result<bool, String> {
    use std::path::Path;

    log::debug!("Installing extensions {extensions:?} in environment '{environment}'");

    // Get installation directory
    let install_dir = get_installation_directory_impl(fs, env_sys)?;
    let conda_dir = Path::new(&install_dir).join("conda");

    // Get the Python executable path for the environment
    let env_python_path = if env_sys.consts_os() == "windows" {
        if environment == "base" {
            conda_dir.join("python.exe")
        } else {
            conda_dir.join("envs").join(&environment).join("python.exe")
        }
    } else if environment == "base" {
        conda_dir.join("bin").join("python")
    } else {
        conda_dir
            .join("envs")
            .join(&environment)
            .join("bin")
            .join("python")
    }; // Check if Python executable exists
    if !fs.exists(&env_python_path) {
        log::error!(
            "Python executable not found at: {}",
            env_python_path.display()
        );
        return Err(format!(
            "Environment '{}' does not exist - Python executable not found at: {}",
            environment,
            env_python_path.display()
        ));
    } else {
        log::debug!("Found Python executable at: {}", env_python_path.display());
    }

    let python_path_to_use = env_python_path;

    let conda_exe = if env_sys.consts_os() == "windows" {
        conda_dir.join("Scripts").join("conda.exe")
    } else {
        conda_dir.join("bin").join("conda")
    };

    let has_openbb = extensions.iter().any(|ext| ext.to_lowercase() == "openbb");
    let regular_extensions: Vec<&String> = extensions
        .iter()
        .filter(|ext| ext.to_lowercase() != "openbb")
        .collect();

    // 2. Collect conda packages and pip packages
    let mut conda_packages: Vec<&str> = Vec::new();
    let mut pip_packages: Vec<&str> = Vec::new();

    for extension in &regular_extensions {
        if let Some(extension) = extension.strip_prefix("conda:") {
            // Add conda package without the prefix
            conda_packages.push(extension);
        } else {
            // Add to pip packages
            pip_packages.push(extension.as_str());
        }
    }

    // 3. Install all conda packages at once if there are any
    if !conda_packages.is_empty() {
        log::debug!("Installing {} conda packages at once", conda_packages.len());

        let mut conda_args = if environment == "base" {
            vec!["install", "-y"]
        } else {
            vec!["install", "-n", &environment, "-y"]
        };

        // Add all packages to the command
        conda_args.extend(conda_packages.iter());

        let mut conda_command = env_sys.new_conda_command(&conda_exe, &conda_dir);

        let conda_output = conda_command
            .args(&conda_args)
            .output()
            .map_err(|e| format!("Failed to install conda packages: {e}"))?;

        if !conda_output.status.success() {
            let stderr = String::from_utf8_lossy(&conda_output.stderr);
            let stdout = String::from_utf8_lossy(&conda_output.stdout);
            return Err(format!(
                "Failed to install conda packages: \nStdout: {stdout}\nStderr: {stderr}"
            ));
        }

        log::debug!("Successfully installed all conda packages");
    }

    // 4. Install all pip packages at once if there are any
    if !pip_packages.is_empty() {
        log::debug!("Installing {} pip packages at once", pip_packages.len());

        let mut pip_args = vec!["-m", "pip", "install"];
        pip_args.extend(pip_packages.clone());

        let mut pip_command = env_sys.new_conda_command(&python_path_to_use, &conda_dir);

        let pip_output = pip_command
            .args(&pip_args)
            .output()
            .map_err(|e| format!("Failed to install pip packages: {e}"))?;

        if !pip_output.status.success() {
            let stderr = String::from_utf8_lossy(&pip_output.stderr);
            let stdout = String::from_utf8_lossy(&pip_output.stdout);
            return Err(format!(
                "Failed to install pip packages: \nStdout: {stdout}\nStderr: {stderr}"
            ));
        }

        log::debug!("Successfully installed all pip packages");
    }

    // 5. Handle OpenBB separately if it's in the list
    if has_openbb {
        log::debug!("Installing OpenBB separately with --no-deps");

        let mut pip_command = env_sys.new_conda_command(&python_path_to_use, &conda_dir);

        let pip_output = pip_command
            .args(["-m", "pip", "install", "openbb", "--no-deps"])
            .output()
            .map_err(|e| format!("Failed to install OpenBB: {e}"))?;

        if !pip_output.status.success() {
            let stderr = String::from_utf8_lossy(&pip_output.stderr);
            let stdout = String::from_utf8_lossy(&pip_output.stdout);
            log::warn!(
                "OpenBB installation may have issues: Exit code: {}",
                pip_output.status
            );
            log::warn!("STDOUT: {stdout}");
            log::warn!("STDERR: {stderr}");
        } else {
            log::debug!("OpenBB installed successfully");

            // Now run openbb-build as a direct executable
            let openbb_build_path = if env_sys.consts_os() == "windows" {
                if environment == "base" {
                    conda_dir.join("Scripts").join("openbb-build.exe")
                } else {
                    conda_dir
                        .join("envs")
                        .join(&environment)
                        .join("Scripts")
                        .join("openbb-build.exe")
                }
            } else if environment == "base" {
                conda_dir.join("bin").join("openbb-build")
            } else {
                conda_dir
                    .join("envs")
                    .join(&environment)
                    .join("bin")
                    .join("openbb-build")
            };

            let mut build_command = env_sys.new_conda_command(&openbb_build_path, &conda_dir);
            let build_output = build_command.output();

            match build_output {
                Ok(output) => {
                    let stdout = String::from_utf8_lossy(&output.stdout);
                    let stderr = String::from_utf8_lossy(&output.stderr);

                    if !output.status.success() {
                        log::warn!("openbb-build command execution failed: {stderr}");
                        log::debug!("openbb-build output: {stdout}");
                    } else {
                        log::debug!("openbb-build executed successfully");
                        log::debug!("openbb-build output: {stdout}");
                    }
                }
                Err(e) => log::warn!("Failed to run openbb-build: {e}"),
            }
        }
    }
    log::debug!("All extensions installed successfully");

    let envs_dir = match get_environments_directory_impl(env_sys) {
        Ok(dir) => dir,
        Err(e) => {
            log::warn!("Failed to get environments directory: {e}");
            log::warn!("Skipping YAML file update");
            return Ok(true);
        }
    };

    let yaml_path = envs_dir.join(format!("{environment}.yaml"));

    if fs.exists(&yaml_path) {
        // First get existing Python version and package information from YAML
        let existing_yaml_content = fs
            .read_to_string(&yaml_path)
            .map_err(|e| format!("Failed to read existing environment YAML file: {e}"))?;

        let existing_yaml: serde_yaml::Value = serde_yaml::from_str(&existing_yaml_content)
            .map_err(|e| format!("Failed to parse existing environment YAML: {e}"))?;

        // Extract Python version
        let mut python_version = "3.12".to_string(); // Default fallback
        if let Some(deps) = existing_yaml
            .get("dependencies")
            .and_then(|d| d.as_sequence())
        {
            for dep in deps {
                if let Some(dep_str) = dep.as_str()
                    && dep_str.starts_with("python=")
                    && let Some(version) = dep_str.strip_prefix("python=")
                {
                    python_version = version.to_string();
                    break;
                }
            }
        }

        // Extract existing conda channels
        let mut conda_channels_map: std::collections::HashMap<String, Vec<String>> =
            std::collections::HashMap::new();
        if let Some(channels) = existing_yaml.get("channels").and_then(|c| c.as_sequence()) {
            for channel in channels {
                if let Some(channel_str) = channel.as_str() {
                    conda_channels_map.insert(channel_str.to_string(), Vec::new());
                }
            }
        }

        // If no channels defined, add defaults
        if conda_channels_map.is_empty() {
            conda_channels_map.insert("defaults".to_string(), Vec::new());
            conda_channels_map.insert("conda-forge".to_string(), Vec::new());
        }

        // Extract existing conda packages
        let mut existing_conda_packages: Vec<String> = Vec::new();
        if let Some(deps) = existing_yaml
            .get("dependencies")
            .and_then(|d| d.as_sequence())
        {
            for dep in deps {
                if let Some(dep_str) = dep.as_str()
                    && !dep_str.starts_with("python=")
                    && dep_str != "pip"
                {
                    existing_conda_packages.push(dep_str.to_string());
                }
            }
        }

        // Extract existing pip packages
        let mut existing_pip_packages: Vec<String> = Vec::new();
        if let Some(deps) = existing_yaml
            .get("dependencies")
            .and_then(|d| d.as_sequence())
        {
            for dep in deps {
                if let Some(pip_map) = dep.as_mapping()
                    && let Some(pip_key) = pip_map.get(serde_yaml::Value::String("pip".to_string()))
                    && let Some(pip_deps) = pip_key.as_sequence()
                {
                    for pip_dep in pip_deps {
                        if let Some(pip_dep_str) = pip_dep.as_str() {
                            existing_pip_packages.push(pip_dep_str.to_string());
                        }
                    }
                }
            }
        }

        // Add newly installed conda packages, removing any duplicates
        let mut updated_conda_packages = existing_conda_packages.clone();
        for pkg in conda_packages {
            let pkg_name = pkg.split(['=', '<', '>']).next().unwrap_or("").trim();
            if !pkg_name.is_empty() {
                // Remove any existing version of this package
                updated_conda_packages
                    .retain(|p| p.split(['=', '<', '>']).next().unwrap_or("").trim() != pkg_name);
            }
            // Add the new package
            updated_conda_packages.push(pkg.to_string());
        }

        // Add newly installed pip packages, removing any duplicates
        let mut updated_pip_packages = existing_pip_packages.clone();
        for pkg in pip_packages {
            let pkg_name = pkg.split(['=', '<', '>']).next().unwrap_or("").trim();
            if !pkg_name.is_empty() {
                // Remove any existing version of this package
                updated_pip_packages
                    .retain(|p| p.split(['=', '<', '>']).next().unwrap_or("").trim() != pkg_name);
            }
            // Add the new package
            updated_pip_packages.push(pkg.to_string());
        }

        // Update the YAML file
        if let Err(e) = save_environment_as_yaml_impl(
            &environment,
            &python_version,
            &updated_conda_packages,
            &updated_pip_packages,
            &conda_channels_map,
            &install_dir,
            fs,
            env_sys,
        )
        .await
        {
            log::warn!("Failed to update environment YAML file: {e}");
            log::warn!("Extensions were installed successfully, but YAML file was not updated");
        } else {
            log::debug!("Environment YAML file updated successfully");
        }
    } else {
        log::warn!(
            "Environment YAML file not found at {}, skipping update",
            yaml_path.display()
        );
    }
    Ok(true)
}

#[tauri::command]
pub async fn install_extensions(
    environment: String,
    extensions: Vec<String>,
) -> Result<bool, String> {
    install_extensions_impl(environment, extensions, &RealFileSystem, &RealEnvSystem).await
}

pub async fn remove_environment_impl<F: FileSystem, E: EnvSystem>(
    name: String,
    fs: &F,
    env_sys: &E,
) -> Result<bool, String> {
    use std::path::Path;

    log::debug!("Removing environment '{name}'");

    // Prevent removal of base environment
    if name == "base" {
        return Err("Cannot remove the base environment".to_string());
    }

    // Get installation directory
    let install_dir = get_installation_directory_impl(fs, env_sys)?;
    let conda_dir = Path::new(&install_dir).join("conda");

    // Check if environment exists
    let env_path = conda_dir.join("envs").join(&name);
    if !fs.exists(&env_path) {
        return Err(format!("Environment '{name}' does not exist"));
    }

    let conda_exe = if env_sys.consts_os() == "windows" {
        conda_dir.join("Scripts").join("conda.exe")
    } else {
        conda_dir.join("bin").join("conda")
    };

    // Remove the environment
    let mut remove_command = env_sys.new_conda_command(&conda_exe, &conda_dir);
    let remove_output = remove_command
        .args(["env", "remove", "-n", &name, "-y"])
        .output()
        .map_err(|e| format!("Failed to remove environment: {e}"))?;

    if !remove_output.status.success() {
        log::warn!(
            "'conda env remove' failed for '{name}', attempting forceful directory removal."
        );
        if let Err(e) = fs.remove_dir_all(std::path::Path::new(&env_path)) {
            let stderr = String::from_utf8_lossy(&remove_output.stderr);
            return Err(format!(
                "Failed to remove environment '{name}' with conda (Stderr: {stderr}) and failed to forcefully remove directory (Error: {e})"
            ));
        }
    }

    // Also remove the YAML file if it exists
    let envs_dir = get_environments_directory_impl(env_sys)?;
    let yaml_path = envs_dir.join(format!("{name}.yaml"));
    if fs.exists(&yaml_path) {
        if let Err(e) = fs.remove_file(&yaml_path.to_string_lossy()) {
            log::warn!("Failed to remove YAML file for environment '{name}': {e}");
        } else {
            log::debug!("Removed YAML file for environment '{name}'");
        }
    }

    log::debug!("Successfully removed environment '{name}'");
    Ok(true)
}

#[tauri::command]
pub async fn remove_environment(name: String) -> Result<bool, String> {
    remove_environment_impl(name, &RealFileSystem, &RealEnvSystem).await
}

#[tauri::command]
pub async fn update_installation_error(error: String) -> Result<(), String> {
    log::debug!("[installation_state] Updating state to error: {error}");

    let mut state = INSTALLATION_STATE.lock().unwrap();
    state.is_downloading = false;
    state.is_installing = false;
    state.is_configuring = false;
    state.is_complete = false;
    state.message = format!("Error: {error}");

    Ok(())
}

pub async fn update_environment_impl<F: FileSystem, E: EnvSystem>(
    environment: String,
    directory: String,
    fs: &F,
    env_sys: &E,
) -> Result<bool, String> {
    use std::path::Path;

    log::info!("Updating packages in environment: {environment}");

    // Path to conda
    let conda_dir = Path::new(&directory).join("conda");

    // First, read the YAML file to get the environment definition
    let envs_dir = get_environments_directory_impl(env_sys)?;
    let yaml_path = envs_dir.join(format!("{environment}.yaml"));

    if !fs.exists(&yaml_path) {
        return Err(format!("Environment YAML file not found for {environment}"));
    }

    // Read and parse YAML to extract packages
    let yaml_content = fs
        .read_to_string(&yaml_path)
        .map_err(|e| format!("Failed to read environment YAML: {e}"))?;
    let yaml_value: serde_yaml::Value = serde_yaml::from_str(&yaml_content)
        .map_err(|e| format!("Failed to parse environment YAML: {e}"))?;

    // Extract conda and pip packages from YAML
    let mut conda_packages: Vec<String> = Vec::new();
    let mut pip_packages: Vec<String> = Vec::new();

    if let Some(deps) = yaml_value.get("dependencies").and_then(|d| d.as_sequence()) {
        for dep in deps {
            // Check if it's a pip mapping
            if let Some(pip_map) = dep.as_mapping()
                && let Some(pip_deps) = pip_map
                    .get(serde_yaml::Value::String("pip".to_string()))
                    .and_then(|p| p.as_sequence())
            {
                for pip_dep in pip_deps {
                    if let Some(pip_dep_str) = pip_dep.as_str() {
                        pip_packages.push(pip_dep_str.to_string());
                    }
                }
            } else if let Some(conda_dep) = dep.as_str() {
                // It's a conda package (string entry)
                // Extract just the package name (remove version specifiers like =3.11)
                let pkg_name = conda_dep
                    .split(['=', '>', '<', '!'])
                    .next()
                    .unwrap_or(conda_dep);
                // Skip infrastructure packages - we don't want to upgrade these
                if !matches!(pkg_name, "python" | "pip" | "nodejs" | "setuptools") {
                    conda_packages.push(pkg_name.to_string());
                }
            }
        }
    }

    log::info!(
        "Found {} conda packages and {} pip packages to update",
        conda_packages.len(),
        pip_packages.len()
    );

    if conda_packages.is_empty() && pip_packages.is_empty() {
        log::info!("No packages found in environment YAML, nothing to update");
        return Ok(true);
    }

    // Get conda executable
    let conda_exe = if env_sys.consts_os() == "windows" {
        conda_dir.join("Scripts").join("conda.exe")
    } else {
        conda_dir.join("bin").join("conda")
    };

    // Update conda packages if any (excluding python, pip)
    if !conda_packages.is_empty() {
        log::info!(
            "Updating {} conda packages: {:?}",
            conda_packages.len(),
            conda_packages
        );

        let mut conda_args = vec!["install", "-n", &environment, "-y"];
        let pkg_refs: Vec<&str> = conda_packages.iter().map(|s| s.as_str()).collect();
        conda_args.extend(pkg_refs);

        log::info!("Running: {} {}", conda_exe.display(), conda_args.join(" "));

        // Use spawn with timeout to prevent hanging forever
        let mut conda_command = env_sys.new_conda_command(&conda_exe, &conda_dir);
        let mut child = conda_command
            .args(&conda_args)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn conda install: {e}"))?;

        // Run the wait in a blocking thread to not block the async runtime
        let result = tokio::task::spawn_blocking(move || {
            let timeout = std::time::Duration::from_secs(300);
            let start = std::time::Instant::now();

            loop {
                match child.try_wait() {
                    Ok(Some(status)) => {
                        // Process finished
                        let stdout = child
                            .stdout
                            .take()
                            .map(|mut s| {
                                let mut buf = String::new();
                                std::io::Read::read_to_string(&mut s, &mut buf).ok();
                                buf
                            })
                            .unwrap_or_default();
                        let stderr = child
                            .stderr
                            .take()
                            .map(|mut s| {
                                let mut buf = String::new();
                                std::io::Read::read_to_string(&mut s, &mut buf).ok();
                                buf
                            })
                            .unwrap_or_default();
                        return (Some(status), stdout, stderr);
                    }
                    Ok(None) => {
                        // Still running
                        if start.elapsed() > timeout {
                            log::warn!("Conda update timed out after 5 minutes, killing process");
                            let _ = child.kill();
                            let _ = child.wait();
                            return (None, String::new(), "Timed out".to_string());
                        }
                        std::thread::sleep(std::time::Duration::from_millis(100));
                    }
                    Err(e) => {
                        return (None, String::new(), format!("Error: {e}"));
                    }
                }
            }
        })
        .await
        .unwrap_or((None, String::new(), "Task panicked".to_string()));

        let (status, stdout, stderr) = result;
        log::info!("conda stdout: {}", stdout);
        if !stderr.is_empty() {
            log::info!("conda stderr: {}", stderr);
        }
        if let Some(s) = status
            && !s.success()
        {
            log::warn!(
                "Conda update had issues: {}",
                if stderr.is_empty() { &stdout } else { &stderr }
            );
        }
    }

    // Update pip packages
    if !pip_packages.is_empty() {
        log::info!(
            "Updating {} pip packages: {:?}",
            pip_packages.len(),
            pip_packages
        );

        // Get python executable path for this environment
        let env_python = if env_sys.consts_os() == "windows" {
            conda_dir.join("envs").join(&environment).join("python.exe")
        } else {
            conda_dir
                .join("envs")
                .join(&environment)
                .join("bin")
                .join("python")
        };

        if !fs.exists(&env_python) {
            return Err(format!(
                "Python executable not found for environment {}: {}",
                environment,
                env_python.display()
            ));
        }

        let mut pip_command = env_sys.new_conda_command(&env_python, &conda_dir);
        let mut args = vec!["-m", "pip", "install", "--upgrade"];
        let package_refs: Vec<&str> = pip_packages.iter().map(|s| s.as_str()).collect();
        args.extend(package_refs);

        log::info!("Running: {} {}", env_python.display(), args.join(" "));

        let output = pip_command
            .args(&args)
            .stdin(std::process::Stdio::null())
            .output()
            .map_err(|e| format!("Failed to run pip upgrade: {e}"))?;

        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);

        log::info!("pip stdout: {}", stdout);
        if !stderr.is_empty() {
            log::info!("pip stderr: {}", stderr);
        }

        if !output.status.success() {
            return Err(format!(
                "Failed to update pip packages: {}",
                if stderr.is_empty() {
                    stdout.to_string()
                } else {
                    stderr.to_string()
                }
            ));
        }
    }

    // Rebuild OpenBB if it's in the environment
    if pip_packages
        .iter()
        .any(|p| p == "openbb" || p.starts_with("openbb-"))
    {
        log::info!("OpenBB packages detected, running openbb-build");

        let openbb_build = if env_sys.consts_os() == "windows" {
            conda_dir
                .join("envs")
                .join(&environment)
                .join("Scripts")
                .join("openbb-build.exe")
        } else {
            conda_dir
                .join("envs")
                .join(&environment)
                .join("bin")
                .join("openbb-build")
        };

        if fs.exists(&openbb_build) {
            let mut build_command = env_sys.new_conda_command(&openbb_build, &conda_dir);
            let build_output = build_command
                .stdin(std::process::Stdio::null())
                .output()
                .map_err(|e| format!("Failed to run openbb-build: {e}"))?;

            if !build_output.status.success() {
                let build_stderr = String::from_utf8_lossy(&build_output.stderr);
                log::warn!("openbb-build had issues: {}", build_stderr);
                // Don't fail the whole update if openbb-build has issues
            } else {
                log::info!("openbb-build completed successfully");
            }
        }
    }

    log::info!("Successfully updated environment: {environment}");
    Ok(true)
}

#[tauri::command]
pub async fn update_environment(environment: String, directory: String) -> Result<bool, String> {
    update_environment_impl(environment, directory, &RealFileSystem, &RealEnvSystem).await
}

pub async fn execute_in_environment_impl<F: FileSystem, E: EnvSystem>(
    command: String,
    environment: String,
    directory: String,
    fs: &F,
    env_sys: &E,
) -> Result<serde_json::Value, String> {
    use std::path::Path;

    let conda_dir = Path::new(&directory).join("conda");

    #[cfg(windows)]
    let output = {
        log::debug!("Executing command '{command}' in environment '{environment}'");
        let is_shell_command = {
            command.starts_with("start ")
                || command.contains("cmd.exe")
                || command.contains("powershell")
                || command.contains("bash")
                || command.contains(".bat")
                || command.contains(".sh")
        };
        if is_shell_command {
            let shell = "cmd.exe";
            let shell_arg = "/c";
            let opens_new_window = command.starts_with("start ")
                || command.contains("start cmd.exe")
                || command.contains("start powershell");
            if opens_new_window {
                if command.starts_with("start ") {
                    log::debug!("Executing Windows start command: {command}");
                    let temp_dir = env_sys.temp_dir();
                    let batch_file = temp_dir.join("openbb_start_command.bat");
                    let batch_content = format!(
                        r#"@echo off
setlocal enabledelayedexpansion
set "CONDA_ROOT={}"
set "CONDA_ENVS_PATH={}"
set "CONDA_PKGS_DIRS={}"
set "CONDARC={}"
set CONDA_DEFAULT_ENV=
set CONDA_PREFIX=
set CONDA_SHLVL=
set "PATH={};{};%PATH%"
REM Initialize conda first - call conda.bat directly
call "{}\Scripts\conda.bat" init cmd.exe >nul 2>&1
REM Source conda environment
call "{}\condabin\conda.bat" activate base >nul 2>&1
if errorlevel 1 (
    echo Failed to initialize conda base environment
    pause
    exit /b 1
)
REM Now activate the target environment if it's not base
if /i not "{}" == "base" (
    call "{}\condabin\conda.bat" activate {} 2>nul
    if errorlevel 1 (
        echo Failed to activate environment: {}
        echo Available environments:
        call "{}\condabin\conda.bat" env list
        pause
        exit /b 1
    )
)
REM Execute the command
{}"#,
                        conda_dir.to_string_lossy(),
                        conda_dir.join("envs").to_string_lossy(),
                        conda_dir.join("pkgs").to_string_lossy(),
                        conda_dir.join(".condarc").to_string_lossy(),
                        conda_dir.join("Scripts").to_string_lossy(),
                        conda_dir.join("condabin").to_string_lossy(),
                        conda_dir.to_string_lossy(),
                        conda_dir.to_string_lossy(),
                        environment,
                        conda_dir.to_string_lossy(),
                        environment,
                        environment,
                        conda_dir.to_string_lossy(),
                        command
                    );
                    fs.write(&batch_file, &batch_content)
                        .map_err(|e| format!("Failed to write batch file: {e}"))?;
                    match env_sys
                        .new_command("cmd.exe")
                        .args(["/c", &batch_file.to_string_lossy()])
                        .spawn()
                    {
                        Ok(_) => {
                            let batch_file_string =
                                batch_file.clone().to_string_lossy().to_string();
                            std::thread::spawn(move || {
                                std::thread::sleep(std::time::Duration::from_secs(2));
                                let _ = std::fs::remove_file(&batch_file_string);
                            });
                            return Ok(serde_json::json!({
                                "stdout": "Command executed successfully (new window opened)",
                                "stderr": "",
                                "exit_code": 0
                            }));
                        }
                        Err(e) => {
                            let _ = fs.remove_file(&batch_file.to_string_lossy());
                            return Err(format!("Failed to spawn shell command: {e}"));
                        }
                    }
                } else {
                    return Err("Unsupported platform for new window shell command".to_string());
                }
            } else {
                env_sys
                    .new_conda_command(Path::new(shell), &conda_dir)
                    .arg(shell_arg)
                    .arg(&command)
                    .output()
                    .map_err(|e| format!("Failed to execute shell command: {e}"))?
            }
        } else {
            let env_python_path = if environment == "base" {
                conda_dir.join("python.exe")
            } else {
                conda_dir.join("envs").join(&environment).join("python.exe")
            };
            if !fs.exists(&env_python_path) {
                return Err(format!("Environment '{environment}' does not exist"));
            }
            env_sys
                .new_conda_command(&env_python_path, &conda_dir)
                .args(["-c", &command])
                .output()
                .map_err(|e| format!("Failed to execute Python command: {e}"))?
        }
    };

    #[cfg(not(windows))]
    let output = {
        let script_path = env_sys.temp_dir().join("openbb_console_command.sh");
        let script_content = format!(
            r#"#!/bin/bash
export CONDA_ROOT="{conda_root}"
export CONDA_ENVS_PATH="{conda_envs}"
export CONDA_PKGS_DIRS="{conda_pkgs}"
export CONDARC="{condarc}"
unset CONDA_DEFAULT_ENV
unset CONDA_PREFIX
unset CONDA_SHLVL
export PATH="{conda_bin}:{conda_condabin}:$PATH"
source "{activate}" "{env}"
{cmd}
"#,
            conda_root = conda_dir.to_string_lossy(),
            conda_envs = conda_dir.join("envs").to_string_lossy(),
            conda_pkgs = conda_dir.join("pkgs").to_string_lossy(),
            condarc = conda_dir.join(".condarc").to_string_lossy(),
            conda_bin = conda_dir.join("bin").to_string_lossy(),
            conda_condabin = conda_dir.join("condabin").to_string_lossy(),
            activate = conda_dir.join("bin").join("activate").to_string_lossy(),
            env = environment,
            cmd = command,
        );
        fs.write(&script_path, &script_content)
            .map_err(|e| format!("Failed to create command script: {e}"))?;
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs
            .metadata(&script_path)
            .map_err(|e| format!("Failed to get script permissions: {e}"))?
            .permissions();
        perms.set_mode(0o755); // rwxr-xr-x
        fs.set_permissions(&script_path, perms)
            .map_err(|e| format!("Failed to set script permissions: {e}"))?;
        // Execute the script
        let output = env_sys
            .new_command("sh")
            .arg(&script_path)
            .output()
            .map_err(|e| format!("Failed to execute command: {e}"))?;
        // Clean up the script
        let _ = fs.remove_file(&script_path.to_string_lossy());
        output
    };

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    Ok(serde_json::json!({
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": output.status.code()
    }))
}

#[tauri::command]
pub async fn execute_in_environment(
    command: String,
    environment: String,
    directory: String,
) -> Result<serde_json::Value, String> {
    execute_in_environment_impl(
        command,
        environment,
        directory,
        &RealFileSystem,
        &RealEnvSystem,
    )
    .await
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tauri_handlers::helpers::{MockEnvSystem, MockFileSystem};
    use mockall::predicate::*;
    use std::path::PathBuf;

    fn home_dir() -> String {
        if cfg!(windows) {
            "C:\\mock\\home".to_string()
        } else {
            "/mock/home".to_string()
        }
    }
    fn install_dir() -> String {
        if cfg!(windows) {
            "C:\\mock\\install".to_string()
        } else {
            "/mock/install".to_string()
        }
    }
    fn envs_dir() -> PathBuf {
        if cfg!(windows) {
            PathBuf::from("C:\\mock\\home\\.openbb_platform\\environments")
        } else {
            PathBuf::from("/mock/home/.openbb_platform/environments")
        }
    }
    fn conda_dir() -> PathBuf {
        if cfg!(windows) {
            PathBuf::from("C:\\mock\\install\\conda")
        } else {
            PathBuf::from("/mock/install/conda")
        }
    }
    fn python_path(env: &str) -> PathBuf {
        let base = conda_dir().join("envs").join(env);
        if cfg!(windows) {
            base.join("python.exe")
        } else {
            base.join("bin").join("python")
        }
    }
    fn conda_exe() -> PathBuf {
        if cfg!(windows) {
            conda_dir().join("Scripts").join("conda.exe")
        } else {
            conda_dir().join("bin").join("conda")
        }
    }
    fn mock_command_echo(arg: &str) -> std::process::Command {
        if cfg!(windows) {
            let mut cmd = std::process::Command::new("cmd");
            cmd.arg("/C").arg(format!("echo {arg}"));
            cmd
        } else {
            let mut cmd = std::process::Command::new("echo");
            cmd.arg(arg);
            cmd
        }
    }
    fn mock_home_var(mock_env: &mut MockEnvSystem) {
        mock_env
            .expect_var()
            .with(eq("HOME"))
            .returning(|_| Ok(home_dir()));
    }
    fn mock_system_settings(mock_fs: &mut MockFileSystem) {
        let settings_path = PathBuf::from(home_dir())
            .join(".openbb_platform")
            .join("system_settings.json");
        let install_dir_str = install_dir().replace('\\', "\\\\");
        let settings_content =
            format!(r#"{{"install_settings":{{"installation_directory":"{install_dir_str}"}}}}"#);
        mock_fs
            .expect_read_to_string()
            .with(eq(settings_path.clone()))
            .returning(move |_| Ok(settings_content.clone()));
        mock_fs
            .expect_exists()
            .with(eq(settings_path))
            .return_const(true);
    }
    fn mock_env_yaml(mock_fs: &mut MockFileSystem, env_name: &str) {
        let envs_dir = envs_dir();
        let yaml_path = envs_dir.join(format!("{env_name}.yaml"));
        let yaml_path_for_closure = yaml_path.clone();

        mock_fs
            .expect_exists()
            .with(eq(envs_dir.clone()))
            .return_const(true);
        mock_fs
            .expect_exists()
            .with(eq(yaml_path.clone()))
            .return_const(true);
        mock_fs
            .expect_is_file()
            .with(eq(yaml_path.to_string_lossy().to_string()))
            .return_const(true);
        mock_fs
            .expect_create_dir_all()
            .with(eq(envs_dir.clone()))
            .returning(|_| Ok(()));
        mock_fs
            .expect_read_dir()
            .with(eq(envs_dir.clone()))
            .returning(move |_| Ok(vec![yaml_path_for_closure.clone()]));
        mock_fs
            .expect_read_to_string()
            .with(eq(yaml_path.clone()))
            .returning(move |_| {
                Ok(r#"
channels: [defaults]
dependencies:
- python=3.12
- pip
- pip:
    - pandas
"#
                .to_string())
            });
        mock_fs.expect_write().returning(|_, _| Ok(()));
        mock_fs
            .expect_remove_file()
            .with(eq(yaml_path.to_string_lossy().to_string()))
            .returning(|_| Ok(()));
    }

    #[tokio::test]
    async fn test_install_extensions_impl_success() {
        let mut mock_fs = MockFileSystem::new();
        let mut mock_env = MockEnvSystem::new();

        mock_env
            .expect_consts_os()
            .return_const(if cfg!(windows) { "windows" } else { "unix" });
        mock_home_var(&mut mock_env);
        mock_system_settings(&mut mock_fs);
        mock_env_yaml(&mut mock_fs, "test_env");

        let python_path = python_path("test_env");
        mock_fs
            .expect_exists()
            .with(eq(python_path.clone()))
            .return_const(true);

        mock_env
            .expect_new_conda_command()
            .with(eq(python_path.clone()), eq(conda_dir()))
            .returning(|_, _| mock_command_echo(""));

        let envs_dir = envs_dir();
        let yaml_path = envs_dir.join("test_env.yaml");
        mock_fs
            .expect_exists()
            .with(eq(yaml_path.clone()))
            .return_const(true);
        mock_fs
            .expect_is_file()
            .with(eq(yaml_path.to_string_lossy().to_string()))
            .return_const(true);

        let result = install_extensions_impl(
            "test_env".to_string(),
            vec!["numpy".to_string(), "pandas".to_string()],
            &mock_fs,
            &mock_env,
        )
        .await;
        assert!(result.is_ok());
        assert!(result.unwrap());
    }

    #[tokio::test]
    async fn test_create_environment_from_requirements_impl_txt_success() {
        let mut mock_fs = MockFileSystem::new();
        let mut mock_env = MockEnvSystem::new();

        let os = if cfg!(windows) { "windows" } else { "unix" };
        mock_env.expect_consts_os().return_const(os);
        mock_home_var(&mut mock_env);
        mock_system_settings(&mut mock_fs);

        let req_path = if cfg!(windows) {
            PathBuf::from("C:\\mock\\requirements.txt")
        } else {
            PathBuf::from("/mock/requirements.txt")
        };
        mock_fs
            .expect_exists()
            .with(eq(req_path.clone()))
            .return_const(true);
        mock_fs
            .expect_read_to_string()
            .with(eq(req_path.clone()))
            .returning(|_| Ok("numpy\npython==3.12\n".to_string()));
        mock_fs.expect_write().returning(|_, _| Ok(()));

        let setup_py_path = if cfg!(windows) {
            PathBuf::from("C:\\mock\\setup.py")
        } else {
            PathBuf::from("/mock/setup.py")
        };
        mock_fs
            .expect_exists()
            .with(eq(setup_py_path))
            .return_const(false);

        let pyproject_toml_path = if cfg!(windows) {
            PathBuf::from("C:\\mock\\pyproject.toml")
        } else {
            PathBuf::from("/mock/pyproject.toml")
        };
        mock_fs
            .expect_exists()
            .with(eq(pyproject_toml_path))
            .return_const(false);

        let env_path = conda_dir().join("envs").join("test_env");
        mock_fs
            .expect_exists()
            .with(eq(env_path))
            .return_const(false);

        mock_env
            .expect_new_conda_command()
            .with(eq(conda_exe()), eq(conda_dir()))
            .returning(|_, _| mock_command_echo(""));

        let envs_dir = envs_dir();
        mock_fs
            .expect_create_dir_all()
            .with(eq(envs_dir))
            .returning(|_| Ok(()));

        let result = create_environment_from_requirements_impl(
            "test_env".to_string(),
            req_path.to_string_lossy().to_string(),
            install_dir(),
            "test_process".to_string(),
            None,
            &mock_fs,
            &mock_env,
        )
        .await;
        assert!(result.is_ok(), "Result was not ok: {:?}", result.err());
        assert!(result.unwrap());
    }

    #[tokio::test]
    async fn test_create_environment_from_requirements_impl_toml_success() {
        let mut mock_fs = MockFileSystem::new();
        let mut mock_env = MockEnvSystem::new();

        let os = if cfg!(windows) { "windows" } else { "unix" };
        mock_env.expect_consts_os().return_const(os);
        mock_home_var(&mut mock_env);
        mock_system_settings(&mut mock_fs);

        let toml_path = if cfg!(windows) {
            PathBuf::from("C:\\mock\\pyproject.toml")
        } else {
            PathBuf::from("/mock/pyproject.toml")
        };
        mock_fs
            .expect_exists()
            .with(eq(toml_path.clone()))
            .return_const(true);
        mock_fs
            .expect_read_to_string()
            .with(eq(toml_path.clone()))
            .returning(|_| {
                Ok(r#"[project]
name = "test-project"
requires-python = ">=3.12"
dependencies = ["numpy", "pandas"]
"#
                .to_string())
            });

        let temp_dir = if cfg!(windows) {
            PathBuf::from("C:\\tmp")
        } else {
            PathBuf::from("/tmp")
        };
        mock_env.expect_temp_dir().return_const(temp_dir.clone());

        mock_fs.expect_write().returning(|_, _| Ok(()));
        mock_fs.expect_remove_file().returning(|_| Ok(()));

        mock_env
            .expect_new_command()
            .returning(|_| mock_command_echo(""));

        let script_ext = if cfg!(windows) { "bat" } else { "sh" };
        let script_path = temp_dir.join(format!("create_and_install_test_env.{script_ext}"));

        let temp_dir_clone = temp_dir.clone();
        mock_fs
            .expect_metadata()
            .with(eq(script_path.clone()))
            .returning(move |_| std::fs::metadata(temp_dir_clone.clone()));
        mock_fs.expect_set_permissions().returning(|_, _| Ok(()));

        let dev_script_path = temp_dir.join(format!("install_project_dev.{script_ext}"));
        let temp_dir_clone2 = temp_dir.clone();
        mock_fs
            .expect_metadata()
            .with(eq(dev_script_path.clone()))
            .returning(move |_| std::fs::metadata(temp_dir_clone2.clone()));
        mock_fs.expect_set_permissions().returning(|_, _| Ok(()));

        let envs_dir = envs_dir();
        mock_fs
            .expect_create_dir_all()
            .with(eq(envs_dir))
            .returning(|_| Ok(()));

        let result = create_environment_from_requirements_impl(
            "test_env".to_string(),
            toml_path.to_string_lossy().to_string(),
            install_dir(),
            "test_process".to_string(),
            None,
            &mock_fs,
            &mock_env,
        )
        .await;

        assert!(result.is_ok(), "Result was not ok: {:?}", result.err());
        assert!(result.unwrap());
    }

    #[tokio::test]
    async fn test_select_requirements_file_impl_returns_path() {
        let mut mock_env = MockEnvSystem::new();
        mock_env
            .expect_consts_os()
            .return_const(if cfg!(windows) { "windows" } else { "unix" });
        mock_home_var(&mut mock_env);

        if cfg!(windows) {
            mock_env.expect_new_command().returning(|program| {
                assert_eq!(program, "powershell");
                let mut cmd = std::process::Command::new("cmd");
                cmd.arg("/C").arg("echo C:\\mock\\requirements.txt");
                cmd
            });
        } else {
            mock_env
                .expect_new_command()
                .with(eq("osascript"))
                .returning(|_| {
                    let mut cmd = std::process::Command::new("echo");
                    cmd.arg("/mock/requirements.txt");
                    cmd
                });
        }

        let result = select_requirements_file_impl(&mock_env).await;

        if cfg!(windows) {
            assert!(result.is_ok(), "Test failed on Windows: {:?}", result.err());
            assert_eq!(
                result.unwrap().trim(),
                "C:\\mock\\requirements.txt\" -Command \""
            );
        } else {
            assert!(result.is_ok());
            assert_eq!(
                result.unwrap(),
                "/mock/requirements.txt -e \n            try\n                tell application \"System Events\"\n                    activate\n                    set defaultFolder to POSIX file \"/mock/home\"\n                    set fileTypes to {\"txt\", \"toml\", \"yml\", \"yaml\"}\n                    set filePath to POSIX path of (choose file default location defaultFolder with prompt \"Select Requirements File\" of type fileTypes)\n                    return filePath\n                end tell\n            on error errMsg number errNum\n                if errNum is -128 then\n                    -- User canceled, return empty string\n                    return \"\"\n                else\n                    -- Real error, return the error message with a prefix so we can detect it\n                    return \"ERROR: \" & errMsg\n                end if\n            end try"
            );
        }
    }

    #[tokio::test]
    async fn test_remove_extension_impl_pip_success() {
        let mut mock_fs = MockFileSystem::new();
        let mut mock_env = MockEnvSystem::new();

        mock_env
            .expect_consts_os()
            .return_const(if cfg!(windows) { "windows" } else { "unix" });
        mock_home_var(&mut mock_env);
        mock_system_settings(&mut mock_fs);
        mock_env_yaml(&mut mock_fs, "test_env");

        let python_path = python_path("test_env");
        mock_fs
            .expect_exists()
            .with(eq(python_path.clone()))
            .return_const(true);

        mock_env
            .expect_new_conda_command()
            .with(eq(python_path.clone()), eq(conda_dir()))
            .returning(|_, _| mock_command_echo(""));

        let result = remove_extension_impl(
            "pandas".to_string(),
            "test_env".to_string(),
            install_dir(),
            &mock_fs,
            &mock_env,
        )
        .await;
        assert!(result.is_ok());
        assert!(result.unwrap());
    }

    #[tokio::test]
    async fn test_update_extension_impl_pip_success() {
        let mut mock_fs = MockFileSystem::new();
        let mut mock_env = MockEnvSystem::new();

        mock_env
            .expect_consts_os()
            .return_const(if cfg!(windows) { "windows" } else { "unix" });
        mock_home_var(&mut mock_env);
        mock_system_settings(&mut mock_fs);

        let python_path = python_path("test_env");
        mock_fs
            .expect_exists()
            .with(eq(python_path.clone()))
            .return_const(true);

        mock_env
            .expect_new_conda_command()
            .with(eq(python_path.clone()), eq(conda_dir()))
            .returning(|_, _| mock_command_echo(""));

        let result = update_extension_impl(
            "pandas".to_string(),
            "test_env".to_string(),
            install_dir(),
            &mock_fs,
            &mock_env,
        )
        .await;
        assert!(result.is_ok());
        assert!(result.unwrap());
    }

    #[tokio::test]
    async fn test_remove_environment_impl_success() {
        let mut mock_fs = MockFileSystem::new();
        let mut mock_env = MockEnvSystem::new();

        mock_env
            .expect_consts_os()
            .return_const(if cfg!(windows) { "windows" } else { "unix" });
        mock_home_var(&mut mock_env);
        mock_system_settings(&mut mock_fs);
        mock_env_yaml(&mut mock_fs, "test_env");

        let env_path = conda_dir().join("envs").join("test_env");
        mock_fs
            .expect_exists()
            .with(eq(env_path.clone()))
            .return_const(true);

        let conda_exe = conda_exe();
        mock_env
            .expect_new_conda_command()
            .with(eq(conda_exe.clone()), eq(conda_dir()))
            .returning(|_, _| mock_command_echo(""));

        let envs_dir = envs_dir();
        let yaml_path = envs_dir.join("test_env.yaml");
        mock_fs
            .expect_exists()
            .with(eq(yaml_path.clone()))
            .return_const(true);
        mock_fs
            .expect_remove_file()
            .with(eq(yaml_path.to_string_lossy().to_string()))
            .returning(|_| Ok(()));

        let result = remove_environment_impl("test_env".to_string(), &mock_fs, &mock_env).await;
        assert!(result.is_ok());
        assert!(result.unwrap());
    }

    #[tokio::test]
    async fn test_update_environment_impl_success() {
        let mut mock_fs = MockFileSystem::new();
        let mut mock_env = MockEnvSystem::new();

        mock_env
            .expect_consts_os()
            .return_const(if cfg!(windows) { "windows" } else { "unix" });
        mock_home_var(&mut mock_env);
        mock_system_settings(&mut mock_fs);
        mock_env_yaml(&mut mock_fs, "test_env");

        let envs_dir = envs_dir();
        let yaml_path = envs_dir.join("test_env.yaml");
        mock_fs
            .expect_exists()
            .with(eq(yaml_path.clone()))
            .return_const(true);

        let conda_exe = conda_exe();
        mock_env
            .expect_new_conda_command()
            .with(eq(conda_exe.clone()), eq(conda_dir()))
            .returning(|_, _| mock_command_echo(""));

        let python_path = python_path("test_env");
        mock_fs
            .expect_exists()
            .with(eq(python_path.clone()))
            .return_const(true);

        mock_env
            .expect_new_conda_command()
            .with(eq(python_path.clone()), eq(conda_dir()))
            .returning(|_, _| mock_command_echo(""));

        let result =
            update_environment_impl("test_env".to_string(), install_dir(), &mock_fs, &mock_env)
                .await;
        assert!(result.is_ok());
        assert!(result.unwrap());
    }

    #[tokio::test]
    async fn test_execute_in_environment_impl_success() {
        let mut mock_fs = MockFileSystem::new();
        let mut mock_env = MockEnvSystem::new();

        mock_env
            .expect_consts_os()
            .return_const(if cfg!(windows) { "windows" } else { "unix" });
        mock_home_var(&mut mock_env);
        mock_system_settings(&mut mock_fs);

        let command = if cfg!(windows) {
            // On Windows, "echo hello" is not a shell command according to our logic,
            // so it will be executed with python -c
            "print('hello')".to_string()
        } else {
            // On Linux, a script is created and run with sh
            "echo hello".to_string()
        };

        if cfg!(windows) {
            let python_path = python_path("test_env");
            mock_fs
                .expect_exists()
                .with(eq(python_path.clone()))
                .return_const(true);
            mock_env
                .expect_new_conda_command()
                .with(eq(python_path.clone()), eq(conda_dir()))
                .returning(|_, _| mock_command_echo("hello"));
        } else {
            mock_fs.expect_exists().return_const(true);
            mock_env
                .expect_temp_dir()
                .returning(|| PathBuf::from("/tmp"));
            mock_fs.expect_write().returning(|_, _| Ok(()));
            mock_fs
                .expect_metadata()
                .returning(|_| std::fs::metadata("/tmp"));
            mock_fs.expect_set_permissions().returning(|_, _| Ok(()));
            mock_env
                .expect_new_command()
                .with(eq("sh".to_string()))
                .returning(|_| mock_command_echo("hello"));
            mock_fs.expect_remove_file().returning(|_| Ok(()));
        }

        let result = execute_in_environment_impl(
            command,
            "test_env".to_string(),
            install_dir(),
            &mock_fs,
            &mock_env,
        )
        .await;
        assert!(result.is_ok());
        let output = result.unwrap();
        assert!(output["stdout"].as_str().unwrap().contains("hello"));
    }

    #[tokio::test]
    async fn test_create_environment_impl_success() {
        let mut mock_fs = MockFileSystem::new();
        let mut mock_env = MockEnvSystem::new();

        let os = if cfg!(windows) { "windows" } else { "unix" };
        mock_env.expect_consts_os().return_const(os);
        mock_home_var(&mut mock_env);
        mock_system_settings(&mut mock_fs);

        let env_path = conda_dir().join("envs").join("test_env");
        mock_fs
            .expect_exists()
            .with(eq(env_path))
            .return_const(false); // Environment does not exist initially

        let conda_exe_path = conda_exe();
        mock_fs
            .expect_exists()
            .with(eq(conda_exe_path.clone()))
            .return_const(true);

        mock_env
            .expect_new_conda_command()
            .with(eq(conda_exe_path), eq(conda_dir()))
            .returning(|_, _| mock_command_echo(""));

        let envs_dir = envs_dir();
        mock_fs
            .expect_create_dir_all()
            .with(eq(envs_dir))
            .returning(|_| Ok(()));

        mock_fs.expect_write().returning(|_, _| Ok(()));

        let result = create_environment_impl(
            "test_env".to_string(),
            "3.12".to_string(),
            vec!["numpy".to_string()],
            "test_process".to_string(),
            None,
            &mock_fs,
            &mock_env,
        )
        .await;

        assert!(result.is_ok(), "Result was not ok: {:?}", result.err());
        assert!(result.unwrap());
    }
}
