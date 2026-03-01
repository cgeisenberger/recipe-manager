#!/usr/bin/env python3
"""
Fix Cookbook Names
Updates recipes with folder-based names to use proper cookbook names from config
"""

import click
from pathlib import Path
import json
from database import DatabaseManager

@click.command()
@click.option('--db', default='data/recipes.db', help='Database path')
@click.option('--cookbooks-dir', default='cookbooks', help='Path to cookbooks directory')
@click.option('--dry-run', is_flag=True, help='Show changes without applying')
def fix_cookbook_names(db, cookbooks_dir, dry_run):
    """Fix cookbook names from 'images' to proper names from config"""
    
    db_manager = DatabaseManager(db)
    cookbooks_path = Path(cookbooks_dir)
    
    print("🔍 Checking for cookbook name issues...\n")
    
    # Get all cookbooks
    cookbooks = db_manager.list_cookbooks()
    
    issues_found = 0
    
    for cookbook in cookbooks:
        # Check if it's a problematic folder name
        if cookbook.name in ['images', 'photos', 'scans']:
            print(f"⚠️  Found problematic cookbook: '{cookbook.name}' (ID: {cookbook.id})")
            
            # Try to find recipes from this cookbook to get image paths
            recipes = db_manager.list_recipes(cookbook_id=cookbook.id, limit=1)
            
            if recipes and recipes[0].image_path:
                # Get the parent cookbook folder from image path
                image_path = Path(recipes[0].image_path)
                
                # Traverse up to find config.json
                current = image_path.parent
                config_path = None
                
                for _ in range(3):  # Check up to 3 levels up
                    potential_config = current / "config.json"
                    if potential_config.exists():
                        config_path = potential_config
                        break
                    current = current.parent
                
                if config_path:
                    print(f"   Found config: {config_path}")
                    
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                    
                    # Get proper name from config
                    proper_name = None
                    if 'cookbook' in config and 'name' in config['cookbook']:
                        proper_name = config['cookbook']['name']
                    elif 'book_name' in config:
                        proper_name = config['book_name']
                    
                    if proper_name:
                        print(f"   → Should be: '{proper_name}'")
                        
                        if not dry_run:
                            # Update cookbook
                            conn = db_manager.get_connection()
                            cursor = conn.cursor()
                            
                            # Update name and config path
                            cursor.execute(
                                "UPDATE cookbooks SET name = ?, config_path = ? WHERE id = ?",
                                (proper_name, str(config_path), cookbook.id)
                            )
                            
                            conn.commit()
                            conn.close()
                            print(f"   ✓ Updated to '{proper_name}'\n")
                        else:
                            print(f"   [Dry run - would update to '{proper_name}']\n")
                        
                        issues_found += 1
                    else:
                        print(f"   ✗ Could not find proper name in config\n")
                else:
                    print(f"   ✗ Could not find config.json file\n")
            else:
                # Try searching cookbooks directory
                print(f"   Searching in {cookbooks_path}...")
                
                found_config = None
                for config_file in cookbooks_path.rglob("config.json"):
                    with open(config_file, 'r') as f:
                        config = json.load(f)
                    
                    # Check if this could be the right cookbook
                    if 'cookbook' in config:
                        print(f"   Found potential config: {config_file}")
                        print(f"   Name in config: {config['cookbook'].get('name', 'N/A')}")
                        
                        if click.confirm(f"   Use this config?"):
                            found_config = config_file
                            break
                
                if found_config:
                    with open(found_config, 'r') as f:
                        config = json.load(f)
                    
                    proper_name = None
                    if 'cookbook' in config and 'name' in config['cookbook']:
                        proper_name = config['cookbook']['name']
                    elif 'book_name' in config:
                        proper_name = config['book_name']
                    
                    if proper_name and not dry_run:
                        conn = db_manager.get_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "UPDATE cookbooks SET name = ?, config_path = ? WHERE id = ?",
                            (proper_name, str(found_config), cookbook.id)
                        )
                        conn.commit()
                        conn.close()
                        print(f"   ✓ Updated to '{proper_name}'\n")
                        issues_found += 1
                else:
                    print(f"   ✗ No suitable config found\n")
    
    if issues_found == 0:
        print("✓ No issues found! All cookbook names look good.\n")
    else:
        if dry_run:
            print(f"Found {issues_found} issue(s). Run without --dry-run to fix.\n")
        else:
            print(f"✓ Fixed {issues_found} cookbook name(s)!\n")
            print("Tip: Restart Streamlit app to see changes: streamlit run recipe_app.py")

if __name__ == '__main__':
    fix_cookbook_names()
