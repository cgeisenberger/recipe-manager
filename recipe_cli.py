#!/usr/bin/env python3
"""
Recipe Manager CLI
Command-line interface for recipe digitization system
"""

import click
import json
from pathlib import Path
from tabulate import tabulate

from recipe_processor_integrated import IntegratedRecipeProcessor
from database import DatabaseManager, Cookbook
from mealie_client import MealieClient
from cookbook_config import CookbookConfigManager


@click.group()
def cli():
    """Recipe Digitization CLI - Process cookbooks and manage recipes"""
    pass


@cli.command()
@click.argument('input_path', type=click.Path(exists=True))
@click.option('--cookbook', '-c', help='Cookbook name')
@click.option('--db', default='data/recipes.db', help='Database path')
@click.option('--no-skip-duplicates', is_flag=True, help='Process duplicates')
@click.option('--sync-mealie', is_flag=True, help='Sync to Mealie')
@click.option('--mealie-url', envvar='MEALIE_URL', help='Mealie base URL')
@click.option('--mealie-token', envvar='MEALIE_TOKEN', help='Mealie API token')
def process(input_path, cookbook, db, no_skip_duplicates, sync_mealie, mealie_url, mealie_token):
    """Process recipe image(s)"""
    
    # Initialize processor
    processor = IntegratedRecipeProcessor(
        db_path=db,
        mealie_base_url=mealie_url,
        mealie_api_token=mealie_token
    )
    
    input_path = Path(input_path)
    
    if input_path.is_file():
        # Single image
        if not cookbook:
            cookbook = input_path.parent.name
        
        # Load config if exists
        config_path = input_path.parent / "config.json"
        config = None
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
        
        success, recipe_id, message = processor.process_image(
            str(input_path),
            cookbook,
            config,
            skip_duplicates=not no_skip_duplicates,
            sync_to_mealie=sync_mealie
        )
        
        if success:
            click.echo(f"\n✅ Success! Recipe ID: {recipe_id}")
        else:
            click.echo(f"\n❌ {message}")
    
    elif input_path.is_dir():
        # Folder of images
        if not cookbook:
            cookbook = input_path.name
        
        stats = processor.process_folder(
            str(input_path),
            cookbook,
            skip_duplicates=not no_skip_duplicates,
            sync_to_mealie=sync_mealie
        )
        
        click.echo(f"\n📊 Final Statistics:")
        click.echo(f"   Total: {stats['total']}")
        click.echo(f"   Processed: {stats['processed']}")
        click.echo(f"   Skipped: {stats['skipped']}")
        click.echo(f"   Failed: {stats['failed']}")


@cli.command()
@click.option('--db', default='data/recipes.db', help='Database path')
def stats(db):
    """Show database statistics"""
    db_manager = DatabaseManager(db)
    stats = db_manager.get_processing_stats()
    
    click.echo("\n📊 Recipe Database Statistics\n")
    
    # Total recipes
    click.echo(f"Total Recipes: {stats['total_recipes']}")
    
    # Processing status
    if stats['processing_status']:
        click.echo(f"\nProcessing Status:")
        for status, count in stats['processing_status'].items():
            click.echo(f"  {status}: {count}")
    
    # Mealie sync
    if stats['mealie_sync']:
        click.echo(f"\nMealie Sync:")
        click.echo(f"  Total: {stats['mealie_sync']['total']}")
        click.echo(f"  Synced: {stats['mealie_sync']['synced']}")
        unsynced = stats['mealie_sync']['total'] - stats['mealie_sync']['synced']
        click.echo(f"  Unsynced: {unsynced}")
    
    # By cookbook
    if stats['by_cookbook']:
        click.echo(f"\nBy Cookbook:")
        for cookbook, count in stats['by_cookbook'].items():
            click.echo(f"  {cookbook}: {count}")


