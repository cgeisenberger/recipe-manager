"""
Recipe Digitizer - Streamlit Web Interface
Upload photos, process recipes, manage database
"""

import streamlit as st
import pandas as pd
import tempfile
import shutil
from pathlib import Path
import json
from datetime import datetime
from dataclasses import asdict
from typing import List, Dict, Optional

from recipe_processor_integrated import IntegratedRecipeProcessor
from database import DatabaseManager, Cookbook
from mealie_client import MealieClient, load_mealie_config
from cookbook_config import CookbookConfigManager

OPENAI_CONFIG_PATH = "config/openai_config.json"


def load_openai_key(config_path: str = OPENAI_CONFIG_PATH) -> Optional[str]:
    """Read the OpenAI API key from config/openai_config.json.

    This file is the single source of truth (config/ is gitignored). Returns
    None if the file is missing or the key is blank.
    """
    try:
        with open(config_path) as f:
            return json.load(f).get("api_key") or None
    except Exception:
        return None


def apply_openai_key() -> Optional[str]:
    """Re-read the key from config and push it into the cached LLM clients.

    Called immediately before every LLM action so a key edited on disk takes
    effect without restarting the app or rebuilding session state.
    """
    key = load_openai_key()
    if key:
        if st.session_state.get("processor"):
            st.session_state.processor.set_openai_key(key)
        if st.session_state.get("config_manager"):
            st.session_state.config_manager.set_openai_key(key)
    return key


def test_openai_connection(api_key: str):
    """Lightweight auth check against the OpenAI API.

    Lists models (a cheap, no-cost call) to verify the key authenticates.
    Returns (ok, message).
    """
    try:
        from openai import OpenAI
        OpenAI(api_key=api_key).models.list()
        return True, "Connected"
    except Exception as e:
        return False, str(e)


