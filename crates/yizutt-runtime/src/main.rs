use anyhow::{anyhow, Context, Result};
use chrono::Utc;
use clap::{Parser, Subcommand};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::{mpsc, Mutex};
use tokio::time::{sleep, timeout, Duration};
use tokio_stream::wrappers::ReceiverStream;
use tonic::{transport::Server, Request, Response, Status};
use tracing::{info, warn};
use uuid::Uuid;

mod yizutt;

use yizutt::runtime_service_client::RuntimeServiceClient;
use yizutt::runtime_service_server::{RuntimeService, RuntimeServiceServer};
use yizutt::worker_service_client::WorkerServiceClient;
use yizutt::worker_service_server::{WorkerService, WorkerServiceServer};
use yizutt::{Empty, PoolStatusReply, TaskReply, TaskRequest, TraceEvent, WorkerHealth, WorkerSnapshot};

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
        #[arg(long, default_value_t = false)]
        resume_incomplete_tasks: bool,
        #[arg(long, default_value_t = false)]
        expire_incomplete_tasks: bool,
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
        #[arg(long)]
        stream: bool,
    },
    /// Print worker pool status from a running runtime.
    Status {
        #[arg(long, alias = "runtime-addr", default_value = "http://127.0.0.1:50200")]
        addr: String,
    },
    /// Print persisted task queue status from the local runtime home.
    Tasks {
        #[arg(long, default_value = ".yizutt/runtime")]
        home: PathBuf,
        #[arg(long, default_value = "20")]
        limit: usize,
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RecoveryMode {
    None,
    Resume,
    Expire,
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
    task_log: Arc<Mutex<TaskLog>>,
    min_workers: usize,
    max_workers: usize,
}

#[derive(Clone)]
struct TaskLog {
    path: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct TaskLogRecord {
    task_id: String,
    parent_task_id: String,
    kind: String,
    session_id: String,
    task: String,
    context_json: String,
    worker_id: String,
    worker_task_id: String,
    status: String,
    output: String,
    trace_summary: String,
    timestamp: String,
}

impl TaskLog {
    fn new(path: PathBuf) -> Result<Self> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        Ok(Self { path })
    }

    fn append(&self, record: &TaskLogRecord) -> Result<()> {
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent)?;
        }
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)?;
        writeln!(file, "{}", serde_json::to_string(record)?)?;
        Ok(())
    }

    fn list(path: PathBuf, limit: usize) -> Result<Vec<TaskLogRecord>> {
        let mut items = Self::latest(path)?;
        items.truncate(limit);
        Ok(items)
    }

    fn latest(path: PathBuf) -> Result<Vec<TaskLogRecord>> {
        if !path.exists() {
            return Ok(Vec::new());
        }
        let text = fs::read_to_string(path)?;
        let mut records = Vec::new();
        for line in text.lines().filter(|line| !line.trim().is_empty()) {
            if let Ok(record) = serde_json::from_str::<TaskLogRecord>(line) {
                records.push(record);
            }
        }
        let mut latest = std::collections::BTreeMap::<String, TaskLogRecord>::new();
        for record in records {
            latest.insert(record.task_id.clone(), record);
        }
        let mut items = latest.into_values().collect::<Vec<_>>();
        items.sort_by(|left, right| right.timestamp.cmp(&left.timestamp));
        Ok(items)
    }
}

fn is_final_task_status(status: &str) -> bool {
    matches!(
        status,
        "ok"
            | "error"
            | "failed"
            | "completed"
            | "completed_with_parallel_subtasks"
            | "expired_on_startup"
            | "queue_rejected"
            | "skipped_dependency_failed"
    )
}

fn incomplete_task_records(path: PathBuf) -> Result<Vec<TaskLogRecord>> {
    Ok(TaskLog::latest(path)?
        .into_iter()
        .filter(|record| !is_final_task_status(&record.status))
        .collect())
}

