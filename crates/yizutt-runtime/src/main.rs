use anyhow::{anyhow, Context, Result};
use chrono::Utc;
use clap::{Parser, Subcommand};
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use tokio::process::{Child, Command};
use tokio::sync::Mutex;
use tokio::time::{sleep, timeout, Duration};
use tonic::{transport::Server, Request, Response, Status};
use tracing::{info, warn};
use uuid::Uuid;

mod yizutt;

use yizutt::runtime_service_client::RuntimeServiceClient;
use yizutt::runtime_service_server::{RuntimeService, RuntimeServiceServer};
use yizutt::worker_service_client::WorkerServiceClient;
use yizutt::worker_service_server::{WorkerService, WorkerServiceServer};
use yizutt::{Empty, PoolStatusReply, TaskReply, TaskRequest, WorkerHealth, WorkerSnapshot};

#[derive(Parser, Debug)]
#[command(name = "yizutt-runtime", version, about = "Yizutt AGI local runtime")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand, Debug)]
enum Commands {
    /// Start the runtime service and managed worker pool.
    Run {
        #[arg(long, default_value = "127.0.0.1:50200")]
        bind: String,
        #[arg(long, default_value = "50210")]
        worker_base_port: u16,
        #[arg(long, default_value = "1")]
        min_workers: usize,
        #[arg(long, default_value = "4")]
        max_workers: usize,
        #[arg(long, default_value = ".yizutt/runtime")]
        home: PathBuf,
        #[arg(long, default_value = "120")]
        task_timeout_secs: u64,
        #[arg(long, default_value = "3")]
        health_timeout_secs: u64,
    },
    /// Internal worker process. Usually started by `run`.
    #[command(hide = true)]
    Worker {
        #[arg(long, default_value = "50100")]
        port: u16,
        #[arg(long, default_value = "worker-dev")]
        id: String,
        #[arg(long, default_value = "120")]
        task_timeout_secs: u64,
        #[arg(long, default_value = "3")]
        health_timeout_secs: u64,
    },
    /// Submit one task to a running runtime.
    Submit {
        #[arg(long, alias = "runtime-addr", default_value = "http://127.0.0.1:50200")]
        addr: String,
        #[arg(long)]
        task: String,
        #[arg(long, default_value = "default")]
        session: String,
        #[arg(long, default_value = "{}")]
        context_json: String,
    },
    /// Print worker pool status from a running runtime.
    Status {
        #[arg(long, alias = "runtime-addr", default_value = "http://127.0.0.1:50200")]
        addr: String,
    },
}

#[derive(Clone)]
struct RuntimeConfig {
    bind: String,
    worker_base_port: u16,
    min_workers: usize,
    max_workers: usize,
    home: PathBuf,
    project_root: PathBuf,
    task_timeout_secs: u64,
    health_timeout_secs: u64,
}

struct WorkerHandle {
    id: String,
    addr: String,
    port: u16,
    child: Child,
    inflight: usize,
    healthy: bool,
    checked_at: String,
    last_error: String,
}

struct WorkerPool {
    cfg: RuntimeConfig,
    workers: Vec<WorkerHandle>,
    next_port: u16,
}

impl WorkerPool {
    async fn new(cfg: RuntimeConfig) -> Result<Self> {
        let mut pool = Self {
            next_port: cfg.worker_base_port,
            cfg,
            workers: Vec::new(),
        };
        for _ in 0..pool.cfg.min_workers {
            pool.spawn_worker().await?;
        }
        Ok(pool)
    }

