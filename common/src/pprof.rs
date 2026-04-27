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

use std::time::Duration;

use axum::{
    extract::Query,
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
    Router,
};
use pprof::ProfilerGuardBuilder;
use serde_derive::Deserialize;
use tokio::net::TcpListener;

const DEFAULT_PPROF_PORT: u16 = 6060;
const DEFAULT_SAMPLE_SECONDS: u64 = 30;
const DEFAULT_FREQUENCY: i32 = 99;

#[derive(Deserialize)]
struct ProfileParams {
    seconds: Option<u64>,
    frequency: Option<i32>,
}

async fn cpu_profile(Query(params): Query<ProfileParams>) -> Response {
    let seconds = params.seconds.unwrap_or(DEFAULT_SAMPLE_SECONDS);
    let frequency = params.frequency.unwrap_or(DEFAULT_FREQUENCY);

    let guard = match ProfilerGuardBuilder::default()
        .frequency(frequency)
        .blocklist(&["libc", "libgcc", "pthread", "vdso"])
        .build()
    {
        Ok(g) => g,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("Failed to start profiler: {}", e),
            )
                .into_response()
        }
    };

    tokio::time::sleep(Duration::from_secs(seconds)).await;

    match guard.report().build() {
        Ok(report) => {
            let mut body = Vec::new();
            if let Err(e) = report.flamegraph(&mut body) {
                return (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    format!("Failed to generate flamegraph: {}", e),
                )
                    .into_response();
            }
            ([(header::CONTENT_TYPE, "image/svg+xml")], body).into_response()
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("Failed to build report: {}", e),
        )
            .into_response(),
    }
}

async fn cpu_profile_proto(Query(params): Query<ProfileParams>) -> Response {
    let seconds = params.seconds.unwrap_or(DEFAULT_SAMPLE_SECONDS);
    let frequency = params.frequency.unwrap_or(DEFAULT_FREQUENCY);

    let guard = match ProfilerGuardBuilder::default()
        .frequency(frequency)
        .blocklist(&["libc", "libgcc", "pthread", "vdso"])
        .build()
    {
        Ok(g) => g,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("Failed to start profiler: {}", e),
            )
                .into_response()
        }
    };

    tokio::time::sleep(Duration::from_secs(seconds)).await;

    match guard.report().build() {
        Ok(report) => {
            let profile = match report.pprof() {
                Ok(p) => p,
                Err(e) => {
                    return (
                        StatusCode::INTERNAL_SERVER_ERROR,
                        format!("Failed to generate pprof proto: {:?}", e),
                    )
                        .into_response();
                }
            };
            let mut body = Vec::new();
            use pprof::protos::Message;
            if let Err(e) = profile.encode(&mut body) {
                return (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    format!("Failed to encode pprof proto: {}", e),
                )
                    .into_response();
            }
            ([(header::CONTENT_TYPE, "application/octet-stream")], body).into_response()
        }
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("Failed to build report: {}", e),
        )
            .into_response(),
    }
}

async fn health() -> impl IntoResponse {
    "pprof server is running"
}

pub async fn run_pprof_server(port: Option<u16>) {
    let port = port.unwrap_or(DEFAULT_PPROF_PORT);
    let addr = format!("0.0.0.0:{}", port);

    let app = Router::new()
        .route("/debug/pprof/profile", get(cpu_profile))
        .route("/debug/pprof/profile.proto", get(cpu_profile_proto))
        .route("/health", get(health));

    tracing::info!("pprof server listening on {}", addr);

    let listener = match TcpListener::bind(&addr).await {
        Ok(l) => l,
        Err(e) => {
            tracing::error!("Failed to bind pprof server to {}: {}", addr, e);
            return;
        }
    };

    if let Err(e) = axum::serve(listener, app).await {
        tracing::error!("pprof server error: {}", e);
    }
}
