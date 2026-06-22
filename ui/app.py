"""
ConsultRAG demo UI — a thin Streamlit client over the FastAPI service. This
file holds NO business logic and never touches the DB, vector store, or RAG
engine directly; every server interaction goes through api_client.py.

Run (see README "Demo UI" section for the full sequence):
    streamlit run ui/app.py
"""

from __future__ import annotations

import os

import streamlit as st

from api_client import (
    ApiError,
    ForbiddenError,
    NotAuthenticatedError,
    ServerError,
    ingest,
    me,
    query,
)

st.set_page_config(page_title="ConsultRAG", page_icon="🔍")
st.title("ConsultRAG")
st.caption(
    "Demo UI — local dev only. Running with DEV_AUTH_BYPASS means there's no "
    "real sign-in behind this session; see the README before using this "
    "against anything but a local demo API."
)

# --- current user / engagement selector --------------------------------------

try:
    with st.spinner("Loading your access..."):
        me_info = me()
except NotAuthenticatedError:
    st.error("Not signed in. Start the API and confirm DEV_AUTH_BYPASS is on for local use.")
    st.stop()
except ServerError as e:
    st.error(f"The API is unavailable right now ({e.detail}). Try again shortly.")
    st.stop()

st.sidebar.subheader("Signed in as")
st.sidebar.write(f"User: `{me_info.user_id}`")
st.sidebar.write(f"Clearance: {me_info.clearance}")
if me_info.is_admin:
    st.sidebar.write("Role: **admin** (crosses all engagements)")

engagement_options = list(me_info.engagements)
if not engagement_options:
    # Covers two real cases, deliberately treated the same way: /me declined
    # entirely (not applicable here, since me() already succeeded above), or
    # /me succeeded but returned zero specific engagement memberships — which
    # is exactly what happens for the DEV_AUTH_BYPASS admin user (admins
    # bypass the engagement check rather than holding explicit memberships).
    fallback = os.environ.get("FALLBACK_ENGAGEMENTS", "")
    engagement_options = [e.strip() for e in fallback.split(",") if e.strip()]

if not engagement_options:
    st.sidebar.warning(
        "No engagements found for this user, and no FALLBACK_ENGAGEMENTS configured."
    )
    engagement = None
else:
    engagement = st.sidebar.selectbox("Engagement", engagement_options)

# --- query panel --------------------------------------------------------------

st.subheader("Ask a question")
question = st.text_input("Question")
submitted = st.button("Submit", disabled=not question)

if submitted:
    try:
        with st.spinner("Retrieving and answering..."):
            result = query(question, engagement=engagement)
    except NotAuthenticatedError:
        st.error("Not signed in.")
    except ForbiddenError:
        st.warning("You don't have access to this engagement.")
    except ServerError as e:
        st.error(f"Something went wrong on the server ({e.detail}). Try again.")
    except ApiError as e:
        st.error(f"Request failed ({e.detail}).")
    else:
        st.markdown("### Answer")
        st.write(result.answer)

        st.markdown("### Sources")
        if not result.citations:
            st.caption("No supporting sources were returned.")
        for c in result.citations:
            # Future seam: a date/staleness badge belongs on this line, once
            # the live-data layer tags external sources with a date and the
            # API actually returns one (see ARCHITECTURE.md §8). Not built
            # on the API side yet, so deliberately not rendered here either.
            st.write(f"- `{c.source_path}` [{c.locator}] — score {c.score:.3f}")

# --- optional ingest panel ----------------------------------------------------

st.divider()
show_ingest = st.toggle("Show ingest panel")

if show_ingest:
    st.subheader("Ingest")
    st.caption(
        "`path` is a path on the API server's filesystem, not a browser file "
        "upload — the API has no upload endpoint today, only "
        "POST /ingest {path, engagement, clearance}."
    )
    ingest_path = st.text_input("Server-side path to ingest", key="ingest_path")
    ingest_engagement = st.selectbox(
        "Engagement", engagement_options or ["(none available)"], key="ingest_engagement"
    )
    ingest_clearance = st.number_input("Clearance", min_value=0, value=1, step=1)
    st.caption(
        "The server enforces your own clearance ceiling regardless of what "
        "you select here — you cannot ingest above your own clearance."
    )
    if st.button("Ingest", disabled=not ingest_path):
        try:
            with st.spinner("Ingesting..."):
                n = ingest(ingest_path, ingest_engagement, int(ingest_clearance))
        except NotAuthenticatedError:
            st.error("Not signed in.")
        except ForbiddenError as e:
            st.warning(f"Not allowed ({e.detail}).")
        except ServerError as e:
            st.error(f"Something went wrong on the server ({e.detail}). Try again.")
        except ApiError as e:
            st.error(f"Request failed ({e.detail}).")
        else:
            st.success(f"Ingested {n} chunk(s).")
