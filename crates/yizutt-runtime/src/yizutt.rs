#[derive(Clone, PartialEq, ::prost::Message)]
pub struct Empty {}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TaskRequest {
    #[prost(string, tag = "1")]
    pub session_id: String,
    #[prost(string, tag = "2")]
    pub task: String,
    #[prost(string, tag = "3")]
    pub context_json: String,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TaskReply {
    #[prost(string, tag = "1")]
    pub task_id: String,
    #[prost(string, tag = "2")]
    pub worker_id: String,
    #[prost(string, tag = "3")]
    pub status: String,
    #[prost(string, tag = "4")]
    pub output: String,
    #[prost(string, tag = "5")]
    pub trace_json: String,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct TraceEvent {
    #[prost(string, tag = "1")]
    pub task_id: String,
    #[prost(string, tag = "2")]
    pub worker_id: String,
    #[prost(string, tag = "3")]
    pub event_json: String,
    #[prost(bool, tag = "4")]
    pub final_event: bool,
    #[prost(string, tag = "5")]
    pub status: String,
    #[prost(string, tag = "6")]
    pub output: String,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct WorkerHealth {
    #[prost(string, tag = "1")]
    pub worker_id: String,
    #[prost(bool, tag = "2")]
    pub healthy: bool,
    #[prost(uint32, tag = "3")]
    pub inflight: u32,
    #[prost(string, tag = "4")]
    pub checked_at: String,
    #[prost(string, tag = "5")]
    pub last_error: String,
    #[prost(string, tag = "6")]
    pub worker_kind: String,
    #[prost(string, tag = "7")]
    pub sandbox_profile: String,
    #[prost(string, tag = "8")]
    pub isolation_status: String,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct WorkerSnapshot {
    #[prost(string, tag = "1")]
    pub worker_id: String,
    #[prost(string, tag = "2")]
    pub address: String,
    #[prost(uint32, tag = "3")]
    pub inflight: u32,
    #[prost(bool, tag = "4")]
    pub healthy: bool,
    #[prost(string, tag = "5")]
    pub checked_at: String,
    #[prost(string, tag = "6")]
    pub last_error: String,
    #[prost(string, tag = "7")]
    pub worker_kind: String,
    #[prost(string, tag = "8")]
    pub sandbox_profile: String,
    #[prost(string, tag = "9")]
    pub isolation_status: String,
}

#[derive(Clone, PartialEq, ::prost::Message)]
pub struct PoolStatusReply {
    #[prost(message, repeated, tag = "1")]
    pub workers: ::prost::alloc::vec::Vec<WorkerSnapshot>,
    #[prost(uint32, tag = "2")]
    pub min_workers: u32,
    #[prost(uint32, tag = "3")]
    pub max_workers: u32,
    #[prost(uint32, tag = "4")]
    pub max_inflight_per_worker: u32,
    #[prost(uint32, tag = "5")]
    pub max_runtime_queue_depth: u32,
    #[prost(uint32, tag = "6")]
    pub current_inflight: u32,
    #[prost(uint64, tag = "7")]
    pub backpressure_rejections: u64,
}

pub mod runtime_service_client {
    use super::{Empty, PoolStatusReply, TaskReply, TaskRequest, TraceEvent};
    use tonic::codegen::*;

    #[derive(Debug, Clone)]
    pub struct RuntimeServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }

    impl RuntimeServiceClient<tonic::transport::Channel> {
        pub async fn connect<D>(dst: D) -> Result<Self, tonic::transport::Error>
        where
            D: TryInto<tonic::transport::Endpoint>,
            D::Error: Into<StdError>,
        {
            let conn = tonic::transport::Endpoint::new(dst)?.connect().await?;
            Ok(Self::new(conn))
        }
    }

    impl<T> RuntimeServiceClient<T>
    where
        T: tonic::client::GrpcService<tonic::body::Body>,
        T::Error: Into<StdError>,
        T::ResponseBody: Body<Data = Bytes> + Send + 'static,
        <T::ResponseBody as Body>::Error: Into<StdError> + Send,
    {
        pub fn new(inner: T) -> Self {
            Self {
                inner: tonic::client::Grpc::new(inner),
            }
        }

        pub async fn submit(
            &mut self,
            request: impl tonic::IntoRequest<TaskRequest>,
        ) -> Result<tonic::Response<TaskReply>, tonic::Status> {
            self.inner.ready().await.map_err(|e| {
                tonic::Status::unknown(format!("service was not ready: {}", e.into()))
            })?;
            let path = http::uri::PathAndQuery::from_static("/yizutt.RuntimeService/Submit");
            self.inner
                .unary(
                    request.into_request(),
                    path,
                    tonic_prost::ProstCodec::default(),
                )
                .await
        }

        pub async fn submit_stream(
            &mut self,
            request: impl tonic::IntoRequest<TaskRequest>,
        ) -> Result<tonic::Response<tonic::codec::Streaming<TraceEvent>>, tonic::Status> {
            self.inner.ready().await.map_err(|e| {
                tonic::Status::unknown(format!("service was not ready: {}", e.into()))
            })?;
            let path = http::uri::PathAndQuery::from_static("/yizutt.RuntimeService/SubmitStream");
            self.inner
                .server_streaming(
                    request.into_request(),
                    path,
                    tonic_prost::ProstCodec::default(),
                )
                .await
        }

        pub async fn pool_status(
            &mut self,
            request: impl tonic::IntoRequest<Empty>,
        ) -> Result<tonic::Response<PoolStatusReply>, tonic::Status> {
            self.inner.ready().await.map_err(|e| {
                tonic::Status::unknown(format!("service was not ready: {}", e.into()))
            })?;
            let path = http::uri::PathAndQuery::from_static("/yizutt.RuntimeService/PoolStatus");
            self.inner
                .unary(
                    request.into_request(),
                    path,
                    tonic_prost::ProstCodec::default(),
                )
                .await
        }
    }
}

pub mod worker_service_client {
    use super::{Empty, TaskReply, TaskRequest, TraceEvent, WorkerHealth};
    use tonic::codegen::*;

    #[derive(Debug, Clone)]
    pub struct WorkerServiceClient<T> {
        inner: tonic::client::Grpc<T>,
    }

    impl WorkerServiceClient<tonic::transport::Channel> {
        pub async fn connect<D>(dst: D) -> Result<Self, tonic::transport::Error>
        where
            D: TryInto<tonic::transport::Endpoint>,
            D::Error: Into<StdError>,
        {
            let conn = tonic::transport::Endpoint::new(dst)?.connect().await?;
            Ok(Self::new(conn))
        }
    }

    impl<T> WorkerServiceClient<T>
    where
        T: tonic::client::GrpcService<tonic::body::Body>,
        T::Error: Into<StdError>,
        T::ResponseBody: Body<Data = Bytes> + Send + 'static,
        <T::ResponseBody as Body>::Error: Into<StdError> + Send,
    {
        pub fn new(inner: T) -> Self {
            Self {
                inner: tonic::client::Grpc::new(inner),
            }
        }

        pub async fn execute(
            &mut self,
            request: impl tonic::IntoRequest<TaskRequest>,
        ) -> Result<tonic::Response<TaskReply>, tonic::Status> {
            self.inner.ready().await.map_err(|e| {
                tonic::Status::unknown(format!("service was not ready: {}", e.into()))
            })?;
            let path = http::uri::PathAndQuery::from_static("/yizutt.WorkerService/Execute");
            self.inner
                .unary(
                    request.into_request(),
                    path,
                    tonic_prost::ProstCodec::default(),
                )
                .await
        }

        pub async fn execute_stream(
            &mut self,
            request: impl tonic::IntoRequest<TaskRequest>,
        ) -> Result<tonic::Response<tonic::codec::Streaming<TraceEvent>>, tonic::Status> {
            self.inner.ready().await.map_err(|e| {
                tonic::Status::unknown(format!("service was not ready: {}", e.into()))
            })?;
            let path = http::uri::PathAndQuery::from_static("/yizutt.WorkerService/ExecuteStream");
            self.inner
                .server_streaming(
                    request.into_request(),
                    path,
                    tonic_prost::ProstCodec::default(),
                )
                .await
        }

        #[allow(dead_code)]
        pub async fn health(
            &mut self,
            request: impl tonic::IntoRequest<Empty>,
        ) -> Result<tonic::Response<WorkerHealth>, tonic::Status> {
            self.inner.ready().await.map_err(|e| {
                tonic::Status::unknown(format!("service was not ready: {}", e.into()))
            })?;
            let path = http::uri::PathAndQuery::from_static("/yizutt.WorkerService/Health");
            self.inner
                .unary(
                    request.into_request(),
                    path,
                    tonic_prost::ProstCodec::default(),
                )
                .await
        }
    }
}

pub mod runtime_service_server {
    use super::{Empty, PoolStatusReply, TaskReply, TaskRequest, TraceEvent};
    use std::sync::Arc;
    use std::task::{Context, Poll};
    use tonic::codegen::*;

    #[tonic::async_trait]
    pub trait RuntimeService: Send + Sync + 'static {
        async fn submit(
            &self,
            request: tonic::Request<TaskRequest>,
        ) -> Result<tonic::Response<TaskReply>, tonic::Status>;

        type SubmitStreamStream: tonic::codegen::tokio_stream::Stream<Item = Result<TraceEvent, tonic::Status>>
            + Send
            + 'static;

        async fn submit_stream(
            &self,
            request: tonic::Request<TaskRequest>,
        ) -> Result<tonic::Response<Self::SubmitStreamStream>, tonic::Status>;

        async fn pool_status(
            &self,
            request: tonic::Request<Empty>,
        ) -> Result<tonic::Response<PoolStatusReply>, tonic::Status>;
    }

    #[derive(Debug)]
    pub struct RuntimeServiceServer<T: RuntimeService> {
        inner: Arc<T>,
    }

    impl<T: RuntimeService> RuntimeServiceServer<T> {
        pub fn new(inner: T) -> Self {
            Self {
                inner: Arc::new(inner),
            }
        }
    }

    impl<T: RuntimeService> Clone for RuntimeServiceServer<T> {
        fn clone(&self) -> Self {
            Self {
                inner: self.inner.clone(),
            }
        }
    }

    impl<T, B> Service<http::Request<B>> for RuntimeServiceServer<T>
    where
        T: RuntimeService,
        B: Body + Send + 'static,
        B::Error: Into<StdError> + Send + 'static,
    {
        type Response = http::Response<tonic::body::Body>;
        type Error = std::convert::Infallible;
        type Future = BoxFuture<Self::Response, Self::Error>;

        fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }

        fn call(&mut self, req: http::Request<B>) -> Self::Future {
            match req.uri().path() {
                "/yizutt.RuntimeService/Submit" => {
                    struct SubmitSvc<T: RuntimeService>(pub Arc<T>);
                    impl<T: RuntimeService> tonic::server::UnaryService<TaskRequest> for SubmitSvc<T> {
                        type Response = TaskReply;
                        type Future = BoxFuture<tonic::Response<Self::Response>, tonic::Status>;
                        fn call(&mut self, request: tonic::Request<TaskRequest>) -> Self::Future {
                            let inner = self.0.clone();
                            let fut = async move { inner.submit(request).await };
                            Box::pin(fut)
                        }
                    }
                    let inner = self.inner.clone();
                    Box::pin(async move {
                        let method = SubmitSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec);
                        Ok(grpc.unary(method, req).await)
                    })
                }
                "/yizutt.RuntimeService/SubmitStream" => {
                    struct SubmitStreamSvc<T: RuntimeService>(pub Arc<T>);
                    impl<T: RuntimeService> tonic::server::ServerStreamingService<TaskRequest> for SubmitStreamSvc<T> {
                        type Response = TraceEvent;
                        type ResponseStream = T::SubmitStreamStream;
                        type Future =
                            BoxFuture<tonic::Response<Self::ResponseStream>, tonic::Status>;
                        fn call(&mut self, request: tonic::Request<TaskRequest>) -> Self::Future {
                            let inner = self.0.clone();
                            let fut = async move { inner.submit_stream(request).await };
                            Box::pin(fut)
                        }
                    }
                    let inner = self.inner.clone();
                    Box::pin(async move {
                        let method = SubmitStreamSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec);
                        Ok(grpc.server_streaming(method, req).await)
                    })
                }
                "/yizutt.RuntimeService/PoolStatus" => {
                    struct PoolStatusSvc<T: RuntimeService>(pub Arc<T>);
                    impl<T: RuntimeService> tonic::server::UnaryService<Empty> for PoolStatusSvc<T> {
                        type Response = PoolStatusReply;
                        type Future = BoxFuture<tonic::Response<Self::Response>, tonic::Status>;
                        fn call(&mut self, request: tonic::Request<Empty>) -> Self::Future {
                            let inner = self.0.clone();
                            let fut = async move { inner.pool_status(request).await };
                            Box::pin(fut)
                        }
                    }
                    let inner = self.inner.clone();
                    Box::pin(async move {
                        let method = PoolStatusSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec);
                        Ok(grpc.unary(method, req).await)
                    })
                }
                _ => Box::pin(async move { Ok(unimplemented_response()) }),
            }
        }
    }

    impl<T: RuntimeService> tonic::server::NamedService for RuntimeServiceServer<T> {
        const NAME: &'static str = "yizutt.RuntimeService";
    }

    fn unimplemented_response() -> http::Response<tonic::body::Body> {
        let mut response = http::Response::new(tonic::body::Body::empty());
        *response.status_mut() = http::StatusCode::OK;
        response
            .headers_mut()
            .insert("grpc-status", http::HeaderValue::from_static("12"));
        response.headers_mut().insert(
            "content-type",
            http::HeaderValue::from_static("application/grpc"),
        );
        response
    }
}

