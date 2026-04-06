"""
Classifies a job description into one of 4 tracks and returns
the path to the correct base resume.
"""

import os
import json
import anthropic
from rich.console import Console

console = Console()

FIELDS = {
    "data_science":     "Data Science / Data Engineering",
    "ml_ai":            "Machine Learning / AI",
    "software_eng":     "Software Engineering / Developer",
    "neuroscience":     "Neuroscience Research",
}

BASE_RESUME_PATHS = {
    "data_science":  "resumes/base/data_science.md",
    "ml_ai":         "resumes/base/ml_ai.md",
    "software_eng":  "resumes/base/software_eng.md",
    "neuroscience":  "resumes/base/neuroscience.md",
}


def classify_field(job_description: str, role: str, company: str) -> tuple[str, str]:
    """
    Uses Claude to classify the job into one of 4 fields.
    Returns (field_key, field_label).
    e.g. ("ml_ai", "Machine Learning / AI")
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    prompt = f"""Classify this job into exactly ONE of these 4 categories:

1. data_science     — Data Scientist, Data Analyst, Data Engineer, Analytics Engineer, BI Engineer
2. ml_ai            — ML Engineer, AI Engineer, Research Scientist (ML), NLP/CV Engineer, MLOps, LLM roles
3. software_eng     — Software Engineer, Backend, Full-Stack, Frontend, Platform, Infrastructure, DevOps, Mobile
4. neuroscience     — Neuroscience Researcher, Research Assistant/Associate, Computational Neuroscience, Cognitive Science research roles

Job: {role} at {company}

Job Description (first 1500 chars):
{job_description[:1500]}

Rules:
- If it's a hybrid (e.g. "ML + SWE"), pick the PRIMARY emphasis
- If it involves building ML models/systems → ml_ai
- If it involves data pipelines/analysis without model training → data_science
- If it involves neuro research in a lab/academic context → neuroscience
- Otherwise → software_eng

Respond with ONLY a JSON object, nothing else:
{{"field": "one_of_the_four_keys", "confidence": "high|medium|low", "reason": "one sentence"}}"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()
    try:
        result = json.loads(raw)
        field_key = result.get("field", "software_eng")
        if field_key not in FIELDS:
            field_key = "software_eng"
        label = FIELDS[field_key]
        console.print(f"[dim]Field: [bold]{label}[/bold] (confidence: {result.get('confidence', '?')}) — {result.get('reason', '')}[/dim]")
        return field_key, label
    except Exception:
        # Fallback: keyword match
        return _keyword_classify(job_description, role)


def _keyword_classify(job_description: str, role: str) -> tuple[str, str]:
    """Fallback keyword-based classifier if Claude call fails."""
    text = (job_description + " " + role).lower()

    neuro_keywords = ["neuroscience", "neuroscientist", "fmri", "eeg", "electrophysiology",
                      "cognitive science", "brain", "neural circuit", "rodent", "patch clamp"]
    ml_keywords = ["machine learning", "deep learning", "pytorch", "tensorflow", "llm",
                   "nlp", "computer vision", "model training", "mlops", "ai engineer",
                   "research scientist", "huggingface", "fine-tun"]
    ds_keywords = ["data scientist", "data engineer", "data analyst", "etl", "pipeline",
                   "sql", "spark", "dbt", "airflow", "analytics", "bi engineer", "tableau"]

    if any(k in text for k in neuro_keywords):
        return "neuroscience", FIELDS["neuroscience"]
    if any(k in text for k in ml_keywords):
        return "ml_ai", FIELDS["ml_ai"]
    if any(k in text for k in ds_keywords):
        return "data_science", FIELDS["data_science"]
    return "software_eng", FIELDS["software_eng"]


def get_base_resume_path(field_key: str) -> str:
    """Returns the relative path to the base resume for a given field."""
    return BASE_RESUME_PATHS.get(field_key, BASE_RESUME_PATHS["software_eng"])
