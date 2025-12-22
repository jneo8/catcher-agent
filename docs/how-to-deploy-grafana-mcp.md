# How to deploy grafana mcp

Follow the instruction to deploy the grafana-mcp.

```sh
helm upgrade --install my-release grafana/grafana-mcp \
  --namespace mcp-grafana \
  --create-namespace \
  --set "extraArgs={--disable-write}" \
  --set "grafana.apiKey={put-api-key-here}" \
  --set "grafana.url=http://grafana.grafana-namespace.svc.cluster.local:3000"
```

Reference: https://github.com/grafana/mcp-grafana
