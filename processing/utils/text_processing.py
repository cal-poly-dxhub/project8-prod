"""
Comprehensive text processing utilities for annotation workflows.
Handles sentence splitting, text normalization, transcript batching, and prompt management.
"""

import os
import nltk
import tiktoken
import unicodedata
from nltk.tokenize import sent_tokenize

# Download required NLTK data
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download("punkt")

# Token budget constants
TRANSCRIPT_TOKEN_BUDGET = 5000


# ========== Text Utilities ==========

def extract_paragraph_snippet(paragraph_text, indices=None, paragraph_id=None):
    """
    Given a paragraph's raw text and indices (a list of sentence indices),
    return the snippet or a helpful error message if indices are invalid.
    If indices is None, return the whole paragraph.
    Indices should always be a list of integers.
    """
    if paragraph_text is None:
        pid = paragraph_id if paragraph_id is not None else 'Unknown'
        return f"Paragraph {pid} not found."

    sentences = split_sentences(paragraph_text)
    if not sentences:
        return f"Paragraph {paragraph_id or ''} is empty."

    if indices is None:
        return paragraph_text

    # Indices should always be a list of integers representing sentence indices.
    try:
        if isinstance(indices, list) and all(isinstance(idx, int) for idx in indices):
            if all(0 <= idx < len(sentences) for idx in indices):
                return ' '.join([sentences[idx] for idx in indices])
            else:
                return ''.join(sentences) # return the full paragraph if indices are out of range
        else:
            return f"Invalid indices format for paragraph {paragraph_id or ''}. Indices must be a list of integers."
    except Exception as e:
        return f"Error extracting snippet: {str(e)}"


def split_sentences(text):
    """Split text into sentences using NLTK's sent_tokenize."""
    return [s.strip() for s in sent_tokenize(text)]


def normalize(text):
    """Normalize text by handling unicode characters and whitespace."""
    return unicodedata.normalize("NFKC", text).replace("\u00A0", " ").strip()


# ========== Transcript Processing ==========

def generate_batched_transcript_inputs(parsed_docs, token_limit=TRANSCRIPT_TOKEN_BUDGET, scope="doc", selected_doc_id=None, selected_paragraph_id=None):
    """
    Generate batched transcript inputs for annotation, respecting token limits.

    Args:
        parsed_docs: List of parsed document dictionaries
        token_limit: Maximum tokens per batch
        scope: Scope of processing ("all", "doc", "paragraph")
        selected_doc_id: Specific document ID when scope is "doc"
        selected_paragraph_id: Specific paragraph ID when scope is "paragraph"

    Returns:
        List of batched transcript strings ready for annotation
    """
    tokenizer = tiktoken.get_encoding("cl100k_base")
    batches = []
    current_batch = []
    current_tokens = 0

    for doc in parsed_docs:
        doc_id = doc.get("doc_id", doc.get("filename"))
        if scope != "all" and doc_id != selected_doc_id:
            continue
        for utt in doc["utterances"]:
            if scope == "paragraph" and utt["id"] != selected_paragraph_id:
                continue
            sentences = split_sentences(utt["text"])
            numbered_sentences = [
                f"[{i}] {s}" for i, s in enumerate(sentences)]
            chunk = f"[{utt['id']}] {utt['speaker']}:\n" + \
                "".join(numbered_sentences)
            chunk_tokens = len(tokenizer.encode(chunk))

            if current_tokens + chunk_tokens > token_limit:
                if current_batch:
                    batches.append("\n\n".join(current_batch))
                    current_batch = []
                    current_tokens = 0

            current_batch.append(chunk)
            current_tokens += chunk_tokens

    if current_batch:
        batches.append("\n\n".join(current_batch))

    return batches


def calculate_token_budget(full_prompt, max_total_tokens=30000):
    """
    Calculate available token budget for transcript content.

    Args:
        full_prompt: The complete prompt text
        max_total_tokens: Maximum total tokens allowed

    Returns:
        Available token budget for transcript content
    """
    encoder = tiktoken.get_encoding("cl100k_base")
    prompt_token_count = len(encoder.encode(full_prompt))
    token_limit = min(TRANSCRIPT_TOKEN_BUDGET,
                      max_total_tokens - prompt_token_count)
    return token_limit


# ========== Prompt Management ==========

def load_prompt_template(prompt_name="labeling_prompt.txt"):
    """
    Load a prompt template from the prompts directory.

    Args:
        prompt_name: Name of the prompt file to load

    Returns:
        Prompt template as string
    """
    prompt_path = os.path.join(os.path.dirname(
        __file__), "..", "prompts", prompt_name)
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def build_full_prompt_with_codebook(prompt_template, codebook_placeholder="{{CODEBOOK_HERE}}"):
    """
    Build a complete prompt by replacing codebook placeholder with actual codebook.

    Args:
        prompt_template: Template string with codebook placeholder
        codebook_placeholder: Placeholder text to replace

    Returns:
        Complete prompt with codebook included
    """
    from .codebook import load_codebook

    categories = load_codebook()
    codebook_text = "\n".join(
        f"{row['Id']} – {row['Name']}" + (f" | Notes: {row['Notes']}" if row.get(
            'Notes') and str(row['Notes']).strip() and str(row['Notes']) != 'nan' else "")
        for row in categories
    )
    return prompt_template.replace(codebook_placeholder, codebook_text)


def build_group_prompt(group_name, codebook_placeholder="{CODEBOOK_HERE}"):
    """
    Build a complete group-specific prompt with filtered codebook.

    Args:
        group_name: Name of the concept group
        codebook_placeholder: Placeholder text to replace with codebook

    Returns:
        Complete prompt with group-specific codebook included
    """
    from .codebook import get_codes_for_group, format_codebook_for_group, load_codebook, load_group_prompt

    # Load group prompt template
    group_prompt = load_group_prompt(group_name)
    if not group_prompt:
        return None

    # Get codes for this group and format them
    all_categories = load_codebook()
    group_codes = get_codes_for_group(group_name, all_categories)
    if not group_codes:
        return None

    # Format codebook for this group
    codebook_text = format_codebook_for_group(group_codes)

    # Replace placeholder with formatted codebook
    return group_prompt.replace(codebook_placeholder, codebook_text)