@cli.command()
@click.option('--cookbook', '-c', help='Filter by cookbook')
@click.option('--limit', '-l', type=int, default=20, help='Number of recipes to show')
@click.option('--db', default='data/recipes.db', help='Database path')
def list(cookbook, limit, db):
    """List recipes"""
    db_manager = DatabaseManager(db)
    
    # Get cookbook ID if name provided
    cookbook_id = None
    if cookbook:
        cb = db_manager.get_cookbook_by_name(cookbook)
        if cb:
            cookbook_id = cb.id
        else:
            click.echo(f"Cookbook not found: {cookbook}")
            return
    
    recipes = db_manager.list_recipes(cookbook_id, limit)
    
    if not recipes:
        click.echo("No recipes found")
        return
    
    # Format as table
    table_data = []
    for recipe in recipes:
        table_data.append([
            recipe.id,
            recipe.title[:40],
            recipe.cookbook_id,
            f"{len(recipe.ingredients)} ingredients",
            "✓" if recipe.mealie_id else "✗"
        ])
    
    headers = ["ID", "Title", "Cookbook", "Ingredients", "Mealie"]
    click.echo("\n" + tabulate(table_data, headers=headers, tablefmt="simple"))


@cli.command()
@click.argument('query')
@click.option('--db', default='data/recipes.db', help='Database path')
def search(query, db):
    """Search recipes"""
    db_manager = DatabaseManager(db)
    recipes = db_manager.search_recipes(query)
    
    if not recipes:
        click.echo(f"No recipes found for: {query}")
        return
    
    click.echo(f"\nFound {len(recipes)} recipe(s):\n")
    
    for recipe in recipes:
        click.echo(f"[{recipe.id}] {recipe.title}")
        if recipe.tags:
            click.echo(f"    Tags: {', '.join(recipe.tags)}")
        click.echo(f"    Cookbook ID: {recipe.cookbook_id}")
        click.echo()


@cli.command()
@click.option('--cookbook', '-c', help='Sync specific cookbook')
@click.option('--all', '-a', 'sync_all', is_flag=True, help='Sync all unsynced recipes')
@click.option('--db', default='data/recipes.db', help='Database path')
@click.option('--mealie-url', envvar='MEALIE_URL', required=True, help='Mealie base URL')
@click.option('--mealie-token', envvar='MEALIE_TOKEN', required=True, help='Mealie API token')
def sync(cookbook, sync_all, db, mealie_url, mealie_token):
    """Sync recipes to Mealie"""
    
    db_manager = DatabaseManager(db)
    mealie_client = MealieClient(mealie_url, mealie_token)
    
    # Test connection
    if not mealie_client.test_connection():
        click.echo("❌ Failed to connect to Mealie")
        return
    
    click.echo("✓ Connected to Mealie\n")
    
    # Get unsynced recipes
    recipes = db_manager.get_unsynced_recipes()
    
    if cookbook:
        # Filter by cookbook
        cb = db_manager.get_cookbook_by_name(cookbook)
        if cb:
            recipes = [r for r in recipes if r.cookbook_id == cb.id]
        else:
            click.echo(f"Cookbook not found: {cookbook}")
            return
    
    if not recipes:
        click.echo("No unsynced recipes found")
        return
    
    click.echo(f"Found {len(recipes)} unsynced recipe(s)\n")
    
    if not sync_all:
        if not click.confirm("Sync these recipes to Mealie?"):
            return
    
    # Sync each recipe
    success_count = 0
    for recipe in recipes:
        click.echo(f"Syncing: {recipe.title}...")
        
        try:
            # Convert to dict
            recipe_dict = {
                'title': recipe.title,
                'ingredients': recipe.ingredients,
                'instructions': recipe.instructions,
                'background_info': recipe.background_info,
                'handwritten_notes': recipe.handwritten_notes,
                'prep_time': recipe.prep_time,
                'cook_time': recipe.cook_time,
                'total_time': recipe.total_time,
                'servings': recipe.servings,
                'tags': recipe.tags,
                'cuisine': recipe.cuisine
            }
            
            mealie_id = mealie_client.sync_recipe(recipe_dict, recipe.image_path)
            
            if mealie_id:
                db_manager.update_mealie_sync(recipe.id, mealie_id)
                click.echo(f"  ✓ Synced: {mealie_id}\n")
                success_count += 1
            else:
                click.echo(f"  ✗ Failed\n")
                
        except Exception as e:
            click.echo(f"  ✗ Error: {e}\n")
    
    click.echo(f"\n✨ Synced {success_count}/{len(recipes)} recipes")