# Page config
st.set_page_config(
    page_title="Recipe Digitizer",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main {
        padding-top: 2rem;
    }
    .stButton>button {
        width: 100%;
    }
    .upload-text {
        text-align: center;
        padding: 2rem;
        border: 2px dashed #ccc;
        border-radius: 10px;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'processor' not in st.session_state:
    st.session_state.processor = None
if 'db' not in st.session_state:
    st.session_state.db = DatabaseManager("data/recipes.db")
if 'processing_results' not in st.session_state:
    st.session_state.processing_results = []
if 'confirm_delete_recipe_id' not in st.session_state:
    st.session_state.confirm_delete_recipe_id = None
if 'edit_success' not in st.session_state:
    st.session_state.edit_success = False
if 'config_manager' not in st.session_state:
    st.session_state.config_manager = None
if 'analyzed_config' not in st.session_state:
    st.session_state.analyzed_config = None
if 'show_config_editor' not in st.session_state:
    st.session_state.show_config_editor = False
if 'editing_cookbook_id' not in st.session_state:
    st.session_state.editing_cookbook_id = None


# ==================== Mealie Sync Helpers ====================

def sync_recipe_to_mealie(recipe, mealie_url: str, mealie_token: str):
    """
    Sync a single recipe to Mealie with verbose, step-by-step UI feedback.
    Captures the client's stdout so backend messages surface in the browser.
    """
    import io
    import contextlib

    if not (mealie_url and mealie_token):
        st.error("Mealie is not configured (missing URL or token).")
        return

    status = st.status(f"Syncing '{recipe.title}' to Mealie…", expanded=True)
    buffer = io.StringIO()
    try:
        with status:
            st.write("→ Connecting to Mealie…")
            client = MealieClient(mealie_url, mealie_token)
            if not client.test_connection():
                status.update(label="Connection failed", state="error")
                st.error(f"Could not reach Mealie at {mealie_url}")
                return

            st.write("→ Creating recipe and uploading content…")
            with contextlib.redirect_stdout(buffer):
                mealie_id = client.sync_recipe(asdict(recipe), recipe.image_path)

            # Surface backend log lines
            log = buffer.getvalue().strip()
            if log:
                st.code(log, language="text")

            if mealie_id:
                st.session_state.db.update_mealie_sync(recipe.id, mealie_id, recipe.content_fingerprint())
                recipe_link = f"{mealie_url}/recipe/{mealie_id}"
                status.update(label=f"✓ Synced '{recipe.title}'", state="complete")
                st.success(f"Synced as `{mealie_id}`")
                st.markdown(f"[🔗 View in Mealie]({recipe_link})")
            else:
                status.update(label="Sync failed", state="error")
                st.error("Mealie did not accept the recipe. See the log above for details.")
                return
    except Exception as e:
        status.update(label="Sync error", state="error")
        st.error(f"Unexpected error: {e}")
        log = buffer.getvalue().strip()
        if log:
            st.code(log, language="text")
        return

    st.rerun()


def categorize_recipes_for_sync(recipes):
    """
    Split recipes into (to_create, to_update, unchanged) based on Mealie sync state.

    - to_create: never synced (no mealie_id)
    - to_update: synced before, but content changed since (fingerprint mismatch)
    - unchanged: synced and content identical to last sync
    """
    to_create, to_update, unchanged = [], [], []
    for r in recipes:
        if not r.mealie_id:
            to_create.append(r)
        elif r.mealie_synced_hash != r.content_fingerprint():
            to_update.append(r)
        else:
            unchanged.append(r)
    return to_create, to_update, unchanged


def bulk_sync_to_mealie(mealie_url: str, mealie_token: str):
    """
    Sync the entire recipe database to Mealie: create new recipes, update changed
    ones, skip unchanged ones. Only the latest version is pushed.
    """
    import io
    import contextlib

    if not (mealie_url and mealie_token):
        st.error("Mealie is not configured (missing URL or token).")
        return

    db = st.session_state.db
    client = MealieClient(mealie_url, mealie_token)

    if not client.test_connection():
        st.error(f"Could not reach Mealie at {mealie_url}")
        return

    recipes = db.list_recipes()  # all recipes, no limit
    to_create, to_update, unchanged = categorize_recipes_for_sync(recipes)
    work = [(r, 'create') for r in to_create] + [(r, 'update') for r in to_update]

    if not work:
        st.success(f"Everything is up to date — {len(unchanged)} recipe(s) already synced.")
        return

    progress = st.progress(0.0, text="Starting sync…")
    created = updated = failed = 0
    failures = []

    for i, (recipe, action) in enumerate(work):
        progress.progress(i / len(work), text=f"{action.capitalize()}: {recipe.title}")
        try:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                if action == 'create':
                    mealie_id = client.sync_recipe(asdict(recipe), recipe.image_path)
                    ok = mealie_id is not None
                else:
                    ok = client.update_recipe(recipe.mealie_id, asdict(recipe))
                    mealie_id = recipe.mealie_id
                    # If the recipe was deleted in Mealie, recreate it
                    if not ok:
                        mealie_id = client.sync_recipe(asdict(recipe), recipe.image_path)
                        ok = mealie_id is not None

            if ok:
                db.update_mealie_sync(recipe.id, mealie_id, recipe.content_fingerprint())
                if action == 'create':
                    created += 1
                else:
                    updated += 1
            else:
                failed += 1
                failures.append((recipe.title, buffer.getvalue().strip()))
        except Exception as e:
            failed += 1
            failures.append((recipe.title, str(e)))

    progress.progress(1.0, text="Sync complete")

    summary = f"✓ {created} created, {updated} updated, {len(unchanged)} unchanged"
    if failed:
        summary += f", {failed} failed"
        detail = "\n\n".join(f"{title}\n{d}" for title, d in failures if d)
    else:
        detail = None

    # Stash result and rerun so the sidebar counts recompute; result is shown once.
    st.session_state.mealie_action_result = {
        'level': 'warning' if failed else 'success',
        'summary': summary,
        'detail': detail,
    }
    st.rerun()


def delete_all_from_mealie(mealie_url: str, mealie_token: str):
    """
    Delete every recipe this app synced (tagged 'recipe_digitizer') from Mealie,
    then clear the corresponding local sync state. Destructive and irreversible.
    """
    if not (mealie_url and mealie_token):
        st.error("Mealie is not configured (missing URL or token).")
        return

    db = st.session_state.db
    client = MealieClient(mealie_url, mealie_token)

    with st.status("Deleting app-synced recipes from Mealie…", expanded=True) as status:
        st.write("→ Connecting to Mealie…")
        if not client.test_connection():
            status.update(label="Connection failed", state="error")
            st.error(f"Could not reach Mealie at {mealie_url}")
            return

        st.write("→ Finding and deleting tagged recipes…")
        deleted, failed = client.delete_app_synced_recipes()

        # Clear local sync state for everything that was removed
        local_by_mealie_id = {r.mealie_id: r for r in db.list_recipes() if r.mealie_id}
        cleared = 0
        for slug in deleted:
            recipe = local_by_mealie_id.get(slug)
            if recipe:
                db.clear_mealie_sync(recipe.id)
                cleared += 1

    if failed:
        result = {
            'level': 'warning',
            'summary': f"Deleted {len(deleted)} recipe(s); {len(failed)} could not be deleted.",
            'detail': "\n".join(failed),
        }
    elif deleted:
        result = {
            'level': 'success',
            'summary': f"Deleted {len(deleted)} recipe(s) from Mealie; cleared {cleared} local sync record(s).",
            'detail': None,
        }
    else:
        result = {
            'level': 'info',
            'summary': "No app-synced recipes found in Mealie.",
            'detail': None,
        }

    # Stash result and rerun so all sidebar counts recompute; result is shown once.
    st.session_state.mealie_action_result = result
    st.rerun()


def render_recipe_detail(recipe, mealie_enabled, mealie_url=None, mealie_token=None, show_actions=True):
    """Render the full detail for one recipe.

    Used below the Recipes table (with actions) and inside the View Full Recipe
    modal (read-only — set show_actions=False to avoid opening nested dialogs).
    """
    cookbooks = {cb.id: cb.name for cb in st.session_state.db.list_cookbooks()}

    st.markdown(f"### {recipe.title}")

    # Metadata badges
    meta = []
    if recipe.servings:
        meta.append(f"🍽 {recipe.servings}")
    if recipe.prep_time:
        meta.append(f"⏱ Prep {recipe.prep_time}")
    if recipe.cook_time:
        meta.append(f"🔥 Cook {recipe.cook_time}")
    elif recipe.total_time:
        meta.append(f"⏱ {recipe.total_time}")
    if recipe.cookbook_id in cookbooks:
        meta.append(f"📚 {cookbooks[recipe.cookbook_id]}")
    if meta:
        st.caption(" · ".join(meta))

    if recipe.tags:
        st.caption("🏷 " + " · ".join(recipe.tags))

    # Optional source image (only persistent paths still exist on disk)
    if recipe.image_path and Path(recipe.image_path).exists():
        with st.expander("🖼 Source image"):
            st.image(recipe.image_path, width='stretch')

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Ingredients:**")
        for ing in recipe.ingredients:
            st.markdown(f"- {ing}")
    with col_b:
        st.markdown("**Instructions:**")
        for i, inst in enumerate(recipe.instructions, 1):
            st.markdown(f"{i}. {inst}")

    if recipe.background_info:
        st.markdown("**About:**")
        st.markdown(recipe.background_info)
    if recipe.handwritten_notes:
        st.info(f"**Notes:** {recipe.handwritten_notes}")

    # Actions
    if not show_actions:
        return

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if recipe.markdown_path and Path(recipe.markdown_path).exists():
            with open(recipe.markdown_path, 'r') as f:
                st.download_button(
                    "📥 Download MD", f.read(),
                    file_name=f"{recipe.title}.md",
                    key=f"dl_{recipe.id}", width='stretch',
                )
    with c2:
        if st.button("✏️ Edit", key=f"edit_{recipe.id}", width='stretch'):
            edit_recipe_dialog(recipe.id, mealie_enabled, mealie_url, mealie_token)
    with c3:
        if recipe.mealie_id and mealie_enabled:
            st.link_button("🔗 View in Mealie", f"{mealie_url}/recipe/{recipe.mealie_id}",
                           width='stretch')
        elif mealie_enabled:
            if st.button("☁️ Sync to Mealie", key=f"sync_{recipe.id}", width='stretch'):
                sync_recipe_to_mealie(recipe, mealie_url, mealie_token)
    with c4:
        if st.button("🗑️ Delete", key=f"delete_{recipe.id}", width='stretch'):
            st.session_state.confirm_delete_recipe_id = recipe.id
            st.rerun()


# Sidebar configuration
with st.sidebar:
    st.title("⚙️ Settings")
    
    # OpenAI integration — key loaded from config/openai_config.json (single source of truth)
    st.subheader("OpenAI Integration")
    openai_key = load_openai_key()
    if openai_key:
        st.caption("✓ OpenAI key loaded from config/openai_config.json")
        if st.button("🔌 Test OpenAI Connection", width='stretch'):
            with st.spinner("Testing OpenAI connection…"):
                ok, msg = test_openai_connection(openai_key)
            if ok:
                st.success("✓ Connected!")
            else:
                st.error(f"✗ Connection failed: {msg}")
    else:
        st.caption("⚠️ No OpenAI key — create config/openai_config.json (see README)")

    st.divider()

    # Mealie integration — loaded from config/mealie_config.json
    st.subheader("Mealie Integration")

    _mealie_cfg = load_mealie_config()
    _cfg_url = _mealie_cfg.get('base_url') if _mealie_cfg else None
    _cfg_token = _mealie_cfg.get('api_token') if _mealie_cfg else None

    if _cfg_url and _cfg_token:
        mealie_enabled = True
        mealie_url = _cfg_url
        mealie_token = _cfg_token
        st.caption("✓ Mealie API token loaded from config/mealie_config.json")
        st.caption(f"🔗 {_cfg_url}")
        if st.button("🔌 Test Mealie Connection", width='stretch'):
            with st.spinner("Testing Mealie connection…"):
                ok = MealieClient(_cfg_url, _cfg_token).test_connection()
            if ok:
                st.success("✓ Connected!")
            else:
                st.error("✗ Connection failed")
    else:
        st.caption("⚠️ No config found — add config/mealie_config.json")
        mealie_enabled = False
        mealie_url = None
        mealie_token = None

    # Sync whole database to Mealie
    if mealie_enabled:
        st.divider()
        st.subheader("🔄 Sync Database")

        # Show the result of the last sync/delete action once, then clear it
        _action_result = st.session_state.pop('mealie_action_result', None)
        if _action_result:
            getattr(st, _action_result['level'])(_action_result['summary'])
            if _action_result.get('detail'):
                with st.expander("Details"):
                    st.code(_action_result['detail'], language="text")

        all_recipes = st.session_state.db.list_recipes()
        to_create, to_update, unchanged = categorize_recipes_for_sync(all_recipes)
        pending = len(to_create) + len(to_update)

        if pending:
            st.caption(
                f"🆕 {len(to_create)} new · ✏️ {len(to_update)} changed · "
                f"✅ {len(unchanged)} up to date"
            )
        else:
            st.caption(f"✅ All {len(unchanged)} recipe(s) up to date")

        if st.button(
            "☁️ Sync All to Mealie",
            width='stretch',
            disabled=pending == 0,
            help="Push new and changed recipes; unchanged ones are skipped",
        ):
            bulk_sync_to_mealie(mealie_url, mealie_token)

        # Danger zone — delete everything this app synced
        with st.expander("⚠️ Danger zone"):
            synced_count = sum(1 for r in all_recipes if r.mealie_id)
            st.caption(
                f"Delete all {synced_count} app-synced recipe(s) (tagged "
                f"`{MealieClient.APP_TAG}`) from Mealie. Recipes you added to "
                "Mealie another way are not touched. This cannot be undone."
            )
            confirm_delete_all = st.checkbox(
                "I understand this permanently deletes them from Mealie",
                key="confirm_delete_all_mealie",
            )
            if st.button(
                "🗑️ Delete All from Mealie",
                width='stretch',
                disabled=not confirm_delete_all,
            ):
                delete_all_from_mealie(mealie_url, mealie_token)

    # Initialize processor and config manager once. The LLM key is refreshed
    # from config before each LLM action via apply_openai_key(), so these are
    # created regardless of whether a key is present yet.
    if st.session_state.processor is None:
        st.session_state.processor = IntegratedRecipeProcessor(
            db_path="data/recipes.db",
            swift_script_path="apple_ocr.swift",
            openai_api_key=openai_key,
            mealie_base_url=_cfg_url,
            mealie_api_token=_cfg_token,
        )

    if st.session_state.config_manager is None:
        st.session_state.config_manager = CookbookConfigManager(openai_api_key=openai_key)
    
    # Database stats
    st.divider()
    st.subheader("📊 Database Stats")
    stats = st.session_state.db.get_processing_stats()
    st.metric("Total Recipes", stats['total_recipes'])
    if stats['mealie_sync']:
        st.metric("Synced to Mealie", stats['mealie_sync']['synced'])

# Main content
st.title("📚 Recipe Digitizer")
st.markdown("Upload cookbook photos and extract recipes automatically")

# Create tabs
# Display order: Recipes → Cookbooks → Upload → Search → Statistics.
# Variables stay bound to their original content blocks (tab1=Upload, tab2=Cookbooks,
# tab3=Recipes, tab4=Search, tab5=Statistics); only the displayed order/labels change.
tab3, tab2, tab1, tab4, tab5 = st.tabs(["📖 Recipes", "📚 Cookbooks", "📤 Upload", "🔍 Search", "📊 Statistics"])


# ==================== Dialog Functions ====================

@st.dialog("Recipe", width="large")
def view_recipe_dialog(recipe_id: int, mealie_enabled: bool, mealie_url: str = None, mealie_token: str = None):
    """Show the full detail for one recipe in a modal (read-only)."""
    recipe = st.session_state.db.get_recipe(recipe_id)
    if not recipe:
        st.error("Recipe not found")
        return
    render_recipe_detail(recipe, mealie_enabled, mealie_url, mealie_token, show_actions=False)


@st.dialog("Edit Recipe", width="large")
def edit_recipe_dialog(recipe_id: int, mealie_enabled: bool, mealie_url: str = None, mealie_token: str = None):
    """Edit recipe dialog with all fields and optional Mealie sync"""
    recipe = st.session_state.db.get_recipe(recipe_id)
    if not recipe:
        st.error("Recipe not found")
        return

    cookbooks = st.session_state.db.list_cookbooks()
    cookbook_map = {cb.id: cb.name for cb in cookbooks}

    with st.form("edit_recipe_form"):
        st.subheader("Basic Info")
        col1, col2 = st.columns(2)
        with col1:
            title = st.text_input("Title *", value=recipe.title, help="Recipe title (required)")
            cuisine = st.text_input("Cuisine", value=recipe.cuisine or "", help="e.g., Italian, Mexican")
        with col2:
            cookbook_options = list(cookbook_map.keys())
            cookbook_labels = [cookbook_map[k] for k in cookbook_options]
            current_cookbook_idx = cookbook_options.index(recipe.cookbook_id) if recipe.cookbook_id in cookbook_options else 0
            cookbook_id = st.selectbox(
                "Cookbook",
                options=cookbook_options,
                format_func=lambda x: cookbook_map[x],
                index=current_cookbook_idx
            )
            servings = st.text_input("Servings", value=recipe.servings or "", help="e.g., 4, 6-8")

        st.subheader("Time Info")
        col1, col2, col3 = st.columns(3)
        with col1:
            prep_time = st.text_input("Prep Time", value=recipe.prep_time or "", help="e.g., 15 minutes")
        with col2:
            cook_time = st.text_input("Cook Time", value=recipe.cook_time or "", help="e.g., 30 minutes")
        with col3:
            total_time = st.text_input("Total Time", value=recipe.total_time or "", help="e.g., 45 minutes")

        st.subheader("Content")
        ingredients = st.text_area(
            "Ingredients *",
            value="\n".join(recipe.ingredients),
            height=150,
            help="One ingredient per line (required)"
        )
        instructions = st.text_area(
            "Instructions *",
            value="\n".join(recipe.instructions),
            height=200,
            help="One instruction per line (required)"
        )

        st.subheader("Additional Info")
        col1, col2 = st.columns(2)
        with col1:
            background_info = st.text_area(
                "Background Info",
                value=recipe.background_info or "",
                height=100,
                help="Context about the recipe"
            )
        with col2:
            handwritten_notes = st.text_area(
                "Handwritten Notes",
                value=recipe.handwritten_notes or "",
                height=100,
                help="Notes from handwritten text"
            )

        tags = st.text_input(
            "Tags",
            value=", ".join(recipe.tags) if recipe.tags else "",
            help="Comma-separated tags"
        )

        st.subheader("Technical Fields")
        col1, col2, col3 = st.columns(3)
        with col1:
            page_number = st.number_input(
                "Page Number",
                value=recipe.page_number or 0,
                min_value=0,
                help="Page in cookbook"
            )
        with col2:
            ocr_confidence = st.number_input(
                "OCR Confidence",
                value=recipe.ocr_confidence or 0.0,
                min_value=0.0,
                max_value=1.0,
                step=0.01,
                help="OCR quality score"
            )
        with col3:
            image_path = st.text_input("Image Path", value=recipe.image_path or "")

        markdown_path = st.text_input("Markdown Path", value=recipe.markdown_path or "")

        # Mealie sync option
        sync_to_mealie = False
        if mealie_enabled:
            st.divider()

            col_mealie1, col_mealie2 = st.columns([1, 1])
            with col_mealie1:
                sync_to_mealie = st.checkbox(
                    "Sync to Mealie",
                    value=recipe.mealie_id is not None,
                    help="Update or create recipe in Mealie"
                )

            with col_mealie2:
                if recipe.mealie_id:
                    mealie_recipe_url = f"{mealie_url}/recipe/{recipe.mealie_id}"
                    st.markdown(f"[🔗 View in Mealie]({mealie_recipe_url})", unsafe_allow_html=False)

        st.divider()
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            save_button = st.form_submit_button("💾 Save Changes", type="primary", width='stretch')
        with col2:
            cancel_button = st.form_submit_button("❌ Cancel", width='stretch')
        with col3:
            delete_button = st.form_submit_button("🗑️ Delete Recipe", width='stretch')

    # Handle form submission
    if cancel_button:
        st.rerun()

    if delete_button:
        st.session_state.confirm_delete_recipe_id = recipe_id
        st.rerun()

    if save_button:
        # Validation
        errors = []
        if not title or not title.strip():
            errors.append("Title is required")

        ingredients_list = [line.strip() for line in ingredients.split("\n") if line.strip()]
        if not ingredients_list:
            errors.append("At least one ingredient is required")

        instructions_list = [line.strip() for line in instructions.split("\n") if line.strip()]
        if not instructions_list:
            errors.append("At least one instruction is required")

        if errors:
            for error in errors:
                st.error(error)
            st.stop()

        # Parse tags
        tags_list = [tag.strip() for tag in tags.split(",") if tag.strip()]

        # Update recipe object
        recipe.title = title.strip()
        recipe.cookbook_id = cookbook_id
        recipe.cuisine = cuisine.strip()
        recipe.servings = servings.strip()
        recipe.prep_time = prep_time.strip()
        recipe.cook_time = cook_time.strip()
        recipe.total_time = total_time.strip()
        recipe.ingredients = ingredients_list
        recipe.instructions = instructions_list
        recipe.background_info = background_info.strip()
        recipe.handwritten_notes = handwritten_notes.strip()
        recipe.tags = tags_list
        recipe.page_number = page_number if page_number > 0 else None
        recipe.ocr_confidence = ocr_confidence if ocr_confidence > 0 else None
        recipe.image_path = image_path.strip()
        recipe.markdown_path = markdown_path.strip()

        try:
            # Save to database
            st.session_state.db.update_recipe(recipe)

            # Auto-regenerate markdown
            if st.session_state.processor:
                try:
                    markdown_path = st.session_state.processor._export_markdown(recipe)
                    recipe.markdown_path = markdown_path
                    st.session_state.db.update_recipe(recipe)
                except Exception as e:
                    st.warning(f"Recipe saved but markdown regeneration failed: {e}")

            # Sync to Mealie if requested
            if sync_to_mealie and mealie_url and mealie_token:
                try:
                    mealie_client = MealieClient(mealie_url, mealie_token)
                    if recipe.mealie_id:
                        # Update existing
                        success = mealie_client.update_recipe(recipe.mealie_id, asdict(recipe))
                        if success:
                            st.session_state.db.update_mealie_sync(recipe.id, recipe.mealie_id)
                        else:
                            st.warning("Recipe saved but Mealie update failed")
                    else:
                        # Create new
                        mealie_id = st.session_state.processor._sync_to_mealie(recipe, recipe.image_path)
                        if mealie_id:
                            st.session_state.db.update_mealie_sync(recipe.id, mealie_id)
                        else:
                            st.warning("Recipe saved but Mealie sync failed")
                except Exception as e:
                    st.warning(f"Recipe saved but Mealie sync failed: {e}")

            st.success("Recipe updated successfully!")
            st.session_state.edit_success = True
            st.rerun()

        except Exception as e:
            st.error(f"Error saving recipe: {e}")


@st.dialog("Delete Recipe", width="large")
def confirm_delete_dialog(recipe_id: int, mealie_enabled: bool, mealie_url: str = None, mealie_token: str = None):
    """Confirm recipe deletion with warning"""
    recipe = st.session_state.db.get_recipe(recipe_id)
    if not recipe:
        st.error("Recipe not found")
        return

    st.warning(f"⚠️ You are about to delete: **{recipe.title}**")
    st.write("This action will delete:")
    st.write("- Database entry")
    if recipe.markdown_path and Path(recipe.markdown_path).exists():
        st.write("- Markdown file")
    if recipe.mealie_id and mealie_enabled:
        st.write("- Mealie recipe")

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        if st.button("✓ Yes, Delete", type="primary", width='stretch'):
            success = True
            messages = []

            # Delete from Mealie first
            if recipe.mealie_id and mealie_enabled and mealie_url and mealie_token:
                try:
                    mealie_client = MealieClient(mealie_url, mealie_token)
                    if mealie_client.delete_recipe(recipe.mealie_id):
                        messages.append("Deleted from Mealie")
                    else:
                        messages.append("Warning: Could not delete from Mealie")
                        success = False
                except Exception as e:
                    messages.append(f"Warning: Mealie deletion failed: {e}")

            # Delete markdown file
            if recipe.markdown_path:
                try:
                    md_path = Path(recipe.markdown_path)
                    if md_path.exists():
                        md_path.unlink()
                        messages.append("Deleted markdown file")
                except Exception as e:
                    messages.append(f"Warning: Could not delete markdown file: {e}")

            # Delete from database
            try:
                if st.session_state.db.delete_recipe(recipe_id):
                    messages.append("Deleted from database")
                else:
                    messages.append("Error: Could not delete from database")
                    success = False
            except Exception as e:
                messages.append(f"Error: Database deletion failed: {e}")
                success = False

            # Show results
            if success:
                st.success("Recipe deleted successfully!")
                for msg in messages:
                    st.info(msg)
            else:
                st.error("Deletion completed with errors")
                for msg in messages:
                    st.warning(msg)

            # Clear confirmation state
            st.session_state.confirm_delete_recipe_id = None
            st.rerun()

    with col2:
        if st.button("❌ Cancel", width='stretch'):
            st.session_state.confirm_delete_recipe_id = None
            st.rerun()


@st.dialog("Delete Cookbook", width="large")
def confirm_delete_cookbook_dialog(cookbook_id: int, mealie_enabled: bool, mealie_url: str = None, mealie_token: str = None):
    """Confirm cookbook deletion, including all of its recipes."""
    cookbook = st.session_state.db.get_cookbook(cookbook_id)
    if not cookbook:
        st.error("Cookbook not found")
        return

    recipes = st.session_state.db.list_recipes(cookbook_id=cookbook_id)
    synced = [r for r in recipes if r.mealie_id]
    cookbook_path = Path("cookbooks") / cookbook.name.lower().replace(" ", "-")

    st.warning(f"⚠️ You are about to delete the cookbook **{cookbook.name}**. This cannot be undone.")
    st.write("This action will delete:")
    st.write("- The cookbook database entry")
    if recipes:
        st.write(f"- All {len(recipes)} recipe(s) in this cookbook (database entries)")
    if synced and mealie_enabled:
        st.write(f"- {len(synced)} recipe(s) from Mealie")

    delete_folder = False
    if cookbook_path.exists():
        delete_folder = st.checkbox(
            f"Also delete the folder `{cookbook_path}` from disk "
            "(source images, Markdown exports, config)",
            key=f"delete_cookbook_folder_{cookbook_id}",
        )

    st.divider()
    col1, col2 = st.columns(2)

    with col1:
        if st.button("✓ Yes, Delete", type="primary", width='stretch'):
            success = True
            messages = []

            # Delete synced recipes from Mealie first
            if synced and mealie_enabled and mealie_url and mealie_token:
                try:
                    mealie_client = MealieClient(mealie_url, mealie_token)
                    deleted = sum(1 for r in synced if mealie_client.delete_recipe(r.mealie_id))
                    messages.append(f"Deleted {deleted}/{len(synced)} recipe(s) from Mealie")
                    if deleted < len(synced):
                        success = False
                except Exception as e:
                    messages.append(f"Warning: Mealie deletion failed: {e}")
                    success = False

            # Delete per-recipe Markdown files, unless the whole folder is going
            if not delete_folder:
                removed_md = 0
                for r in recipes:
                    if r.markdown_path and Path(r.markdown_path).exists():
                        try:
                            Path(r.markdown_path).unlink()
                            removed_md += 1
                        except Exception as e:
                            messages.append(f"Warning: Could not delete markdown for '{r.title}': {e}")
                if removed_md:
                    messages.append(f"Deleted {removed_md} markdown file(s)")

            # Delete the cookbook folder from disk
            if delete_folder:
                try:
                    shutil.rmtree(cookbook_path)
                    messages.append(f"Deleted folder {cookbook_path}")
                except Exception as e:
                    messages.append(f"Warning: Could not delete folder: {e}")
                    success = False

            # Delete the cookbook and its recipes from the database
            try:
                if st.session_state.db.delete_cookbook(cookbook_id):
                    messages.append("Deleted cookbook and its recipes from the database")
                else:
                    messages.append("Error: Could not delete cookbook from database")
                    success = False
            except Exception as e:
                messages.append(f"Error: Database deletion failed: {e}")
                success = False

            if success:
                st.success(f"Cookbook '{cookbook.name}' deleted successfully!")
            else:
                st.error("Deletion completed with errors")
            for msg in messages:
                st.info(msg)

            st.rerun()

    with col2:
        if st.button("❌ Cancel", width='stretch'):
            st.rerun()


@st.dialog("Generate Config with AI", width="large")
def generate_config_dialog(cookbook_id: int):
    """Upload a sample page and (re)generate the cookbook config via AI.

    Works whether or not a config already exists — an existing config is
    overwritten. This is how you recover a cookbook whose config fell back to
    default values when AI generation failed at creation time.
    """
    cookbook = st.session_state.db.get_cookbook(cookbook_id)
    if not cookbook:
        st.error("Cookbook not found")
        return

    cookbook_path = Path("cookbooks") / cookbook.name.lower().replace(" ", "-")
    config_exists = (cookbook_path / "config.json").exists()

    st.markdown(f"### {cookbook.name}")
    if config_exists:
        st.info("Analyze a sample page and **overwrite** the current config with the result.")
    else:
        st.info("Upload a sample page to detect this cookbook's layout and structure.")

    if not load_openai_key():
        st.warning("⚠️ No OpenAI key — add it to config/openai_config.json to use AI generation.")
        return

    sample = st.file_uploader(
        "Sample page",
        type=['jpg', 'jpeg', 'png'],
        key=f"regen_sample_{cookbook_id}",
    )

    if sample and st.button("🤖 Analyze & Save", type="primary", width='stretch'):
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
            tmp_file.write(sample.read())
            tmp_path = tmp_file.name

        try:
            with st.spinner("🤖 Analyzing page structure..."):
                apply_openai_key()
                success, ai_config, message = st.session_state.config_manager.analyze_cookbook_structure(tmp_path)

            if success:
                final_config = st.session_state.config_manager.merge_with_template(
                    ai_config,
                    {
                        "name": cookbook.name,
                        "authors": [a.strip() for a in cookbook.authors.split(",")] if isinstance(cookbook.authors, str) else cookbook.authors,
                        "cuisine": cookbook.cuisine,
                        "language": cookbook.language,
                    },
                )
                st.session_state.config_manager.create_folder_structure(cookbook_path)
                saved, save_msg = st.session_state.config_manager.save_config(final_config, cookbook_path)
                if saved:
                    st.success("✓ Config generated and saved!")
                    st.rerun()
                else:
                    st.error(f"Could not save config: {save_msg}")
            else:
                st.error(f"Analysis failed: {message}")
        finally:
            Path(tmp_path).unlink(missing_ok=True)


@st.dialog("View Generated Config", width="large")
def view_config_dialog(config: Dict):
    """Display generated config in a readable format"""
    st.markdown("### Generated Configuration")

    # Show formatted summary
    if st.session_state.config_manager:
        summary = st.session_state.config_manager.format_config_summary(config)
        st.markdown(summary)

    st.divider()

    # Show raw JSON
    with st.expander("📄 View Raw JSON"):
        st.json(config)

    if st.button("Close"):
        st.rerun()


@st.dialog("Edit Cookbook Config", width="large")
def edit_cookbook_config_dialog(cookbook_id: int):
    """Edit existing cookbook configuration"""
    cookbook = st.session_state.db.get_cookbook(cookbook_id)
    if not cookbook:
        st.error("Cookbook not found")
        return

    # Load existing config
    cookbook_path = Path("cookbooks") / cookbook.name.lower().replace(" ", "-")
    success, existing_config, message = st.session_state.config_manager.load_config(cookbook_path)

    if not success:
        st.warning(f"No existing config found. {message}")
        existing_config = st.session_state.config_manager.create_config_template(
            cookbook.name,
            cookbook.authors if isinstance(cookbook.authors, str) else ", ".join(cookbook.authors),
            cookbook.language,
            cookbook.cuisine
        )

    st.markdown(f"### Edit Config: {cookbook.name}")

    # Tab for pretty view vs JSON view
    view_tab1, view_tab2 = st.tabs(["📋 Pretty View", "</> JSON View"])

    with view_tab1:
        with st.form("edit_config_form"):
            st.subheader("Basic Info")
            col1, col2 = st.columns(2)

            with col1:
                name = st.text_input("Name", value=existing_config.get("cookbook", {}).get("name", ""))
                language = st.selectbox(
                    "Language",
                    ["en", "de", "fr", "es", "it"],
                    index=["en", "de", "fr", "es", "it"].index(existing_config.get("cookbook", {}).get("language", "en"))
                )

            with col2:
                authors_str = ", ".join(existing_config.get("cookbook", {}).get("authors", []))
                authors = st.text_input("Authors (comma-separated)", value=authors_str)
                cuisine = st.text_input("Cuisine", value=existing_config.get("cookbook", {}).get("cuisine", ""))

            st.subheader("Layout")
            col1, col2 = st.columns(2)

            with col1:
                typical_columns = st.number_input(
                    "Number of Columns",
                    min_value=1,
                    max_value=3,
                    value=existing_config.get("layout", {}).get("typical_columns", 1)
                )
                title_position = st.selectbox(
                    "Title Position",
                    ["top", "center", "left-column", "right-column"],
                    index=["top", "center", "left-column", "right-column"].index(
                        existing_config.get("layout", {}).get("title_position", "top")
                    )
                )

            with col2:
                has_background_stories = st.checkbox(
                    "Has Background Stories",
                    value=existing_config.get("layout", {}).get("has_background_stories", False)
                )
                has_handwritten_notes = st.checkbox(
                    "Has Handwritten Notes",
                    value=existing_config.get("layout", {}).get("has_handwritten_notes", False)
                )

            if typical_columns > 1:
                col1, col2 = st.columns(2)
                with col1:
                    ingredients_side = st.selectbox(
                        "Ingredients Location",
                        ["left-column", "right-column", "top-section"],
                        index=["left-column", "right-column", "top-section"].index(
                            existing_config.get("layout", {}).get("ingredients_side", "left-column")
                        ) if existing_config.get("layout", {}).get("ingredients_side") in ["left-column", "right-column", "top-section"] else 0
                    )
                with col2:
                    instructions_side = st.selectbox(
                        "Instructions Location",
                        ["left-column", "right-column", "below-ingredients"],
                        index=["left-column", "right-column", "below-ingredients"].index(
                            existing_config.get("layout", {}).get("instructions_side", "right-column")
                        ) if existing_config.get("layout", {}).get("instructions_side") in ["left-column", "right-column", "below-ingredients"] else 1
                    )
            else:
                ingredients_side = "top-section"
                instructions_side = "below-ingredients"

            st.subheader("Extraction Hints")
            description = st.text_area(
                "Description",
                value=existing_config.get("extraction_hints", {}).get("description", ""),
                help="Brief description of this cookbook's style"
            )

            special_instructions = st.text_area(
                "Special Instructions for AI",
                value=existing_config.get("extraction_hints", {}).get("special_instructions", ""),
                help="Detailed instructions for the AI parser",
                height=100
            )

            default_tags = st.text_input(
                "Default Tags (comma-separated)",
                value=", ".join(existing_config.get("default_tags", []))
            )

            col1, col2 = st.columns(2)
            with col1:
                if st.form_submit_button("💾 Save Config", type="primary", width='stretch'):
                    # Build updated config
                    updated_config = {
                        "cookbook": {
                            "name": name,
                            "authors": [a.strip() for a in authors.split(",") if a.strip()],
                            "language": language,
                            "cuisine": cuisine
                        },
                        "layout": {
                            "title_position": title_position,
                            "has_background_stories": has_background_stories,
                            "typical_columns": typical_columns,
                            "has_handwritten_notes": has_handwritten_notes,
                            "typical_page_structure": existing_config.get("layout", {}).get("typical_page_structure", "")
                        },
                        "extraction_hints": {
                            "description": description,
                            "special_instructions": special_instructions,
                            "common_headings": existing_config.get("extraction_hints", {}).get("common_headings", {}),
                            "language_specific": existing_config.get("extraction_hints", {}).get("language_specific", {
                                "output_language": language,
                                "preserve_original": True,
                                "do_not_translate": language != "en"
                            })
                        },
                        "default_tags": [t.strip() for t in default_tags.split(",") if t.strip()]
                    }

                    if typical_columns > 1:
                        updated_config["layout"]["ingredients_side"] = ingredients_side
                        updated_config["layout"]["instructions_side"] = instructions_side

                    # Save config
                    success, msg = st.session_state.config_manager.save_config(updated_config, cookbook_path)

                    if success:
                        st.success("✓ Config saved successfully!")
                        st.rerun()
                    else:
                        st.error(f"Error saving config: {msg}")

            with col2:
                if st.form_submit_button("❌ Cancel", width='stretch'):
                    st.rerun()

    with view_tab2:
        st.markdown("### Raw JSON Editor")
        st.info("Advanced users can edit the JSON directly")

        edited_json = st.text_area(
            "Config JSON",
            value=json.dumps(existing_config, indent=2),
            height=400
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 Save JSON", width='stretch'):
                try:
                    parsed_config = json.loads(edited_json)
                    success, msg = st.session_state.config_manager.save_config(parsed_config, cookbook_path)

                    if success:
                        st.success("✓ Config saved!")
                        st.rerun()
                    else:
                        st.error(f"Error: {msg}")
                except json.JSONDecodeError as e:
                    st.error(f"Invalid JSON: {e}")

        with col2:
            if st.button("❌ Cancel", width='stretch'):
                st.rerun()


# TAB 1: Upload
with tab1:
    if not openai_key:
        st.warning("⚠️ Please enter your OpenAI API key in the sidebar to get started")
        st.stop()
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("Upload Recipe Photos")
        
        # Cookbook selection
        cookbooks = st.session_state.db.list_cookbooks()
        cookbook_names = [cb.name for cb in cookbooks]
        
        if cookbook_names:
            selected_cookbook = st.selectbox(
                "Select Cookbook",
                cookbook_names,
                help="Choose which cookbook these recipes are from"
            )
        else:
            st.info("No cookbooks found. Go to the Cookbooks tab to create one!")
            selected_cookbook = None

        # File upload
        uploaded_files = st.file_uploader(
            "Upload recipe photos",
            accept_multiple_files=True,
            type=['jpg', 'jpeg', 'png', 'heic'],
            help="Drag and drop or click to browse"
        )
        
        # Processing options
        col_opt1, col_opt2 = st.columns(2)
        with col_opt1:
            skip_duplicates = st.checkbox("Skip duplicates", value=True)
        with col_opt2:
            sync_to_mealie = st.checkbox("Sync to Mealie", value=False, disabled=not mealie_enabled)
        
        # Process button
        if uploaded_files and selected_cookbook:
            if st.button("🚀 Process Recipes", type="primary"):
                st.session_state.processing_results = []

                progress_bar = st.progress(0)

                for i, uploaded_file in enumerate(uploaded_files):
                    label = f"Processing {i+1}/{len(uploaded_files)}: {uploaded_file.name}"
                    with st.status(label, expanded=True) as status:
                        # Stream each pipeline step into the status panel
                        def report(msg, _status=status):
                            _status.write(msg)

                        # Save to temp file
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
                            tmp_file.write(uploaded_file.read())
                            tmp_path = tmp_file.name

                        try:
                            report("🔑 Loading OpenAI key…")
                            apply_openai_key()
                            success, recipe_id, message = st.session_state.processor.process_image(
                                tmp_path,
                                selected_cookbook,
                                skip_duplicates=skip_duplicates,
                                sync_to_mealie=sync_to_mealie,
                                progress_callback=report,
                            )

                            st.session_state.processing_results.append({
                                'filename': uploaded_file.name,
                                'success': success,
                                'recipe_id': recipe_id,
                                'message': message,
                            })

                            if success:
                                status.update(label=f"✓ {uploaded_file.name}", state="complete", expanded=False)
                            elif 'duplicate' in message.lower():
                                report(message)
                                status.update(
                                    label=f"⏭️ {uploaded_file.name} (already processed)",
                                    state="complete", expanded=False,
                                )
                            else:
                                report(f"❌ {message}")
                                status.update(label=f"✗ {uploaded_file.name}", state="error")

                        except Exception as e:
                            st.session_state.processing_results.append({
                                'filename': uploaded_file.name,
                                'success': False,
                                'recipe_id': None,
                                'message': str(e),
                            })
                            report(f"❌ {e}")
                            status.update(label=f"✗ {uploaded_file.name}", state="error")

                        finally:
                            # Clean up temp file
                            Path(tmp_path).unlink(missing_ok=True)

                    progress_bar.progress((i + 1) / len(uploaded_files))

                st.success(f"✓ Finished processing {len(uploaded_files)} image(s)!")
    
    with col2:
        st.subheader("Processing Results")
        
        if st.session_state.processing_results:
            for result in st.session_state.processing_results:
                if result['success']:
                    st.success(f"✓ {result['filename']}")
                    
                    # Show recipe preview
                    if result['recipe_id']:
                        recipe = st.session_state.db.get_recipe(result['recipe_id'])
                        if recipe:
                            with st.expander(f"Preview: {recipe.title}"):
                                st.markdown(f"**Ingredients:** {len(recipe.ingredients)}")
                                st.markdown(f"**Steps:** {len(recipe.instructions)}")
                                
                                if st.button("View Full Recipe", key=f"view_{result['recipe_id']}"):
                                    view_recipe_dialog(result['recipe_id'], mealie_enabled, mealie_url, mealie_token)
                
                elif 'duplicate' in result['message'].lower():
                    st.info(f"⏭️ {result['filename']} (already processed)")
                else:
                    st.error(f"✗ {result['filename']}: {result['message']}")
        else:
            st.info("Upload photos and click 'Process Recipes' to begin")

# TAB 2: Cookbooks
with tab2:
    st.subheader("📚 Cookbook Manager")

    if not openai_key:
        st.warning("⚠️ Please enter your OpenAI API key in the sidebar to use AI-powered config generation")

    # Sub-tabs for different views
    # "Manage Existing" shown first; variables stay bound to their original blocks.
    cookbook_tab2, cookbook_tab1 = st.tabs(["📋 Manage Existing", "➕ Create New"])

    # TAB 2.1: Create New Cookbook
    with cookbook_tab1:
        st.markdown("### Create New Cookbook")

        with st.form("new_cookbook_form"):
            st.markdown("#### Basic Information")
            col1, col2 = st.columns(2)

            with col1:
                new_name = st.text_input("Cookbook Name *", help="e.g., 'Ottolenghi Simple'")
                new_language = st.selectbox("Language", ["en", "de", "fr", "es", "it"])

            with col2:
                new_authors = st.text_input("Authors (comma-separated)", help="e.g., 'Yotam Ottolenghi'")
                new_cuisine = st.text_input("Cuisine Type", help="e.g., 'Mediterranean', 'Middle Eastern'")

            st.divider()

            # AI Analysis Section
            st.markdown("#### 🤖 AI-Powered Structure Analysis (Optional)")
            st.markdown("Upload a sample page from this cookbook to automatically detect layout and structure.")

            sample_page = st.file_uploader(
                "Sample Page",
                type=['jpg', 'jpeg', 'png'],
                help="Upload one representative recipe page",
                key="sample_page_upload"
            )

            analyze_clicked = st.form_submit_button("🔍 Analyze & Create Cookbook", type="primary", width='stretch')

        # Handle analysis
        if analyze_clicked:
            if not new_name:
                st.error("Please enter a cookbook name")
            else:
                # Check if cookbook already exists
                existing = st.session_state.db.get_cookbook_by_name(new_name)
                if existing:
                    st.error(f"Cookbook '{new_name}' already exists!")
                else:
                    with st.spinner("Creating cookbook..."):
                        # Create basic config
                        author_list = [a.strip() for a in new_authors.split(',')] if new_authors else []

                        if sample_page and openai_key:
                            # Save sample page temporarily
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
                                tmp_file.write(sample_page.read())
                                tmp_path = tmp_file.name

                            try:
                                # Analyze with AI
                                with st.spinner("🤖 Analyzing page structure..."):
                                    apply_openai_key()
                                    success, ai_config, message = st.session_state.config_manager.analyze_cookbook_structure(tmp_path)

                                if success:
                                    st.success("✓ Analysis complete!")

                                    # Merge with user info
                                    final_config = st.session_state.config_manager.merge_with_template(
                                        ai_config,
                                        {
                                            "name": new_name,
                                            "authors": author_list,
                                            "cuisine": new_cuisine,
                                            "language": new_language
                                        }
                                    )

                                    # Show analysis results
                                    with st.expander("📊 Analysis Results", expanded=True):
                                        summary = st.session_state.config_manager.format_config_summary(final_config)
                                        st.markdown(summary)

                                        col_a, col_b = st.columns(2)
                                        with col_a:
                                            if st.button("📄 View Full JSON"):
                                                view_config_dialog(final_config)
                                        with col_b:
                                            if st.button("✏️ Edit Config"):
                                                st.session_state.analyzed_config = final_config
                                                st.session_state.show_config_editor = True

                                    # Save config
                                    cookbook_path = Path("cookbooks") / new_name.lower().replace(" ", "-")
                                    success, msg = st.session_state.config_manager.create_folder_structure(cookbook_path)

                                    if success:
                                        success, msg = st.session_state.config_manager.save_config(final_config, cookbook_path)

                                        if success:
                                            # Add to database
                                            cookbook = Cookbook(
                                                name=new_name,
                                                authors=", ".join(author_list),
                                                language=new_language,
                                                cuisine=new_cuisine,
                                                config_path=str(cookbook_path / "config.json")
                                            )
                                            cookbook_id = st.session_state.db.add_cookbook(cookbook)

                                            st.success(f"✅ Cookbook '{new_name}' created successfully!")
                                            st.info(f"📁 Folder: {cookbook_path}")
                                            st.info(f"📂 Add recipe images to: {cookbook_path / 'images'}")

                                            # Clear form
                                            st.rerun()
                                        else:
                                            st.error(f"Error saving config: {msg}")
                                    else:
                                        st.error(f"Error creating folders: {msg}")

                                else:
                                    st.error(f"Analysis failed: {message}")
                                    st.info("Creating cookbook with basic template...")

                                    # Fallback to basic template
                                    basic_config = st.session_state.config_manager.create_config_template(
                                        new_name, new_authors, new_language, new_cuisine
                                    )

                                    cookbook_path = Path("cookbooks") / new_name.lower().replace(" ", "-")
                                    st.session_state.config_manager.create_folder_structure(cookbook_path)
                                    st.session_state.config_manager.save_config(basic_config, cookbook_path)

                                    cookbook = Cookbook(
                                        name=new_name,
                                        authors=", ".join(author_list),
                                        language=new_language,
                                        cuisine=new_cuisine,
                                        config_path=str(cookbook_path / "config.json")
                                    )
                                    cookbook_id = st.session_state.db.add_cookbook(cookbook)

                                    st.success(f"✅ Cookbook '{new_name}' created with basic template")

                            finally:
                                # Clean up temp file
                                Path(tmp_path).unlink(missing_ok=True)

                        else:
                            # No sample page - create with basic template
                            st.info("Creating cookbook with basic template (no AI analysis)")

                            basic_config = st.session_state.config_manager.create_config_template(
                                new_name, new_authors, new_language, new_cuisine
                            )

                            cookbook_path = Path("cookbooks") / new_name.lower().replace(" ", "-")
                            st.session_state.config_manager.create_folder_structure(cookbook_path)
                            st.session_state.config_manager.save_config(basic_config, cookbook_path)

                            cookbook = Cookbook(
                                name=new_name,
                                authors=", ".join(author_list),
                                language=new_language,
                                cuisine=new_cuisine,
                                config_path=str(cookbook_path / "config.json")
                            )
                            cookbook_id = st.session_state.db.add_cookbook(cookbook)

                            st.success(f"✅ Cookbook '{new_name}' created!")
                            st.info("💡 Tip: Upload a sample page next time for AI-powered config generation")

                            st.rerun()

    # TAB 2.2: Manage Existing Cookbooks
    with cookbook_tab2:
        st.markdown("### Existing Cookbooks")

        cookbooks = st.session_state.db.list_cookbooks()

        if not cookbooks:
            st.info("No cookbooks yet. Create one in the 'Create New' tab!")
        else:
            for cookbook in cookbooks:
                with st.container():
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        st.markdown(f"### {cookbook.name}")

                        # Determine cookbook path and check config
                        cookbook_path = Path("cookbooks") / cookbook.name.lower().replace(" ", "-")
                        config_exists = (cookbook_path / "config.json").exists()

                        # Load config data if available to supplement database info
                        authors_to_show = cookbook.authors
                        language_to_show = cookbook.language
                        cuisine_to_show = cookbook.cuisine

                        if config_exists and st.session_state.config_manager:
                            success, config, msg = st.session_state.config_manager.load_config(cookbook_path)
                            if success and 'cookbook' in config:
                                # Use config data if database is empty
                                if not authors_to_show and 'authors' in config['cookbook']:
                                    authors_to_show = config['cookbook']['authors']
                                if not language_to_show and 'language' in config['cookbook']:
                                    language_to_show = config['cookbook']['language']
                                if not cuisine_to_show and 'cuisine' in config['cookbook']:
                                    cuisine_to_show = config['cookbook']['cuisine']

                        # Show authors
                        if authors_to_show:
                            if isinstance(authors_to_show, list):
                                authors_display = ", ".join(authors_to_show)
                            else:
                                authors_display = authors_to_show
                            st.caption(f"👥 Authors: {authors_display}")

                        # Show language and cuisine
                        info_parts = []
                        if language_to_show:
                            lang_names = {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian"}
                            info_parts.append(f"🌍 {lang_names.get(language_to_show, language_to_show)}")
                        if cuisine_to_show:
                            info_parts.append(f"🍽️ {cuisine_to_show}")
                        if info_parts:
                            st.caption(" | ".join(info_parts))

                        # Recipe count
                        recipes = st.session_state.db.list_recipes(cookbook_id=cookbook.id)
                        st.caption(f"📖 {len(recipes)} recipes")

                        # Config status

                        if config_exists:
                            st.caption("✅ Config available")
                        else:
                            st.caption("⚠️ No config found")

                    with col2:
                        # Action buttons
                        if config_exists:
                            if st.button("📝 Edit Config", key=f"edit_config_{cookbook.id}", width='stretch'):
                                edit_cookbook_config_dialog(cookbook.id)
                            # Re-run AI generation even though a config already exists —
                            # recovers cookbooks left with default values after a failed
                            # generation at creation time.
                            if st.button("🤖 Regenerate Config (AI)", key=f"regen_config_{cookbook.id}", width='stretch'):
                                generate_config_dialog(cookbook.id)
                        else:
                            if st.button("🤖 Generate Config", key=f"gen_config_{cookbook.id}", width='stretch'):
                                generate_config_dialog(cookbook.id)

                        if st.button("📊 View Recipes", key=f"view_recipes_{cookbook.id}", width='stretch'):
                            st.info(f"Switch to the Browse tab and filter by '{cookbook.name}'")

                        if st.button("🗑️ Delete Cookbook", key=f"delete_cookbook_{cookbook.id}", width='stretch'):
                            confirm_delete_cookbook_dialog(cookbook.id, mealie_enabled, mealie_url, mealie_token)

                    st.divider()

# TAB 3: Recipes (sortable table + detail panel)
with tab3:
    st.subheader("📖 Recipe Database")

    cookbooks = st.session_state.db.list_cookbooks()
    cookbook_names = {cb.id: cb.name for cb in cookbooks}

    # Filters
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        cookbook_filter = st.selectbox(
            "Filter by Cookbook",
            ["All"] + [cb.name for cb in cookbooks],
            key="browse_filter",
        )
    with col2:
        sync_filter = st.selectbox(
            "Sync status", ["All", "Synced", "Not synced"], key="browse_sync_filter"
        )
    with col3:
        limit = st.number_input("Max recipes", min_value=10, max_value=500, value=100, step=10)

    # Fetch + apply filters
    if cookbook_filter == "All":
        recipes = st.session_state.db.list_recipes(limit=limit)
    else:
        cb = st.session_state.db.get_cookbook_by_name(cookbook_filter)
        recipes = st.session_state.db.list_recipes(cookbook_id=cb.id, limit=limit) if cb else []

    if sync_filter == "Synced":
        recipes = [r for r in recipes if r.mealie_id]
    elif sync_filter == "Not synced":
        recipes = [r for r in recipes if not r.mealie_id]

    if not recipes:
        st.info("No recipes found. Upload some photos to get started!")
    else:
        # Build the table (row order matches `recipes` so selection maps back by position)
        table = pd.DataFrame([
            {
                "Title": r.title,
                "Cookbook": cookbook_names.get(r.cookbook_id, "—"),
                "Tags": ", ".join(r.tags) if r.tags else "",
                "Ingr.": len(r.ingredients),
                "Steps": len(r.instructions),
                "Time": r.total_time or r.cook_time or "",
                "Servings": r.servings or "",
                "Synced": bool(r.mealie_id),
            }
            for r in recipes
        ])

        st.caption(f"{len(recipes)} recipe(s) · click a column header to sort, a row to open")

        event = st.dataframe(
            table,
            hide_index=True,
            width='stretch',
            on_select="rerun",
            selection_mode="single-row",
            key="recipes_table",
            column_config={
                "Title": st.column_config.TextColumn("Title", width="large"),
                "Tags": st.column_config.TextColumn("Tags", width="medium"),
                "Ingr.": st.column_config.NumberColumn("Ingr.", help="Number of ingredients"),
                "Steps": st.column_config.NumberColumn("Steps", help="Number of steps"),
                "Synced": st.column_config.CheckboxColumn("Synced", disabled=True),
            },
        )

        # Detail panel for the selected row
        selected = event.selection.rows
        if selected:
            st.divider()
            with st.container(border=True):
                render_recipe_detail(recipes[selected[0]], mealie_enabled, mealie_url, mealie_token)
        else:
            st.caption("⬑ Select a recipe row to view ingredients, instructions and actions.")

    # Handle delete confirmation dialog
    if st.session_state.confirm_delete_recipe_id is not None:
        confirm_delete_dialog(
            st.session_state.confirm_delete_recipe_id,
            mealie_enabled,
            mealie_url,
            mealie_token
        )

# TAB 4: Search
with tab4:
    st.subheader("🔍 Search Recipes")
    
    search_query = st.text_input(
        "Search by title, ingredients, or tags",
        placeholder="e.g., chicken, hummus, vegetarian"
    )
    
    if search_query:
        recipes = st.session_state.db.search_recipes(search_query)
        
        st.markdown(f"Found **{len(recipes)}** recipe(s)")
        
        for recipe in recipes:
            with st.container():
                st.markdown(f"### {recipe.title}")
                st.caption(f"Ingredients: {len(recipe.ingredients)} | Steps: {len(recipe.instructions)}")
                
                with st.expander("View Recipe"):
                    st.markdown("**Ingredients:**")
                    for ing in recipe.ingredients:
                        st.markdown(f"- {ing}")
                    
                    st.markdown("**Instructions:**")
                    for i, inst in enumerate(recipe.instructions, 1):
                        st.markdown(f"{i}. {inst}")
                
                st.divider()
    else:
        st.info("Enter a search term to find recipes")

# TAB 5: Statistics
with tab5:
    st.subheader("📊 Database Statistics")
    
    stats = st.session_state.db.get_processing_stats()
    
    # Overall metrics
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Recipes", stats['total_recipes'])
    
    with col2:
        if stats['mealie_sync']:
            st.metric("Synced to Mealie", stats['mealie_sync']['synced'])
    
    with col3:
        if stats['mealie_sync']:
            unsynced = stats['mealie_sync']['total'] - stats['mealie_sync']['synced']
            st.metric("Unsynced", unsynced)
    
    with col4:
        if stats['processing_status']:
            total_processed = sum(stats['processing_status'].values())
            st.metric("Total Processed", total_processed)
    
    st.divider()
    
    # Processing status
    if stats['processing_status']:
        st.markdown("### Processing Status")
        for status, count in stats['processing_status'].items():
            st.markdown(f"**{status.capitalize()}:** {count}")
    
    st.divider()
    
    # By cookbook
    if stats['by_cookbook']:
        st.markdown("### Recipes by Cookbook")
        for cookbook, count in stats['by_cookbook'].items():
            st.markdown(f"**{cookbook}:** {count} recipes")

# Footer
st.divider()
st.caption("Recipe Digitizer v1.0 | Powered by Apple Vision OCR + OpenAI")
