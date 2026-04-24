/*
Copyright 2023 The Flame Authors.
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

use clap::Parser;
use futures::future::select_all;
use tokio::runtime::{Builder, Runtime};

use common::ctx::FlameClusterContext;
use common::FlameError;

mod client;
mod executor;
mod manager;
mod shims;
mod states;
mod stream_handler;

#[derive(Parser)]
#[command(name = "flame-executor-manager")]
#[command(author = "XFLOPS <support@xflops.io>")]
#[command(version = "0.5.0")]
#[command(about = "Flame Executor Manager", long_about = None)]
struct Cli {
    #[arg(long)]
    config: Option<String>,
    #[arg(long)]
    slots: Option<i32>,
}

fn build_runtime(name: &str, threads: usize) -> Result<Runtime, FlameError> {
    Builder::new_multi_thread()
        .worker_threads(threads)
        .thread_name(name)
        .enable_all()
        .build()
        .map_err(|e| FlameError::Internal(format!("failed to build runtime <{name}>: {e}")))
}

#[tokio::main]
async fn main() -> Result<(), FlameError> {
    let _log_guard = common::init_logger(Some("fem"))?;

    let cli = Cli::parse();
    let ctx = FlameClusterContext::from_file(cli.config)?;

    tracing::info!("flame-executor-manager is starting ...");

    let mut handlers = vec![];

    if let Some(pprof_config) = &ctx.cluster.pprof {
        let port = pprof_config.port;
        tokio::spawn(async move {
            common::pprof::run_pprof_server(Some(port)).await;
        });
    }

    let num_cpus = std::thread::available_parallelism()
        .map(|p| p.get())
        .unwrap_or(4);
    let cache_threads = if ctx.cache.is_some() {
        if num_cpus > 1 {
            2
        } else {
            1
        }
    } else {
        0
    };
    let manager_threads = ctx.cluster.limits.max_executors as usize + 1;

    tracing::info!(
        "CPU allocation: total={}, cache={}, manager={}, max_executors={}",
        num_cpus,
        cache_threads,
        manager_threads,
        ctx.cluster.limits.max_executors
    );

    let cache_rt = if let Some(ref cache_config) = ctx.cache {
        let cache_rt = build_runtime("cache", cache_threads)?;
        let cache_config = cache_config.clone();
        let handler = cache_rt.spawn(async move {
            let result = flame_cache::run(&cache_config).await;
            if let Err(e) = &result {
                tracing::error!("Object cache exited with error: {e}");
            } else {
                tracing::info!("Object cache exited successfully.");
            }
            result
        });
        handlers.push(handler);
        tracing::info!("Object cache thread started.");
        Some(cache_rt)
    } else {
        tracing::info!("No cache configuration found, object cache will not be started.");
        None
    };

    let manager_rt = build_runtime("manager", manager_threads)?;
    {
        let ctx = ctx.clone();
        let handler = manager_rt.spawn(async move {
            let result = manager::run(&ctx).await;
            if let Err(e) = &result {
                tracing::error!("Executor manager exited with error: {e}");
            } else {
                tracing::info!("Executor manager exited successfully.");
            }
            result
        });
        handlers.push(handler);
    }

    tracing::info!("flame-executor-manager started.");

    let (res, idx, _) = select_all(handlers).await;
    tracing::info!("Thread <{idx}> exited with result: {res:?}");

    Ok(())
}
