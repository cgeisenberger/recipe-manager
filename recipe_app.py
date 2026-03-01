"""
Recipe Digitizer - Streamlit Web Interface
Upload photos, process recipes, manage database
"""

import streamlit as st
import os
import tempfile
from pathlib import Path
import json
from datetime import datetime
from dataclasses import asdict
from typing import List

from recipe_processor_integrated import IntegratedRecipeProcessor
from database import DatabaseManager, Cookbook
from mealie_client import MealieClient

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

# Sidebar configuration
with st.sidebar:
    st.title("⚙️ Settings")
    
    # OpenAI API Key
    openai_key = st.text_input(
        "OpenAI API Key",
        value=os.environ.get('OPENAI_API_KEY', ''),
        type="password",
        help="Your OpenAI API key"
    )
    
    if openai_key:
        os.environ['OPENAI_API_KEY'] = openai_key
    
    # Mealie settings
    st.subheader("Mealie Integration")
    mealie_enabled = st.checkbox("Enable Mealie", value=False)
    
    if mealie_enabled:
        mealie_url = st.text_input(
            "Mealie URL",
            value=os.environ.get('MEALIE_URL', 'http://localhost:9000'),
            help="URL of your Mealie instance"
        )
        
        mealie_token = st.text_input(
            "Mealie API Token",
            value=os.environ.get('MEALIE_TOKEN', ''),
            type="password",
            help="API token from Mealie settings"
        )
        
        if st.button("Test Mealie Connection"):
            if mealie_url and mealie_token:
                client = MealieClient(mealie_url, mealie_token)
                if client.test_connection():
                    st.success("✓ Connected to Mealie!")
                else:
                    st.error("✗ Connection failed")
            else:
                st.warning("Please enter URL and token")
    else:
        mealie_url = None
        mealie_token = None
    
    # Initialize processor
    if openai_key and not st.session_state.processor:
        st.session_state.processor = IntegratedRecipeProcessor(
            db_path="data/recipes.db",
            swift_script_path="apple_ocr.swift",
            openai_api_key=openai_key,
            mealie_base_url=mealie_url if mealie_enabled else None,
            mealie_api_token=mealie_token if mealie_enabled else None
        )
    
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
tab1, tab2, tab3, tab4 = st.tabs(["📤 Upload", "📖 Browse", "🔍 Search", "📊 Statistics"])


# ==================== Dialog Functions ====================

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
            sync_to_mealie = st.checkbox(
                "Sync to Mealie",
                value=recipe.mealie_id is not None,
                help="Update or create recipe in Mealie"
            )

        st.divider()
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            save_button = st.form_submit_button("💾 Save Changes", type="primary", use_container_width=True)
        with col2:
            cancel_button = st.form_submit_button("❌ Cancel", use_container_width=True)
        with col3:
            delete_button = st.form_submit_button("🗑️ Delete Recipe", use_container_width=True)

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
                        mealie_id = st.session_state.processor._sync_to_mealie(recipe)
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
        if st.button("✓ Yes, Delete", type="primary", use_container_width=True):
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
        if st.button("❌ Cancel", use_container_width=True):
            st.session_state.confirm_delete_recipe_id = None
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
            st.info("No cookbooks found. Create one below!")
            selected_cookbook = None
        
        # Create new cookbook
        with st.expander("➕ Create New Cookbook"):
            new_name = st.text_input("Cookbook Name")
            new_authors = st.text_input("Authors (comma-separated)")
            new_language = st.selectbox("Language", ["en", "de", "fr", "es", "it"])
            new_cuisine = st.text_input("Cuisine Type")
            
            if st.button("Create Cookbook"):
                if new_name:
                    cookbook = Cookbook(
                        name=new_name,
                        authors=new_authors,
                        language=new_language,
                        cuisine=new_cuisine
                    )
                    cookbook_id = st.session_state.db.add_cookbook(cookbook)
                    st.success(f"✓ Created cookbook: {new_name}")
                    st.rerun()
                else:
                    st.error("Please enter a cookbook name")
        
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
                status_text = st.empty()
                
                for i, uploaded_file in enumerate(uploaded_files):
                    status_text.info(f"Processing {i+1}/{len(uploaded_files)}: {uploaded_file.name}")
                    
                    # Save to temp file
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
                        tmp_file.write(uploaded_file.read())
                        tmp_path = tmp_file.name
                    
                    try:
                        # Process
                        success, recipe_id, message = st.session_state.processor.process_image(
                            tmp_path,
                            selected_cookbook,
                            skip_duplicates=skip_duplicates,
                            sync_to_mealie=sync_to_mealie
                        )
                        
                        st.session_state.processing_results.append({
                            'filename': uploaded_file.name,
                            'success': success,
                            'recipe_id': recipe_id,
                            'message': message
                        })
                        
                    except Exception as e:
                        st.session_state.processing_results.append({
                            'filename': uploaded_file.name,
                            'success': False,
                            'recipe_id': None,
                            'message': str(e)
                        })
                    
                    finally:
                        # Clean up temp file
                        Path(tmp_path).unlink(missing_ok=True)
                    
                    progress_bar.progress((i + 1) / len(uploaded_files))
                
                status_text.success(f"✓ Processed {len(uploaded_files)} images!")
    
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
                                
                                if st.button(f"View Full Recipe", key=f"view_{result['recipe_id']}"):
                                    st.session_state.selected_recipe = result['recipe_id']
                
                elif 'duplicate' in result['message'].lower():
                    st.info(f"⏭️ {result['filename']} (already processed)")
                else:
                    st.error(f"✗ {result['filename']}: {result['message']}")
        else:
            st.info("Upload photos and click 'Process Recipes' to begin")