@cli.command()
@click.argument('name', required=False)
@click.option('--authors', help='Comma-separated authors')
@click.option('--language', default='en', help='Language code')
@click.option('--cuisine', help='Cuisine type')
@click.option('--sample-page', type=click.Path(exists=True), help='Path to sample page for AI analysis')
@click.option('--openai-key', envvar='OPENAI_API_KEY', help='OpenAI API key for AI analysis')
@click.option('--db', default='data/recipes.db', help='Database path')
@click.option('--interactive', '-i', is_flag=True, help='Interactive mode with prompts')
def init_cookbook(name, authors, language, cuisine, sample_page, openai_key, db, interactive):
    """Initialize a new cookbook with optional AI-powered config generation"""

    db_manager = DatabaseManager(db)
    config_manager = CookbookConfigManager(openai_api_key=openai_key)

    # Interactive mode
    if interactive or not name:
        click.echo("📚 Create New Cookbook - Interactive Mode\n")

        if not name:
            name = click.prompt("Cookbook name")

        if not authors:
            authors = click.prompt("Authors (comma-separated)", default="")

        if not language:
            language = click.prompt("Language", default="en")

        if not cuisine:
            cuisine = click.prompt("Cuisine type (optional)", default="")

        # Ask about AI analysis
        if openai_key and not sample_page:
            click.echo("\n🤖 AI-Powered Config Generation")
            click.echo("You can upload a sample recipe page for automatic structure detection.")
            sample_page = click.prompt("Path to sample page (or press Enter to skip)", default="", show_default=False)
            if sample_page and not Path(sample_page).exists():
                click.echo("⚠️  File not found, skipping AI analysis")
                sample_page = None

    # Check if exists
    if db_manager.get_cookbook_by_name(name):
        click.echo(f"❌ Cookbook already exists: {name}")
        return

    # Create folder structure
    folder_name = name.lower().replace(" ", "-")
    folder = Path(f"cookbooks/{folder_name}")

    success, msg = config_manager.create_folder_structure(folder)
    if not success:
        click.echo(f"❌ {msg}")
        return

    click.echo(f"✓ Created folder structure: {folder}")

    # Process with AI if sample page provided
    final_config = None
    author_list = [a.strip() for a in authors.split(',')] if authors else []

    if sample_page and openai_key:
        click.echo(f"\n🤖 Analyzing sample page: {Path(sample_page).name}")

        with click.progressbar(length=100, label='Analyzing') as bar:
            success, ai_config, message = config_manager.analyze_cookbook_structure(sample_page)
            bar.update(100)

        if success:
            click.echo("✓ Analysis complete!\n")

            # Merge with user info
            final_config = config_manager.merge_with_template(
                ai_config,
                {
                    "name": name,
                    "authors": author_list,
                    "cuisine": cuisine,
                    "language": language
                }
            )

            # Show summary
            click.echo("📊 Detected Structure:")
            click.echo(config_manager.format_config_summary(final_config))
            click.echo()

            # Ask for confirmation
            if interactive:
                if not click.confirm("Use this configuration?", default=True):
                    click.echo("Creating with basic template instead...")
                    final_config = None
        else:
            click.echo(f"⚠️  Analysis failed: {message}")
            click.echo("Creating with basic template...\n")

    # Use basic template if no AI config
    if not final_config:
        final_config = config_manager.create_config_template(
            name, authors, language, cuisine
        )
        if not sample_page:
            click.echo("💡 Tip: Use --sample-page to enable AI-powered config generation")

    # Save config
    success, msg = config_manager.save_config(final_config, folder)
    if success:
        click.echo(f"✓ Created config: {folder / 'config.json'}")
    else:
        click.echo(f"❌ Error saving config: {msg}")
        return

    # Add to database
    cookbook = Cookbook(
        name=name,
        authors=", ".join(author_list),
        language=language,
        cuisine=cuisine,
        config_path=str(folder / "config.json")
    )

    cookbook_id = db_manager.add_cookbook(cookbook)
    click.echo(f"✓ Added to database (ID: {cookbook_id})")

    # Summary
    click.echo(f"\n✅ Cookbook '{name}' created successfully!")
    click.echo(f"\n📂 Next steps:")
    click.echo(f"   1. Add recipe images to: {folder / 'images'}/")
    click.echo(f"   2. Process images: python recipe_cli.py process {folder / 'images'}/")
    click.echo(f"   3. (Optional) Edit config: {folder / 'config.json'}")


if __name__ == '__main__':
    cli()
