"""
Integrated Recipe Processor
Combines OCR, AI parsing, database storage, and Mealie sync
"""

import os
import json
import base64
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from openai import OpenAI
from dataclasses import asdict

from database import DatabaseManager, Recipe, Cookbook
from mealie_client import MealieClient
from ocr_backends import OCRBackend, auto_detect_backend, iso_to_tesseract_lang


class IntegratedRecipeProcessor:
    """
    Complete recipe processing pipeline with:
    - Duplicate detection via image hashing
    - Apple OCR + OpenAI parsing
    - Database storage
    - Mealie synchronization
    - Markdown export
    """
    
    def __init__(
        self,
        db_path: str = "data/recipes.db",
        swift_script_path: str = "./apple_ocr.swift",
        openai_api_key: Optional[str] = None,
        mealie_base_url: Optional[str] = None,
        mealie_api_token: Optional[str] = None,
        ocr_backend: Optional[OCRBackend] = None,
        ocr_lang: str = "eng",
    ):
        self.db = DatabaseManager(db_path)
        self.openai_client = OpenAI(api_key=openai_api_key or os.environ.get('OPENAI_API_KEY'))

        if ocr_backend is not None:
            self.ocr_backend = ocr_backend
        else:
            self.ocr_backend = auto_detect_backend(
                swift_script_path=swift_script_path,
                tesseract_lang=ocr_lang,
            )

        # Mealie client (optional)
        self.mealie_client = None
        if mealie_base_url and mealie_api_token:
            self.mealie_client = MealieClient(mealie_base_url, mealie_api_token)
    
    def process_image(
        self,
        image_path: str,
        cookbook_name: str,
        config: Optional[Dict] = None,
        skip_duplicates: bool = True,
        sync_to_mealie: bool = False
    ) -> Tuple[bool, Optional[int], str]:
        """
        Complete processing pipeline for a single image
        
        Args:
            image_path: Path to recipe image
            cookbook_name: Name of the cookbook
            config: Optional cookbook configuration
            skip_duplicates: Skip if image already processed
            sync_to_mealie: Sync to Mealie after processing
        
        Returns:
            (success, recipe_id, message)
        """
        image_path = str(Path(image_path).resolve())
        
        print(f"\n📸 Processing: {Path(image_path).name}")
        
        # Step 1: Calculate image hash
        try:
            image_hash = self.db.calculate_image_hash(image_path)
        except Exception as e:
            error_msg = f"Failed to read image: {e}"
            print(f"❌ {error_msg}")
            self.db.log_processing(image_path, "", "failed", error_msg)
            return False, None, error_msg
        
        # Step 2: Check for duplicates
        is_duplicate, existing_recipe_id = self.db.is_duplicate(image_hash)
        
        if is_duplicate and skip_duplicates:
            msg = f"⏭️  Skipped (duplicate - recipe #{existing_recipe_id})"
            print(msg)
            self.db.log_processing(image_path, image_hash, "duplicate", None)
            return False, existing_recipe_id, msg
        
        # Step 3: Get or create cookbook
        cookbook = self.db.get_cookbook_by_name(cookbook_name)
        if not cookbook:
            print(f"📚 Creating new cookbook: {cookbook_name}")
            cookbook_id = self.db.add_cookbook(Cookbook(
                name=cookbook_name,
                config_path=str(config.get('config_path', '')) if config else ''
            ))
        else:
            cookbook_id = cookbook.id
        
        # Step 4: Run OCR
        print(f"🔍 Running OCR ({self.ocr_backend.name})...")
        try:
            ocr_result = self.ocr_backend.extract(image_path)
            ocr_text = ocr_result['text']
            ocr_confidence = ocr_result['confidence']
            print(f"✓ Extracted {len(ocr_text)} characters (confidence: {ocr_confidence:.2%})")
        except Exception as e:
            error_msg = f"OCR failed: {e}"
            print(f"❌ {error_msg}")
            self.db.log_processing(image_path, image_hash, "failed", error_msg)
            return False, None, error_msg
        
        # Step 5: Parse with OpenAI
        print("🤖 Parsing with OpenAI...")
        try:
            recipe_data = self._parse_with_openai(image_path, ocr_text, config)
            print(f"✓ Extracted recipe: {recipe_data['title']}")
        except Exception as e:
            error_msg = f"OpenAI parsing failed: {e}"
            print(f"❌ {error_msg}")
            self.db.log_processing(image_path, image_hash, "failed", error_msg)
            return False, None, error_msg
        
        # Step 6: Create Recipe object
        recipe = Recipe(
            cookbook_id=cookbook_id,
            title=recipe_data['title'],
            page_number=recipe_data.get('page_number'),
            image_hash=image_hash,
            image_path=image_path,
            ingredients=recipe_data['ingredients'],
            instructions=recipe_data['instructions'],
            background_info=recipe_data.get('background_info', ''),
            handwritten_notes=recipe_data.get('handwritten_notes', ''),
            prep_time=recipe_data.get('prep_time', ''),
            cook_time=recipe_data.get('cook_time', ''),
            total_time=recipe_data.get('total_time', ''),
            servings=recipe_data.get('servings', ''),
            tags=recipe_data.get('tags', []),
            ocr_confidence=ocr_confidence
        )
        
        # Step 7: Save to database
        try:
            recipe_id = self.db.add_recipe(recipe)
            recipe.id = recipe_id
            print(f"💾 Saved to database (ID: {recipe_id})")
        except Exception as e:
            error_msg = f"Database save failed: {e}"
            print(f"❌ {error_msg}")
            self.db.log_processing(image_path, image_hash, "failed", error_msg)
            return False, None, error_msg
        
        # Step 8: Export to markdown
        try:
            markdown_path = self._export_markdown(recipe, cookbook_name, config)
            recipe.markdown_path = markdown_path
            self.db.update_recipe(recipe)
            print(f"📝 Exported markdown: {markdown_path}")
        except Exception as e:
            print(f"⚠️  Markdown export failed: {e}")
        
        # Step 9: Sync to Mealie (if enabled)
        if sync_to_mealie and self.mealie_client:
            try:
                print("☁️  Syncing to Mealie...")
                mealie_id = self._sync_to_mealie(recipe, image_path)
                if mealie_id:
                    self.db.update_mealie_sync(recipe_id, mealie_id)
                    print(f"✓ Synced to Mealie: {mealie_id}")
            except Exception as e:
                print(f"⚠️  Mealie sync failed: {e}")
        
        # Log success
        self.db.log_processing(image_path, image_hash, "success", None)
        
        return True, recipe_id, "Success"
    
    def _parse_with_openai(
        self,
        image_path: str,
        ocr_text: str,
        config: Optional[Dict] = None
    ) -> Dict:
        """Parse recipe using OpenAI"""
        base64_image = self._encode_image(image_path)
        
        system_message = self._build_system_message(config)
        
        user_message = f"""I have a recipe page from a cookbook. I've already extracted the text using OCR:

<ocr_text>
{ocr_text}
</ocr_text>

Please analyze both the image and the OCR text to extract a complete, structured recipe.

CRITICAL INSTRUCTIONS:
- Use the OCR text as your primary source - it's more accurate than reading the image directly
- The image is provided for context (layout, handwritten notes, visual elements)
- Separate background stories/context from cooking instructions
- Include handwritten notes if visible in the image
- Extract ALL ingredients with their quantities
- PRESERVE PARAGRAPH STRUCTURE: Each instruction item should be a PARAGRAPH, not a sentence. If the original has multiple sentences grouped together in a paragraph, keep them together as one instruction step. Number by paragraphs, not sentences.
- Be precise with measurements and timing

Return a JSON object with these exact fields:
{{
    "title": "Recipe name",
    "page_number": null or number,
    "ingredients": ["ingredient 1", "ingredient 2", ...],
    "instructions": ["Paragraph 1 (may contain multiple sentences)", "Paragraph 2", ...],
    "handwritten_notes": "Any handwritten annotations visible",
    "background_info": "Any introductory text, stories, or context (NOT cooking steps)",
    "prep_time": "e.g. 15 minutes",
    "cook_time": "e.g. 30 minutes", 
    "total_time": "e.g. 45 minutes",
    "servings": "e.g. 4 servings",
    "tags": ["tag1", "tag2", ...]
}}"""

        response = self.openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_message},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_message},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=2000,
            temperature=0.1
        )
        
        content = response.choices[0].message.content
        
        # Extract JSON
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        else:
            json_str = content.strip()
        
        return json.loads(json_str)
    
    def _build_system_message(self, config: Optional[Dict]) -> str:
        """Build system message with config hints"""
        base_message = """You are an expert recipe extraction assistant. Your job is to parse recipe pages and extract structured data.

You excel at:
- Distinguishing between recipe instructions and background stories
- Preserving exact measurements and timing
- Identifying handwritten notes and annotations
- Handling multi-column layouts
- Extracting complete ingredient lists"""

        if config:
            hints = []

            # Support both old flat format and new nested format
            # Cookbook name
            cookbook_name = None
            if 'cookbook' in config and 'name' in config['cookbook']:
                cookbook_name = config['cookbook']['name']
            elif 'book_name' in config:
                cookbook_name = config['book_name']

            if cookbook_name:
                hints.append(f"Cookbook: {cookbook_name}")

            # Authors
            authors = None
            if 'cookbook' in config and 'authors' in config['cookbook']:
                authors = config['cookbook']['authors']
            elif 'authors' in config:
                authors = config['authors']

            if authors:
                if isinstance(authors, list):
                    hints.append(f"Authors: {', '.join(authors)}")
                else:
                    hints.append(f"Authors: {authors}")

            # Layout - support both 'layout' (new) and 'layout_hints' (old)
            layout = config.get('layout', config.get('layout_hints', {}))
            if layout:
                hints.append("\nLayout information:")

                if layout.get('typical_page_structure'):
                    hints.append(f"- Page structure: {layout['typical_page_structure']}")

                if layout.get('typical_columns'):
                    hints.append(f"- Columns: {layout['typical_columns']}")

                if layout.get('has_background_stories'):
                    bg_loc = layout.get('background_location', 'top')
                    hints.append(f"- Background stories typically at: {bg_loc}")

                if layout.get('ingredients_side'):
                    hints.append(f"- Ingredients typically on: {layout['ingredients_side']}")

                if layout.get('instructions_side'):
                    hints.append(f"- Instructions typically on: {layout['instructions_side']}")

                if layout.get('has_handwritten_notes'):
                    note_locs = layout.get('note_locations', ['margins'])
                    hints.append(f"- Handwritten notes in: {', '.join(note_locs)}")

            # Extraction hints - support both formats
            extraction_hints = config.get('extraction_hints', {})

            # Description
            if extraction_hints.get('description'):
                hints.append(f"\nDescription: {extraction_hints['description']}")

            # Special instructions - new format
            if extraction_hints.get('special_instructions'):
                hints.append(f"\nSpecial instructions: {extraction_hints['special_instructions']}")
            # Old format fallback
            elif config.get('extraction_instructions'):
                hints.append(f"\nSpecial instructions: {config['extraction_instructions']}")

            # Common headings
            if extraction_hints.get('common_headings'):
                headings = extraction_hints['common_headings']
                hints.append("\nCommon headings in this cookbook:")
                if headings.get('ingredients'):
                    hints.append(f"- Ingredients: {', '.join(headings['ingredients'])}")
                if headings.get('instructions'):
                    hints.append(f"- Instructions: {', '.join(headings['instructions'])}")
                if headings.get('servings'):
                    hints.append(f"- Servings: {', '.join(headings['servings'])}")

            # Language-specific
            if extraction_hints.get('language_specific'):
                lang_spec = extraction_hints['language_specific']
                if lang_spec.get('do_not_translate'):
                    hints.append(f"\nIMPORTANT: Preserve original {lang_spec.get('output_language', 'language')} text exactly - do not translate!")

            if hints:
                base_message += "\n\n" + "\n".join(hints)

        return base_message
    
    def _encode_image(self, image_path: str) -> str:
        """Encode image to base64"""
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')
    
    def _export_markdown(
        self,
        recipe: Recipe,
        cookbook_name: str,
        config: Optional[Dict] = None
    ) -> str:
        """Export recipe to markdown"""
        # Determine output directory
        if config and config.get('output_dir'):
            output_dir = Path(config['output_dir']) / cookbook_name / "extracted"
        else:
            # Use cookbook folder structure
            image_dir = Path(recipe.image_path).parent
            output_dir = image_dir.parent / "extracted"
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Sanitize filename
        safe_title = "".join(
            c for c in recipe.title if c.isalnum() or c in (' ', '-', '_')
        ).strip()
        safe_title = safe_title.replace(' ', '_')[:50]
        
        output_path = output_dir / f"{safe_title}.md"
        
        # Build markdown
        md = f"# {recipe.title}\n\n"
        
        if recipe.background_info:
            md += f"## About This Dish\n\n{recipe.background_info}\n\n"
        
        # Metadata
        metadata = []
        if recipe.prep_time:
            metadata.append(f"**Prep Time:** {recipe.prep_time}")
        if recipe.cook_time:
            metadata.append(f"**Cook Time:** {recipe.cook_time}")
        if recipe.total_time:
            metadata.append(f"**Total Time:** {recipe.total_time}")
        if recipe.servings:
            metadata.append(f"**Servings:** {recipe.servings}")
        
        if metadata:
            md += " | ".join(metadata) + "\n\n"
        
        # Ingredients
        md += "## Ingredients\n\n"
        for ingredient in recipe.ingredients:
            md += f"- {ingredient}\n"
        md += "\n"
        
        # Instructions
        md += "## Instructions\n\n"
        for i, instruction in enumerate(recipe.instructions, 1):
            md += f"{i}. {instruction}\n"
        md += "\n"
        
        # Handwritten notes
        if recipe.handwritten_notes:
            md += f"## Notes\n\n{recipe.handwritten_notes}\n\n"
        
        # Tags
        if recipe.tags:
            md += f"**Tags:** {', '.join(recipe.tags)}\n\n"
        
        # Source
        md += f"**Source:** {cookbook_name}"
        if recipe.page_number:
            md += f", page {recipe.page_number}"
        md += "\n"
        
        # Write file
        with open(output_path, 'w') as f:
            f.write(md)
        
        return str(output_path)
    
    def _sync_to_mealie(self, recipe: Recipe, image_path: str) -> Optional[str]:
        """Sync recipe to Mealie"""
        if not self.mealie_client:
            return None
        
        # Convert recipe to dict
        recipe_data = asdict(recipe)
        
        # Sync to Mealie
        mealie_id = self.mealie_client.sync_recipe(recipe_data, image_path)
        
        return mealie_id
    
    def process_folder(
        self,
        folder_path: str,
        cookbook_name: Optional[str] = None,
        skip_duplicates: bool = True,
        sync_to_mealie: bool = False
    ) -> Dict:
        """
        Process all images in a folder
        
        Args:
            folder_path: Path to folder containing images
            cookbook_name: Name of cookbook (defaults to folder name)
            skip_duplicates: Skip already processed images
            sync_to_mealie: Sync to Mealie after processing
        
        Returns:
            Statistics dict
        """
        folder = Path(folder_path)
        
        if not folder.exists():
            raise FileNotFoundError(f"Folder not found: {folder_path}")
        
        # Default cookbook name
        if not cookbook_name:
            cookbook_name = folder.name
        
        # Look for config
        config = None
        config_path = folder / "config.json"
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = json.load(f)
            # Use cookbook name from config if available
            if 'cookbook' in config and 'name' in config['cookbook']:
                cookbook_name = config['cookbook']['name']
            elif 'book_name' in config:
                cookbook_name = config['book_name']
            print(f"📚 Using config for: {cookbook_name}")

            # Update Tesseract language to match cookbook config
            from ocr_backends import TesseractOCR
            if isinstance(self.ocr_backend, TesseractOCR):
                iso_lang = (
                    config.get('cookbook', {}).get('language')
                    or config.get('language', 'en')
                )
                self.ocr_backend.lang = iso_to_tesseract_lang(iso_lang)
        else:
            # No config found - offer to generate one
            print(f"⚠️  No config.json found in {folder}")
            print(f"   Processing will use generic extraction (lower accuracy)")
            print(f"\n💡 Tip: For better results, create a config file:")
            print(f"   - Run: python recipe_cli.py init-cookbook \"{cookbook_name}\" --interactive")
            print(f"   - Or use the Streamlit app's Cookbooks tab")
            print()

        # Find images
        image_extensions = {'.jpg', '.jpeg', '.png', '.heic'}
        images = [
            f for f in folder.iterdir()
            if f.suffix.lower() in image_extensions and f.is_file()
        ]
        
        if not images:
            print(f"No images found in {folder_path}")
            return {'total': 0, 'processed': 0, 'skipped': 0, 'failed': 0}
        
        print(f"\nFound {len(images)} images to process\n")
        print("=" * 60)
        
        # Process each image
        stats = {'total': len(images), 'processed': 0, 'skipped': 0, 'failed': 0}
        
        for i, image_path in enumerate(sorted(images), 1):
            print(f"\n[{i}/{len(images)}]")
            
            success, recipe_id, message = self.process_image(
                str(image_path),
                cookbook_name,
                config,
                skip_duplicates,
                sync_to_mealie
            )
            
            if success:
                stats['processed'] += 1
            elif 'duplicate' in message.lower():
                stats['skipped'] += 1
            else:
                stats['failed'] += 1
        
        # Print summary
        print("\n" + "=" * 60)
        print(f"\n✨ Processing Complete!")
        print(f"   Total: {stats['total']}")
        print(f"   ✓ Processed: {stats['processed']}")
        print(f"   ⏭️  Skipped (duplicates): {stats['skipped']}")
        print(f"   ❌ Failed: {stats['failed']}")
        
        return stats
