"""
Core annotation engine for Claude-based concept annotation.
Provides both single-pass and multi-pass annotation workflows.
"""

import asyncio
try:
    import streamlit as st
except ImportError:
    st = None
from .text_processing import generate_batched_transcript_inputs, calculate_token_budget, build_full_prompt_with_codebook, build_group_prompt, load_prompt_template, extract_paragraph_snippet, TRANSCRIPT_TOKEN_BUDGET
from .annotation_io import save_annotation_history
from .bedrock import query_claude_with_bedrock, blocking_bedrock_call_for_group
from .parsers import extract_json_from_claude_response
from .codebook import load_concept_notes, get_codes_for_group, extract_used_concept_ids, filter_remaining_codes, load_codebook, load_group_prompt
from config import CODE_GROUPS, MAX_TOTAL_TOKENS, ASYNC_CONCURRENT_REQUESTS, MAX_CONCURRENT_CALLS, CODEBOOK_WITH_NOTES_CSV
import os

# Semaphores for concurrency control
semaphore_single = asyncio.Semaphore(ASYNC_CONCURRENT_REQUESTS)
semaphore_multi = asyncio.Semaphore(MAX_CONCURRENT_CALLS)


def get_extended_paragraph_context(parsed_docs, doc_id, target_paragraph_id, before=2, after=1):
    """
    Get extended context around a target paragraph with specified number of paragraphs before and after.

    Args:
        parsed_docs: List of parsed document dictionaries
        doc_id: Document ID to search in
        target_paragraph_id: The paragraph ID to get context for
        before: Number of paragraphs to include before target (default: 2)
        after: Number of paragraphs to include after target (default: 1)

    Returns:
        String containing the extended context, or empty string if paragraph not found
    """
    try:
        # Find the target document
        target_doc = None
        for doc in parsed_docs:
            if doc.get("doc_id") == doc_id:
                target_doc = doc
                break

        if not target_doc:
            return ""

        utterances = target_doc.get("utterances", [])
        if not utterances:
            return ""

        # Find the target paragraph index
        target_index = None
        for i, utterance in enumerate(utterances):
            if utterance.get("id") == target_paragraph_id:
                target_index = i
                break

        if target_index is None:
            return ""

        # Calculate the range of paragraphs to include
        start_index = max(0, target_index - before)
        end_index = min(len(utterances), target_index + after + 1)

        # Collect the context paragraphs
        context_parts = []
        for i in range(start_index, end_index):
            utterance = utterances[i]
            speaker = utterance.get("speaker", "Unknown")
            timestamp = utterance.get("timestamp", "")
            text = utterance.get("text", "")

            # Mark the target paragraph
            if i == target_index:
                context_parts.append(
                    f">>> TARGET: {speaker} [{timestamp}]: {text}")
            else:
                context_parts.append(f"{speaker} [{timestamp}]: {text}")

        return "\n\n".join(context_parts)

    except Exception as e:
        print(
            f"Warning: Could not get extended context for {target_paragraph_id}: {e}")
        return ""


async def annotate_with_claude(parsed_docs, scope="all", selected_doc_id=None, selected_paragraph_id=None):
    """
    Single-pass Claude annotation using the main labeling prompt.

    Args:
        parsed_docs: List of parsed document dictionaries
        scope: Scope of processing ("all", "doc", "paragraph")
        selected_doc_id: Specific document ID when scope is "doc"
        selected_paragraph_id: Specific paragraph ID when scope is "paragraph"

    Returns:
        List of annotation dictionaries
    """
    # Load and build the complete prompt
    prompt_template = load_prompt_template("generic_notes_focused_prompt.txt")
    full_prompt = build_full_prompt_with_codebook(prompt_template)

    # Calculate token budget
    token_limit = calculate_token_budget(full_prompt, MAX_TOTAL_TOKENS)

    # Generate transcript batches
    transcript_batches = generate_batched_transcript_inputs(
        parsed_docs,
        token_limit=token_limit,
        scope=scope,
        selected_doc_id=selected_doc_id,
        selected_paragraph_id=selected_paragraph_id,
    )

    total_batches = len(transcript_batches)
    print(f"🔄 Total Batches: {total_batches}")

    # Initialize progress tracking
    progress_bar = None
    if st:
        progress_bar = st.progress(
            0.0, text="Starting annotation...(0/" + str(total_batches) + ")")
    completed_ref = [0]
    lock = asyncio.Lock()

    # Create annotation tasks
    tasks = [
        query_claude_with_bedrock(full_prompt, "TRANSCRIPTS_HERE\n\n" + batch_input,
                                  idx, semaphore_single, progress_bar, total_batches, completed_ref, lock)
        for idx, batch_input in enumerate(transcript_batches, 1)
    ]

    # Execute annotations
    all_annotations = []
    results = await asyncio.gather(*tasks)
    results.sort(key=lambda x: x[0])

    # Process results
    for idx, result in results:
        if not result:
            print(f"❌ Claude returned no result for batch {idx}.")
            continue
        try:
            annotations = extract_json_from_claude_response(result)
            for ann in annotations:
                ann["source"] = "claude"
            all_annotations.extend(annotations)
            print(f"✅ Batch {idx} completed and parsed.")
        except Exception as e:
            print(f"⚠️ Failed to parse batch {idx}. Error: {e}")
            print("Raw output:", result)

    # Save to history
    if all_annotations:
        save_annotation_history(all_annotations, scope)
    else:
        print("❗ No annotations extracted.")

    return all_annotations