pub mod worker_service_server {
    use super::{Empty, TaskReply, TaskRequest, TraceEvent, WorkerHealth};
    use std::sync::Arc;
    use std::task::{Context, Poll};
    use tonic::codegen::*;

    #[tonic::async_trait]
    pub trait WorkerService: Send + Sync + 'static {
        async fn execute(
            &self,
            request: tonic::Request<TaskRequest>,
        ) -> Result<tonic::Response<TaskReply>, tonic::Status>;

        type ExecuteStreamStream: tonic::codegen::tokio_stream::Stream<Item = Result<TraceEvent, tonic::Status>>
            + Send
            + 'static;

        async fn execute_stream(
            &self,
            request: tonic::Request<TaskRequest>,
        ) -> Result<tonic::Response<Self::ExecuteStreamStream>, tonic::Status>;

        async fn health(
            &self,
            request: tonic::Request<Empty>,
        ) -> Result<tonic::Response<WorkerHealth>, tonic::Status>;
    }

    #[derive(Debug)]
    pub struct WorkerServiceServer<T: WorkerService> {
        inner: Arc<T>,
    }

    impl<T: WorkerService> WorkerServiceServer<T> {
        pub fn new(inner: T) -> Self {
            Self {
                inner: Arc::new(inner),
            }
        }
    }

    impl<T: WorkerService> Clone for WorkerServiceServer<T> {
        fn clone(&self) -> Self {
            Self {
                inner: self.inner.clone(),
            }
        }
    }

    impl<T, B> Service<http::Request<B>> for WorkerServiceServer<T>
    where
        T: WorkerService,
        B: Body + Send + 'static,
        B::Error: Into<StdError> + Send + 'static,
    {
        type Response = http::Response<tonic::body::Body>;
        type Error = std::convert::Infallible;
        type Future = BoxFuture<Self::Response, Self::Error>;

        fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
            Poll::Ready(Ok(()))
        }

        fn call(&mut self, req: http::Request<B>) -> Self::Future {
            match req.uri().path() {
                "/yizutt.WorkerService/Execute" => {
                    struct ExecuteSvc<T: WorkerService>(pub Arc<T>);
                    impl<T: WorkerService> tonic::server::UnaryService<TaskRequest> for ExecuteSvc<T> {
                        type Response = TaskReply;
                        type Future = BoxFuture<tonic::Response<Self::Response>, tonic::Status>;
                        fn call(&mut self, request: tonic::Request<TaskRequest>) -> Self::Future {
                            let inner = self.0.clone();
                            let fut = async move { inner.execute(request).await };
                            Box::pin(fut)
                        }
                    }
                    let inner = self.inner.clone();
                    Box::pin(async move {
                        let method = ExecuteSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec);
                        Ok(grpc.unary(method, req).await)
                    })
                }
                "/yizutt.WorkerService/ExecuteStream" => {
                    struct ExecuteStreamSvc<T: WorkerService>(pub Arc<T>);
                    impl<T: WorkerService> tonic::server::ServerStreamingService<TaskRequest> for ExecuteStreamSvc<T> {
                        type Response = TraceEvent;
                        type ResponseStream = T::ExecuteStreamStream;
                        type Future =
                            BoxFuture<tonic::Response<Self::ResponseStream>, tonic::Status>;
                        fn call(&mut self, request: tonic::Request<TaskRequest>) -> Self::Future {
                            let inner = self.0.clone();
                            let fut = async move { inner.execute_stream(request).await };
                            Box::pin(fut)
                        }
                    }
                    let inner = self.inner.clone();
                    Box::pin(async move {
                        let method = ExecuteStreamSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec);
                        Ok(grpc.server_streaming(method, req).await)
                    })
                }
                "/yizutt.WorkerService/Health" => {
                    struct HealthSvc<T: WorkerService>(pub Arc<T>);
                    impl<T: WorkerService> tonic::server::UnaryService<Empty> for HealthSvc<T> {
                        type Response = WorkerHealth;
                        type Future = BoxFuture<tonic::Response<Self::Response>, tonic::Status>;
                        fn call(&mut self, request: tonic::Request<Empty>) -> Self::Future {
                            let inner = self.0.clone();
                            let fut = async move { inner.health(request).await };
                            Box::pin(fut)
                        }
                    }
                    let inner = self.inner.clone();
                    Box::pin(async move {
                        let method = HealthSvc(inner);
                        let codec = tonic_prost::ProstCodec::default();
                        let mut grpc = tonic::server::Grpc::new(codec);
                        Ok(grpc.unary(method, req).await)
                    })
                }
                _ => Box::pin(async move { Ok(unimplemented_response()) }),
            }
        }
    }

    impl<T: WorkerService> tonic::server::NamedService for WorkerServiceServer<T> {
        const NAME: &'static str = "yizutt.WorkerService";
    }

    fn unimplemented_response() -> http::Response<tonic::body::Body> {
        let mut response = http::Response::new(tonic::body::Body::empty());
        *response.status_mut() = http::StatusCode::OK;
        response
            .headers_mut()
            .insert("grpc-status", http::HeaderValue::from_static("12"));
        response.headers_mut().insert(
            "content-type",
            http::HeaderValue::from_static("application/grpc"),
        );
        response
    }
}
