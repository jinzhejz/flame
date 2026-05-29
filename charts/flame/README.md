# Flame Helm Chart

This chart installs a static Flame cluster on Kubernetes:

- one `flame-session-manager`
- a configurable number of `flame-object-cache` replicas
- a configurable number of `flame-executor-manager` replicas

It does not implement the future Kubernetes provider or application pod
autoscaling. Executor capacity is static and follows
`executorManager.replicas`. Object-cache capacity follows
`objectCache.replicas`; each StatefulSet replica owns its own cache volume when
persistence is enabled.

## Install

```bash
helm install flame ./charts/flame --namespace flame --create-namespace
```

For local Kind testing without persistent volumes:

```bash
helm install flame ./charts/flame \
  --namespace flame \
  --create-namespace \
  --set sessionManager.persistence.enabled=false \
  --set objectCache.persistence.enabled=false
```

To install multiple object-cache replicas:

```bash
helm install flame ./charts/flame \
  --namespace flame \
  --create-namespace \
  --set objectCache.replicas=3
```

## Verify

```bash
helm test flame --namespace flame
kubectl -n flame get pods,svc
```

Port-forward for local inspection:

```bash
kubectl -n flame port-forward svc/flame-session-manager 8080:8080
kubectl -n flame port-forward svc/flame-object-cache 9090:9090
```

Then configure local clients:

```bash
export FLAME_ENDPOINT=http://127.0.0.1:8080
export FLAME_CACHE_ENDPOINT=grpc://127.0.0.1:9090
```

Port-forwarded cache endpoints are suitable for local inspection. Package
deployment flows should use a cache endpoint that is reachable by both the
client and executor-manager pods.
