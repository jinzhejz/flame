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

use std::fs;
use std::path::{Path, PathBuf};

use crate::DEFAULT_PYTHON_VERSION;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PythonRuntime {
    pub version: String,
    pub site_packages: Option<PathBuf>,
}

pub fn get_python_runtime(flame_home: &Path, requested: Option<&str>) -> PythonRuntime {
    let version = requested
        .map(version_number)
        .filter(|version| !version.is_empty())
        .map(ToOwned::to_owned)
        .or_else(|| latest_installed_version(flame_home))
        .unwrap_or_else(|| DEFAULT_PYTHON_VERSION.to_string());
    let site_packages = site_packages_path(flame_home, &version);
    let site_packages = site_packages.exists().then_some(site_packages);

    PythonRuntime {
        version,
        site_packages,
    }
}

fn version_number(version: &str) -> &str {
    version.strip_prefix("python").unwrap_or(version)
}

fn latest_installed_version(flame_home: &Path) -> Option<String> {
    let lib_path = flame_home.join("lib");
    let mut versions = fs::read_dir(lib_path)
        .ok()?
        .flatten()
        .filter_map(|entry| {
            let path = entry.path();
            if !path.is_dir() || !path.join("site-packages").is_dir() {
                return None;
            }

            let name = entry.file_name();
            let name = name.to_string_lossy();
            name.strip_prefix("python")
                .filter(|version| !version.is_empty())
                .map(|version| version.to_string())
        })
        .collect::<Vec<_>>();

    versions.sort_by_key(|version| minor_version(version));
    versions.pop()
}

fn site_packages_path(flame_home: &Path, version: &str) -> PathBuf {
    flame_home
        .join("lib")
        .join(format!("python{}", version_number(version)))
        .join("site-packages")
}

fn minor_version(version: &str) -> Vec<u32> {
    version
        .split('.')
        .map(|part| part.parse::<u32>().unwrap_or(0))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn resolves_requested_version_even_when_not_installed() {
        let temp = tempdir().unwrap();

        assert_eq!(
            get_python_runtime(temp.path(), Some("python3.11")),
            PythonRuntime {
                version: "3.11".to_string(),
                site_packages: None,
            }
        );
    }

    #[test]
    fn resolves_latest_installed_version_when_unspecified() {
        let temp = tempdir().unwrap();
        let site_packages = temp.path().join("lib/python3.12/site-packages");
        fs::create_dir_all(temp.path().join("lib/python3.11/site-packages")).unwrap();
        fs::create_dir_all(&site_packages).unwrap();

        assert_eq!(
            get_python_runtime(temp.path(), None),
            PythonRuntime {
                version: "3.12".to_string(),
                site_packages: Some(site_packages),
            }
        );
    }

    #[test]
    fn falls_back_to_default_when_nothing_installed() {
        let temp = tempdir().unwrap();

        assert_eq!(
            get_python_runtime(temp.path(), None),
            PythonRuntime {
                version: "3.12".to_string(),
                site_packages: None,
            }
        );
    }
}
