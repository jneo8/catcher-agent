# Deploy Kubernetes MCP Server in local k8s

This guide explains how to deploy the [Kubernetes MCP Server](https://github.com/containers/kubernetes-mcp-server) using Helm.

## Prerequisites

- Kubernetes cluster
- Helm
- kubectl

## Installation Steps

### 1. Clone the Repository

Clone the Kubernetes MCP Server repository and navigate to the Helm chart directory:

```sh
git clone https://github.com/containers/kubernetes-mcp-server.git
cd kubernetes-mcp-server/charts/kubernetes-mcp-server
```

### 2. Install with Helm

Deploy the Kubernetes MCP Server using Helm with the following configuration:

```sh
helm upgrade -i -n kubernetes-mcp-server \
  --create-namespace \
  kubernetes-mcp-server . \
  --set openshift=false \
  --set ingress.enabled=false
```

### 3. Grant Cluster Admin Permissions

To allow the MCP server to manage cluster resources, create a ClusterRoleBinding:

```sh
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: kubernetes-mcp-server-admin
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- kind: ServiceAccount
  name: kubernetes-mcp-server
  namespace: kubernetes-mcp-server
EOF
```

**Note:** This grants `cluster-admin` privileges to the MCP server. For production environments, consider creating a more restrictive Role/ClusterRole based on your security requirements.

## Play with inspector

```ssh
kubectl port-forward -n kubernetes-mcp-server svc/kubernetes-mcp-server 8080:8080
npx @modelcontextprotocol/inspector
```

## Troubleshooting

To uninstall:

```sh
helm uninstall kubernetes-mcp-server -n kubernetes-mcp-server
kubectl delete clusterrolebinding kubernetes-mcp-server-admin
```
