# IaC Copilot

A FastAPI + Streamlit prototype where a user describes desired cloud infrastructure in plain English, an LLM generates Terraform or Kubernetes YAML, validators check it, and validated configs wait for human approval before apply.

## Features

- Chat-style Streamlit UI for infrastructure requests
- Groq or Ollama-backed generation constrained to JSON-wrapped Terraform/Kubernetes output
- Validation loop with up to 3 repair attempts
- `terraform init -backend=false && terraform validate` for Terraform
- Offline YAML checks for Kubernetes by default
- PostgreSQL audit log for every generated config and original prompt
- Attempt-level audit records at `GET /requests/{id}/attempts`
- Approval, rejection, and explicit apply endpoints

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1 \\ source .venv/Scripts/activate
pip install -r requirements.txt
Copy-Item .env.example .env
docker compose up -d postgres
```

Edit `.env` and set either:

```text
LLM_PROVIDER=groq
GROQ_API_KEY=...
GROQ_MODEL=llama-3.3-70b-versatile
```

or:

```text
LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.1
```

Start the backend:

```powershell
uvicorn backend.api:app --reload
```

Start the UI in another shell:

```powershell
streamlit run frontend/streamlit_app.py
```

## Notes

- Applying Terraform or Kubernetes changes is intentionally separate from approval.
- The backend must have `terraform` and/or `kubectl` installed on `PATH`.
- Kubernetes validation defaults to offline YAML checks so generation works without a live cluster.
- Set `KUBECTL_DRY_RUN=server` when you want server-side schema/admission validation and `kubectl` points at a reachable cluster.
- This prototype uses `Base.metadata.create_all` for setup. Use Alembic migrations before production.


deploy a Redis cluster with 3 replicas and a persistent volume
