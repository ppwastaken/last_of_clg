import os

import requests
import streamlit as st


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


st.set_page_config(page_title="IaC Copilot", layout="wide")
st.title("IaC Copilot")


def api(method: str, path: str, **kwargs):
    response = requests.request(method, f"{API_BASE_URL}{path}", timeout=180, **kwargs)
    response.raise_for_status()
    return response.json()


with st.sidebar:
    st.subheader("Approval Queue")
    status_filter = st.selectbox(
        "Status",
        ["pending", "validation_failed", "approved", "rejected", "applied", "apply_failed"],
    )
    refresh = st.button("Refresh")

left, right = st.columns([0.95, 1.05], gap="large")

with left:
    st.subheader("Describe Infrastructure")
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = [
            {
                "role": "assistant",
                "content": "Describe the infrastructure you want, then choose Terraform or Kubernetes.",
            }
        ]

    artifact_type = st.radio("Output", ["kubernetes", "terraform"], horizontal=True)

    for message in st.session_state["chat_messages"]:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    prompt = st.chat_input("deploy a Redis cluster with 3 replicas and a persistent volume")
    if prompt:
        st.session_state["chat_messages"].append({"role": "user", "content": prompt})
        with st.spinner("Generating IaC and running validation..."):
            try:
                result = api(
                    "POST",
                    "/generate",
                    json={"prompt": prompt, "artifact_type": artifact_type},
                )
                st.session_state["selected_request_id"] = result["id"]
                if result["status"] == "pending":
                    reply = f"Request #{result['id']} validated and queued for approval."
                    st.success(reply)
                else:
                    reply = f"Request #{result['id']} failed validation after {result['attempts']} attempts."
                    st.error(reply)
                st.session_state["chat_messages"].append({"role": "assistant", "content": reply})
                st.code(result["generated_config"], language="yaml" if artifact_type == "kubernetes" else "hcl")
                st.text_area("Validation output", result["validation_output"], height=140)
            except requests.HTTPError as exc:
                st.error(exc.response.text)
            except requests.RequestException as exc:
                st.error(str(exc))

with right:
    st.subheader("Review and Approve")
    try:
        requests_data = api("GET", "/requests", params={"status": status_filter})
    except requests.RequestException as exc:
        st.error(f"Could not load queue: {exc}")
        requests_data = []

    ids = [item["id"] for item in requests_data]
    selected_id = st.selectbox("Request", ids, index=0 if ids else None, disabled=not ids)
    if selected_id:
        item = next(row for row in requests_data if row["id"] == selected_id)
        st.caption(f"Status: {item['status']} | Type: {item['artifact_type']} | Attempts: {item['attempts']}")
        st.text_area("Original prompt", item["prompt"], height=90)
        st.code(
            item["generated_config"],
            language="yaml" if item["artifact_type"] == "kubernetes" else "hcl",
        )
        st.text_area("Validation output", item["validation_output"], height=110)
        note = st.text_input("Reviewer note")

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Approve", disabled=item["status"] != "pending"):
                api("POST", f"/requests/{selected_id}/approve", json={"note": note})
                st.rerun()
        with c2:
            if st.button("Reject", disabled=item["status"] not in {"pending", "validation_failed"}):
                api("POST", f"/requests/{selected_id}/reject", json={"note": note})
                st.rerun()
        with c3:
            if st.button("Apply", disabled=item["status"] != "approved"):
                with st.spinner("Applying approved config..."):
                    updated = api("POST", f"/requests/{selected_id}/apply")
                    st.text_area("Apply output", updated.get("apply_output") or "", height=120)
                st.rerun()

if refresh:
    st.rerun()