fn make_task_log_record(
    task_id: String,
    parent_task_id: String,
    kind: &str,
    req: &TaskRequest,
    status: &str,
    worker_id: String,
    worker_task_id: String,
    output: String,
    trace_summary: String,
) -> TaskLogRecord {
    TaskLogRecord {
        task_id,
        parent_task_id,
        kind: kind.to_string(),
        session_id: req.session_id.clone(),
        task: req.task.clone(),
        context_json: req.context_json.clone(),
        worker_id,
        worker_task_id,
        status: status.to_string(),
        output: truncate(&output, 2000),
        trace_summary: truncate(&trace_summary, 1200),
        timestamp: Utc::now().to_rfc3339(),
    }
}

async fn append_task_log(task_log: Arc<Mutex<TaskLog>>, record: TaskLogRecord) {
    let log = task_log.lock().await;
    if let Err(err) = log.append(&record) {
        warn!(error = %err, task_id = %record.task_id, "failed to append task log record");
    }
}

#[tonic::async_trait]
impl RuntimeService for RuntimeServer {
    type SubmitStreamStream = ReceiverStream<std::result::Result<TraceEvent, Status>>;

    async fn submit(
        &self,
        request: Request<TaskRequest>,
    ) -> std::result::Result<Response<TaskReply>, Status> {
        let task = request.into_inner();
        let runtime_task_id = Uuid::new_v4().to_string();
        let reply = execute_top_level_task(
            self.pool.clone(),
            self.task_log.clone(),
            runtime_task_id,
            task,
        )
        .await?;
        Ok(Response::new(reply))
    }

