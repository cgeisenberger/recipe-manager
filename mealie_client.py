"""
Mealie API Client
Handles communication with Mealie recipe manager
"""

import requests
import json
import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import base64


class MealieClient:
    """Client for Mealie API integration"""

    # Tag applied to every recipe this app pushes to Mealie
    APP_TAG = "recipe_digitizer"

    def __init__(self, base_url: str, api_token: str):
        """
        Initialize Mealie client
        
        Args:
            base_url: Mealie instance URL (e.g., http://localhost:9000)
            api_token: API token from Mealie settings
        """
        self.base_url = base_url.rstrip('/')
        self.api_token = api_token
        self.headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json'
        }
    
    def test_connection(self) -> bool:
        """Test connection to Mealie"""
        try:
            response = requests.get(
                f'{self.base_url}/api/app/about',
                headers=self.headers,
                timeout=5
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Connection test failed: {e}")
            return False
    
    def convert_time_to_iso(self, time_str: str) -> Optional[str]:
        """
        Convert human-readable time to ISO 8601 duration
        Examples: "15 minutes" -> "PT15M", "1 hour" -> "PT1H"
        """
        if not time_str:
            return None
        
        time_str = time_str.lower().strip()
        
        # Parse time
        hours = 0
        minutes = 0
        
        if 'hour' in time_str:
            try:
                hours = int(time_str.split('hour')[0].strip().split()[-1])
            except:
                pass
        
        if 'minute' in time_str or 'min' in time_str:
            try:
                # Extract number before 'minute' or 'min'
                for word in time_str.split():
                    if word.isdigit():
                        minutes = int(word)
                        break
            except:
                pass
        
        if hours == 0 and minutes == 0:
            return None
        
        # Build ISO duration
        duration = "PT"
        if hours > 0:
            duration += f"{hours}H"
        if minutes > 0:
            duration += f"{minutes}M"
        
        return duration
    
    @staticmethod
    def _slugify(text: str) -> str:
        """Convert a name to a Mealie-style slug."""
        return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

    def _resolve_organizer(self, kind: str, name: str) -> Optional[Dict]:
        """
        Get-or-create a tag or category and return its full {id, name, slug}.

        Mealie rejects a recipe PUT if a referenced tag/category is sent without
        its real id (it tries to recreate it and hits a slug collision). So we
        resolve each one to a complete object first.

        Args:
            kind: 'tags' or 'categories'
            name: organizer name

        Returns:
            Full organizer dict, or None if it couldn't be resolved.
        """
        name = name.strip()
        if not name:
            return None
        slug = self._slugify(name)

        # Try existing first
        try:
            existing = requests.get(
                f'{self.base_url}/api/organizers/{kind}/slug/{slug}',
                headers=self.headers,
                timeout=10
            )
            if existing.status_code == 200:
                return existing.json()
        except Exception as e:
            print(f"  Lookup of {kind} '{name}' failed: {e}")

        # Create it
        try:
            created = requests.post(
                f'{self.base_url}/api/organizers/{kind}',
                headers=self.headers,
                json={"name": name},
                timeout=10
            )
            if created.status_code in (200, 201):
                return created.json()
            print(f"  Could not create {kind} '{name}': {created.status_code} {created.text[:150]}")
        except Exception as e:
            print(f"  Creating {kind} '{name}' failed: {e}")

        return None

    def apply_recipe_fields(self, base: Dict, recipe_data: Dict) -> Dict:
        """
        Merge our recipe content into a full Mealie recipe object (from GET).

        Mealie's update endpoint requires the complete object round-tripped back
        with our fields overwritten. Mealie serializes/accepts camelCase. Tags and
        categories must be objects carrying a slug; Mealie auto-creates missing ones.

        Args:
            base: Full recipe object fetched from Mealie (GET /api/recipes/{slug})
            recipe_data: Our recipe dict from the database

        Returns:
            The mutated `base` dict, ready to PUT back.
        """
        ingredients = recipe_data.get('ingredients', [])
        if isinstance(ingredients, str):
            ingredients = json.loads(ingredients)

        instructions = recipe_data.get('instructions', [])
        if isinstance(instructions, str):
            instructions = json.loads(instructions)

        tags = recipe_data.get('tags', [])
        if isinstance(tags, str):
            tags = json.loads(tags)

        description_parts = []
        if recipe_data.get('background_info'):
            description_parts.append(recipe_data['background_info'])
        if recipe_data.get('handwritten_notes'):
            description_parts.append(f"**Notes:** {recipe_data['handwritten_notes']}")

        base['description'] = "\n\n".join(description_parts)
        base['recipeIngredient'] = [
            {"note": ing, "originalText": ing, "display": ing}
            for ing in ingredients
        ]
        base['recipeInstructions'] = [{"text": step} for step in instructions]
        base['recipeYield'] = recipe_data.get('servings', '') or ''
        # Always tag app-synced recipes, plus the recipe's own tags (deduped)
        tag_names = list(tags)
        if not any(t.strip().lower() == self.APP_TAG for t in tag_names):
            tag_names.append(self.APP_TAG)
        # Resolve tags to full objects (get-or-create) so Mealie accepts the PUT
        base['tags'] = [
            resolved for name in tag_names
            if (resolved := self._resolve_organizer('tags', name)) is not None
        ]

        prep = self.convert_time_to_iso(recipe_data.get('prep_time', ''))
        cook = self.convert_time_to_iso(recipe_data.get('cook_time', ''))
        total = self.convert_time_to_iso(recipe_data.get('total_time', ''))
        if prep:
            base['prepTime'] = prep
        if cook:
            base['cookTime'] = cook
        if total:
            base['totalTime'] = total

        if recipe_data.get('cuisine'):
            category = self._resolve_organizer('categories', recipe_data['cuisine'])
            if category is not None:
                base['recipeCategory'] = [category]

        return base
    
    def create_recipe(self, recipe_data: Dict) -> Optional[str]:
        """
        Create a new recipe in Mealie.

        Mealie v1.x only accepts a name on POST and returns the slug. The full
        content must then be round-tripped: GET the created object, overwrite
        our fields, and PUT it back (Mealie's PUT rejects partial bodies).

        Returns the slug on success, None otherwise.
        """
        try:
            title = recipe_data.get('title', 'Untitled Recipe')

            # Step 1: create with name only → slug
            response = requests.post(
                f'{self.base_url}/api/recipes',
                headers=self.headers,
                json={"name": title},
                timeout=30
            )
            if response.status_code not in [200, 201]:
                print(f"Failed to create recipe '{title}': {response.status_code} {response.text}")
                return None

            result = response.json()
            slug = result if isinstance(result, str) else (result.get('slug') or result.get('id'))
            if not slug:
                print(f"Mealie returned no slug for '{title}'")
                return None
            print(f"  Created shell recipe: {slug}")

            # Step 2: populate content via round-trip
            if self._populate_recipe(slug, recipe_data):
                return slug

            # Content update failed — remove the empty shell so we don't leave junk
            print(f"  Content update failed; removing empty shell {slug}")
            self.delete_recipe(slug)
            return None

        except Exception as e:
            print(f"Error creating recipe: {e}")
            return None

    def _populate_recipe(self, slug: str, recipe_data: Dict) -> bool:
        """GET the recipe, merge our fields in, and PUT it back."""
        full = self.get_recipe(slug)
        if full is None:
            print(f"  Could not fetch recipe {slug} for update")
            return False

        payload = self.apply_recipe_fields(full, recipe_data)
        put = requests.put(
            f'{self.base_url}/api/recipes/{slug}',
            headers=self.headers,
            json=payload,
            timeout=30
        )
        if put.status_code in (200, 201):
            return True

        print(f"  PUT failed for {slug}: {put.status_code} {put.text[:300]}")
        return False
    
    def upload_recipe_image(self, recipe_id: str, image_path: str) -> bool:
        """
        Upload image for a recipe
        
        Args:
            recipe_id: Mealie recipe ID (slug)
            image_path: Path to image file
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if not Path(image_path).exists():
                print(f"Image not found: {image_path}")
                return False
            
            # Mealie expects multipart form data
            with open(image_path, 'rb') as f:
                files = {
                    'image': (Path(image_path).name, f, 'image/jpeg')
                }
                
                # Remove Content-Type from headers for multipart
                upload_headers = {
                    'Authorization': f'Bearer {self.api_token}'
                }
                
                response = requests.post(
                    f'{self.base_url}/api/recipes/{recipe_id}/image',
                    headers=upload_headers,
                    files=files,
                    timeout=30
                )
                
                if response.status_code in [200, 201]:
                    return True
                else:
                    print(f"Failed to upload image: {response.status_code}")
                    print(f"Response: {response.text}")
                    return False
                    
        except Exception as e:
            print(f"Error uploading image: {e}")
            return False
    
    def get_recipe(self, recipe_id: str) -> Optional[Dict]:
        """
        Get a recipe from Mealie
        
        Args:
            recipe_id: Mealie recipe ID (slug)
        
        Returns:
            Recipe dict if found, None otherwise
        """
        try:
            response = requests.get(
                f'{self.base_url}/api/recipes/{recipe_id}',
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json()
            return None
            
        except Exception as e:
            print(f"Error getting recipe: {e}")
            return None
    
    def update_recipe(self, recipe_id: str, recipe_data: Dict) -> bool:
        """
        Update an existing recipe in Mealie via GET → merge → PUT round-trip.

        Args:
            recipe_id: Mealie recipe ID (slug)
            recipe_data: Recipe dict from our database

        Returns:
            True if successful, False otherwise
        """
        try:
            return self._populate_recipe(recipe_id, recipe_data)

        except Exception as e:
            print(f"Error updating recipe: {e}")
            return False
    
    def delete_recipe(self, recipe_id: str) -> bool:
        """
        Delete a recipe from Mealie
        
        Args:
            recipe_id: Mealie recipe ID (slug)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.delete(
                f'{self.base_url}/api/recipes/{recipe_id}',
                headers=self.headers,
                timeout=10
            )
            
            return response.status_code in [200, 204]

        except Exception as e:
            print(f"Error deleting recipe: {e}")
            return False

    def list_app_synced_slugs(self) -> List[str]:
        """
        Return the slugs of all recipes tagged with APP_TAG (i.e. pushed by this app).

        Mealie's tag-by-slug endpoint embeds the full list of recipes carrying the
        tag. Returns an empty list if the tag doesn't exist yet.
        """
        tag_slug = self._slugify(self.APP_TAG)
        try:
            resp = requests.get(
                f'{self.base_url}/api/organizers/tags/slug/{tag_slug}',
                headers=self.headers,
                timeout=10
            )
            if resp.status_code != 200:
                return []
            recipes = resp.json().get('recipes', [])
            return [r['slug'] for r in recipes if r.get('slug')]
        except Exception as e:
            print(f"Error listing app-synced recipes: {e}")
            return []

    def delete_app_synced_recipes(self) -> Tuple[List[str], List[str]]:
        """
        Delete every recipe tagged with APP_TAG from Mealie.

        Re-fetches the tagged list after each pass so any server-side paging is
        handled; stops when only previously-failed slugs remain. Recipes added to
        Mealie by other means (without the tag) are left untouched.

        Returns:
            (deleted_slugs, failed_slugs)
        """
        deleted: List[str] = []
        failed: List[str] = []

        while True:
            pending = [s for s in self.list_app_synced_slugs() if s not in failed]
            if not pending:
                break
            for slug in pending:
                if self.delete_recipe(slug):
                    deleted.append(slug)
                else:
                    failed.append(slug)

        return deleted, failed

    def search_recipes(self, query: str) -> List[Dict]:
        """
        Search for recipes in Mealie
        
        Args:
            query: Search query string
        
        Returns:
            List of matching recipes
        """
        try:
            response = requests.get(
                f'{self.base_url}/api/recipes',
                headers=self.headers,
                params={'search': query},
                timeout=10
            )
            
            if response.status_code == 200:
                return response.json().get('items', [])
            return []
            
        except Exception as e:
            print(f"Error searching recipes: {e}")
            return []
    
    def sync_recipe(self, recipe_data: Dict, image_path: Optional[str] = None) -> Optional[str]:
        """
        Complete sync operation: create recipe and upload image
        
        Args:
            recipe_data: Recipe dict from our database
            image_path: Optional path to recipe image
        
        Returns:
            Mealie recipe ID if successful, None otherwise
        """
        # Create recipe
        recipe_id = self.create_recipe(recipe_data)
        
        if not recipe_id:
            return None
        
        print(f"✓ Created recipe in Mealie: {recipe_id}")
        
        # Upload image if provided
        if image_path:
            success = self.upload_recipe_image(recipe_id, image_path)
            if success:
                print(f"✓ Uploaded image for: {recipe_id}")
            else:
                print(f"⚠ Failed to upload image for: {recipe_id}")
        
        return recipe_id


def load_mealie_config(config_path: str = "config/mealie_config.json") -> Optional[Dict]:
    """Load Mealie configuration from file"""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading Mealie config: {e}")
        return None


def create_mealie_client_from_config(config_path: str = "config/mealie_config.json") -> Optional[MealieClient]:
    """Create MealieClient from config file"""
    config = load_mealie_config(config_path)
    
    if not config:
        return None
    
    return MealieClient(
        base_url=config.get('base_url', 'http://localhost:9000'),
        api_token=config.get('api_token', '')
    )
