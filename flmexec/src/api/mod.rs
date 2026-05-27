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

use flame_rs::FlameMessage;
use serde_derive::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, FlameMessage)]
pub struct Script {
    pub language: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub runtime: Option<String>,
    pub code: String,
    pub input: Option<Vec<u8>>,
}

#[derive(Debug, Clone, Serialize, Deserialize, FlameMessage)]
pub struct ScriptOutput {
    pub data: Vec<u8>,
}

#[cfg(test)]
mod tests {
    use flame_rs::FlameMessage;

    use super::*;

    #[test]
    fn decodes_request_without_runtime() {
        let script =
            Script::decode(br#"{"language":"python","code":"print(1)","input":null}"#).unwrap();

        assert_eq!(script.language, "python");
        assert_eq!(script.runtime, None);
        assert_eq!(script.code, "print(1)");
        assert_eq!(script.input, None);
    }

    #[test]
    fn encodes_request_runtime_when_present() {
        let script = Script {
            language: "shell".to_string(),
            runtime: Some("zsh".to_string()),
            code: "echo ok".to_string(),
            input: None,
        };

        let encoded = script.encode().unwrap();
        let encoded = String::from_utf8(encoded.to_vec()).unwrap();

        assert!(encoded.contains(r#""runtime":"zsh""#));
    }
}