    async fn submit_stream(
        &self,
        request: Request<TaskRequest>,
    ) -> std::result::Result<Response<Self::SubmitStreamStream>, Status> {
        let task = request.into_inner();
        let runtime_task_id = Uuid::new_v4().to_string();
        append_task_log(
            self.task_log.clone(),
            make_task_log_record(
                runtime_task_id.clone(),
                String::new(),
                "task_stream",
                &task,
                "queued",
                String::new(),
                String::new(),
                String::new(),
                String::new(),
            ),
        )
        .await;
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
        let pool = self.pool.clone();
        let task_log = self.task_log.clone();
        let task_for_log = task.clone();
        let (tx, rx) = mpsc::channel(32);
        tokio::spawn(async move {
            append_task_log(
                task_log.clone(),
                make_task_log_record(
                    runtime_task_id.clone(),
                    String::new(),
                    "task_stream",
                    &task,
                    "running",
                    worker_id.clone(),
                    String::new(),
                    String::new(),
                    String::new(),
                ),
            )
            .await;
            let mut final_status = "error".to_string();
            let mut final_output = String::new();
            let mut final_worker_task_id = String::new();
            let mut final_trace = String::new();
            let call_result = async {
                let mut client = WorkerServiceClient::connect(addr.clone())
                    .await
                    .map_err(|e| Status::unavailable(e.to_string()))?;
                let mut stream = client
                    .execute_stream(Request::new(task.clone()))
                    .await?
                    .into_inner();
                while let Some(event) = stream.message().await? {
                    if event.final_event {
                        final_status = event.status.clone();
                        final_output = event.output.clone();
                        final_worker_task_id = event.task_id.clone();
                        final_trace = event.event_json.clone();
                    }
                    if tx.send(Ok(event)).await.is_err() {
                        break;
                    }
                }
                Ok::<(), Status>(())
            }
            .await;
            {
                let mut pool = pool.lock().await;
                if let Some(w) = pool.workers.get_mut(idx) {
                    w.inflight = w.inflight.saturating_sub(1);
                }
                if let Err(err) = &call_result {
                    pool.mark_failed(&worker_id, &err.to_string()).await;
                }
            }
            if let Err(err) = call_result {
                append_task_log(
                    task_log,
                    make_task_log_record(
                        runtime_task_id,
                        String::new(),
                        "task_stream",
                        &task_for_log,
                        "error",
                        worker_id,
                        final_worker_task_id,
                        err.to_string(),
                        String::new(),
                    ),
                )
                .await;
                let _ = tx.send(Err(err)).await;
            } else {
                append_task_log(
                    task_log,
                    TaskLogRecord {
                        task_id: runtime_task_id,
                        parent_task_id: String::new(),
                        kind: "task_stream".to_string(),
                        session_id: task_for_log.session_id,
                        task: task_for_log.task,
                        context_json: task_for_log.context_json,
                        worker_id,
                        worker_task_id: final_worker_task_id,
                        status: final_status,
                        output: final_output,
                        trace_summary: trace_summary(&final_trace),
                        timestamp: Utc::now().to_rfc3339(),
                    },
                )
                .await;
            }
        });
        Ok(Response::new(ReceiverStream::new(rx)))
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
    type ExecuteStreamStream = ReceiverStream<std::result::Result<TraceEvent, Status>>;

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

    async fn execute_stream(
        &self,
        request: Request<TaskRequest>,
    ) -> std::result::Result<Response<Self::ExecuteStreamStream>, Status> {
        let req = request.into_inner();
        let task_id = Uuid::new_v4().to_string();
        Ok(Response::new(execute_sidecar_stream(
            self.id.clone(),
            task_id,
            req,
            self.task_timeout_secs,
        )))
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

async fn execute_top_level_task(
    pool: Arc<Mutex<WorkerPool>>,
    task_log: Arc<Mutex<TaskLog>>,
    runtime_task_id: String,
    task: TaskRequest,
) -> std::result::Result<TaskReply, Status> {
    append_task_log(
        task_log.clone(),
        make_task_log_record(
            runtime_task_id.clone(),
            String::new(),
            "task",
            &task,
            "queued",
            String::new(),
            String::new(),
            String::new(),
            String::new(),
        ),
    )
    .await;
    let mut reply = dispatch_runtime_task(
        pool.clone(),
        task_log.clone(),
        runtime_task_id.clone(),
        String::new(),
        "task",
        task.clone(),
    )
    .await?;
    if should_execute_plan_parallel(&task.context_json) {
        let subtasks = extract_plan_subtasks(&reply.trace_json);
        if !subtasks.is_empty() {
            let subtask_results = dispatch_parallel_subtasks(
                pool,
                task_log.clone(),
                runtime_task_id.clone(),
                &task,
                subtasks,
            )
            .await;
            let summary = json!({
                "parent": serde_json::from_str::<Value>(&reply.output).unwrap_or_else(|_| json!(reply.output)),
                "parallel_subtasks": subtask_results,
            });
            reply.output = serde_json::to_string_pretty(&summary).unwrap_or_else(|_| summary.to_string());
            reply.trace_json = merge_parallel_trace(&reply.trace_json, &summary);
            append_task_log(
                task_log,
                make_task_log_record(
                    runtime_task_id,
                    String::new(),
                    "task",
                    &task,
                    "completed_with_parallel_subtasks",
                    reply.worker_id.clone(),
                    reply.task_id.clone(),
                    reply.output.clone(),
                    trace_summary(&reply.trace_json),
                ),
            )
            .await;
        }
    }
    Ok(reply)
}

async fn dispatch_runtime_task(
    pool: Arc<Mutex<WorkerPool>>,
    task_log: Arc<Mutex<TaskLog>>,
    runtime_task_id: String,
    parent_task_id: String,
    kind: &str,
    task: TaskRequest,
) -> std::result::Result<TaskReply, Status> {
    let (idx, addr, worker_id) = {
        let mut pool = pool.lock().await;
        let idx = pool.choose_worker().await.map_err(anyhow_to_status)?;
        pool.workers[idx].inflight += 1;
        (
            idx,
            pool.workers[idx].addr.clone(),
            pool.workers[idx].id.clone(),
        )
    };
    append_task_log(
        task_log.clone(),
        make_task_log_record(
            runtime_task_id.clone(),
            parent_task_id.clone(),
            kind,
            &task,
            "running",
            worker_id.clone(),
            String::new(),
            String::new(),
            String::new(),
        ),
    )
    .await;
    let call_result = async {
        let mut client = WorkerServiceClient::connect(addr.clone())
            .await
            .map_err(|e| Status::unavailable(e.to_string()))?;
        let reply = client.execute(Request::new(task.clone())).await?.into_inner();
        Ok::<TaskReply, Status>(reply)
    }
    .await;
    {
        let mut pool = pool.lock().await;
        if let Some(w) = pool.workers.get_mut(idx) {
            w.inflight = w.inflight.saturating_sub(1);
        }
        if let Err(err) = &call_result {
            pool.mark_failed(&worker_id, &err.to_string()).await;
        }
    }
    match call_result {
        Ok(reply) => {
            append_task_log(
                task_log,
                make_task_log_record(
                    runtime_task_id,
                    parent_task_id,
                    kind,
                    &task,
                    &reply.status,
                    worker_id,
                    reply.task_id.clone(),
                    reply.output.clone(),
                    trace_summary(&reply.trace_json),
                ),
            )
            .await;
            Ok(reply)
        }
        Err(err) => {
            append_task_log(
                task_log,
                make_task_log_record(
                    runtime_task_id,
                    parent_task_id,
                    kind,
                    &task,
                    "error",
                    worker_id,
                    String::new(),
                    err.to_string(),
                    String::new(),
                ),
            )
            .await;
            Err(err)
        }
    }
}

async fn dispatch_parallel_subtasks(
    pool: Arc<Mutex<WorkerPool>>,
    task_log: Arc<Mutex<TaskLog>>,
    parent_task_id: String,
    parent: &TaskRequest,
    subtasks: Vec<Value>,
) -> Vec<Value> {
    let context = serde_json::from_str::<Value>(&parent.context_json).unwrap_or_else(|_| json!({}));
    let max_queue_depth = context_usize(&context, "max_parallel_subtasks", 16).max(1);
    let max_concurrency = context_usize(&context, "max_parallel_concurrency", 4).max(1);
    let max_retries = context_usize(&context, "max_subtask_retries", 0);
    if subtasks.len() > max_queue_depth {
        return vec![json!({
            "status": "queue_rejected",
            "reason": "max_parallel_subtasks_exceeded",
            "subtask_count": subtasks.len(),
            "max_parallel_subtasks": max_queue_depth,
        })];
    }

    let plans = normalize_subtask_plans(subtasks);
    let mut results = Vec::new();
    let mut completed = std::collections::BTreeMap::<String, bool>::new();
    let mut pending = plans;
    while !pending.is_empty() {
        let ready_indices = pending
            .iter()
            .enumerate()
            .filter(|(_, plan)| {
                plan.depends_on
                    .iter()
                    .all(|dep| completed.get(dep).copied().unwrap_or(false))
            })
            .map(|(idx, _)| idx)
            .collect::<Vec<_>>();
        if ready_indices.is_empty() {
            for plan in pending {
                let missing = plan
                    .depends_on
                    .iter()
                    .filter(|dep| !completed.get(*dep).copied().unwrap_or(false))
                    .cloned()
                    .collect::<Vec<_>>();
                completed.insert(plan.id.clone(), false);
                results.push(json!({
                    "id": plan.id,
                    "status": "skipped_dependency_failed",
                    "missing_dependencies": missing,
                }));
            }
            break;
        }

        let mut ready = Vec::new();
        let mut remaining = Vec::new();
        for (idx, plan) in pending.into_iter().enumerate() {
            if ready_indices.contains(&idx) {
                ready.push(plan);
            } else {
                remaining.push(plan);
            }
        }
        for chunk in ready.chunks(max_concurrency) {
            let mut handles = Vec::new();
            for plan in chunk.iter().cloned() {
                let req = TaskRequest {
                    session_id: parent.session_id.clone(),
                    task: plan.objective.clone(),
                    context_json: child_context(&parent.context_json, &parent_task_id, &plan.id, &parent.task).to_string(),
                };
                let pool = pool.clone();
                let task_log = task_log.clone();
                let parent_task_id = parent_task_id.clone();
                handles.push(tokio::spawn(async move {
                    dispatch_subtask_with_retries(
                        pool,
                        task_log,
                        parent_task_id,
                        plan,
                        req,
                        max_retries,
                    )
                    .await
                }));
            }
            for handle in handles {
                match handle.await {
                    Ok(item) => {
                        let id = item.get("id").and_then(Value::as_str).unwrap_or("").to_string();
                        let ok = item.get("status").and_then(Value::as_str) == Some("ok");
                        if !id.is_empty() {
                            completed.insert(id, ok);
                        }
                        results.push(item);
                    }
                    Err(err) => results.push(json!({"status": "join_error", "error": err.to_string()})),
                }
            }
        }
        pending = remaining;
    }
    results
}

#[derive(Clone)]
struct SubtaskPlan {
    id: String,
    title: String,
    objective: String,
    depends_on: Vec<String>,
}

fn normalize_subtask_plans(subtasks: Vec<Value>) -> Vec<SubtaskPlan> {
    subtasks
        .into_iter()
        .enumerate()
        .filter_map(|(idx, subtask)| {
            let id = subtask
                .get("id")
                .and_then(Value::as_str)
                .map(str::to_string)
                .unwrap_or_else(|| format!("step-{}", idx + 1));
            let title = subtask
                .get("title")
                .and_then(Value::as_str)
                .unwrap_or(&id)
                .to_string();
            let objective = subtask
                .get("objective")
                .or_else(|| subtask.get("task"))
                .or_else(|| subtask.get("description"))
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string();
            if objective.trim().is_empty() {
                return None;
            }
            Some(SubtaskPlan {
                id,
                title,
                objective,
                depends_on: value_to_strings(subtask.get("depends_on")),
            })
        })
        .collect()
}

async fn dispatch_subtask_with_retries(
    pool: Arc<Mutex<WorkerPool>>,
    task_log: Arc<Mutex<TaskLog>>,
    parent_task_id: String,
    plan: SubtaskPlan,
    req: TaskRequest,
    max_retries: usize,
) -> Value {
    let mut attempts = Vec::new();
    for attempt in 0..=max_retries {
        let runtime_subtask_id = if attempt == 0 {
            format!("{}:{}", parent_task_id, plan.id)
        } else {
            format!("{}:{}:retry-{}", parent_task_id, plan.id, attempt)
        };
        append_task_log(
            task_log.clone(),
            make_task_log_record(
                runtime_subtask_id.clone(),
                parent_task_id.clone(),
                "subtask",
                &req,
                if attempt == 0 { "queued" } else { "retry_queued" },
                String::new(),
                String::new(),
                String::new(),
                String::new(),
            ),
        )
        .await;
        let result = dispatch_runtime_task(
            pool.clone(),
            task_log.clone(),
            runtime_subtask_id.clone(),
            parent_task_id.clone(),
            "subtask",
            req.clone(),
        )
        .await;
        match result {
            Ok(reply) => {
                let item = json!({
                    "attempt": attempt + 1,
                    "runtime_task_id": runtime_subtask_id,
                    "worker_task_id": reply.task_id,
                    "worker_id": reply.worker_id,
                    "status": reply.status,
                    "output": reply.output,
                    "trace": serde_json::from_str::<Value>(&reply.trace_json).unwrap_or_else(|_| json!({})),
                });
                let ok = item.get("status").and_then(Value::as_str) == Some("ok");
                attempts.push(item);
                if ok {
                    return json!({
                        "id": plan.id,
                        "title": plan.title,
                        "status": "ok",
                        "attempts": attempts,
                    });
                }
            }
            Err(err) => attempts.push(json!({
                "attempt": attempt + 1,
                "runtime_task_id": runtime_subtask_id,
                "status": "error",
                "error": err.to_string(),
            })),
        }
    }
    json!({
        "id": plan.id,
        "title": plan.title,
        "status": "failed",
        "attempts": attempts,
    })
}

fn should_execute_plan_parallel(context_json: &str) -> bool {
    let context = serde_json::from_str::<Value>(context_json).unwrap_or_else(|_| json!({}));
    for key in ["execute_plan_parallel", "runtime_execute_plan_parallel"] {
        if truthy(context.get(key)) {
            return true;
        }
    }
    false
}

fn truthy(value: Option<&Value>) -> bool {
    match value {
        Some(Value::Bool(flag)) => *flag,
        Some(Value::String(text)) => matches!(text.to_lowercase().as_str(), "1" | "true" | "yes" | "on"),
        Some(Value::Number(number)) => number.as_i64().unwrap_or_default() != 0,
        _ => false,
    }
}

fn context_usize(context: &Value, key: &str, default: usize) -> usize {
    match context.get(key) {
        Some(Value::Number(number)) => number.as_u64().map(|value| value as usize).unwrap_or(default),
        Some(Value::String(text)) => text.parse::<usize>().unwrap_or(default),
        _ => default,
    }
}

fn value_to_strings(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::Array(items)) => items
            .iter()
            .filter_map(Value::as_str)
            .map(str::to_string)
            .collect(),
        Some(Value::String(text)) => text
            .split(',')
            .map(str::trim)
            .filter(|item| !item.is_empty())
            .map(str::to_string)
            .collect(),
        _ => Vec::new(),
    }
}

fn extract_plan_subtasks(trace_json: &str) -> Vec<Value> {
    let trace = serde_json::from_str::<Value>(trace_json).unwrap_or_else(|_| json!({}));
    let events = trace
        .get("events")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    for event in events {
        if event.get("event_type").and_then(Value::as_str) != Some("plan_created") {
            continue;
        }
        if let Some(plan) = event.get("plan").and_then(Value::as_array) {
            return plan.clone();
        }
        if let Some(payload) = event.get("payload").and_then(Value::as_str) {
            let parsed = serde_json::from_str::<Value>(payload).unwrap_or_else(|_| json!({}));
            if let Some(plan) = parsed.get("plan").and_then(Value::as_array) {
                return plan.clone();
            }
        }
    }
    Vec::new()
}

fn child_context(parent_context_json: &str, parent_task_id: &str, subtask_id: &str, parent_task: &str) -> Value {
    let mut context = serde_json::from_str::<Value>(parent_context_json).unwrap_or_else(|_| json!({}));
    if !context.is_object() {
        context = json!({});
    }
    if let Some(map) = context.as_object_mut() {
        map.insert("orchestrate".to_string(), Value::Bool(false));
        map.insert("execute_plan".to_string(), Value::Bool(false));
        map.insert("execute_plan_parallel".to_string(), Value::Bool(false));
        map.insert("parent_task_id".to_string(), Value::String(parent_task_id.to_string()));
        map.insert("subtask_id".to_string(), Value::String(subtask_id.to_string()));
        map.insert("parent_task".to_string(), Value::String(parent_task.to_string()));
    }
    context
}

fn merge_parallel_trace(parent_trace_json: &str, parallel_summary: &Value) -> String {
    let mut trace = serde_json::from_str::<Value>(parent_trace_json).unwrap_or_else(|_| json!({}));
    if let Some(map) = trace.as_object_mut() {
        map.insert("parallel_subtasks".to_string(), parallel_summary["parallel_subtasks"].clone());
        map.insert("parallel_finished_at".to_string(), Value::String(Utc::now().to_rfc3339()));
    }
    trace.to_string()
}

fn trace_summary(trace_json: &str) -> String {
    let trace = serde_json::from_str::<Value>(trace_json).unwrap_or_else(|_| json!({}));
    if let Some(events) = trace.get("events").and_then(Value::as_array) {
        let mut parts = Vec::new();
        for event in events.iter().rev().take(4) {
            let event_type = event
                .get("event_type")
                .and_then(Value::as_str)
                .unwrap_or("event");
            let payload = event.get("payload").and_then(Value::as_str).unwrap_or("");
            parts.push(format!("{event_type}: {}", truncate(payload, 240)));
        }
        parts.reverse();
        return parts.join("\n");
    }
    truncate(trace_json, 1000)
}

fn truncate(text: &str, max_chars: usize) -> String {
    if text.chars().count() <= max_chars {
        return text.to_string();
    }
    let mut output = text.chars().take(max_chars).collect::<String>();
    output.push_str("...");
    output
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

fn execute_sidecar_stream(
    worker_id: String,
    task_id: String,
    req: TaskRequest,
    timeout_secs: u64,
) -> ReceiverStream<std::result::Result<TraceEvent, Status>> {
    let (tx, rx) = mpsc::channel(32);
    tokio::spawn(async move {
        let error_task_id = task_id.clone();
        let error_worker_id = worker_id.clone();
        let stream_tx = tx.clone();
        let run_result = timeout(
            Duration::from_secs(timeout_secs),
            async move {
                let started_at = Utc::now().to_rfc3339();
                let context = serde_json::from_str::<Value>(&req.context_json).unwrap_or(json!({}));
                let python = env::var("YIZUTT_PYTHON").unwrap_or_else(|_| "python".to_string());
                let mut child = Command::new(python)
                    .arg("-m")
                    .arg("yizutt_agi.executor")
                    .arg("--task-id")
                    .arg(&task_id)
                    .arg("--worker-id")
                    .arg(&worker_id)
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
                    .spawn()
                    .with_context(|| "spawn python sidecar for stream")?;
                let stdout = child
                    .stdout
                    .take()
                    .ok_or_else(|| anyhow!("python sidecar stdout was not captured"))?;
                let stderr = child.stderr.take();
                let stderr_task = tokio::spawn(async move {
                    let mut text = String::new();
                    if let Some(mut stderr) = stderr {
                        let _ = stderr.read_to_string(&mut text).await;
                    }
                    text
                });
                let mut lines = BufReader::new(stdout).lines();
                let mut events = Vec::new();
                let mut final_output = String::new();
                while let Some(line) = lines.next_line().await? {
                    if line.trim().is_empty() {
                        continue;
                    }
                    let event = serde_json::from_str::<Value>(&line).unwrap_or_else(|_| {
                        json!({
                            "event_type": "stdout",
                            "payload": line,
                            "timestamp": Utc::now().to_rfc3339()
                        })
                    });
                    if event.get("event_type").and_then(Value::as_str) == Some("output") {
                        if let Some(payload) = event.get("payload").and_then(Value::as_str) {
                            final_output.push_str(payload);
                        }
                    }
                    if event.get("event_type").and_then(Value::as_str) == Some("completed")
                        && final_output.is_empty()
                    {
                        if let Some(payload) = event.get("payload").and_then(Value::as_str) {
                            final_output.push_str(payload);
                        }
                    }
                    events.push(event.clone());
                    if stream_tx
                        .send(Ok(TraceEvent {
                            task_id: task_id.clone(),
                            worker_id: worker_id.clone(),
                            event_json: event.to_string(),
                            final_event: false,
                            status: "event".to_string(),
                            output: String::new(),
                        }))
                        .await
                        .is_err()
                    {
                        return Ok::<(), anyhow::Error>(());
                    }
                }
                let status = child.wait().await?;
                let stderr = stderr_task.await.unwrap_or_default();
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
                    "sidecar_status": status.code()
                });
                let stream_status = if status.success() { "ok" } else { "error" };
                if final_output.is_empty() {
                    final_output = if status.success() {
                        "task completed without output".to_string()
                    } else {
                        format!("python sidecar failed: {}", stderr.trim())
                    };
                }
                let _ = stream_tx
                    .send(Ok(TraceEvent {
                        task_id: trace
                            .get("task_id")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                        worker_id: trace
                            .get("worker_id")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_string(),
                        event_json: trace.to_string(),
                        final_event: true,
                        status: stream_status.to_string(),
                        output: final_output,
                    }))
                    .await;
                Ok::<(), anyhow::Error>(())
            },
        )
        .await;
        match run_result {
            Ok(Ok(())) => {}
            Ok(Err(err)) => {
                let event = json!({
                    "event_type": "error",
                    "payload": err.to_string(),
                    "timestamp": Utc::now().to_rfc3339()
                });
                let _ = tx
                    .send(Ok(TraceEvent {
                        task_id: error_task_id,
                        worker_id: error_worker_id,
                        event_json: event.to_string(),
                        final_event: true,
                        status: "error".to_string(),
                        output: err.to_string(),
                    }))
                    .await;
            }
            Err(_) => {
                let message = format!("task timed out after {timeout_secs}s");
                let event = json!({
                    "event_type": "error",
                    "payload": message,
                    "timestamp": Utc::now().to_rfc3339()
                });
                let _ = tx
                    .send(Ok(TraceEvent {
                        task_id: error_task_id,
                        worker_id: error_worker_id,
                        event_json: event.to_string(),
                        final_event: true,
                        status: "error".to_string(),
                        output: message,
                    }))
                    .await;
            }
        }
    });
    ReceiverStream::new(rx)
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

async fn recover_incomplete_tasks(
    pool: Arc<Mutex<WorkerPool>>,
    task_log: Arc<Mutex<TaskLog>>,
    log_path: PathBuf,
    mode: RecoveryMode,
) -> Result<()> {
    if mode == RecoveryMode::None {
        return Ok(());
    }
    let incomplete = incomplete_task_records(log_path)?;
    if incomplete.is_empty() {
        return Ok(());
    }
    info!(count = incomplete.len(), ?mode, "recovering incomplete task log records");
    for record in incomplete {
        let req = TaskRequest {
            session_id: record.session_id.clone(),
            task: record.task.clone(),
            context_json: record.context_json.clone(),
        };
        match mode {
            RecoveryMode::Expire => {
                append_task_log(
                    task_log.clone(),
                    make_task_log_record(
                        record.task_id,
                        record.parent_task_id,
                        &record.kind,
                        &req,
                        "expired_on_startup",
                        String::new(),
                        record.worker_task_id,
                        "task expired by runtime startup recovery".to_string(),
                        "expired_on_startup".to_string(),
                    ),
                )
                .await;
            }
            RecoveryMode::Resume => {
                append_task_log(
                    task_log.clone(),
                    make_task_log_record(
                        record.task_id.clone(),
                        record.parent_task_id.clone(),
                        &record.kind,
                        &req,
                        "recovery_queued",
                        String::new(),
                        record.worker_task_id.clone(),
                        String::new(),
                        "recovery_queued".to_string(),
                    ),
                )
                .await;
                if record.parent_task_id.is_empty() && record.kind == "task" {
                    let _ = execute_top_level_task(
                        pool.clone(),
                        task_log.clone(),
                        record.task_id,
                        req,
                    )
                    .await;
                } else {
                    let _ = dispatch_runtime_task(
                        pool.clone(),
                        task_log.clone(),
                        record.task_id,
                        record.parent_task_id,
                        &record.kind,
                        req,
                    )
                    .await;
                }
            }
            RecoveryMode::None => {}
        }
    }
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
    recovery_mode: RecoveryMode,
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
    let pool = Arc::new(Mutex::new(WorkerPool::new(cfg.clone()).await?));
    let task_log = Arc::new(Mutex::new(TaskLog::new(cfg.home.join("tasks.jsonl"))?));
    recover_incomplete_tasks(
        pool.clone(),
        task_log.clone(),
        cfg.home.join("tasks.jsonl"),
        recovery_mode,
    )
    .await?;
    let server = RuntimeServer {
        pool,
        task_log,
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
    stream: bool,
) -> Result<()> {
    let mut client = RuntimeServiceClient::connect(addr).await?;
    if stream {
        let mut events = client
            .submit_stream(Request::new(TaskRequest {
                session_id,
                task,
                context_json,
            }))
            .await?
            .into_inner();
        while let Some(event) = events.message().await? {
            let event_json = serde_json::from_str::<Value>(&event.event_json).unwrap_or(json!({
                "raw": event.event_json
            }));
            println!(
                "{}",
                serde_json::to_string_pretty(&json!({
                    "task_id": event.task_id,
                    "worker_id": event.worker_id,
                    "status": event.status,
                    "final": event.final_event,
                    "output": event.output,
                    "event": event_json
                }))?
            );
        }
        return Ok(());
    }
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

fn run_tasks(home: PathBuf, limit: usize) -> Result<()> {
    let items = TaskLog::list(home.join("tasks.jsonl"), limit)?;
    println!("{}", serde_json::to_string_pretty(&items)?);
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
            resume_incomplete_tasks,
            expire_incomplete_tasks,
        } => {
            if resume_incomplete_tasks && expire_incomplete_tasks {
                return Err(anyhow!(
                    "--resume-incomplete-tasks and --expire-incomplete-tasks are mutually exclusive"
                ));
            }
            let recovery_mode = if resume_incomplete_tasks {
                RecoveryMode::Resume
            } else if expire_incomplete_tasks {
                RecoveryMode::Expire
            } else {
                RecoveryMode::None
            };
            run_runtime(
                bind,
                worker_base_port,
                min_workers,
                max_workers,
                home,
                task_timeout_secs,
                health_timeout_secs,
                recovery_mode,
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
            stream,
        } => run_submit(addr, task, session, context_json, stream).await,
        Commands::Status { addr } => run_status(addr).await,
        Commands::Tasks { home, limit } => run_tasks(home, limit),
    }
}
