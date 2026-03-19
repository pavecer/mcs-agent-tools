# Azure Portal Setup — Click-Through Guide

Complete walkthrough for setting up the Azure infrastructure and GitHub Actions
deployment for PP Agent Toolkit entirely through the Azure Portal UI.

**Estimated time:** ~30 minutes
**Prerequisites:** An Azure account with Owner or Contributor access.

---

## Before You Start — Decide Your Names

Pick these once and use them consistently throughout the guide.
Write them down somewhere handy.

| Item | Example | Your value |
|------|---------|------------|
| Resource group | `rg-pp-toolkit` | __________ |
| Region | `West Europe` | __________ |
| Container Registry name | `ppagentregistry` | __________ |
| Container App name | `pp-agent-toolkit` | __________ |
| App password (USERS) | `admin:StrongPass!` | __________ |

The Container Registry name must be **globally unique** and contain
**only letters and numbers** (no dashes).

---

## Part 1 — Resource Group

A resource group is a logical folder that holds all the Azure resources.

1. Go to [portal.azure.com](https://portal.azure.com) and sign in.
2. In the top search bar type **Resource groups** → click it.
3. Click **+ Create** (top-left).
4. Fill in:
   - **Subscription** → your subscription
   - **Resource group** → e.g. `rg-pp-toolkit`
   - **Region** → e.g. `West Europe`
5. Click **Review + create** → **Create**.
6. Wait for the green "Your deployment is complete" banner.

---

## Part 2 — Azure Container Registry (ACR)

ACR is a private Docker image store. GitHub Actions will push images here.

1. In the top search bar type **Container registries** → click it.
2. Click **+ Create**.
3. Fill in:
   - **Subscription** → your subscription
   - **Resource group** → the one you created in Part 1
   - **Registry name** → e.g. `ppagentregistry` *(must be globally unique)*
   - **Location** → same region as your resource group
   - **Pricing plan** → **Basic**
4. Click **Review + create** → **Create**.
5. Once deployed click **Go to resource** and note the **Login server** value
   (e.g. `ppagentregistry.azurecr.io`) — you'll need it later.

---

## Part 3 — Container Apps Environment

An environment is the networking boundary that Container Apps run inside.

1. In the top search bar type **Container Apps Environments** → click it.
2. Click **+ Create**.
3. **Basics** tab:
   - **Subscription** → your subscription
   - **Resource group** → your resource group
   - **Name** → e.g. `pp-toolkit-env`
   - **Region** → same region
4. Leave all other tabs at defaults.
5. Click **Review + create** → **Create**.
6. Wait for deployment to complete.

---

## Part 4 — Container App

This is the actual running application.

1. In the top search bar type **Container Apps** → click it.
2. Click **+ Create**.

### Basics tab
- **Subscription** → your subscription
- **Resource group** → your resource group
- **Container app name** → e.g. `pp-agent-toolkit`
- **Region** → same region
- **Container Apps Environment** → select the environment from Part 3
- Click **Next: Container >**

### Container tab
- Uncheck **Use quickstart image**
- **Image source** → **Docker Hub or other registries**
- **Image type** → **Public**
- **Registry login server** → `mcr.microsoft.com`
- **Image and tag** → `azuredocs/containerapps-helloworld:latest`

  *(This is a placeholder — GitHub Actions will replace it on first deploy)*

- **CPU and Memory** → `0.5 CPU, 1 Gi memory`
- Click **Next: Bindings >** → **Next: Ingress >**

### Ingress tab
- **Ingress** → toggle **Enabled**
- **Ingress traffic** → **Accepting traffic from anywhere**
- **Target port** → `2009`
- Click **Next: Tags >** → **Review + create** → **Create**

### After creation — add app secrets
1. Click **Go to resource** on the newly created Container App.
2. In the left menu choose **Secrets**.
3. Click **+ Add**.
4. Fill in:
   - **Key** → `app-users`
   - **Type** → **Container Apps Secret**
   - **Value** → your USERS value, e.g. `admin:StrongPass!`
5. Click **Add**. Wait for the spinner to finish.

### Add environment variables
1. In the left menu choose **Containers**.
2. Click **Edit and deploy**.
3. Click the container row to edit it.
4. Under **Environment variables** click **+ Add**:

   | Name | Source | Value |
   |------|--------|-------|
   | `REFLEX_ENV` | Manual entry | `prod` |
   | `PORT` | Manual entry | `2009` |
   | `USERS` | Reference a secret | select `app-users` |

5. Click **Save** → **Create** (creates a new revision).

### Scale to zero
1. In the left menu choose **Scale**.
2. Set **Min replicas** → `0`, **Max replicas** → `1`.
3. Click **Save**.

---

## Part 5 — App Registration (GitHub Actions Identity)

This creates the identity that GitHub Actions will use. No passwords —
it uses OIDC federated credentials.

1. In the top search bar type **App registrations** → click it.
2. Click **+ New registration**.
3. Fill in:
   - **Name** → `pp-toolkit-gh-deploy`
   - **Supported account types** → **Accounts in this organizational directory only**
4. Click **Register**.
5. You are now on the app's overview page. **Copy and save**:
   - **Application (client) ID** → this is your `AZURE_CLIENT_ID`
   - **Directory (tenant) ID** → this is your `AZURE_TENANT_ID`

---

## Part 6 — Federated Credential (OIDC for GitHub Actions)

This tells Azure "trust tokens issued by GitHub for this repo/branch".

> **Important:** Do **not** add a GitHub `environment:` field to the deploy job,
> because that changes the OIDC subject claim from
> `repo:<org>/<repo>:ref:refs/heads/main` to
> `repo:<org>/<repo>:environment:production`, which would not match this
> credential and cause login to fail.

1. Still on the App Registration page from Part 5.
2. In the left menu choose **Certificates & secrets**.
3. Click the **Federated credentials** tab.
4. Click **+ Add credential**.
5. **Federated credential scenario** → select **GitHub Actions deploying Azure resources**.
6. Fill in:
   - **Organisation** → `pavecer` *(your GitHub username or org)*
   - **Repository** → `mcs-agent-tools` *(your repo name)*
   - **Entity type** → **Branch**
   - **Branch** → `main`
   - **Name** → `github-main`
7. Click **Add**.

---

## Part 7 — Role Assignments

Grant the App Registration permission to push images and update the Container App.

### Role 1: AcrPush on the Container Registry

1. In the top search bar type **Container registries** → click it → open your registry.
2. In the left menu choose **Access control (IAM)**.
3. Click **+ Add** → **Add role assignment**.
4. **Role** tab: search for `AcrPush` → select it → click **Next**.
5. **Members** tab:
   - **Assign access to** → **User, group, or service principal**
   - Click **+ Select members**
   - Search for `pp-toolkit-gh-deploy` → select it → click **Select**
6. Click **Review + assign** → **Review + assign**.

### Role 2: Contributor on the Resource Group

1. In the top search bar type **Resource groups** → click it → open your resource group.
2. In the left menu choose **Access control (IAM)**.
3. Click **+ Add** → **Add role assignment**.
4. **Role** tab: search for `Contributor` → select it → click **Next**.
5. **Members** tab:
   - **Assign access to** → **User, group, or service principal**
   - Click **+ Select members**
   - Search for `pp-toolkit-gh-deploy` → select it → click **Select**
6. Click **Review + assign** → **Review + assign**.

---

## Part 8 — GitHub Secrets

1. Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions**.
2. Click **New repository secret** for each of the following:

### Optional secrets for self-service account requests

If you want `/request-account` enabled, add these secrets in the same GitHub environment:

| Secret | Purpose |
|--------|---------|
| `AUTH_SIGNUP_ENABLED` | Set to `true` to enable feature wiring in deploy workflow |
| `AUTH_DB_DSN` | PostgreSQL connection string (Azure Database for PostgreSQL Flexible Server) |
| `TURNSTILE_SITE_KEY` | Cloudflare Turnstile client key |
| `TURNSTILE_SECRET_KEY` | Cloudflare Turnstile server key |
| `ACS_EMAIL_CONNECTION_STRING` | Azure Communication Services email connection string |
| `ACS_EMAIL_SENDER` | Verified ACS sender address |

When `AUTH_SIGNUP_ENABLED=true`, deployment validates all secrets above and injects them into Container App.

---

## Optional Part 9 — Provision services for account requests

### PostgreSQL (Flexible Server)

Create an Azure Database for PostgreSQL Flexible Server and database, then build DSN in this format:

`postgresql://<admin>:<password>@<server>.postgres.database.azure.com:5432/<db>?sslmode=require`

### Cloudflare Turnstile

Create a Turnstile widget for your app hostname and copy:

- site key -> `TURNSTILE_SITE_KEY`
- secret key -> `TURNSTILE_SECRET_KEY`

### Azure Communication Services Email

1. Create ACS resource.
2. Connect Email Communication Service.
3. Add and verify a sender domain (DNS records required).
4. Use connection string and verified sender in GitHub secrets.

   | Secret name | Where to find the value |
   |-------------|------------------------|
   | `AZURE_CLIENT_ID` | App Registration overview → **Application (client) ID** |
   | `AZURE_TENANT_ID` | App Registration overview → **Directory (tenant) ID** |
   | `AZURE_SUBSCRIPTION_ID` | Azure Portal top-right → **Subscriptions** → copy the ID |
   | `ACR_NAME` | Your registry name, e.g. `ppagentregistry` *(without `.azurecr.io`)* |
   | `AZURE_RESOURCE_GROUP` | e.g. `rg-pp-toolkit` |
   | `AZURE_CONTAINER_APP_NAME` | e.g. `pp-agent-toolkit` |

---

## Part 9 — Grant ACR Pull to the Container App

The Container App needs permission to pull images from ACR.

1. In the top search bar type **Container Apps** → open your app.
2. In the left menu choose **Identity**.
3. Under **System assigned** toggle **Status → On** → click **Save** → confirm.
4. Copy the **Object (principal) ID** that appears.
5. In the top search bar type **Container registries** → open your registry.
6. In the left menu choose **Access control (IAM)**.
7. Click **+ Add** → **Add role assignment**.
8. **Role** tab: search for `AcrPull` → select it → click **Next**.
9. **Members** tab:
   - **Assign access to** → **Managed identity**
   - Click **+ Select members**
   - **Managed identity** → **Container App**
   - Select your app → click **Select**
10. Click **Review + assign** → **Review + assign**.

---

## Part 10 — Trigger the First Deployment

1. Go to your GitHub repository → **Actions** tab.
2. Find **Pipeline** in the left workflow list.
3. Click **Run workflow** → **Run workflow** (green button).
4. Watch the job — it should:
   - ✅ Azure Login (OIDC)
   - ✅ Build & push image to ACR
   - ✅ Deploy to Azure Container App
   - ✅ Show active revision

### Verify in the portal
1. Open your Container App in the portal.
2. In the left menu choose **Revisions and replicas**.
3. You should see a new revision with the git SHA in its name, status **Running**.
4. In the left menu choose **Overview** — click the **Application URL** to open the app.

---

## Updating the Password Later

1. Open your Container App → **Secrets** (left menu).
2. Click the `app-users` secret → edit the value → click **Save**.
3. Go to **Revisions and replicas** → click **Create new revision**.
4. No other changes needed — just click **Create** to pick up the new secret value.

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| GitHub Actions login fails | Verify all 3 Azure secrets are correct; check the federated credential repo/branch exactly matches |
| ACR build fails | Confirm `AcrPush` role is assigned to the App Registration |
| Deploy fails with "unable to pull image using Managed identity system" | Ensure Container App system identity is enabled and has `AcrPull` on the ACR scope |
| Container App shows error | Open the app → **Log stream** (left menu) to see Python startup errors |
| App loads but can't log in | Check the `USERS` secret value — format must be `username:password` |
| Blank page on load | Check the latest revision status and logs; the image already contains a prebuilt frontend |
