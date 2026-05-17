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
use std::io::Read;
use std::path::{Component, Path, PathBuf};

use flame_rs::apis::FlameError;
use flate2::read::GzDecoder;
use flate2::write::GzEncoder;
use flate2::{Compression, GzBuilder};
use sha2::{Digest, Sha256};
use tar::{Archive, Builder, EntryType, Header};
use tempfile::TempDir;

const PACKAGE_EXTENSIONS: [&str; 2] = [".tar.gz", ".tgz"];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApplicationInputKind {
    ExecutableFile,
    TarGz,
    Directory,
}

impl std::fmt::Display for ApplicationInputKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ExecutableFile => write!(f, "executable-file"),
            Self::TarGz => write!(f, "tar.gz"),
            Self::Directory => write!(f, "directory"),
        }
    }
}

pub struct PreparedApplication {
    pub kind: ApplicationInputKind,
    pub detection_root: PathBuf,
    pub package_path: PathBuf,
    pub sha256: String,
    _temp_dir: TempDir,
}

impl PreparedApplication {
    pub fn filename(&self, app_name: &str) -> String {
        match self.kind {
            ApplicationInputKind::ExecutableFile => format!("{}.tar.gz", app_name),
            ApplicationInputKind::TarGz | ApplicationInputKind::Directory => {
                format!("{}-{}.tar.gz", app_name, &self.sha256[..16])
            }
        }
    }

    pub fn object_key(&self, app_name: &str) -> String {
        let object_name = match self.kind {
            ApplicationInputKind::ExecutableFile => {
                format!("{}-{}.tar.gz", app_name, &self.sha256[..16])
            }
            ApplicationInputKind::TarGz | ApplicationInputKind::Directory => {
                self.filename(app_name)
            }
        };
        format!("{}/pkg/{}", app_name, object_name)
    }
}

pub fn prepare_application(path: &Path) -> Result<PreparedApplication, FlameError> {
    let input_path = path.canonicalize().map_err(|e| {
        FlameError::InvalidConfig(format!("failed to resolve {}: {}", path.display(), e))
    })?;

    let kind = classify_application(&input_path)?;
    let temp_dir = TempDir::new()
        .map_err(|e| FlameError::Internal(format!("failed to create temp dir: {}", e)))?;

    let detection_root = match kind {
        ApplicationInputKind::ExecutableFile => {
            let root = temp_dir.path().join("binary");
            let bin_dir = root.join("bin");
            fs::create_dir_all(&bin_dir).map_err(|e| {
                FlameError::Internal(format!("failed to create binary package dir: {}", e))
            })?;
            let filename = input_path.file_name().ok_or_else(|| {
                FlameError::InvalidConfig(format!("invalid binary path: {}", input_path.display()))
            })?;
            fs::copy(&input_path, bin_dir.join(filename)).map_err(|e| {
                FlameError::Internal(format!("failed to copy binary into package dir: {}", e))
            })?;
            root
        }
        ApplicationInputKind::TarGz => {
            let root = temp_dir.path().join("extract");
            fs::create_dir_all(&root).map_err(|e| {
                FlameError::Internal(format!("failed to create extraction dir: {}", e))
            })?;
            unpack_tar_gz(&input_path, &root)?;
            select_detection_root(&root)?
        }
        ApplicationInputKind::Directory => input_path,
    };

    let package_path = temp_dir.path().join("application.tar.gz");
    package_directory(&detection_root, &package_path)?;
    let sha256 = sha256_file(&package_path)?;

    Ok(PreparedApplication {
        kind,
        detection_root,
        package_path,
        sha256,
        _temp_dir: temp_dir,
    })
}

pub fn classify_application(path: &Path) -> Result<ApplicationInputKind, FlameError> {
    if path.is_dir() {
        return Ok(ApplicationInputKind::Directory);
    }

    if path.is_file() && has_package_extension(path) {
        return Ok(ApplicationInputKind::TarGz);
    }

    if path.is_file() && is_executable(path)? {
        return Ok(ApplicationInputKind::ExecutableFile);
    }

    Err(FlameError::InvalidConfig(format!(
        "{} must be a directory, .tar.gz/.tgz package, or executable file",
        path.display()
    )))
}