# TAB 2: Browse
with tab2:
    st.subheader("📖 Recipe Database")
    
    # Filter options
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        cookbooks = st.session_state.db.list_cookbooks()
        cookbook_filter = st.selectbox(
            "Filter by Cookbook",
            ["All"] + [cb.name for cb in cookbooks],
            key="browse_filter"
        )
    
    with col2:
        limit = st.number_input("Show recipes", min_value=10, max_value=100, value=20, step=10)
    
    with col3:
        if st.button("🔄 Refresh"):
            st.rerun()
    
    # Get recipes
    if cookbook_filter == "All":
        recipes = st.session_state.db.list_recipes(limit=limit)
    else:
        cb = st.session_state.db.get_cookbook_by_name(cookbook_filter)
        recipes = st.session_state.db.list_recipes(cookbook_id=cb.id, limit=limit) if cb else []
    
    # Display recipes
    if recipes:
        for recipe in recipes:
            with st.container():
                col1, col2, col3 = st.columns([3, 1, 1])
                
                with col1:
                    st.markdown(f"### {recipe.title}")
                    tags = ", ".join(recipe.tags) if recipe.tags else "No tags"
                    st.caption(f"Tags: {tags}")
                
                with col2:
                    st.metric("Ingredients", len(recipe.ingredients))
                
                with col3:
                    mealie_status = "✓ Synced" if recipe.mealie_id else "Not synced"
                    st.caption(mealie_status)
                
                # Expandable details
                with st.expander("View Details"):
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
                    col_action1, col_action2, col_action3, col_action4 = st.columns(4)

                    with col_action1:
                        if recipe.markdown_path and Path(recipe.markdown_path).exists():
                            with open(recipe.markdown_path, 'r') as f:
                                st.download_button(
                                    "📥 Download MD",
                                    f.read(),
                                    file_name=f"{recipe.title}.md",
                                    key=f"dl_{recipe.id}"
                                )

                    with col_action2:
                        if st.button("✏️ Edit", key=f"edit_{recipe.id}", use_container_width=True):
                            edit_recipe_dialog(recipe.id, mealie_enabled, mealie_url, mealie_token)

                    with col_action3:
                        if not recipe.mealie_id and mealie_enabled:
                            if st.button("☁️ Sync to Mealie", key=f"sync_{recipe.id}"):
                                # Sync logic here
                                st.info("Syncing...")

                    with col_action4:
                        if st.button("🗑️ Delete", key=f"delete_{recipe.id}", use_container_width=True):
                            st.session_state.confirm_delete_recipe_id = recipe.id
                            st.rerun()
                
                st.divider()
    else:
        st.info("No recipes found. Upload some photos to get started!")

    # Handle delete confirmation dialog
    if st.session_state.confirm_delete_recipe_id is not None:
        confirm_delete_dialog(
            st.session_state.confirm_delete_recipe_id,
            mealie_enabled,
            mealie_url,
            mealie_token
        )

# TAB 3: Search
with tab3:
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

# TAB 4: Statistics
with tab4:
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
