"""
Cookbook Configuration Management
Handles AI-powered config inference and cookbook setup
"""

import json
import base64
from pathlib import Path
from typing import Dict, Optional, Tuple
import openai


class CookbookConfigManager:
    """Manages cookbook configuration with AI-powered inference"""

    def __init__(self, openai_api_key: Optional[str] = None):
        """
        Initialize config manager

        Args:
            openai_api_key: OpenAI API key for AI inference
        """
        self.openai_api_key = openai_api_key
        if openai_api_key:
            openai.api_key = openai_api_key

    def set_openai_key(self, api_key: str) -> None:
        """Update the key used for AI inference (module-global openai.api_key)."""
        self.openai_api_key = api_key
        openai.api_key = api_key

    def analyze_cookbook_structure(self, image_path: str) -> Tuple[bool, Dict, str]:
        """
        Analyze a cookbook page to infer structure and generate config

        Args:
            image_path: Path to sample cookbook page image

        Returns:
            Tuple of (success, config_dict, message)
        """
        try:
            if not self.openai_api_key:
                return False, {}, "OpenAI API key not configured"

            # Encode image
            base64_image = self._encode_image(image_path)

            # Create analysis prompt
            prompt = self._create_analysis_prompt()

            # Call GPT-4o Vision
            response = openai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=2000,
                temperature=0.1  # Low temperature for consistent analysis
            )

            # Parse response
            result_text = response.choices[0].message.content

            # Extract JSON from response (handle markdown code blocks)
            config = self._extract_json_from_response(result_text)

            if not config:
                return False, {}, "Failed to parse AI response"

            return True, config, "Analysis successful"

        except Exception as e:
            return False, {}, f"Error during analysis: {str(e)}"

    def _create_analysis_prompt(self) -> str:
        """Create the analysis prompt for GPT-4o Vision"""
        return """Analyze this cookbook page and determine its structure for recipe extraction.

Your task is to identify:

1. **Language Detection**
   - What language is the text in? (en, de, fr, es, it, etc.)
   - Are there any language-specific quirks or formatting?

2. **Layout Structure**
   - How many columns does the page have? (1, 2, or 3)
   - Where is the recipe title positioned? (top, center, left-column, right-column)
   - Where are the ingredients located? (left-column, right-column, top-section, bottom-section)
   - Where are the cooking instructions? (left-column, right-column, top-section, bottom-section, below-ingredients)
   - Is there a specific visual structure or pattern?

3. **Special Features**
   - Are there background stories, quotes, or contextual information? Where are they located?
   - Are there any handwritten notes or annotations visible?
   - Are there icons or symbols for time, servings, difficulty?
   - Are there photos of the finished dish?
   - Any other special elements (tips, variations, nutritional info)?

4. **Common Headings**
   - What words are used for "Ingredients"? (e.g., "Zutaten", "Ingrédients", etc.)
   - What words are used for "Instructions"? (e.g., "Zubereitung", "Préparation", etc.)
   - What words indicate serving size? (e.g., "Für X Personen", "Serves", "Portions")
   - Any other section headings?

5. **Extraction Hints**
   - What special instructions would help accurately extract recipes from this cookbook?
   - Are columns swappable, or always in the same position?
   - Any common patterns or quirks to note?

Return your analysis as a JSON object in this exact format:

```json
{
  "cookbook": {
    "language": "en",
    "detected_publisher": "Publisher name if visible",
    "estimated_year": "Year if visible"
  },
  "layout": {
    "title_position": "top",
    "has_background_stories": false,
    "background_location": "middle-of-page",
    "ingredients_side": "left-column",
    "instructions_side": "right-column",
    "typical_columns": 2,
    "has_handwritten_notes": false,
    "note_locations": ["margins"],
    "typical_page_structure": "Brief description of overall layout"
  },
  "extraction_hints": {
    "description": "Brief description of this cookbook's style and what makes it unique",
    "special_instructions": "Detailed instructions for AI parser about how to handle this cookbook's specific layout and features",
    "common_headings": {
      "ingredients": ["Ingredients", "What you need"],
      "servings": ["Serves", "Portions"],
      "instructions": ["Method", "Directions"],
      "notes": ["Note", "Tip"]
    },
    "language_specific": {
      "output_language": "en",
      "preserve_original": true,
      "do_not_translate": false
    }
  },
  "default_tags": ["tag1", "tag2"],
  "analysis_confidence": "high"
}
```

Important:
- Return ONLY the JSON object, no additional text
- Use the exact field names shown above
- Be specific and detailed in your observations
- If you're unsure about something, make your best guess but note lower confidence
- For language_specific settings: set do_not_translate to true if the cookbook is in a non-English language and text should be preserved as-is
"""

    def _encode_image(self, image_path: str) -> str:
        """Encode image to base64"""
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')

    def _extract_json_from_response(self, response_text: str) -> Optional[Dict]:
        """
        Extract JSON from AI response, handling markdown code blocks

        Args:
            response_text: Raw text response from AI

        Returns:
            Parsed JSON dict or None if parsing fails
        """
        try:
            # Try parsing directly first
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        import re

        # Match ```json ... ``` or ``` ... ```
        patterns = [
            r'```json\s*\n(.*?)\n```',
            r'```\s*\n(.*?)\n```',
            r'\{.*\}',  # Just find any JSON object
        ]

        for pattern in patterns:
            match = re.search(pattern, response_text, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1) if '```' in pattern else match.group(0)
                    return json.loads(json_str)
                except (json.JSONDecodeError, IndexError):
                    continue

        return None

    def create_config_template(
        self,
        name: str,
        authors: str = "",
        language: str = "en",
        cuisine: str = ""
    ) -> Dict:
        """
        Create a basic config template without AI analysis

        Args:
            name: Cookbook name
            authors: Comma-separated author names
            language: Language code (en, de, fr, etc.)
            cuisine: Cuisine type

        Returns:
            Basic config dictionary
        """
        author_list = [a.strip() for a in authors.split(',')] if authors else []

        return {
            "cookbook": {
                "name": name,
                "authors": author_list,
                "language": language,
                "cuisine": cuisine
            },
            "layout": {
                "title_position": "top",
                "has_background_stories": False,
                "typical_columns": 1,
                "typical_page_structure": "Standard single-column layout"
            },
            "extraction_hints": {
                "description": f"Basic configuration for {name}",
                "special_instructions": "Standard recipe extraction. No special layout considerations.",
                "common_headings": self._get_default_headings(language),
                "language_specific": {
                    "output_language": language,
                    "preserve_original": True,
                    "do_not_translate": language != "en"
                }
            },
            "default_tags": []
        }

    def _get_default_headings(self, language: str) -> Dict:
        """Get default common headings for a language"""
        headings = {
            "en": {
                "ingredients": ["Ingredients", "What you need"],
                "servings": ["Serves", "Portions", "Yield"],
                "instructions": ["Instructions", "Method", "Directions"],
                "notes": ["Note", "Tip", "Chef's note"]
            },
            "de": {
                "ingredients": ["Zutaten", "Für"],
                "servings": ["Für X Personen", "Portionen"],
                "instructions": ["Zubereitung", "So wird's gemacht", "Anleitung"],
                "notes": ["Hinweis", "Tipp", "Variation"]
            },
            "fr": {
                "ingredients": ["Ingrédients", "Pour"],
                "servings": ["Portions", "Pour X personnes"],
                "instructions": ["Préparation", "Instructions", "Méthode"],
                "notes": ["Note", "Conseil", "Astuce"]
            },
            "es": {
                "ingredients": ["Ingredientes", "Para"],
                "servings": ["Porciones", "Para X personas"],
                "instructions": ["Preparación", "Instrucciones", "Modo de preparación"],
                "notes": ["Nota", "Consejo", "Sugerencia"]
            },
            "it": {
                "ingredients": ["Ingredienti", "Per"],
                "servings": ["Porzioni", "Per X persone"],
                "instructions": ["Preparazione", "Istruzioni", "Procedimento"],
                "notes": ["Nota", "Consiglio", "Suggerimento"]
            }
        }

        return headings.get(language, headings["en"])

    def merge_with_template(self, ai_config: Dict, user_info: Dict) -> Dict:
        """
        Merge AI-generated config with user-provided basic info

        Args:
            ai_config: Config from AI analysis
            user_info: User-provided info (name, authors, cuisine, etc.)

        Returns:
            Merged config dictionary
        """
        # Start with AI config
        merged = ai_config.copy()

        # Override cookbook section with user info
        if "cookbook" not in merged:
            merged["cookbook"] = {}

        merged["cookbook"].update({
            "name": user_info.get("name", ""),
            "authors": user_info.get("authors", []),
            "cuisine": user_info.get("cuisine", "")
        })

        # Use detected language if not specified by user
        if "language" in user_info:
            merged["cookbook"]["language"] = user_info["language"]

        return merged

    def save_config(self, config: Dict, cookbook_path: Path) -> Tuple[bool, str]:
        """
        Save config to cookbook folder

        Args:
            config: Configuration dictionary
            cookbook_path: Path to cookbook folder

        Returns:
            Tuple of (success, message)
        """
        try:
            config_file = cookbook_path / "config.json"

            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            return True, f"Config saved to {config_file}"

        except Exception as e:
            return False, f"Error saving config: {str(e)}"

    def load_config(self, cookbook_path: Path) -> Tuple[bool, Optional[Dict], str]:
        """
        Load config from cookbook folder

        Args:
            cookbook_path: Path to cookbook folder

        Returns:
            Tuple of (success, config_dict, message)
        """
        try:
            config_file = cookbook_path / "config.json"

            if not config_file.exists():
                return False, None, "Config file not found"

            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)

            return True, config, "Config loaded successfully"

        except Exception as e:
            return False, None, f"Error loading config: {str(e)}"

    def format_config_summary(self, config: Dict) -> str:
        """
        Format config as human-readable summary

        Args:
            config: Configuration dictionary

        Returns:
            Formatted summary string
        """
        lines = []

        # Cookbook info
        if "cookbook" in config:
            cb = config["cookbook"]
            lines.append("📚 Cookbook Information:")
            lines.append(f"  Language: {cb.get('language', 'Unknown')}")
            if cb.get('detected_publisher'):
                lines.append(f"  Publisher: {cb['detected_publisher']}")

        # Layout
        if "layout" in config:
            layout = config["layout"]
            lines.append("\n📐 Layout Structure:")
            lines.append(f"  Columns: {layout.get('typical_columns', 1)}")
            lines.append(f"  Title position: {layout.get('title_position', 'top')}")

            if layout.get('has_background_stories'):
                lines.append(f"  Background stories: Yes ({layout.get('background_location', 'unknown location')})")

            lines.append(f"  Ingredients: {layout.get('ingredients_side', 'not specified')}")
            lines.append(f"  Instructions: {layout.get('instructions_side', 'not specified')}")

            if layout.get('typical_page_structure'):
                lines.append(f"  Structure: {layout['typical_page_structure']}")

        # Special features
        if "layout" in config and config["layout"].get("has_handwritten_notes"):
            lines.append("\n✍️ Special Features:")
            lines.append("  Handwritten notes detected")
            if config["layout"].get("note_locations"):
                lines.append(f"  Note locations: {', '.join(config['layout']['note_locations'])}")

        # Extraction hints
        if "extraction_hints" in config:
            hints = config["extraction_hints"]
            if hints.get('description'):
                lines.append(f"\n💡 Description:")
                lines.append(f"  {hints['description']}")

        # Confidence
        if config.get('analysis_confidence'):
            lines.append(f"\n🎯 Confidence: {config['analysis_confidence']}")

        return "\n".join(lines)

    def create_folder_structure(self, cookbook_path: Path) -> Tuple[bool, str]:
        """
        Create cookbook folder structure

        Args:
            cookbook_path: Path to cookbook folder

        Returns:
            Tuple of (success, message)
        """
        try:
            cookbook_path.mkdir(parents=True, exist_ok=True)
            (cookbook_path / "images").mkdir(exist_ok=True)
            (cookbook_path / "extracted").mkdir(exist_ok=True)

            return True, f"Created folder structure at {cookbook_path}"

        except Exception as e:
            return False, f"Error creating folders: {str(e)}"