fn has_package_extension(path: &Path) -> bool {
    let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
        return false;
    };
    PACKAGE_EXTENSIONS.iter().any(|ext| name.ends_with(ext))
}

pub fn is_executable(path: &Path) -> Result<bool, FlameError> {
    let metadata = fs::metadata(path).map_err(|e| {
        FlameError::InvalidConfig(format!("failed to stat {}: {}", path.display(), e))
    })?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        Ok(metadata.permissions().mode() & 0o111 != 0)
    }

    #[cfg(not(unix))]
    {
        Ok(metadata.is_file())
    }
}

fn package_directory(src_root: &Path, dest_path: &Path) -> Result<(), FlameError> {
    let file = fs::File::create(dest_path).map_err(|e| {
        FlameError::Internal(format!(
            "failed to create package {}: {}",
            dest_path.display(),
            e
        ))
    })?;
    let encoder = GzBuilder::new()
        .mtime(0)
        .write(file, Compression::default());
    let mut builder = Builder::new(encoder);
    let root = src_root.canonicalize().map_err(|e| {
        FlameError::Internal(format!(
            "failed to resolve package root {}: {}",
            src_root.display(),
            e
        ))
    })?;

    let mut entries = Vec::new();
    collect_entries(&root, Path::new(""), &root, &mut entries)?;
    entries.sort();

    for relative in entries {
        let src = root.join(&relative);
        append_file(&mut builder, &root, &src, &relative)?;
    }

    let encoder = builder
        .into_inner()
        .map_err(|e| FlameError::Internal(format!("failed to finish tar archive: {}", e)))?;
    encoder
        .finish()
        .map_err(|e| FlameError::Internal(format!("failed to finish gzip archive: {}", e)))?;
    Ok(())
}

fn collect_entries(
    root: &Path,
    relative: &Path,
    canonical_root: &Path,
    entries: &mut Vec<PathBuf>,
) -> Result<(), FlameError> {
    let dir = root.join(relative);
    let mut children = Vec::new();
    for entry in fs::read_dir(&dir).map_err(|e| {
        FlameError::Internal(format!("failed to read directory {}: {}", dir.display(), e))
    })? {
        let entry = entry
            .map_err(|e| FlameError::Internal(format!("failed to read directory entry: {}", e)))?;
        children.push(entry.path());
    }
    children.sort();

    for child in children {
        let name = child.file_name().ok_or_else(|| {
            FlameError::Internal(format!("invalid path in package: {}", child.display()))
        })?;
        let child_relative = relative.join(name);
        let metadata = fs::symlink_metadata(&child).map_err(|e| {
            FlameError::Internal(format!("failed to stat {}: {}", child.display(), e))
        })?;

        if metadata.file_type().is_symlink() {
            let target = child.canonicalize().map_err(|e| {
                FlameError::InvalidConfig(format!(
                    "failed to resolve symlink {}: {}",
                    child.display(),
                    e
                ))
            })?;
            if !target.starts_with(canonical_root) {
                return Err(FlameError::InvalidConfig(format!(
                    "symlink {} points outside application root",
                    child.display()
                )));
            }
            if target.is_dir() {
                return Err(FlameError::InvalidConfig(format!(
                    "symlinked directories are not supported: {}",
                    child.display()
                )));
            }
            entries.push(child_relative);
        } else if metadata.is_dir() {
            collect_entries(root, &child_relative, canonical_root, entries)?;
        } else if metadata.is_file() {
            entries.push(child_relative);
        }
    }

    Ok(())
}

