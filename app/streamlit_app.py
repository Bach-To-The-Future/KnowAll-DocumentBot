import streamlit as st
from minio import Minio
import requests
import io, os
import textwrap
from dotenv import load_dotenv

# --- Constants ---
API_BASE_URL = "http://localhost:8000"
PAGE_SIZE = 5

# --- Load environment variables ---
load_dotenv()

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")

client = Minio(
    MINIO_ENDPOINT,
    access_key=ACCESS_KEY,
    secret_key=SECRET_KEY,
    secure=False
)

st.set_page_config(page_title="Know-All Chatbot")
st.title("🧠 Know-All Chatbot")

# --- Session State Initialization ---
st.session_state.setdefault("uploaded_files", set())
st.session_state.setdefault("selected_docs", set())

# --- Helper Functions ---

def safe_api_call(request_func, *args, **kwargs):
    try:
        res = request_func(*args, **kwargs)
        res.raise_for_status()
        return res
    except requests.RequestException as e:
        st.error(f"Network error: {e}")
        return None

@st.cache_data(ttl=30)
def fetch_document_list():
    res = safe_api_call(requests.get, f"{API_BASE_URL}/list_documents")
    if res:
        files = res.json().get("files", [])
        st.session_state.uploaded_files = st.session_state.uploaded_files.intersection(set(files))
        return files
    return None

def upload_and_embed_to_minio(uploaded_file):
    object_name = uploaded_file.name
    if object_name in st.session_state.uploaded_files:
        st.info(f"ℹ️ `{object_name}` already uploaded and embedded.")
        return
    file_data = uploaded_file.getvalue()

    try:
        client.put_object(
            BUCKET_NAME,
            object_name,
            io.BytesIO(file_data),
            length=len(file_data),
            content_type=uploaded_file.type
        )
        st.success(f"✅ Uploaded `{object_name}` to MinIO")
    except Exception as e:
        st.error(f"❌ Failed to upload to MinIO: {e}")
        return

    res = safe_api_call(requests.post, f"{API_BASE_URL}/ingest_from_minio", json={
        "bucket": BUCKET_NAME,
        "object_name": object_name
    })

    if res:
        st.success(res.json().get("message", "✅ File embedded successfully"))
        st.session_state.uploaded_files.add(object_name)
        st.cache_data.clear()
    else:
        st.error("❌ Failed to embed file.")

def format_reference_text(text, max_width=100):
    wrapped = textwrap.fill(text, width=max_width)
    return wrapped.replace("\n", "\n\n")

def clear_doc_list_cache():
    fetch_document_list.clear()

# --- UI Tabs ---
tab1, tab2, tab3 = st.tabs(["📤 Upload & Embed", "🗂️ Select Documents", "💬 Ask a Question"])

# --- Upload Tab ---
with tab1:
    uploaded_files = st.file_uploader(
        "Upload document(s)", 
        type=["pdf", "docx", "txt", "csv", "xlsx"], 
        accept_multiple_files=True
    )

    if uploaded_files:
        if st.button("🚀 Upload & Embed"):
            with st.spinner("Uploading and embedding files..."):
                for uploaded_file in uploaded_files:
                    object_name = uploaded_file.name
                    if object_name not in st.session_state.uploaded_files:
                        upload_and_embed_to_minio(uploaded_file)
                    else:
                        st.info(f"ℹ️ `{object_name}` already uploaded and embedded.")

