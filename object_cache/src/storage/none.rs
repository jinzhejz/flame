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

use async_trait::async_trait;

use common::FlameError;

use crate::{Object, ObjectMetadata};

use super::StorageEngine;

/// Memory-only storage engine - no persistence.
pub struct NoneStorage;

impl NoneStorage {
    pub fn new() -> Self {
        tracing::info!("Using none storage engine (no persistence)");
        Self
    }
}

impl Default for NoneStorage {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl StorageEngine for NoneStorage {
    async fn write_object(&self, _key: &str, _object: &Object) -> Result<(), FlameError> {
        Ok(())
    }

    async fn read_object(&self, _key: &str) -> Result<Option<Object>, FlameError> {
        Ok(None)
    }

    async fn patch_object(&self, key: &str, _delta: &Object) -> Result<ObjectMetadata, FlameError> {
        Err(FlameError::InvalidConfig(format!(
            "patch operation not supported with none storage for object <{}>. Use update_object instead.",
            key
        )))
    }

    async fn delete_object(&self, _key: &str) -> Result<(), FlameError> {
        Ok(())
    }

    async fn delete_objects(&self, _session_id: &str) -> Result<(), FlameError> {
        Ok(())
    }

    async fn load_objects(&self) -> Result<Vec<(String, Object, u64)>, FlameError> {
        Ok(Vec::new())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_none_storage_write_read() {
        let storage = NoneStorage::new();
        let object = Object::new(0, vec![1, 2, 3]);

        storage.write_object("session/obj1", &object).await.unwrap();

        let result = storage.read_object("session/obj1").await.unwrap();
        assert!(result.is_none());
    }

    #[tokio::test]
    async fn test_none_storage_patch_returns_error() {
        let storage = NoneStorage::new();
        let delta = Object::new(0, vec![4, 5, 6]);

        let result = storage.patch_object("session/obj1", &delta).await;
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), FlameError::InvalidConfig(_)));
    }

    #[tokio::test]
    async fn test_none_storage_delete() {
        let storage = NoneStorage::new();

        storage.delete_object("session/obj1").await.unwrap();
        storage.delete_objects("session").await.unwrap();
    }

    #[tokio::test]
    async fn test_none_storage_load_objects() {
        let storage = NoneStorage::new();

        let objects = storage.load_objects().await.unwrap();
        assert!(objects.is_empty());
    }
}