fn append_file(
    builder: &mut Builder<GzEncoder<fs::File>>,
    canonical_root: &Path,
    src: &Path,
    relative: &Path,
) -> Result<(), FlameError> {
    let actual_src = if fs::symlink_metadata(src)
        .map_err(|e| FlameError::Internal(format!("failed to stat {}: {}", src.display(), e)))?
        .file_type()
        .is_symlink()
    {
        src.canonicalize().map_err(|e| {
            FlameError::InvalidConfig(format!(
                "failed to resolve symlink {}: {}",
                src.display(),
                e
            ))
        })?
    } else {
        src.to_path_buf()
    };

    if !actual_src
        .canonicalize()
        .unwrap_or(actual_src.clone())
        .starts_with(canonical_root)
    {
        return Err(FlameError::InvalidConfig(format!(
            "{} is outside application root",
            src.display()
        )));
    }

    let mut file = fs::File::open(&actual_src).map_err(|e| {
        FlameError::Internal(format!("failed to open {}: {}", actual_src.display(), e))
    })?;
    let metadata = file.metadata().map_err(|e| {
        FlameError::Internal(format!("failed to stat {}: {}", actual_src.display(), e))
    })?;

    let mut header = Header::new_gnu();
    header.set_entry_type(EntryType::Regular);
    header.set_size(metadata.len());
    header.set_mtime(0);
    header.set_uid(0);
    header.set_gid(0);
    header.set_mode(file_mode(&metadata));
    header.set_cksum();

    builder
        .append_data(&mut header, relative, &mut file)
        .map_err(|e| FlameError::Internal(format!("failed to append package file: {}", e)))?;
    Ok(())
}

fn file_mode(metadata: &fs::Metadata) -> u32 {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        metadata.permissions().mode() & 0o777
    }

    #[cfg(not(unix))]
    {
        if metadata.permissions().readonly() {
            0o444
        } else {
            0o644
        }
    }
}

fn unpack_tar_gz(package: &Path, dest: &Path) -> Result<(), FlameError> {
    let file = fs::File::open(package).map_err(|e| {
        FlameError::Internal(format!(
            "failed to open package {}: {}",
            package.display(),
            e
        ))
    })?;
    let decoder = GzDecoder::new(file);
    let mut archive = Archive::new(decoder);

    for entry in archive.entries().map_err(|e| {
        FlameError::InvalidConfig(format!(
            "failed to read tar archive {}: {}",
            package.display(),
            e
        ))
    })? {
        let mut entry =
            entry.map_err(|e| FlameError::InvalidConfig(format!("invalid tar entry: {}", e)))?;
        let path = entry
            .path()
            .map_err(|e| FlameError::InvalidConfig(format!("invalid tar path: {}", e)))?;
        let path = path.to_path_buf();
        validate_relative_path(&path)?;

        let entry_type = entry.header().entry_type();
        if !(entry_type.is_dir() || entry_type.is_file()) {
            return Err(FlameError::InvalidConfig(format!(
                "unsupported tar entry type for {}",
                path.display()
            )));
        }

        entry.unpack_in(dest).map_err(|e| {
            FlameError::InvalidConfig(format!("failed to unpack {}: {}", path.display(), e))
        })?;
    }

    Ok(())
}

fn validate_relative_path(path: &Path) -> Result<(), FlameError> {
    for component in path.components() {
        match component {
            Component::Normal(_) | Component::CurDir => {}
            _ => {
                return Err(FlameError::InvalidConfig(format!(
                    "unsafe archive path: {}",
                    path.display()
                )))
            }
        }
    }
    Ok(())
}

fn select_detection_root(root: &Path) -> Result<PathBuf, FlameError> {
    let entries: Vec<PathBuf> = fs::read_dir(root)
        .map_err(|e| FlameError::Internal(format!("failed to read extraction root: {}", e)))?
        .filter_map(|entry| entry.ok().map(|entry| entry.path()))
        .collect();

    if entries.len() == 1 && entries[0].is_dir() {
        Ok(entries[0].clone())
    } else {
        Ok(root.to_path_buf())
    }
}

