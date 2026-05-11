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

#[cfg(test)]
mod tests {
    use crate::storage;
    use common::apis::ApplicationAttributes;
    use common::ctx::{FlameCluster, FlameClusterContext};

    fn test_context() -> FlameClusterContext {
        FlameClusterContext {
            cluster: FlameCluster {
                storage: "none".to_string(),
                ..Default::default()
            },
            ..Default::default()
        }
    }

    fn create_app_attr() -> ApplicationAttributes {
        ApplicationAttributes::default()
    }

    mod register_application {
        use super::*;

        #[tokio::test]
        async fn registers_new_application() {
            let ctx = test_context();
            let storage = storage::new_ptr(&ctx).await.unwrap();

            let attr = create_app_attr();
            storage
                .register_application("test-app".to_string(), attr)
                .await
                .unwrap();

            let apps = storage.list_application().await.unwrap();
            assert_eq!(apps.len(), 1);
            assert_eq!(apps[0].name, "test-app");
        }

        #[tokio::test]
        async fn registers_multiple_applications() {
            let ctx = test_context();
            let storage = storage::new_ptr(&ctx).await.unwrap();

            let attr = create_app_attr();
            storage
                .register_application("app-1".to_string(), attr.clone())
                .await
                .unwrap();
            storage
                .register_application("app-2".to_string(), attr)
                .await
                .unwrap();

            let apps = storage.list_application().await.unwrap();
            assert_eq!(apps.len(), 2);
        }

        #[tokio::test]
        async fn stores_application_attributes() {
            let ctx = test_context();
            let storage = storage::new_ptr(&ctx).await.unwrap();

            let attr = ApplicationAttributes {
                image: Some("custom-image:v1".to_string()),
                command: Some("python main.py".to_string()),
                ..Default::default()
            };
            storage
                .register_application("attr-app".to_string(), attr)
                .await
                .unwrap();

            let app = storage
                .get_application("attr-app".to_string())
                .await
                .unwrap();
            assert_eq!(app.image, Some("custom-image:v1".to_string()));
            assert_eq!(app.command, Some("python main.py".to_string()));
        }
    }

    mod get_application {
        use super::*;

        #[tokio::test]
        async fn returns_application_by_id() {
            let ctx = test_context();
            let storage = storage::new_ptr(&ctx).await.unwrap();

            let attr = create_app_attr();
            storage
                .register_application("get-app".to_string(), attr)
                .await
                .unwrap();

            let app = storage
                .get_application("get-app".to_string())
                .await
                .unwrap();
            assert_eq!(app.name, "get-app");
        }

        #[tokio::test]
        async fn returns_error_for_nonexistent_application() {
            let ctx = test_context();
            let storage = storage::new_ptr(&ctx).await.unwrap();

            let result = storage.get_application("nonexistent".to_string()).await;
            assert!(result.is_err());
        }
    }

    mod update_application {
        use super::*;

        #[tokio::test]
        async fn updates_existing_application() {
            let ctx = test_context();
            let storage = storage::new_ptr(&ctx).await.unwrap();

            let attr = create_app_attr();
            storage
                .register_application("update-app".to_string(), attr)
                .await
                .unwrap();

            let new_attr = ApplicationAttributes {
                image: Some("new-image:v2".to_string()),
                ..Default::default()
            };
            storage
                .update_application("update-app".to_string(), new_attr)
                .await
                .unwrap();

            let app = storage
                .get_application("update-app".to_string())
                .await
                .unwrap();
            assert_eq!(app.image, Some("new-image:v2".to_string()));
        }
    }

    mod unregister_application {
        use super::*;
        use common::apis::{ResourceRequirement, SessionAttributes};

        fn create_session_attr(id: &str, app: &str) -> SessionAttributes {
            SessionAttributes {
                id: id.to_string(),
                application: app.to_string(),
                common_data: None,
                min_instances: 1,
                max_instances: None,
                batch_size: 1,
                priority: 0,
                resreq: Some(ResourceRequirement::default()),
            }
        }

        #[tokio::test]
        async fn removes_application() {
            let ctx = test_context();
            let storage = storage::new_ptr(&ctx).await.unwrap();

            let attr = create_app_attr();
            storage
                .register_application("unregister-app".to_string(), attr)
                .await
                .unwrap();

            storage
                .unregister_application("unregister-app".to_string())
                .await
                .unwrap();

            let apps = storage.list_application().await.unwrap();
            assert!(apps.is_empty());
        }

        #[tokio::test]
        async fn removes_sessions_associated_with_application() {
            let ctx = test_context();
            let storage = storage::new_ptr(&ctx).await.unwrap();

            let app_attr = create_app_attr();
            storage
                .register_application("cleanup-app".to_string(), app_attr)
                .await
                .unwrap();

            let ssn_attr = create_session_attr("cleanup-ssn", "cleanup-app");
            storage.create_session(ssn_attr).await.unwrap();

            assert_eq!(storage.list_session().unwrap().len(), 1);

            storage
                .unregister_application("cleanup-app".to_string())
                .await
                .unwrap();

            assert_eq!(storage.list_session().unwrap().len(), 0);
        }
    }

    mod list_application {
        use super::*;

        #[tokio::test]
        async fn returns_empty_list_when_no_applications() {
            let ctx = test_context();
            let storage = storage::new_ptr(&ctx).await.unwrap();

            let apps = storage.list_application().await.unwrap();
            assert!(apps.is_empty());
        }

        #[tokio::test]
        async fn returns_all_registered_applications() {
            let ctx = test_context();
            let storage = storage::new_ptr(&ctx).await.unwrap();

            let attr = create_app_attr();
            for i in 0..3 {
                storage
                    .register_application(format!("list-app-{}", i), attr.clone())
                    .await
                    .unwrap();
            }

            let apps = storage.list_application().await.unwrap();
            assert_eq!(apps.len(), 3);

            let names: Vec<_> = apps.iter().map(|a| a.name.as_str()).collect();
            assert!(names.contains(&"list-app-0"));
            assert!(names.contains(&"list-app-1"));
            assert!(names.contains(&"list-app-2"));
        }
    }
}