# --- Select Documents Tab ---
with tab2:
    # ----- Handle page selection state updates after deletion -----
    if st.session_state.get("_refresh_page_keys"):
        deleted_files = st.session_state.get("_deleted_files", [])
        for key in list(st.session_state.keys()):
            if key.startswith("page_") and key.endswith("_selection"):
                st.session_state[key] = [f for f in st.session_state[key] if f not in deleted_files]
        st.session_state._refresh_page_keys = False
        st.session_state._deleted_files = []

    # --- Handle confirm checkbox reset key
    if "_delete_confirm_counter" not in st.session_state:
        st.session_state._delete_confirm_counter = 0

    files = fetch_document_list()
    if st.button("🔄 Refresh Document List"):
        st.cache_data.clear()
        files = fetch_document_list()

    if files is not None:
        if len(files) == 0:
            st.info("📭 No documents found in MinIO bucket.")
        else:
            total_pages = max((len(files) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
            page = st.number_input("📄 Page", min_value=1, max_value=total_pages, value=1, step=1)
            st.caption(f"Page {page} of {total_pages}")
            start, end = (page - 1) * PAGE_SIZE, page * PAGE_SIZE
            current_page_files = files[start:end]

            page_key = f"page_{page}_selection"
            select_all_flag = f"{page_key}_select_all"
            deselect_all_flag = f"{page_key}_deselect_all"

            # Handle select/deselect BEFORE multiselect
            if select_all_flag in st.session_state and st.session_state[select_all_flag]:
                st.session_state[page_key] = current_page_files.copy()
                st.session_state.selected_docs.update(current_page_files)
                st.session_state[select_all_flag] = False
            elif deselect_all_flag in st.session_state and st.session_state[deselect_all_flag]:
                st.session_state[page_key] = []
                st.session_state.selected_docs.difference_update(current_page_files)
                st.session_state[deselect_all_flag] = False
            elif page_key not in st.session_state:
                st.session_state[page_key] = [f for f in current_page_files if f in st.session_state.selected_docs]

            # --- Multiselect ---
            selected = st.multiselect(
                "Choose documents (selection persists across pages):",
                options=current_page_files,
                default=st.session_state[page_key],
                key=page_key
            )

            st.session_state.selected_docs.difference_update(current_page_files)
            st.session_state.selected_docs.update(selected)

            # --- Selection Buttons ---
            col1, col2, col3 = st.columns([1, 1, 2])

            with col1:
                if st.button("✅ Select All on Page"):
                    st.session_state[select_all_flag] = True
                    st.rerun()

            with col2:
                if st.button("❌ Deselect All on Page"):
                    st.session_state[deselect_all_flag] = True
                    st.rerun()

            with col3:
                if st.button("🧹 Clear All Selections"):
                    st.session_state.selected_docs.clear()
                    for key in list(st.session_state.keys()):
                        if key.startswith("page_") and key.endswith("_selection"):
                            del st.session_state[key]
                        if key.endswith("_select_all") or key.endswith("_deselect_all"):
                            del st.session_state[key]
                    st.rerun()

            st.info(f"📚 Total selected: {len(st.session_state.selected_docs)}")

            # --- Delete Selected (Robust Handling) ---
            if st.session_state.selected_docs:
                delete_col, confirm_col = st.columns([2, 3])
                with delete_col:
                    delete_clicked = st.button("🗑️ Delete Selected Documents")
                with confirm_col:
                    # The key includes a counter so it resets on each successful deletion
                    confirm_key = f"confirm_delete_checkbox_{st.session_state._delete_confirm_counter}"
                    confirm_delete = st.checkbox("Confirm deletion", key=confirm_key)

                if delete_clicked:
                    if not confirm_delete:
                        st.warning("⚠️ Please check 'Confirm deletion' before deleting.")
                    else:
                        with st.spinner("Deleting selected documents..."):
                            try:
                                res = safe_api_call(
                                    requests.delete,
                                    f"{API_BASE_URL}/delete_documents",
                                    json={"object_names": list(st.session_state.selected_docs)}
                                )
                                if res:
                                    deleted_files = res.json().get("deleted", [])
                                    errors = res.json().get("errors", [])

                                    # Set flags for rerun and selection update
                                    st.session_state.selected_docs.difference_update(deleted_files)
                                    st.session_state._deleted_files = deleted_files
                                    st.session_state._refresh_page_keys = True
                                    st.session_state._delete_confirm_counter += 1  # Checkbox will reset
                                    st.cache_data.clear()
                                    if deleted_files:
                                        st.success(f"✅ Deleted {len(deleted_files)} file(s): {', '.join(deleted_files)}")
                                    if errors:
                                        st.warning(f"⚠️ Some files couldn't be deleted: {errors}")
                                    st.rerun()
                                else:
                                    st.error("❌ Deletion failed due to network error.")
                            except Exception as e:
                                st.error(f"❌ Exception during deletion: {e}")
    else:
        st.error("❌ Could not connect to document service or unexpected response.")

# --- Question Tab ---
with tab3:
    question = st.text_input("Ask a question about the selected documents:")
    if st.button("🔍 Query"):
        if not question.strip():
            st.warning("⚠️ Please enter a question.")
        elif not st.session_state.selected_docs:
            st.warning("⚠️ Please select at least one document.")
        else:
            st.write("📡 Querying...")
            try:
                response = safe_api_call(
                    requests.post,
                    f"{API_BASE_URL}/query",
                    json={
                        "question": question,
                        "documents": list(st.session_state.selected_docs)
                    }
                )
                if response:
                    result = response.json()
                    st.markdown("### 🧠 Answer")
                    st.write(result.get("answer_with_refs", "No answer returned."))

                    citations = result.get("citations", [])
                    if citations:
                        st.markdown("### 📄 References")
                        for ref in citations:
                            index = ref.get("index", "?")
                            source = os.path.basename(ref.get("source", "unknown"))
                            page = ref.get("page_number", "?")
                            snippet = ref.get("text", "")
                            st.markdown(f"**[{index}] Page {page} — {source}**")
                            st.markdown(snippet)
                    else:
                        st.info("ℹ️ No references returned.")
                else:
                    st.error("❌ Query failed due to network error.")
            except Exception as e:
                st.error(f"❌ Exception during query: {e}")

# --- Optionally, add a sidebar for global cache clear ---
# with st.sidebar:
#     if st.button("🔁 Clear Cache"):
#         clear_doc_list_cache()
#         st.session_state.uploaded_files.clear()
#         st.session_state.selected_docs.clear()
#         st.success("✅ Cache and selections cleared.")