async def annotate_with_multi_pass_claude(parsed_docs, num_passes, scope="all", selected_doc_id=None, selected_paragraph_id=None, selected_groups=None, interview_age=None):
    """
    Multi-pass Claude annotation using group-specific prompts.
    Each group runs N passes, filtering out used concepts between passes.

    Args:
        parsed_docs: List of parsed document dictionaries
        num_passes: Number of annotation passes to perform
        scope: Scope of processing ("all", "doc", "paragraph")
        selected_doc_id: Specific document ID when scope is "doc"
        selected_paragraph_id: Specific paragraph ID when scope is "paragraph"
        selected_groups: List of concept groups to process (None for all)

    Returns:
        List of annotation dictionaries
    """
    # Setup
    single_doc_id = parsed_docs[0]["doc_id"] if parsed_docs and len(
        parsed_docs) == 1 else None
    concept_notes_map = load_concept_notes(str(CODEBOOK_WITH_NOTES_CSV))

    # Build paragraph lookup for text extraction
    paragraph_lookup = {}
    for doc in parsed_docs:
        doc_id = doc.get("doc_id")
        paragraph_lookup[doc_id] = {}
        for utterance in doc.get("utterances", []):
            paragraph_lookup[doc_id][utterance["id"]] = utterance["text"]

    # Load data
    all_categories = load_codebook()
    if selected_groups is None:
        selected_groups = list(CODE_GROUPS.keys())

    print(
        f"🔄 Running {num_passes}-pass annotation with {len(selected_groups)} groups")

    # Generate transcript batches
    transcript_batches = generate_batched_transcript_inputs(
        parsed_docs, token_limit=TRANSCRIPT_TOKEN_BUDGET, scope=scope,
        selected_doc_id=selected_doc_id, selected_paragraph_id=selected_paragraph_id
    )
    print(f"📊 Generated {len(transcript_batches)} transcript batches")

    # Run each group's N-pass pipeline in parallel
    async def run_group_npass(group_name):
        """Run N-pass annotation for one group"""
        # Setup
        group_prompt = load_group_prompt(group_name)
        if not group_prompt:
            return []

        group_categories = get_codes_for_group(group_name, all_categories)
        if not group_categories:
            return []

        all_annotations = []
        remaining_codes = group_categories

        # Run multiple passes
        for pass_num in range(1, num_passes + 1):
            if not remaining_codes:
                print(
                    f"⏭️ Pass {pass_num} for {group_name}: No remaining codes")
                break

            print(
                f"🚀 Pass {pass_num} for {group_name}: {len(remaining_codes)} codes")
            pass_annotations = await run_annotation_pass(
                semaphore_multi, transcript_batches, group_name, group_prompt, remaining_codes, pass_num,
                single_doc_id, paragraph_lookup, concept_notes_map, parsed_docs, interview_age
            )
            print(
                f"📊 Pass {pass_num} for {group_name}: {len(pass_annotations)} annotations")

            all_annotations.extend(pass_annotations)

            # For subsequent passes, filter out used concept IDs
            if pass_num < num_passes and pass_annotations:
                used_concept_ids = extract_used_concept_ids(pass_annotations)
                remaining_codes = filter_remaining_codes(
                    remaining_codes, used_concept_ids)

        return all_annotations

    # Run all groups in parallel
    group_tasks = [run_group_npass(group_name)
                   for group_name in selected_groups]
    all_group_results = await asyncio.gather(*group_tasks, return_exceptions=True)

    # Combine results. Log a per-group breakdown so the worker logs show which
    # groups came back empty (throttled/blocked) vs healthy, instead of only a
    # single total that hides partial failures.
    all_annotations = []
    per_group_counts = {}
    for i, result in enumerate(all_group_results):
        group_name = selected_groups[i]
        if isinstance(result, Exception):
            print(f"Group {group_name} FAILED: {type(result).__name__}: {result}")
            per_group_counts[group_name] = "FAILED"
        else:
            all_annotations.extend(result)
            per_group_counts[group_name] = len(result)

    print(f"Per-group annotation counts: {per_group_counts}")
    empty_groups = [g for g, c in per_group_counts.items() if c == 0 or c == "FAILED"]
    if empty_groups:
        print(f"WARNING: {len(empty_groups)} group(s) returned no annotations: {empty_groups}")
    print(
        f"{num_passes}-pass annotation complete: {len(all_annotations)} total annotations")
    return all_annotations