    async fn spawn_worker(&mut self) -> Result<()> {
        if self.workers.len() >= self.cfg.max_workers {
            return Ok(());
        }
        let id = format!("worker-{}", Uuid::new_v4());
        let port = self.next_port;
        self.next_port = self.next_port.saturating_add(1);
        let addr = format!("http://127.0.0.1:{port}");
        let worker_dir = self.cfg.home.join("workers").join(&id);
        fs::create_dir_all(&worker_dir)?;
        let exe = env::current_exe()?;
        let child = Command::new(exe)
            .arg("worker")
            .arg("--port")
            .arg(port.to_string())
            .arg("--id")
            .arg(&id)
            .arg("--task-timeout-secs")
            .arg(self.cfg.task_timeout_secs.to_string())
            .arg("--health-timeout-secs")
            .arg(self.cfg.health_timeout_secs.to_string())
            .current_dir(&worker_dir)
            .env("YIZUTT_WORKER_DIR", &worker_dir)
            .env("YIZUTT_PROJECT_ROOT", &self.cfg.project_root)
            .env(
                "YIZUTT_MEMORY_PATH",
                self.cfg.project_root.join(".yizutt/memory/work.sqlite3"),
            )
            .env(
                "YIZUTT_SKILLS_ROOT",
                self.cfg.project_root.join(".yizutt/skills"),
            )
            .env("PYTHONPATH", python_path(&self.cfg.project_root))
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .with_context(|| format!("spawn {id}"))?;
        sleep(Duration::from_millis(250)).await;
        self.workers.push(WorkerHandle {
            id,
            addr,
            port,
            child,
            inflight: 0,
            healthy: true,
            checked_at: Utc::now().to_rfc3339(),
            last_error: String::new(),
        });
        Ok(())
    }

    async fn choose_worker(&mut self) -> Result<usize> {
        if self.workers.is_empty() {
            self.spawn_worker().await?;
        }
        self.probe_all().await;
        if !self.workers.iter().any(|w| w.healthy) && self.workers.len() < self.cfg.max_workers {
            self.spawn_worker().await?;
        }
        let all_busy = self
            .workers
            .iter()
            .filter(|w| w.healthy)
            .all(|w| w.inflight > 0);
        if all_busy && self.workers.len() < self.cfg.max_workers {
            self.spawn_worker().await?;
        }
        self.workers
            .iter()
            .enumerate()
            .filter(|(_, w)| w.healthy)
            .min_by_key(|(_, w)| w.inflight)
            .map(|(idx, _)| idx)
            .ok_or_else(|| anyhow!("no healthy workers"))
    }

    fn snapshots(&self) -> Vec<WorkerSnapshot> {
        self.workers
            .iter()
            .map(|w| WorkerSnapshot {
                worker_id: w.id.clone(),
                address: w.addr.clone(),
                inflight: w.inflight as u32,
                healthy: w.healthy,
                checked_at: w.checked_at.clone(),
                last_error: w.last_error.clone(),
            })
            .collect()
    }

    async fn mark_failed(&mut self, worker_id: &str, reason: &str) {
        if let Some(w) = self.workers.iter_mut().find(|w| w.id == worker_id) {
            w.healthy = false;
            w.checked_at = Utc::now().to_rfc3339();
            w.last_error = reason.to_string();
            let _ = w.child.kill().await;
            warn!(worker_id, port = w.port, reason, "worker marked unhealthy");
        }
    }

    async fn probe_all(&mut self) {
        let probes = self
            .workers
            .iter()
            .enumerate()
            .map(|(idx, worker)| (idx, worker.id.clone(), worker.addr.clone()))
            .collect::<Vec<_>>();
        for (idx, worker_id, addr) in probes {
            let checked_at = Utc::now().to_rfc3339();
            if let Some(worker) = self.workers.get_mut(idx) {
                match worker.child.try_wait() {
                    Ok(Some(status)) => {
                        worker.healthy = false;
                        worker.checked_at = checked_at;
                        worker.last_error = format!("worker process exited with {status}");
                        warn!(worker_id = %worker.id, port = worker.port, "worker process exited before health probe");
                        continue;
                    }
                    Ok(None) => {}
                    Err(err) => {
                        worker.healthy = false;
                        worker.checked_at = checked_at;
                        worker.last_error = format!("worker process check failed: {err}");
                        warn!(worker_id = %worker.id, port = worker.port, error = %err, "worker process check failed");
                        continue;
                    }
                }
            }

            match probe_worker_health(addr.clone(), self.cfg.health_timeout_secs).await {
                Ok(health) => {
                    if let Some(worker) = self.workers.get_mut(idx) {
                        worker.healthy = health.healthy;
                        worker.checked_at = if health.checked_at.is_empty() {
                            Utc::now().to_rfc3339()
                        } else {
                            health.checked_at
                        };
                        worker.last_error = health.last_error;
                    }
                }
                Err(err) => {
                    if let Some(worker) = self.workers.get_mut(idx) {
                        worker.healthy = false;
                        worker.checked_at = Utc::now().to_rfc3339();
                        worker.last_error = err.to_string();
                        warn!(worker_id, %addr, error = %err, "worker health probe failed");
                    }
                }
            }
        }
    }
}

