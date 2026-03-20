#!/usr/bin/env python3
"""
Generate volunteer codes with embedded tokens
Run this to create codes for volunteers - auto-detects dataset size from CSV
Each row in the CSV is treated as one unit (no sentence splitting)
Volunteers get random alias nicknames
"""

import json
import base64
import csv
import os
import random

# ============== CONFIGURE THESE ==============
GITHUB_TOKEN = "GITHUB-TOKEN-HERE"  # Your GitHub personal access token
DATA_FILE = "data.csv"                      # Path to your CSV file
NUM_VOLUNTEERS = 10                          # Number of volunteers to generate codes for
# ==============================================

# Pool of adjectives and nouns for generating alias nicknames
ADJECTIVES = [
    "Swift", "Bright", "Cool", "Brave", "Happy", "Lucky", "Clever", "Kind",
    "Bold", "Calm", "Eager", "Fair", "Gentle", "Wise", "Quick", "Quiet",
    "Sunny", "Warm", "Wild", "Zesty", "Amber", "Azure", "Crimson", "Golden",
    "Ivory", "Jade", "Onyx", "Ruby", "Silver", "Violet", "Electric", "Neon",
    "Cosmic", "Solar", "Lunar", "Stellar", "Atomic", "Cyber", "Digital", "Quantum"
]

NOUNS = [
    "Falcon", "Tiger", "Eagle", "Wolf", "Bear", "Lion", "Hawk", "Otter",
    "Panda", "Raven", "Fox", "Lynx", "Moose", "Orca", "Seal", "Shark",
    "Dragon", "Phoenix", "Griffin", "Unicorn", "Titan", "Nova", "Comet",
    "Meteor", "Nebula", "Quasar", "Pulsar", "Vortex", "Zenith", "Apex",
    "Spark", "Pulse", "Surge", "Flash", "Blaze", "Frost", "Flame", "Thunder",
    "Shadow", "Spirit", "Ghost", "Phantom", "Specter", "Wraith", "Echo",
    "Cobra", "Viper", "Python", "Mamba", "Cotton", "Maple", "Cedar", "Willow"
]


def generate_alias(existing_aliases):
    """Generate a unique random alias nickname"""
    max_attempts = 1000
    for _ in range(max_attempts):
        adj = random.choice(ADJECTIVES)
        noun = random.choice(NOUNS)
        alias = f"{adj}{noun}"
        
        if alias not in existing_aliases:
            return alias
    
    # Fallback: add number if exhausted
    adj = random.choice(ADJECTIVES)
    noun = random.choice(NOUNS)
    number = random.randint(1, 999)
    return f"{adj}{noun}{number}"


def count_rows_in_csv(csv_path):
    """Count total rows in CSV (each row = one unit)"""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Data file not found: {csv_path}")
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return sum(1 for _ in reader)


def generate_code(github_token, start_index, count, volunteer_name):
    """
    Create encoded volunteer code containing:
    - GitHub personal access token (for Gist updates)
    - Start index in dataset
    - Number of rows to record
    - Volunteer identifier
    """
    payload = {
        "t": github_token,      # Token (obfuscated, not encrypted)
        "s": start_index,       # Start index
        "c": count,             # Count of rows
        "v": volunteer_name     # Volunteer name/alias
    }
    
    json_str = json.dumps(payload)
    # Base64 encode
    encoded = base64.b64encode(json_str.encode()).decode()
    # Remove padding for cleaner look, add VOL- prefix
    code = f"VOL-{encoded.replace('=', '')}"
    return code


def main():
    # Auto-detect total rows from CSV
    try:
        total_rows = count_rows_in_csv(DATA_FILE)
    except FileNotFoundError as e:
        print(f"\n❌ Error: {e}")
        print(f"Please ensure '{DATA_FILE}' exists in the same directory.")
        return
    
    if NUM_VOLUNTEERS <= 0:
        print("\n❌ Error: NUM_VOLUNTEERS must be greater than 0!")
        return
    
    if total_rows == 0:
        print("\n❌ Error: No rows found in the dataset!")
        return
    
    if NUM_VOLUNTEERS > total_rows:
        print(f"\n⚠️  Warning: More volunteers ({NUM_VOLUNTEERS}) than rows ({total_rows})!")
        print("Some volunteers will have 0 rows assigned.")
    
    # Generate unique aliases for volunteers
    aliases = set()
    volunteer_list = []
    for i in range(NUM_VOLUNTEERS):
        alias = generate_alias(aliases)
        aliases.add(alias)
        volunteer_list.append(alias)
    
    # Calculate base count and remainder for fair distribution
    base_count = total_rows // NUM_VOLUNTEERS
    remainder = total_rows % NUM_VOLUNTEERS
    
    print(f"\n{'='*60}")
    print(f"📊 Auto-detected from '{DATA_FILE}'")
    print(f"Generating codes for {NUM_VOLUNTEERS} volunteers")
    print(f"Total rows: {total_rows}")
    print(f"Base allocation: {base_count} rows each")
    print(f"Remainder ({remainder}) distributed to first volunteers")
    print(f"{'='*60}\n")
    
    current_index = 0
    
    for i, alias in enumerate(volunteer_list):
        # First 'remainder' volunteers get 1 extra row
        count = base_count + (1 if i < remainder else 0)
        
        code = generate_code(GITHUB_TOKEN, current_index, count, alias)
        
        print(f"{'─'*60}")
        print(f"👤 Volunteer Alias: {alias}")
        print(f"📍 Range: {current_index} to {current_index + count - 1} ({count} rows)")
        print(f"\n🔑 Code: {code}")
        print(f"{'─'*60}\n")
        
        current_index += count
    
    print(f"{'='*60}")
    print("⚠️  WARNING: These codes contain obfuscated tokens.")
    print("Treat them as sensitive - only share with assigned volunteers!")
    print(f"{'='*60}")
    
    # Save mapping for your reference
    print("\n📋 Volunteer Alias Mapping (save this for your records):")
    for alias in volunteer_list:
        print(f"   - {alias}")


if __name__ == "__main__":
    main()