async def run_annotation_pass(semaphore, transcript_batches, group_name, group_prompt, codebook, pass_num, single_doc_id, paragraph_lookup, concept_notes_map, parsed_docs, interview_age=None):
    """
    Run a single annotation pass for a specific group.

    Args:
        semaphore: Concurrency control semaphore
        transcript_batches: List of transcript batch strings
        group_name: Name of the concept group
        group_prompt: Prompt template for the group
        codebook: List of concept codes for this group
        pass_num: Current pass number
        single_doc_id: Document ID for text lookup
        paragraph_lookup: Mapping of doc_id -> paragraph_id -> text
        concept_notes_map: Mapping of concept_id -> notes
        parsed_docs: List of parsed document dictionaries for context extraction

    Returns:
        List of annotations from this pass
    """
    from utils.codebook import format_codebook_for_group

    # Build the complete prompt for this group
    codebook_text = format_codebook_for_group(codebook)
    full_prompt = group_prompt.replace("{CODEBOOK_HERE}", codebook_text)

    # Optional single-line age hint. The interviewee's age helps the model pick
    # age-appropriate concepts (e.g. developmental milestones vs adult concerns).
    if interview_age is not None:
        full_prompt += f"\n\nThe interviewee is {interview_age} years old at the time of this interview."

    # Create annotation tasks for all batches
    pass_tasks = [
        annotate_batch_with_group(semaphore, i, full_prompt, transcript, group_name, [
                                  0], asyncio.Lock(), None, 0)
        for i, transcript in enumerate(transcript_batches)
    ]

    # Execute all tasks
    pass_results = await asyncio.gather(*pass_tasks, return_exceptions=True)

    # Process results
    pass_annotations = []
    for result in pass_results:
        if not isinstance(result, Exception):
            _, annotations, _ = result
            for ann in annotations:
                ann["pass"] = pass_num
                doc_id = single_doc_id
                paragraph_id = ann.get("paragraph_id")
                concept_id = str(ann.get("concept_id")) if ann.get(
                    "concept_id") is not None else None

                # Enrich annotation with additional data
                raw_paragraph = paragraph_lookup.get(
                    doc_id, {}).get(paragraph_id)
                ann["raw_paragraph"] = raw_paragraph

                # Add extended context with 2 paragraphs before and 1 after
                extended_context = get_extended_paragraph_context(
                    parsed_docs, doc_id, paragraph_id, before=2, after=1)
                ann["extended_context"] = extended_context

                ann["concept_note"] = concept_notes_map.get(concept_id)
                indices = ann.get("sentence_indices")
                ann["raw_highlight"] = extract_paragraph_snippet(
                    raw_paragraph, indices, paragraph_id if pass_num == 2 else None)

                rationale = (ann.get("rationale") or "").lower()
                if "should not be annotated" in rationale or "does not apply" in rationale or "removing this" in rationale:
                    continue

                pass_annotations.append(ann)

    return pass_annotations


async def annotate_batch_with_group(semaphore, batch_idx, prompt, transcript, group_name, completed_ref, lock, progress_bar, total_operations):
    """
    Annotate a single batch with a specific group's prompt.

    Args:
        semaphore: Concurrency control semaphore
        batch_idx: Index of the current batch
        prompt: Complete prompt for annotation
        transcript: Transcript text for this batch
        group_name: Name of the concept group
        completed_ref: Reference to completion counter
        lock: Async lock for thread safety
        progress_bar: Progress bar for UI updates
        total_operations: Total number of operations

    Returns:
        Tuple of (batch_idx, annotations, group_name)
    """
    async with semaphore:
        try:
            result = await asyncio.to_thread(blocking_bedrock_call_for_group, prompt, transcript, group_name)

            async with lock:
                completed_ref[0] += 1
                progress_text = f"Completed {completed_ref[0]}/{total_operations} operations ({group_name})"
                # Note: Progress bar updates disabled to avoid range errors in test mode

            return batch_idx, result, group_name

        except Exception as e:
            print(f"❌ Error in batch {batch_idx} for group {group_name}: {e}")
            return batch_idx, [], group_name
