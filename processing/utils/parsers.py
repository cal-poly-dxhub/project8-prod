import re
import uuid
from docx import Document
import json
import unicodedata

def parse_docx_files(file_list):
    parsed_documents = []

    # 1. Timestamp range (used in WEBVTT or subtitle files)
    # Matches:
    #   00:00:00.000 --> 00:00:05.123
    #   01:10:22 --> 01:12:44.500
    # Parser behavior:
    #   - Save the **start** timestamp (for now)
    #   - Use the next line for the actual utterance (with or without speaker)
    timestamp_range_pattern = re.compile(
        r'^(\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?)\s*-->\s*(\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?)$'
    )

    # 2. Timestamp-only line (with or without brackets)
    # Matches:
    #   [00:01:23]
    #   00:01:23.456
    #   [01:23:00.000]
    # Parser behavior:
    #   - Save as timestamp to apply to upcoming utterance
    timestamp_inline_pattern = re.compile(
        r'^\[?(\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?)\]?$'
    )

    # 3. Speaker name only (awaits text on next line)
    # Matches:
    #   Interviewer:
    #   Caregiver:
    # Parser behavior:
    #   - Save speaker
    #   - Look ahead for text in next line
    speaker_only_pattern = re.compile(
        r'^([A-Za-z\s]+):$'
    )

    # 4. Speaker line with timestamp inline in brackets (optional text after)
    # Matches:
    #   Interviewer: [00:01:23] How are you?
    #   Caregiver [01:23:00] I'm okay
    #   Nurse: [00:10:00]
    # Parser behavior:
    #   - Extract speaker, timestamp, and optional text (can be empty)
    speaker_inline_timestamp_pattern = re.compile(
        r'^([A-Za-z\s]+):?\s*\[(\d{1,2}:\d{2}:\d{2}(?:\.\d{1,3})?)\]\s*(.*)$'
    )

    # 5. Speaker and text (no timestamp)
    # Matches:
    #   Interviewer: How are you?
    #   Caregiver: I’m okay
    # Parser behavior:
    #   - Save speaker and text
    #   - Use previously seen timestamp if available
    speaker_and_text_pattern = re.compile(
        r'^([A-Za-z\s]+):\s*(.+)$'
    )

    for file in file_list:
        file.seek(0)
        doc = Document(file)
        doc_id = str(uuid.uuid4())
        utterances = []
        utterance_counter = 1

        lines = [para.text.strip()
                 for para in doc.paragraphs if para.text.strip()]
        current_speaker = None
        current_timestamp = None
        buffer_text = ""

        i = 0
        while i < len(lines):
            line = lines[i]

            # Skip headers or subtitle numbers
            if line.lower() == "webvtt" or line.isdigit():
                i += 1
                continue

            # Case 1: timestamp range
            if timestamp_range_pattern.match(line):
                current_timestamp = timestamp_range_pattern.match(
                    line).group(1).strip()
                i += 1
                # Check if next line is text without speaker
                if i < len(lines):
                    next_line = lines[i]
                    if not any(p.match(next_line) for p in [speaker_inline_timestamp_pattern, speaker_only_pattern, speaker_and_text_pattern, timestamp_range_pattern]):
                        utterances.append({
                            "id": f"u{utterance_counter:03}",
                            "speaker": "Unknown",
                            "timestamp": current_timestamp,
                            "text": next_line,
                            "codes": []
                        })
                        utterance_counter += 1
                        i += 1
                        continue
                continue

            # Case 2: Speaker [timestamp] text
            if speaker_inline_timestamp_pattern.match(line):
                match = speaker_inline_timestamp_pattern.match(line)
                current_speaker = match.group(1).strip()
                current_timestamp = match.group(2).strip()
                buffer_text = match.group(3).strip()

            # Case 3: Speaker: text (no timestamp)
            elif speaker_and_text_pattern.match(line):
                match = speaker_and_text_pattern.match(line)
                current_speaker = match.group(1).strip()
                current_timestamp = current_timestamp if current_timestamp else "None"
                buffer_text = match.group(2).strip()

            # Case 4: Speaker: (next line is text)
            elif speaker_only_pattern.match(line):
                current_speaker = speaker_only_pattern.match(
                    line).group(1).strip()
                current_timestamp = current_timestamp if current_timestamp else "None"
                # Look ahead
                if i + 1 < len(lines):
                    buffer_text = lines[i + 1].strip()
                    i += 1

            # Case 5: timestamp only
            elif timestamp_inline_pattern.match(line):
                current_timestamp = timestamp_inline_pattern.match(
                    line).group(1).strip()

            # Case 6: text only (fallback)
            else:
                buffer_text = line.strip()
                current_speaker = current_speaker if current_speaker else "Unknown"
                current_timestamp = current_timestamp if current_timestamp else "None"

            # Emit if we have speaker, timestamp, and text
            if current_speaker and current_timestamp and buffer_text:
                utterances.append({
                    "id": f"u{utterance_counter:03}",
                    "speaker": current_speaker,
                    "timestamp": current_timestamp,
                    "text": buffer_text,
                    "codes": []
                })
                utterance_counter += 1
                buffer_text = ""

            i += 1

        parsed_documents.append({
            "doc_id": doc_id,
            "filename": file.name,
            "utterances": utterances
        })

    return parsed_documents


def extract_json_from_claude_response(text: str):
    """
    Robustly extract and sanitize a JSON array from a chatty LLM response.
    Handles:
      - prose before/after the JSON
      - fenced ```json ... ``` blocks
      - smart quotes/dashes & NBSP
      - known model glitches like "tonic'-'clonic"
      - trailing commas before } or ]
    Returns: list (the parsed JSON array)
    Raises: ValueError with helpful context if parsing still fails
    """
    if not text:
        raise ValueError("Empty or None Claude response text")

    original = text

    # 1) Prefer a fenced ```json ... ``` block if present
    m = re.search(r"```json\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        text = m.group(1).strip()
    else:
        # 2) Otherwise, trim to just the outermost JSON array
        start = text.find('[')
        end = text.rfind(']')
        if start != -1 and end != -1 and end > start:
            text = text[start:end+1].strip()

    # 3) Normalize unicode punctuation (curly quotes, em/en dashes, NBSP)
    text = unicodedata.normalize("NFKC", text)
    text = (text
            .replace('\u2018', "'").replace('\u2019', "'")     # ‘ ’ -> '
            .replace('\u201C', '"').replace('\u201D', '"')     # “ ” -> "
            .replace('\u2013', '-').replace('\u2014', '-')     # – — -> -
            .replace('\u00A0', ' ')                            # NBSP -> space
            )

    # 4) Known harmless fixes
    text = text.replace("tonic'-'clonic", "tonic-clonic")
    text = re.sub(r"(?i)tonic'\-?'clonic", "tonic-clonic", text)

    # 5) Remove trailing commas before } or ]
    text = re.sub(r",(\s*[\]}])", r"\1", text)

    # 6) If the whole thing is already valid JSON, great
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        else:
            raise ValueError("Extracted JSON is not a list")
    except json.JSONDecodeError as e:
        # 7) Last resort: try extracting the first JSON-looking array via regex
        m2 = re.search(r"\[\s*{[\s\S]*?}\s*\]", text)
        if m2:
            # re-apply trailing comma fix
            candidate = re.sub(r",(\s*[\]}])", r"\1", m2.group())
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass

        # Give a useful error with a short sanitized preview
        preview = text[:600] + ("..." if len(text) > 600 else "")
        raise ValueError(
            f"Could not parse sanitized JSON. Original error: {e}. "
            f"Sanitized preview:\n{preview}"
        )
