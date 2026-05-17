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

use clap::ValueEnum;
use serde_derive::{Deserialize, Serialize};

pub const DEFAULT_REVISION: &str = "refs/pr/1";
pub const DEFAULT_TOKENIZER_ID: &str = "openai-community/gpt2";
pub const DEFAULT_TEMPERATURE: f64 = 0.8;
pub const DEFAULT_TOP_P: f64 = 0.95;

#[derive(
    Debug,
    Clone,
    Copy,
    Default,
    PartialEq,
    Eq,
    Serialize,
    Deserialize,
    ValueEnum,
    flame_rs::FlameMessage,
)]
pub enum BasedModelSize {
    #[serde(rename = "360m")]
    #[value(name = "360m")]
    #[default]
    W360m,
    #[serde(rename = "1b")]
    #[value(name = "1b")]
    W1b,
    #[serde(rename = "1b-50b")]
    #[value(name = "1b-50b")]
    W1b50b,
}

#[derive(Debug, Clone, Serialize, Deserialize, flame_rs::FlameMessage)]
pub struct BasedModelOptions {
    pub which: BasedModelSize,
    pub model_id: Option<String>,
    pub revision: String,
    pub tokenizer_id: String,
    pub config_file: Option<String>,
    pub tokenizer_file: Option<String>,
    pub weight_files: Option<Vec<String>>,
    pub cpu: bool,
}

impl Default for BasedModelOptions {
    fn default() -> Self {
        Self {
            which: BasedModelSize::default(),
            model_id: None,
            revision: DEFAULT_REVISION.to_string(),
            tokenizer_id: DEFAULT_TOKENIZER_ID.to_string(),
            config_file: None,
            tokenizer_file: None,
            weight_files: None,
            cpu: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, flame_rs::FlameMessage)]
pub struct GenerateRequest {
    pub prompt: String,
    pub sample_len: usize,
    pub temperature: Option<f64>,
    pub top_p: Option<f64>,
    pub seed: u64,
    pub repeat_penalty: f32,
    pub repeat_last_n: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, flame_rs::FlameMessage)]
pub struct GenerateResponse {
    pub text: String,
    pub generated_tokens: usize,
    pub elapsed_ms: u64,
    pub tokens_per_second: f64,
}
