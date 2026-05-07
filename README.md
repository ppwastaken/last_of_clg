g# IaC Copilot 

IaC Copilot is a FastAPI + Streamlit prototype for generating, validating, reviewing, editing, and applying Infrastructure as Code from plain English.

The user describes infrastructure in natural language, chooses either Kubernetes or Terraform, and the backend asks an LLM to generate the configuration. The generated configuration is validated before it can be approved. A reviewer can approve, reject, edit with another prompt, or apply the approved configuration.

## Features

- Streamlit UI for natural-language infrastructure requests
- FastAPI backend with generation, validation, approval, edit, and apply endpoints
- Groq or Ollama LLM support
- Kubernetes YAML generation and validation
- Terraform HCL generation and validation
- Validation repair loop with configurable retry attempts
- Human approval workflow before apply
- Prompt-based edit flow for revising generated IaC before apply
- PostgreSQL storage for requests, statuses, validation output, apply output, and generation attempts
- Attempt history available at `GET /requests/{id}/attempts`

## Architecture

```text
Streamlit UI
    |
    v
FastAPI backend
    |
    +--> Groq or Ollama for IaC generation/editing
    +--> Kubernetes/Terraform validators
    +--> PostgreSQL audit database
    +--> kubectl or terraform for approved apply
```

## Requirements

- Python 3.10+
- Docker Desktop
- Docker Compose
- `kubectl` for Kubernetes apply
- Terraform for Terraform validation/apply
- Groq API key or local Ollama

For Kubernetes apply on a laptop, enable Kubernetes in Docker Desktop or use a local cluster such as Minikube or kind.

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create the environment file:

```bash
cp .env.example .env
```

Configure one LLM provider in `.env`.

For Groq:

```env
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
```

For Ollama:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

If using Ollama, make sure the model is available:

```bash
ollama run llama3.1
```

Start PostgreSQL:

```bash
docker compose up -d postgres
```

Start the backend:

```bash
uvicorn backend.api:app --reload
```

Start the frontend in another terminal:

```bash
source .venv/bin/activate
streamlit run frontend/streamlit_app.py
```

Open the Streamlit app:

```text
http://localhost:8501
```

FastAPI docs are available at:

```text
http://localhost:8000/docs
```

## Kubernetes Apply Setup

Kubernetes generation and offline validation can work without a live cluster. Applying Kubernetes resources needs `kubectl` connected to a real cluster.

For Docker Desktop Kubernetes:

```bash
kubectl config use-context docker-desktop
kubectl get nodes
```

If `kubectl get nodes` works, the app can apply Kubernetes YAML to that local cluster.

## Workflow

1. Enter an infrastructure prompt in the Streamlit UI.
2. Choose `kubernetes` or `terraform`.
3. The backend asks the LLM to generate IaC.
4. The validator checks the generated config.
5. If validation fails, the backend sends the validation error back to the LLM and retries.
6. If validation passes, the request becomes `pending`.
7. A reviewer can inspect the generated config.
8. The reviewer can edit with a prompt, approve, reject, or apply after approval.

Example prompt:

```text
deploy a Redis cluster with 3 replicas and a persistent volume
```

Example edit prompt:

```text
increase Redis storage to 5Gi and add a NetworkPolicy
```

## Request Statuses

- `validation_failed`: generation/editing failed validation after all retry attempts
- `pending`: config passed validation and is waiting for review
- `approved`: reviewer approved the config
- `rejected`: reviewer rejected the config
- `applied`: approved config was applied successfully
- `apply_failed`: apply command ran but failed

## API Endpoints

- `POST /generate`: generate and validate a new request
- `GET /requests`: list requests, optionally filtered by status
- `GET /requests/{id}`: get a single request
- `GET /requests/{id}/attempts`: list generation/edit attempts
- `POST /requests/{id}/edit`: revise existing IaC with a prompt and revalidate
- `POST /requests/{id}/approve`: approve a pending request
- `POST /requests/{id}/reject`: reject a pending or validation-failed request
- `POST /requests/{id}/apply`: apply an approved request

## Validation

Terraform validation runs:

```bash
terraform init -backend=false -input=false
terraform validate -no-color
```

Kubernetes validation defaults to offline YAML checks. It checks required fields such as `apiVersion`, `kind`, `metadata.name`, selectors, pod templates, Service ports, and Redis-specific requirements for Redis StatefulSet output.

Set this in `.env` for server-side Kubernetes validation:

```env
KUBECTL_DRY_RUN=server
```

Server-side validation requires `kubectl` to point at a reachable Kubernetes cluster.

## Important Notes

- Generation is not the same as apply.
- The app does not apply anything until a request is approved.
- Docker Compose is used only for PostgreSQL.
- Kubernetes workloads run in whichever cluster `kubectl` is connected to.
- With Docker Desktop Kubernetes enabled, applied Kubernetes resources run locally on your laptop.
- Do not commit `.env` or API keys.
- This is a prototype and uses SQLAlchemy `Base.metadata.create_all`; use migrations before production.
