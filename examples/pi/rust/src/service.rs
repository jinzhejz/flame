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

mod api;

use rand::distr::{Distribution, Uniform};

use flame_rs::{self as flame, apis::FlameError};

use api::{PiRequest, PiResponse};

#[flame::entrypoint]
async fn estimate_pi(input: PiRequest) -> Result<PiResponse, FlameError> {
    let mut rng = rand::rng();
    let die = Uniform::try_from(0.0..1.0).unwrap();
    let mut inside = 0u32;

    for _ in 0..input.samples {
        let x: f64 = die.sample(&mut rng);
        let y: f64 = die.sample(&mut rng);
        let dist = (x * x + y * y).sqrt();

        if dist <= 1.0 {
            inside += 1;
        }
    }

    Ok(PiResponse { inside })
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    flame::run(estimate_pi).await?;

    tracing::debug!("PiService was stopped.");

    Ok(())
}