#[derive(Clone)]
struct RuntimeServer {
    pool: Arc<Mutex<WorkerPool>>,
    min_workers: usize,
    max_workers: usize,
}

#[tonic::async_trait]
impl RuntimeService for RuntimeServer {
    async fn submit(
        &self,
        request: Request<TaskRequest>,
    ) -> std::result::Result<Response<TaskReply>, Status> {
        let task = request.into_inner();
        let (idx, addr, worker_id) = {
            let mut pool = self.pool.lock().await;
            let idx = pool.choose_worker().await.map_err(anyhow_to_status)?;
            pool.workers[idx].inflight += 1;
            (
                idx,
                pool.workers[idx].addr.clone(),
                pool.workers[idx].id.clone(),
            )
        };
        let call_result = async {
            let mut client = WorkerServiceClient::connect(addr.clone())
                .await
                .map_err(|e| Status::unavailable(e.to_string()))?;
            let reply = client.execute(Request::new(task)).await?.into_inner();
            Ok::<TaskReply, Status>(reply)
        }
        .await;
        {
            let mut pool = self.pool.lock().await;
            if let Some(w) = pool.workers.get_mut(idx) {
                w.inflight = w.inflight.saturating_sub(1);
            }
            if let Err(err) = &call_result {
                pool.mark_failed(&worker_id, &err.to_string()).await;
            }
        }
        call_result.map(Response::new)
    }

    async fn pool_status(
        &self,
        _request: Request<Empty>,
    ) -> std::result::Result<Response<PoolStatusReply>, Status> {
        let mut pool = self.pool.lock().await;
        pool.probe_all().await;
        Ok(Response::new(PoolStatusReply {
            workers: pool.snapshots(),
            min_workers: self.min_workers as u32,
            max_workers: self.max_workers as u32,
        }))
    }
}

#[derive(Clone)]
struct WorkerServer {
    id: String,
    task_timeout_secs: u64,
    health_timeout_secs: u64,
}

#[tonic::async_trait]
impl WorkerService for WorkerServer {
    async fn execute(
        &self,
        request: Request<TaskRequest>,
    ) -> std::result::Result<Response<TaskReply>, Status> {
        let req = request.into_inner();
        let task_id = Uuid::new_v4().to_string();
        let session_id = req.session_id.clone();
        match execute_sidecar(&self.id, task_id.clone(), req, self.task_timeout_secs).await {
            Ok(reply) => Ok(Response::new(reply)),
            Err(err) => {
                let trace = json!({
                    "task_id": task_id,
                    "session_id": session_id,
                    "worker_id": self.id.clone(),
                    "finished_at": Utc::now().to_rfc3339(),
                    "events": [{
                        "event_type": "error",
                        "payload": err.to_string(),
                        "timestamp": Utc::now().to_rfc3339()
                    }]
                });
                Ok(Response::new(TaskReply {
                    task_id,
                    worker_id: self.id.clone(),
                    status: "error".to_string(),
                    output: err.to_string(),
                    trace_json: trace.to_string(),
                }))
            }
        }
    }

