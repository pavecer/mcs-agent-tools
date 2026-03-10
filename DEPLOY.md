# Deploying PP Agent Toolkit to Azure Container Apps

This guide walks you through everything needed to get the app running on Azure,
with automated deployments triggered by every push to `main`.

---

## Architecture

```
GitHub push to main
       │
       ▼
GitHub Actions (pipeline.yml)
       │  OIDC — no stored passwords
       ▼
Azure Container Registry (ACR)
  └─ builds Dockerfile via `az acr build`
  └─ stores image: pp-agent-toolkit:<sha>
       │
       ▼
Azure Container Apps
  └─ pulls new image from ACR
  └─ serves on HTTPS (managed cert, auto-scale to 0)
```

---

## Prerequisites

| Tool | Install |
|------|---------|
| Azure CLI ≥ 2.60 | `brew install azure-cli` |
| An Azure subscription | [portal.azure.com](https://portal.azure.com) |
| Owner / Contributor on the subscription | — |

Log in:
```bash
az login
az account set --subscription "<your-subscription-id>"
export SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```

---

## Step 1 — Create Azure resources

Choose names once and keep them — they're referenced throughout:

```bash
RESOURCE_GROUP="rg-pp-toolkit"
LOCATION="westeurope"           # change to your preferred region
ACR_NAME="ppagentregistry"      # globally unique, alphanumeric only
ACA_ENV="pp-toolkit-env"
APP_NAME="pp-agent-toolkit"
```

### Resource group
```bash
az group create --name $RESOURCE_GROUP --location $LOCATION
```

### Azure Container Registry
```bash
az acr create \
  --name $ACR_NAME \
  --resource-group $RESOURCE_GROUP \
  --sku Basic
```

### Container Apps environment
```bash
az containerapp env create \
  --name $ACA_ENV \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION
```

### Container App (bootstrapped with a placeholder image)
```bash
az containerapp create \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --environment $ACA_ENV \
  --image mcr.microsoft.com/azuredocs/containerapps-helloworld:latest \
  --target-port 2009 \
  --ingress external \
  --min-replicas 0 \
  --max-replicas 1
```

> **Scale note**: `--max-replicas 1` keeps one instance — Reflex stores session
> state in-memory, so multiple instances would cause session loss.
> Increase only after adding a Redis-backed state backend.

---

## Step 2 — Store the USERS secret in the Container App

The `USERS` env var contains credentials (e.g. `admin:mypassword`).
Store it as a Container App secret so it is never in plain text:

```bash
az containerapp secret set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --secrets "app-users=admin:CHANGE_ME_STRONG_PASSWORD"

az containerapp update \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --set-env-vars \
    "REFLEX_ENV=prod" \
    "PORT=2009" \
    "USERS=secretref:app-users"
```

Change `admin:CHANGE_ME_STRONG_PASSWORD` to your desired credentials.
You can list multiple users: `admin:pass1,analyst:pass2`.

To update the password later:
```bash
az containerapp secret set \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --secrets "app-users=admin:NEW_PASSWORD"
```

---

## Step 3 — Configure GitHub Actions credentials (OIDC)

OIDC federated credentials allow GitHub Actions to authenticate to Azure
**without storing any long-lived secrets** in GitHub.

### 3a — Create a service principal

```bash
SP_NAME="pp-toolkit-gh-deploy"

APP_ID=$(az ad app create --display-name $SP_NAME --query appId -o tsv)
az ad sp create --id $APP_ID

echo "Client ID: $APP_ID"
echo "Tenant ID: $(az account show --query tenantId -o tsv)"
```

### 3b — Assign required roles

The service principal needs two roles:

```bash
SP_OBJECT_ID=$(az ad sp show --id $APP_ID --query id -o tsv)

# Push images to ACR
az role assignment create \
  --assignee $SP_OBJECT_ID \
  --role AcrPush \
  --scope $(az acr show --name $ACR_NAME --resource-group $RESOURCE_GROUP --query id -o tsv)

# Update the Container App
az role assignment create \
  --assignee $SP_OBJECT_ID \
  --role Contributor \
  --scope $(az group show --name $RESOURCE_GROUP --query id -o tsv)
```

Optional (only if you want CI to create AcrPull assignments automatically):

```bash
az role assignment create \
  --assignee $SP_OBJECT_ID \
  --role "User Access Administrator" \
  --scope $(az acr show --name $ACR_NAME --resource-group $RESOURCE_GROUP --query id -o tsv)
```

If you do **not** grant `User Access Administrator`, pre-create `AcrPull` once
for the Container App managed identity (see note in Step 5).

### 3c — Create a federated credential for your GitHub repo

Replace `pavecer/mcs-agent-tools` with your actual `<owner>/<repo>`:

```bash
az ad app federated-credential create \
  --id $APP_ID \
  --parameters '{
    "name": "github-main",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:pavecer/mcs-agent-tools:ref:refs/heads/main",
    "audiences": ["api://AzureADTokenExchange"]
  }'
```

If you also want to allow manual `workflow_dispatch` runs from any ref:
```bash
az ad app federated-credential create \
  --id $APP_ID \
  --parameters '{
    "name": "github-dispatch",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:pavecer/mcs-agent-tools:ref:refs/heads/main",
    "audiences": ["api://AzureADTokenExchange"]
  }'
```

---

## Step 4 — Set GitHub secrets

In your repository: **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|-------------|-------|
| `AZURE_CLIENT_ID` | Output of `echo $APP_ID` from Step 3a |
| `AZURE_TENANT_ID` | `az account show --query tenantId -o tsv` |
| `AZURE_SUBSCRIPTION_ID` | `az account show --query id -o tsv` |
| `ACR_NAME` | Your ACR name (e.g. `ppagentregistry`) |
| `AZURE_RESOURCE_GROUP` | e.g. `rg-pp-toolkit` |
| `AZURE_CONTAINER_APP_NAME` | e.g. `pp-agent-toolkit` |

> The workflow uses the `production` GitHub environment — create it at
> **Settings → Environments → New environment → production** (optional but
> allows you to add required reviewers before production deploys).

---

## Step 5 — Trigger the first real deployment

Push to `main` (or click **Run workflow** in the Actions tab).
The workflow will:
1. Authenticate to Azure via OIDC
2. Resolve the Container App public FQDN
3. Build the Docker image inside ACR (`az acr build`) with `API_URL=https://<fqdn>`
4. Ensure ACR pull permissions are available for the app managed identity
5. Update the Container App to the new image

If your CI identity cannot write RBAC role assignments, pre-create AcrPull once:

```bash
APP_NAME="pp-agent-toolkit"
PRINCIPAL_ID=$(az containerapp show --name $APP_NAME --resource-group $RESOURCE_GROUP --query identity.principalId -o tsv)
ACR_ID=$(az acr show --name $ACR_NAME --resource-group $RESOURCE_GROUP --query id -o tsv)

az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role AcrPull \
  --scope "$ACR_ID"
```

Monitor:
```bash
az containerapp logs show \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --follow
```

Get the public URL:
```bash
az containerapp show \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --query "properties.configuration.ingress.fqdn" \
  --output tsv
```

---

## Local Docker testing

Before deploying, test the image locally:

```bash
docker build -t pp-agent-toolkit:local .

docker run --rm -p 2009:2009 \
  -e USERS="admin:localtest" \
  pp-agent-toolkit:local
```

Browse to <http://localhost:2009>.

---

## Notes

| Topic | Detail |
|-------|--------|
| **Uploaded files** | Stored inside the container; lost on restarts/scale-to-zero. Files are only needed for the duration of one user session (upload → process → download), so this is acceptable. |
| **Scaling** | Keep `--max-replicas 1`. Reflex uses in-memory state; horizontal scaling needs a Redis state backend first. |
| **TLS** | Azure Container Apps provides a managed HTTPS certificate automatically for the `*.azurecontainerapps.io` domain. |
| **Custom domain** | `az containerapp hostname add` — see [docs](https://learn.microsoft.com/azure/container-apps/custom-domains-managed-certificates). |
| **Costs** | At `--min-replicas 0` the app scales to zero when idle; you only pay for active request time. Roughly €0 for light usage. |
