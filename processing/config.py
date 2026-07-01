import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "Data"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-west-2")

# Optional PHI detection guardrail. Set by the CDK stack on the Fargate worker;
# unset for local/Streamlit runs, in which case no guardrail is applied.
BEDROCK_GUARDRAIL_ID = os.environ.get("BEDROCK_GUARDRAIL_ID")
BEDROCK_GUARDRAIL_VERSION = os.environ.get("BEDROCK_GUARDRAIL_VERSION")

MAX_TOTAL_TOKENS = 30000
TRANSCRIPT_TOKEN_BUDGET = 5000
ASYNC_CONCURRENT_REQUESTS = 15
MAX_CONCURRENT_CALLS = 100
DEFAULT_TEST_CONCURRENCY = 3

CODEBOOK_WITH_NOTES_CSV = DATA_DIR / "codebook_with_notes.csv"
CODEBOOK_HIERARCHY_CSV = DATA_DIR / "codebook_hierarchy.csv"
CODEBOOK_CSV = CODEBOOK_HIERARCHY_CSV

GENERIC_PROMPT_FILE = "generic_notes_focused_prompt.txt"
GROUP_PROMPT_PATTERN = "{group}_prompt.txt"

CODE_GROUPS = {
    "disease_concepts": {
        "name": "Disease Concepts",
        "id_range": (10, 261),
        "prompt_file": "disease_concepts_prompt.txt",
    },
    "individual_impacts": {
        "name": "Individual Impacts",
        "id_range": (262, 317),
        "prompt_file": "individual_impacts_prompt.txt",
    },
    "caregiver_impacts": {
        "name": "Caregiver Impacts",
        "id_range": (318, 375),
        "prompt_file": "caregiver_impacts_prompt.txt",
    },
    "modifying_factors": {
        "name": "Modifying Factors",
        "id_range": (377, 414),
        "prompt_file": "modifying_factors_prompt.txt",
    },
    "medical_interventions": {
        "name": "Medical Interventions",
        "id_range": (415, 544),
        "prompt_file": "medical_interventions_prompt.txt",
    },
}

ENABLE_EXTENDED_THINKING = False
THINKING_BUDGET_TOKENS = 10000
TEMPERATURE = 0
MAX_READ_TIMEOUT = 300
NUM_PASSES = 2


def get_concurrency_limit():
    return int(os.environ.get("CONCURRENCY", DEFAULT_TEST_CONCURRENCY))


def get_codebook_path():
    return str(CODEBOOK_CSV)


def get_prompt_file_for_group(group_name):
    group_config = CODE_GROUPS.get(group_name, {})
    return group_config.get("prompt_file", GENERIC_PROMPT_FILE)