    async fn health(
        &self,
        _request: Request<Empty>,
    ) -> std::result::Result<Response<WorkerHealth>, Status> {
        let checked_at = Utc::now().to_rfc3339();
        let probe_result = probe_python_sidecar(self.health_timeout_secs).await;
        let (healthy, last_error) = match probe_result {
            Ok(()) => (true, String::new()),
            Err(err) => (false, err.to_string()),
        };
        Ok(Response::new(WorkerHealth {
            worker_id: self.id.clone(),
            healthy,
            inflight: 0,
            checked_at,
            last_error,
        }))
    }
}

fn anyhow_to_status(err: anyhow::Error) -> Status {
    Status::internal(err.to_string())
}

async fn execute_sidecar(
    worker_id: &str,
    task_id: String,
    req: TaskRequest,
    timeout_secs: u64,
) -> Result<TaskReply> {
    let started_at = Utc::now().to_rfc3339();
    let context = serde_json::from_str::<Value>(&req.context_json).unwrap_or(json!({}));
    let python = env::var("YIZUTT_PYTHON").unwrap_or_else(|_| "python".to_string());
    let output = timeout(
        Duration::from_secs(timeout_secs),
        Command::new(python)
            .arg("-m")
            .arg("yizutt_agi.executor")
            .arg("--task-id")
            .arg(&task_id)
            .arg("--worker-id")
            .arg(worker_id)
            .arg("--session-id")
            .arg(&req.session_id)
            .arg("--task")
            .arg(&req.task)
            .arg("--context-json")
            .arg(&req.context_json)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .output(),
    )
    .await
    .with_context(|| format!("task timed out after {timeout_secs}s"))??;

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    let mut events = Vec::new();
    let mut final_output = String::new();
    for line in stdout.lines().filter(|line| !line.trim().is_empty()) {
        match serde_json::from_str::<Value>(line) {
            Ok(event) => {
                if event.get("event_type").and_then(Value::as_str) == Some("output") {
                    if let Some(payload) = event.get("payload").and_then(Value::as_str) {
                        final_output.push_str(payload);
                    }
                }
                if event.get("event_type").and_then(Value::as_str) == Some("completed") {
                    if let Some(payload) = event.get("payload").and_then(Value::as_str) {
                        if final_output.is_empty() {
                            final_output.push_str(payload);
                        }
                    }
                }
                events.push(event);
            }
            Err(_) => events.push(json!({
                "event_type": "stdout",
                "payload": line,
                "timestamp": Utc::now().to_rfc3339()
            })),
        }
    }

    let finished_at = Utc::now().to_rfc3339();
    let trace = json!({
        "task_id": task_id,
        "session_id": req.session_id,
        "worker_id": worker_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "context": context,
        "events": events,
        "stderr": stderr.trim(),
        "sidecar_status": output.status.code()
    });

    if !output.status.success() {
        return Err(anyhow!("python sidecar failed: {}", trace));
    }
    if final_output.is_empty() {
        final_output = "task completed without output".to_string();
    }

    Ok(TaskReply {
        task_id,
        worker_id: worker_id.to_string(),
        status: "ok".to_string(),
        output: final_output,
        trace_json: trace.to_string(),
    })
}

async fn probe_python_sidecar(timeout_secs: u64) -> Result<()> {
    let python = env::var("YIZUTT_PYTHON").unwrap_or_else(|_| "python".to_string());
    let output = timeout(
        Duration::from_secs(timeout_secs.max(1)),
        Command::new(python)
            .arg("-c")
            .arg("import yizutt_agi.executor")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .output(),
    )
    .await
    .with_context(|| format!("sidecar health probe timed out after {timeout_secs}s"))??;
    if output.status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&output.stderr);
    Err(anyhow!("sidecar import failed: {}", stderr.trim()))
}

async fn probe_worker_health(addr: String, timeout_secs: u64) -> Result<WorkerHealth> {
    let mut client = timeout(
        Duration::from_secs(timeout_secs.max(1)),
        WorkerServiceClient::connect(addr.clone()),
    )
    .await
    .with_context(|| format!("worker connect timed out after {timeout_secs}s"))?
    .with_context(|| format!("connect {addr}"))?;
    let reply = timeout(
        Duration::from_secs(timeout_secs.max(1)),
        client.health(Request::new(Empty {})),
    )
    .await
    .with_context(|| format!("worker health timed out after {timeout_secs}s"))??;
    Ok(reply.into_inner())
}