fn sha256_file(path: &Path) -> Result<String, FlameError> {
    let mut file = fs::File::open(path).map_err(|e| {
        FlameError::Internal(format!("failed to open package {}: {}", path.display(), e))
    })?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 1024 * 1024];

    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|e| FlameError::Internal(format!("failed to read package: {}", e)))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }

    Ok(format!("{:x}", hasher.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn classify_directory() {
        let temp = TempDir::new().unwrap();
        assert_eq!(
            classify_application(temp.path()).unwrap(),
            ApplicationInputKind::Directory
        );
    }

    #[test]
    fn prepare_executable_file_packages_under_bin() {
        let temp = TempDir::new().unwrap();
        let bin = temp.path().join("service");
        fs::write(&bin, b"#!/bin/sh\n").unwrap();
        make_executable(&bin);

        let prepared = prepare_application(&bin).unwrap();
        assert_eq!(prepared.kind, ApplicationInputKind::ExecutableFile);
        assert!(prepared.detection_root.join("bin/service").exists());
        assert_eq!(prepared.filename("demo"), "demo.tar.gz");
        assert_eq!(
            prepared.object_key("demo"),
            format!("demo/pkg/demo-{}.tar.gz", &prepared.sha256[..16])
        );
        assert_eq!(prepared.sha256.len(), 64);
    }

    #[test]
    fn tarball_path_traversal_is_rejected() {
        let temp = TempDir::new().unwrap();
        let package = temp.path().join("bad.tar.gz");
        let file = fs::File::create(&package).unwrap();
        let encoder = GzBuilder::new()
            .mtime(0)
            .write(file, Compression::default());
        let mut encoder = encoder;
        write_raw_tar_entry(&mut encoder, "../bad", b"bad");
        encoder.write_all(&[0_u8; 1024]).unwrap();
        encoder.finish().unwrap();

        let dest = temp.path().join("dest");
        fs::create_dir(&dest).unwrap();
        assert!(unpack_tar_gz(&package, &dest).is_err());
    }

    #[test]
    fn tarball_curdir_entries_are_allowed() {
        assert!(validate_relative_path(Path::new("./app.py")).is_ok());
        assert!(validate_relative_path(Path::new("./bin/service")).is_ok());
    }

    fn write_raw_tar_entry<W: Write>(writer: &mut W, name: &str, data: &[u8]) {
        let mut header = [0_u8; 512];
        header[..name.len()].copy_from_slice(name.as_bytes());
        write_octal(&mut header[100..108], 0o644);
        write_octal(&mut header[108..116], 0);
        write_octal(&mut header[116..124], 0);
        write_octal(&mut header[124..136], data.len() as u64);
        write_octal(&mut header[136..148], 0);
        header[148..156].fill(b' ');
        header[156] = b'0';
        header[257..263].copy_from_slice(b"ustar\0");
        header[263..265].copy_from_slice(b"00");
        let checksum: u32 = header.iter().map(|byte| *byte as u32).sum();
        write_octal(&mut header[148..156], checksum as u64);

        writer.write_all(&header).unwrap();
        writer.write_all(data).unwrap();
        let padding = (512 - (data.len() % 512)) % 512;
        if padding > 0 {
            writer.write_all(&vec![0_u8; padding]).unwrap();
        }
    }

    fn write_octal(field: &mut [u8], value: u64) {
        field.fill(0);
        let digits = format!("{:0width$o}", value, width = field.len() - 1);
        field[..digits.len()].copy_from_slice(digits.as_bytes());
    }

    fn make_executable(path: &Path) {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mut permissions = fs::metadata(path).unwrap().permissions();
            permissions.set_mode(0o755);
            fs::set_permissions(path, permissions).unwrap();
        }
        #[cfg(not(unix))]
        {
            let _ = path;
        }
    }

    #[test]
    fn directory_package_is_content_addressed() {
        let temp = TempDir::new().unwrap();
        let file = temp.path().join("app.py");
        let mut f = fs::File::create(file).unwrap();
        writeln!(f, "print('hello')").unwrap();

        let prepared = prepare_application(temp.path()).unwrap();
        assert!(prepared.package_path.exists());
        assert_eq!(
            prepared.filename("demo").len(),
            "demo-".len() + 16 + ".tar.gz".len()
        );
        assert_eq!(
            prepared.object_key("demo"),
            format!("demo/pkg/{}", prepared.filename("demo"))
        );
    }
}
