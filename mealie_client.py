"""
Mealie API Client
Handles communication with Mealie recipe manager
"""

import requests
import json
from typing import Dict, List, Optional
from pathlib import Path
import base64


class MealieClient:
    """Client for Mealie API integration"""
    
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
    
    def format_recipe_for_mealie(self, recipe_data: Dict) -> Dict:
        """
        Convert our recipe format to Mealie's format
        
        Args:
            recipe_data: Recipe dict from our database
        
        Returns:
            Mealie-formatted recipe dict
        """
        # Convert ingredients to Mealie format
        ingredients = recipe_data.get('ingredients', [])
        if isinstance(ingredients, str):
            ingredients = json.loads(ingredients)
        
        # Convert instructions to Mealie format
        instructions = recipe_data.get('instructions', [])
        if isinstance(instructions, str):
            instructions = json.loads(instructions)
        
        instructions_formatted = [
            {"text": instruction} for instruction in instructions
        ]
        
        # Convert tags
        tags = recipe_data.get('tags', [])
        if isinstance(tags, str):
            tags = json.loads(tags)
        
        # Convert times to ISO 8601
        prep_time = self.convert_time_to_iso(recipe_data.get('prep_time', ''))
        cook_time = self.convert_time_to_iso(recipe_data.get('cook_time', ''))
        total_time = self.convert_time_to_iso(recipe_data.get('total_time', ''))
        
        # Build description
        description = []
        if recipe_data.get('background_info'):
            description.append(recipe_data['background_info'])
        if recipe_data.get('handwritten_notes'):
            description.append(f"\n**Notes:** {recipe_data['handwritten_notes']}")
        
        description_text = "\n\n".join(description) if description else ""
        
        mealie_recipe = {
            "name": recipe_data.get('title', 'Untitled Recipe'),
            "description": description_text,
            "recipeIngredient": ingredients,
            "recipeInstructions": instructions_formatted,
            "recipeYield": recipe_data.get('servings', ''),
            "tags": tags,
        }
        
        # Add times if available
        if prep_time:
            mealie_recipe['prepTime'] = prep_time
        if cook_time:
            mealie_recipe['cookTime'] = cook_time
        if total_time:
            mealie_recipe['totalTime'] = total_time
        
        # Add optional fields
        if recipe_data.get('cuisine'):
            mealie_recipe['recipeCategory'] = [recipe_data['cuisine']]
        
        return mealie_recipe
    
    def create_recipe(self, recipe_data: Dict) -> Optional[str]:
        """
        Create a new recipe in Mealie
        
        Args:
            recipe_data: Recipe dict from our database
        
        Returns:
            Mealie recipe ID (slug) if successful, None otherwise
        """
        try:
            mealie_recipe = self.format_recipe_for_mealie(recipe_data)
            
            response = requests.post(
                f'{self.base_url}/api/recipes',
                headers=self.headers,
                json=mealie_recipe,
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                result = response.json()
                # Mealie returns the recipe with an 'id' or 'slug' field
                return result.get('slug') or result.get('id')
            else:
                print(f"Failed to create recipe: {response.status_code}")
                print(f"Response: {response.text}")
                return None
                
        except Exception as e:
            print(f"Error creating recipe: {e}")
            return None
    
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
        Update an existing recipe in Mealie
        
        Args:
            recipe_id: Mealie recipe ID (slug)
            recipe_data: Recipe dict from our database
        
        Returns:
            True if successful, False otherwise
        """
        try:
            mealie_recipe = self.format_recipe_for_mealie(recipe_data)
            
            response = requests.put(
                f'{self.base_url}/api/recipes/{recipe_id}',
                headers=self.headers,
                json=mealie_recipe,
                timeout=30
            )
            
            return response.status_code in [200, 201]
            
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