async fn run_worker(
    port: u16,
    id: String,
    task_timeout_secs: u64,
    health_timeout_secs: u64,
) -> Result<()> {
    let addr: SocketAddr = format!("127.0.0.1:{port}").parse()?;
    info!(%id, %addr, "worker listening");
    Server::builder()
        .add_service(WorkerServiceServer::new(WorkerServer {
            id,
            task_timeout_secs,
            health_timeout_secs,
        }))
        .serve(addr)
        .await?;
    Ok(())
}

async fn run_runtime(
    bind: String,
    worker_base_port: u16,
    min_workers: usize,
    max_workers: usize,
    home: PathBuf,
    task_timeout_secs: u64,
    health_timeout_secs: u64,
) -> Result<()> {
    fs::create_dir_all(home.join("workers"))?;
    let cfg = RuntimeConfig {
        bind: bind.clone(),
        worker_base_port,
        min_workers,
        max_workers,
        home,
        project_root: env::current_dir()?,
        task_timeout_secs,
        health_timeout_secs,
    };
    let pool = WorkerPool::new(cfg.clone()).await?;
    let server = RuntimeServer {
        pool: Arc::new(Mutex::new(pool)),
        min_workers,
        max_workers,
    };
    let addr: SocketAddr = cfg.bind.parse()?;
    info!(%addr, "runtime listening");
    Server::builder()
        .add_service(RuntimeServiceServer::new(server))
        .serve(addr)
        .await?;
    Ok(())
}

async fn run_submit(
    addr: String,
    task: String,
    session_id: String,
    context_json: String,
) -> Result<()> {
    let mut client = RuntimeServiceClient::connect(addr).await?;
    let reply = client
        .submit(Request::new(TaskRequest {
            session_id,
            task,
            context_json,
        }))
        .await?
        .into_inner();
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "task_id": reply.task_id,
            "worker_id": reply.worker_id,
            "status": reply.status,
            "output": reply.output,
            "trace": serde_json::from_str::<serde_json::Value>(&reply.trace_json).unwrap_or(json!({}))
        }))?
    );
    Ok(())
}

async fn run_status(addr: String) -> Result<()> {
    let mut client = RuntimeServiceClient::connect(addr).await?;
    let reply = client
        .pool_status(Request::new(Empty {}))
        .await?
        .into_inner();
    println!(
        "{}",
        serde_json::to_string_pretty(
            &reply
                .workers
                .iter()
                .map(|w| {
                    json!({
                        "worker_id": w.worker_id,
                        "address": w.address,
                        "inflight": w.inflight,
                        "healthy": w.healthy,
                        "checked_at": w.checked_at,
                        "last_error": w.last_error
                    })
                })
                .collect::<Vec<_>>()
        )?
    );
    Ok(())
}

fn python_path(project_root: &PathBuf) -> String {
    let package_path = project_root.join("python");
    match env::var("PYTHONPATH") {
        Ok(existing) if !existing.is_empty() => format!("{}:{existing}", package_path.display()),
        _ => package_path.display().to_string(),
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();
    let cli = Cli::parse();
    match cli.command {
        Commands::Run {
            bind,
            worker_base_port,
            min_workers,
            max_workers,
            home,
            task_timeout_secs,
            health_timeout_secs,
        } => {
            run_runtime(
                bind,
                worker_base_port,
                min_workers,
                max_workers,
                home,
                task_timeout_secs,
                health_timeout_secs,
            )
            .await
        }
        Commands::Worker {
            port,
            id,
            task_timeout_secs,
            health_timeout_secs,
        } => run_worker(port, id, task_timeout_secs, health_timeout_secs).await,
        Commands::Submit {
            addr,
            task,
            session,
            context_json,
        } => run_submit(addr, task, session, context_json).await,
        Commands::Status { addr } => run_status(addr).await,
    }
}
