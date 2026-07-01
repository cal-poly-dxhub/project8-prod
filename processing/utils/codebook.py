from typing import Dict
import csv
import pandas as pd
import os


def format_codebook_for_group(group_categories):
    """Format codebook text for a specific group with usage criteria first"""
    formatted_codes = []

    for row in group_categories:
        # Start with usage criteria if available
        if row.get('Notes') and str(row['Notes']).strip() and str(row['Notes']) != 'nan':
            code_text = f"**WHEN TO USE:** {row['Notes']}\n↳ Code {row['Id']} – {row['Name']}"
        else:
            code_text = f"Code {row['Id']} – {row['Name']}"
        formatted_codes.append(code_text)

    return "\n\n".join(formatted_codes)


def extract_used_concept_ids(annotations):
    """Extract concept IDs that were found in Pass 1"""
    used_ids = set()
    for annotation in annotations:
        if 'concept_id' in annotation and annotation['concept_id'] is not None:
            try:
                used_ids.add(int(annotation['concept_id']))
            except (ValueError, TypeError):
                continue
    return used_ids


def filter_remaining_codes(group_codes, used_concept_ids):
    """Filter out codes that were already used in Pass 1"""
    remaining_codes = []
    for code in group_codes:
        try:
            code_id = int(code["Id"])
            if code_id not in used_concept_ids:
                remaining_codes.append(code)
        except (ValueError, KeyError):
            continue
    return remaining_codes


def get_codes_for_group(group_name, all_categories, code_groups=None):
    """Get filtered codebook for a specific group based on ID range"""
    if code_groups is None:
        from config import CODE_GROUPS
        code_groups = CODE_GROUPS
    if group_name not in code_groups:
        return []

    id_range = code_groups[group_name]["id_range"]
    start_id, end_id = id_range

    # Filter categories by ID range
    filtered_codes = []
    for cat in all_categories:
        try:
            cat_id = int(cat["Id"])
            if start_id <= cat_id < end_id:  # end_id is exclusive in range
                filtered_codes.append(cat)
        except (ValueError, KeyError):
            continue

    return filtered_codes


def load_codebook():
    from config import CODEBOOK_WITH_NOTES_CSV
    df = pd.read_csv(str(CODEBOOK_WITH_NOTES_CSV), encoding="utf-8")
    df["Notes"] = df["Notes"].fillna("")
    return df.astype(str).to_dict(orient="records")


# ========== Concept Notes Utilities ==========
# (Previously in concept_notes.py)


def load_csv_mapping(csv_path: str, key_col: str, value_col: str) -> Dict[str, str]:
    """
    General-purpose CSV mapping loader.
    Returns a dict mapping key_col to value_col (both as strings).
    """
    mapping = {}
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            key = str(row[key_col]).strip()
            value = str(row[value_col]).strip()
            mapping[key] = value
    return mapping


def load_concept_notes(csv_path: str) -> Dict[str, str]:
    """
    Loads concept notes using the general mapping loader.
    """
    return load_csv_mapping(csv_path, key_col='Id', value_col='Notes')


# ========== Group Utilities ==========
# (Previously in group_utils.py)
def load_group_prompt(group_name):
    """Load prompt template for a specific group from file"""
    try:
        from config import get_prompt_file_for_group
        
        # Use the configured prompt file instead of hardcoded pattern
        prompt_file = get_prompt_file_for_group(group_name)
        prompt_path = os.path.join(os.path.dirname(
            __file__), "../prompts", prompt_file)

        with open(prompt_path, 'r', encoding='utf-8') as file:
            return file.read().strip()
    except FileNotFoundError:
        print(f"Warning: Prompt file not found for group {group_name}: {prompt_file}")
        return ""
    except Exception as e:
        print(f"Error loading prompt for group {group_name}: {str(e)}")
        return ""

def get_available_groups(CODE_GROUPS):
    """Get list of available annotation groups"""
    return list(CODE_GROUPS.keys())


def get_group_info(CODE_GROUPS):
    """Get information about all available groups"""
    info = {}
    for group_key, group_config in CODE_GROUPS.items():
        info[group_key] = {
            "name": group_config["name"],
            "id_range": group_config["id_range"],
            "prompt_file": f"{group_key}_prompt.txt"
        }
    return info
