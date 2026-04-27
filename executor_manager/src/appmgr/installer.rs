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

//! Installer trait definition for application package installation.

use std::collections::HashMap;
use std::path::Path;
use std::str::FromStr;

use async_trait::async_trait;
use common::FlameError;

use super::python::PythonInstaller;

/// Installer trait - implemented by each installer type.
///
/// Each installer is responsible for:
/// 1. Installing the package and its dependencies
/// 2. Computing and returning environment variables (e.g., PYTHONPATH, LD_LIBRARY_PATH)
#[async_trait]
pub trait Installer: Send + Sync {
    /// Install the package and return environment variables.
    ///
    /// # Arguments
    /// * `app_name` - The application name
    /// * `src_path` - Path to the extracted package source
    /// * `flame_home` - Path to FLAME_HOME directory
    /// * `app_environments` - Application-defined environment variables to merge
    ///
    /// # Returns
    /// HashMap of environment variables to be exported to the executor
    async fn install(
        &self,
        app_name: &str,
        src_path: &Path,
        flame_home: &Path,
        app_environments: &HashMap<String, String>,
    ) -> Result<HashMap<String, String>, FlameError>;

    /// Get the installer type name (for logging).
    fn name(&self) -> &'static str;
}

/// Supported installer types.
#[derive(Clone, Debug, PartialEq)]
pub enum InstallerType {
    /// Python package installer using uv
    Python,
    // Future: Node, Rust, etc.
}

impl InstallerType {
    /// Create the corresponding Installer implementation.
    pub fn create_installer(&self) -> Box<dyn Installer> {
        match self {
            InstallerType::Python => Box::new(PythonInstaller::new()),
        }
    }
}

impl FromStr for InstallerType {
    type Err = FlameError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "python" => Ok(InstallerType::Python),
            _ => Err(FlameError::InvalidConfig(format!(
                "Unknown installer type: {}. Supported types: python",
                s
            ))),
        }
    }
}

impl std::fmt::Display for InstallerType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            InstallerType::Python => write!(f, "python"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_installer_type_from_str() {
        assert_eq!(
            "python".parse::<InstallerType>().unwrap(),
            InstallerType::Python
        );
        assert_eq!(
            "Python".parse::<InstallerType>().unwrap(),
            InstallerType::Python
        );
        assert_eq!(
            "PYTHON".parse::<InstallerType>().unwrap(),
            InstallerType::Python
        );
        assert!("unknown".parse::<InstallerType>().is_err());
    }

    #[test]
    fn test_installer_type_display() {
        assert_eq!(InstallerType::Python.to_string(), "python");
    }
}
