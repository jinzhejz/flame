/*
Copyright 2025 The Flame Authors.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
    http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

mod binary;
mod downloader;
mod installer;
mod python;

pub use binary::BinaryInstaller;
pub use downloader::{DownloaderRegistry, PackageDownloader};
pub use installer::{Installer, InstallerType};
pub use python::PythonInstaller;

use std::collections::HashMap;
use std::env;
use std::fs;
use std::hash::{Hash, Hasher};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use chrono::{DateTime, Utc};
use flate2::read::GzDecoder;
use sha2::{Digest, Sha256};
use stdng::{lock_ptr, MutexPtr};
use tar::Archive;
use tokio::sync::RwLock;
use tonic::transport::ClientTlsConfig;

use common::apis::ApplicationContext;
use common::FlameError;

#[derive(Clone, Debug, Eq)]
struct InstallKey {
    app_name: String,
    installer: String,
    url: Option<String>,
}

impl InstallKey {
    fn new(app_name: &str, installer: &InstallerType, url: Option<&String>) -> Self {
        Self {
            app_name: app_name.to_string(),
            installer: installer.to_string(),
            url: url.cloned(),
        }
    }

    fn release_id(&self) -> String {
        let mut hasher = Sha256::new();
        update_release_hash(&mut hasher, "app", Some(&self.app_name));
        update_release_hash(&mut hasher, "installer", Some(&self.installer));
        update_release_hash(&mut hasher, "url", self.url.as_deref());
        hasher
            .finalize()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect()
    }
}

fn update_release_hash(hasher: &mut Sha256, label: &str, value: Option<&str>) {
    hasher.update(label.as_bytes());
    hasher.update([0]);
    match value {
        Some(value) => {
            hasher.update([1]);
            hasher.update(value.len().to_be_bytes());
            hasher.update(value.as_bytes());
        }
        None => {
            hasher.update([0]);
        }
    }
}

impl PartialEq for InstallKey {
    fn eq(&self, other: &Self) -> bool {
        self.app_name == other.app_name
            && self.installer == other.installer
            && self.url == other.url
    }
}

impl Hash for InstallKey {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.app_name.hash(state);
        self.installer.hash(state);
        self.url.hash(state);
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum InstallState {
    NotInstalled,
    Installing,
    Installed,
    Failed(String),
}

pub struct AppInstaller {
    pub name: String,
    pub installer_type: InstallerType,
    pub state: InstallState,
    pub install_path: PathBuf,
    pub env_vars: HashMap<String, String>,
    pub installed_at: Option<DateTime<Utc>>,
}

impl AppInstaller {
    pub fn new(name: &str, installer_type: InstallerType) -> Self {
        Self {
            name: name.to_string(),
            installer_type,
            state: InstallState::NotInstalled,
            install_path: PathBuf::new(),
            env_vars: HashMap::new(),
            installed_at: None,
        }
    }
}

pub struct ApplicationManager {
    apps: MutexPtr<HashMap<InstallKey, Arc<RwLock<AppInstaller>>>>,
    flame_home: PathBuf,
    downloader: DownloaderRegistry,
}

impl ApplicationManager {
    pub fn new() -> Result<Self, FlameError> {
        Self::new_with_tls(None)
    }

    pub fn new_with_tls(tls_config: Option<ClientTlsConfig>) -> Result<Self, FlameError> {
        let flame_home = env::var("FLAME_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("/opt/flame"));

        Ok(Self {
            apps: Arc::new(std::sync::Mutex::new(HashMap::new())),
            flame_home,
            downloader: DownloaderRegistry::new_with_tls(tls_config),
        })
    }

    pub async fn install(
        &self,
        app: &ApplicationContext,
    ) -> Result<HashMap<String, String>, FlameError> {
        let installer_type = match &app.installer {
            None => {
                tracing::debug!("No installer configured for app <{}>, skipping", app.name);
                return Ok(HashMap::new());
            }
            Some(installer_str) => installer_str.parse::<InstallerType>()?,
        };
        let install_key = InstallKey::new(&app.name, &installer_type, app.url.as_ref());

        {
            let app_entry = {
                let apps = lock_ptr!(self.apps)?;
                apps.get(&install_key).cloned()
            };
            if let Some(installed) = app_entry {
                let installed = installed.read().await;
                if installed.state == InstallState::Installed {
                    return Ok(installed.env_vars.clone());
                }
            }
        }

        let app_entry = {
            let mut apps = lock_ptr!(self.apps)?;
            apps.entry(install_key.clone())
                .or_insert_with(|| {
                    Arc::new(RwLock::new(AppInstaller::new(
                        &app.name,
                        installer_type.clone(),
                    )))
                })
                .clone()
        };

        let mut installed = app_entry.write().await;

        if installed.state == InstallState::Installed {
            return Ok(installed.env_vars.clone());
        }

        if let InstallState::Failed(msg) = &installed.state {
            return Err(FlameError::Internal(msg.clone()));
        }

        installed.state = InstallState::Installing;

        // If no URL is provided, return base env vars (for built-in apps like flmrun)
        let url = match app.url.as_ref() {
            None => {
                tracing::debug!(
                    "No URL configured for app <{}> with installer, using base env",
                    app.name
                );
                let env_vars = self.get_base_env_vars(&app.environments);
                installed.state = InstallState::Installed;
                installed.env_vars = env_vars.clone();
                installed.installed_at = Some(Utc::now());
                return Ok(env_vars);
            }
            Some(url) => url,
        };

        let release_path = self
            .flame_home
            .join("data/apps")
            .join(&app.name)
            .join("releases")
            .join(install_key.release_id());
        let package_path = self.download_package(url, &release_path).await?;

        let src_path = release_path.join("src");
        self.extract_package(&package_path, &src_path)?;

        let installer = installer_type.create_installer();
        tracing::info!(
            "Running {} installer for app <{}>",
            installer.name(),
            app.name
        );

        let env_vars = match installer
            .install(&app.name, &src_path, &self.flame_home, &app.environments)
            .await
        {
            Ok(vars) => vars,
            Err(e) => {
                installed.state = InstallState::Failed(e.to_string());
                return Err(e);
            }
        };

        installed.state = InstallState::Installed;
        installed.install_path = src_path;
        installed.env_vars = env_vars.clone();
        installed.installed_at = Some(Utc::now());

        Ok(env_vars)
    }

    pub fn is_installed(&self, app_name: &str) -> bool {
        if let Ok(apps) = lock_ptr!(self.apps) {
            for (key, installed) in apps.iter() {
                if key.app_name == app_name {
                    if let Ok(installed) = installed.try_read() {
                        if installed.state == InstallState::Installed {
                            return true;
                        }
                    }
                }
            }
        }
        false
    }

    fn get_base_env_vars(
        &self,
        app_environments: &HashMap<String, String>,
    ) -> HashMap<String, String> {
        let mut env_vars = HashMap::new();

        let python_version = app_environments
            .get("FLAME_PYTHON_VERSION")
            .map(|s| s.as_str())
            .unwrap_or("3.12");

        let lib_path = self.flame_home.join("lib");
        if let Some(site_packages) = Self::find_site_packages(&lib_path, python_version) {
            let site_packages_str = site_packages.to_string_lossy().to_string();

            let mut python_paths = vec![site_packages_str.clone()];
            if let Some(app_pythonpath) = app_environments.get("PYTHONPATH") {
                python_paths.push(app_pythonpath.clone());
            }
            env_vars.insert("PYTHONPATH".to_string(), python_paths.join(":"));

            let mut ld_paths = Self::find_native_lib_paths(&site_packages);
            if let Some(app_ld_path) = app_environments.get("LD_LIBRARY_PATH") {
                ld_paths.push(app_ld_path.clone());
            }
            if !ld_paths.is_empty() {
                env_vars.insert("LD_LIBRARY_PATH".to_string(), ld_paths.join(":"));
            }
        }

        env_vars
    }

    fn find_site_packages(lib_path: &Path, python_version: &str) -> Option<PathBuf> {
        if !lib_path.exists() {
            return None;
        }

        let target_dir = format!("python{}", python_version);
        let site_packages = lib_path.join(&target_dir).join("site-packages");
        if site_packages.exists() {
            return Some(site_packages);
        }

        for entry in fs::read_dir(lib_path).ok()?.flatten() {
            let python_dir = entry.path();
            if python_dir.is_dir() && entry.file_name().to_string_lossy().starts_with("python") {
                let site_packages = python_dir.join("site-packages");
                if site_packages.exists() {
                    return Some(site_packages);
                }
            }
        }
        None
    }

    fn find_native_lib_paths(site_packages: &Path) -> Vec<String> {
        let mut paths = std::collections::HashSet::new();

        fn scan_dir(dir: &Path, paths: &mut std::collections::HashSet<String>, depth: usize) {
            if depth > 4 {
                return;
            }
            if let Ok(entries) = fs::read_dir(dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_dir() {
                        scan_dir(&path, paths, depth + 1);
                    } else if path.extension().map(|e| e == "so").unwrap_or(false) {
                        if let Some(parent) = path.parent() {
                            paths.insert(parent.to_string_lossy().to_string());
                        }
                    }
                }
            }
        }

        scan_dir(site_packages, &mut paths, 0);
        paths.into_iter().collect()
    }

    async fn download_package(
        &self,
        url: &str,
        release_path: &Path,
    ) -> Result<PathBuf, FlameError> {
        let download_dir = release_path.join("download");
        fs::create_dir_all(&download_dir).map_err(|e| {
            FlameError::Internal(format!("failed to create download directory: {}", e))
        })?;

        let parsed_url = url::Url::parse(url)
            .map_err(|e| FlameError::InvalidConfig(format!("invalid url: {}", e)))?;

        let filename = parsed_url
            .path_segments()
            .and_then(|mut segments| segments.next_back())
            .unwrap_or("package.tar.gz");

        let package_path = download_dir.join(filename);

        if package_path.exists() {
            tracing::debug!("Package already downloaded: {}", package_path.display());
            return Ok(package_path);
        }

        self.downloader.download(url, &package_path).await?;

        tracing::info!("Downloaded package to: {}", package_path.display());
        Ok(package_path)
    }

    fn extract_package(
        &self,
        package_path: &PathBuf,
        dest_path: &PathBuf,
    ) -> Result<(), FlameError> {
        if dest_path.exists() {
            tracing::warn!(
                "Cleaning up stale extraction directory: {}",
                dest_path.display()
            );
            fs::remove_dir_all(dest_path).map_err(|e| {
                FlameError::Internal(format!(
                    "failed to clean up stale extraction directory: {}",
                    e
                ))
            })?;
        }

        fs::create_dir_all(dest_path).map_err(|e| {
            FlameError::Internal(format!("failed to create extraction directory: {}", e))
        })?;

        let file = fs::File::open(package_path)
            .map_err(|e| FlameError::Internal(format!("failed to open package file: {}", e)))?;

        let package_name = package_path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("");

        if package_name.ends_with(".tar.gz") || package_name.ends_with(".tgz") {
            let decoder = GzDecoder::new(file);
            let mut archive = Archive::new(decoder);
            archive.unpack(dest_path).map_err(|e| {
                FlameError::Internal(format!("failed to extract tar.gz archive: {}", e))
            })?;
        } else if package_name.ends_with(".zip") {
            let mut archive = zip::ZipArchive::new(file)
                .map_err(|e| FlameError::Internal(format!("failed to read zip archive: {}", e)))?;
            archive.extract(dest_path).map_err(|e| {
                FlameError::Internal(format!("failed to extract zip archive: {}", e))
            })?;
        } else {
            return Err(FlameError::InvalidConfig(format!(
                "unsupported archive format: {}",
                package_name
            )));
        }

        tracing::info!("Extracted package to: {}", dest_path.display());
        Ok(())
    }
}

impl Default for ApplicationManager {
    fn default() -> Self {
        Self::new().expect("failed to create ApplicationManager")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn release_id_is_stable_sha256() {
        let key = InstallKey::new(
            "demo",
            &InstallerType::Binary,
            Some(&"grpc://cache/demo/pkg/demo.tar.gz".to_string()),
        );

        assert_eq!(
            key.release_id(),
            "e39adc06cdb2124e255005866affce6fb279d816c4549a6a6a8c9dc03ac4674a"
        );
    }

    #[test]
    fn release_id_distinguishes_missing_url() {
        let with_url = InstallKey::new(
            "demo",
            &InstallerType::Binary,
            Some(&"grpc://cache/demo/pkg/demo.tar.gz".to_string()),
        );
        let without_url = InstallKey::new("demo", &InstallerType::Binary, None);

        assert_ne!(with_url.release_id(), without_url.release_id());
        assert_eq!(without_url.release_id().len(), 64);
    }
}
