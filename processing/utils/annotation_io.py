"""
Input/Output utilities for annotation workflows.
Handles saving, loading, and history management for annotations.
"""

import json
import datetime
import os


def save_annotation_history(annotations, scope="doc", base_dir="History"):
    """
    Save annotations to history file with timestamp.

    Args:
        annotations: List of annotation dictionaries
        scope: Scope of the annotation (for filename)
        base_dir: Base directory for history files

    Returns:
        Path to saved file
    """
    if not annotations:
        print("❗ No annotations to save.")
        return None

    os.makedirs(base_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(base_dir, f"claude_output_{scope}_{timestamp}.txt")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(annotations, f, indent=2, ensure_ascii=False)

    print(f"📁 Annotations saved to {filename}")
    return filename


def save_annotations_json(annotations, output_path):
    """
    Save annotations to a specific JSON file path.

    Args:
        annotations: List of annotation dictionaries
        output_path: Full path where to save the JSON file

    Returns:
        True if successful, False otherwise
    """
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(annotations, f, indent=2, ensure_ascii=False)
        print(f"📄 Annotations saved to {output_path}")
        return True
    except Exception as e:
        print(f"❌ Error saving annotations to {output_path}: {e}")
        return False


def load_annotations_json(input_path):
    """
    Load annotations from a JSON file.

    Args:
        input_path: Path to the JSON file to load

    Returns:
        List of annotation dictionaries, or empty list if error
    """
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            annotations = json.load(f)
        print(f"📄 Loaded {len(annotations)} annotations from {input_path}")
        return annotations
    except Exception as e:
        print(f"❌ Error loading annotations from {input_path}: {e}")
        return []


def generate_output_filename(parsed_docs, base_name=None, extension=".json"):
    """
    Generate a standardized output filename based on document metadata.

    Args:
        parsed_docs: List of parsed document dictionaries
        base_name: Optional base name override
        extension: File extension to use

    Returns:
        Generated filename
    """
    if base_name:
        return f"{base_name}{extension}"

    if parsed_docs and isinstance(parsed_docs, list):
        doc_meta = parsed_docs[0]
        cg_id = doc_meta.get("caregiver_id")
        if cg_id:
            safe_id = cg_id.replace(" ", "_").replace("/", "_")
            return f"{safe_id}{extension}"
        elif "filename" in doc_meta:
            import re
            match = re.search(r"Caregiver_(\d+)", doc_meta["filename"])
            if match:
                return f"Caregiver_{match.group(1)}{extension}"

    return f"Caregiver_UNKNOWN{extension}"
