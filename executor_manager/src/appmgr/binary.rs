/*
Copyright 2026 The Flame Authors.
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

use std::collections::HashMap;
use std::path::Path;

use async_trait::async_trait;
use common::FlameError;

use super::installer::Installer;

pub struct BinaryInstaller;

impl BinaryInstaller {
    pub fn new() -> Self {
        Self
    }
}

impl Default for BinaryInstaller {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Installer for BinaryInstaller {
    async fn install(
        &self,
        _app_name: &str,
        src_path: &Path,
        _flame_home: &Path,
        app_environments: &HashMap<String, String>,
    ) -> Result<HashMap<String, String>, FlameError> {
        let mut env_vars = HashMap::new();

        env_vars.insert(
            "FLAME_APP_DIR".to_string(),
            src_path.to_string_lossy().to_string(),
        );

        let mut paths = Vec::new();
        let bin_path = src_path.join("bin");
        paths.push(bin_path.to_string_lossy().to_string());
        paths.push(src_path.to_string_lossy().to_string());
        if let Some(app_path) = app_environments.get("PATH") {
            paths.push(app_path.clone());
        }
        if let Ok(current_path) = std::env::var("PATH") {
            paths.push(current_path);
        }
        env_vars.insert("PATH".to_string(), paths.join(":"));

        let mut ld_paths = vec![src_path.join("libs").to_string_lossy().to_string()];
        let lib_path = src_path.join("lib");
        if lib_path.exists() {
            ld_paths.push(lib_path.to_string_lossy().to_string());
        }
        if let Some(app_ld_path) = app_environments.get("LD_LIBRARY_PATH") {
            ld_paths.push(app_ld_path.clone());
        }
        if let Ok(current_ld_path) = std::env::var("LD_LIBRARY_PATH") {
            ld_paths.push(current_ld_path);
        }
        env_vars.insert("LD_LIBRARY_PATH".to_string(), ld_paths.join(":"));

        Ok(env_vars)
    }

    fn name(&self) -> &'static str {
        "binary"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[tokio::test]
    async fn binary_installer_adds_app_paths() {
        let temp = TempDir::new().unwrap();
        let envs = BinaryInstaller::new()
            .install("demo", temp.path(), temp.path(), &HashMap::new())
            .await
            .unwrap();

        assert_eq!(
            envs.get("FLAME_APP_DIR").map(String::as_str),
            Some(temp.path().to_string_lossy().as_ref())
        );
        assert!(envs
            .get("PATH")
            .unwrap()
            .contains(&temp.path().join("bin").to_string_lossy().to_string()));
        assert!(envs
            .get("LD_LIBRARY_PATH")
            .unwrap()
            .contains(&temp.path().join("libs").to_string_lossy().to_string()));
    }
}
