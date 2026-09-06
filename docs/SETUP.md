# Azure AI Foundry Setup — Gate 1

Step-by-step procedure for Azure for Students subscription.

## Prerequisites

- Azure for Students subscription (active, with credits)
- Azure CLI installed (`az --version`)
- Python 3.12+

## Step 1: Verify Subscription

```bash
az login
az account show --query '{name:name, id:id, state:state}' -o table
```

Confirm you see your Azure for Students subscription and it is `Enabled`.

## Step 2: Check Allowed Regions

Azure for Students subscriptions have regional restrictions enforced by policy.

1. Go to **Azure Portal** → **Policy** → **Assignments**
2. Look for **"Allowed resource deployment regions"** or **"Allowed locations"**
3. Note which regions are permitted

Alternatively via CLI:

```bash
az policy assignment list --query "[?contains(displayName,'region') || contains(displayName,'location')].{name:displayName, scope:scope}" -o table
```

> **If no policy restricts regions**, you can choose any region where Azure AI
> Foundry and your desired model are available. Prefer regions with broad model
> availability: `eastus`, `eastus2`, `swedencentral`, `westus3`.

## Step 3: Create Resource Group

```bash
# Replace <REGION> with an allowed region from Step 2
az group create --name rg-legacy-modernization --location <REGION>
```

## Step 4: Create Azure AI Foundry Resource + Project

Use the **current Foundry architecture** (NOT the legacy AI Hub):

```
Resource Group → Foundry resource → Foundry project → model deployment
```

### Via Azure Portal (recommended for first time)

1. Go to [Azure AI Foundry](https://ai.azure.com)
2. Click **Create project**
3. Select your Azure for Students subscription
4. Choose a permitted region from Step 2
5. Let the portal create the Foundry resource automatically
6. Name the project (e.g., `legacy-modernization`)
7. Complete creation

### Via Azure CLI (if portal creation fails)

```bash
# Create the AI Services resource (Foundry resource)
az cognitiveservices account create \
    --name ai-legacy-modernization \
    --resource-group rg-legacy-modernization \
    --kind AIServices \
    --sku S0 \
    --location <REGION> \
    --yes
```

> **Troubleshooting `RequestDisallowedByAzure`:**
> This means the region is not allowed by subscription policy.
> Try a different region from Step 2. If ALL regions fail, open a
> support request referencing the error and your subscription ID.

## Step 5: Deploy a Model

### Selection Criteria

Choose a model based on the intersection of:

1. **Available in your region** — not all models are in all regions
2. **Quota available** — check Usage + Quotas in the portal
3. **Supports Responses API** — required by this PoC
4. **Supports Structured Outputs** — required for Gates 2-3
5. **Cost-appropriate** — smallest capable model for COBOL analysis

### Check Available Models

In Azure AI Foundry portal:
1. Open your project
2. Go to **Models + endpoints** → **Deploy model** → **Deploy base model**
3. Note which models are available and their pricing

### Deploy

1. Select a model (e.g., `gpt-4o-mini` if available)
2. Choose deployment name (e.g., `gpt-4o-mini`)
3. Set tokens-per-minute quota to minimum viable (e.g., 10K TPM)
4. Deploy

Record the **deployment name** — this is your `FOUNDRY_MODEL` value.

## Step 6: Get Project Endpoint

In Azure AI Foundry portal:
1. Open your project → **Overview**
2. Copy the **Project endpoint**
3. Format: `https://<resource>.services.ai.azure.com/api/projects/<project>`

Or via CLI:
```bash
az cognitiveservices account show \
    --name ai-legacy-modernization \
    --resource-group rg-legacy-modernization \
    --query "properties.endpoint" -o tsv
```

> Note: The project endpoint includes the `/api/projects/<project>` path.
> The base endpoint from `az cognitiveservices` may need the project path appended.
> Check the Foundry portal for the exact URL.

## Step 7: Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:
```
FOUNDRY_PROJECT_ENDPOINT=https://<your-resource>.services.ai.azure.com/api/projects/<your-project>
FOUNDRY_MODEL=<your-deployment-name>
```

## Step 8: Install Python Dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/WSL
# or: .venv\Scripts\Activate.ps1  # PowerShell

pip install -e ".[dev]"
```

> Note: `pydantic-settings` is required by `agents/legacy_analyzer/config.py`.
> It will be added to `pyproject.toml` dependencies when running Gate 1.

## Step 9: Run Hello Foundry

```bash
python scripts/hello-foundry.py
```

Expected output:
```
Endpoint: https://...
Model:    ...

[OK] DefaultAzureCredential created
[OK] AIProjectClient connected
[OK] OpenAI client obtained

--- Calling Responses API ---
[OK] Response received in X.XXs

Response: Hello from Azure AI Foundry

--- Metadata ---
{
  "gate": "1",
  "status": "PASS",
  ...
}
```

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `RequestDisallowedByAzure` | Region not allowed by subscription policy | Try another region from Step 2 |
| `QuotaExceeded` / 429 | No quota for this model | Request quota increase or try a different model |
| `401 Unauthorized` | Auth issue | Run `az login` again, verify subscription |
| `404 Not Found` | Wrong endpoint or model name | Verify endpoint URL and deployment name |
| `CredentialUnavailableError` | No Azure CLI login | Run `az login` |
