"""All tunable settings in one place. Every value can be overridden with an environment variable."""
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _env(name, default):
    return os.getenv(f"MICHAEL_{name}", default)


@dataclass
class Settings:
    # models
    ollama_url: str = _env("OLLAMA_URL", "http://localhost:11434")
    llm_model: str = _env("LLM", "qwen2.5:7b")    # repairs, flashcards: careful rewriting against the evidence
    # drafts (default: same as llm_model). qwen2.5:3b drafts gave more verified sentences on the 14 baseline notes
    # (6.3 vs 4.8 per note, 96.6% vs 94.0% correct), but 3b drafts + 7b repairs was SLOWER end to end on a 15 GB
    # laptop (more repair rounds, both models in memory). See Decisions 18 Oct.
    writer_model: str = _env("WRITER", "")
    writer_style: str = _env("WRITER_STYLE", "")      # "extractive": one passage sentence per draft sentence (experiment)
    quote_repair: bool = _env("QUOTE_REPAIR", "1") == "1"   # repair against the closest quote (gate: lost 17.3% -> 16.2%, strict 93.8 -> 94.4%, 0 wrong)
    # drafts as "p3 | sentence" lines instead of JSON: measured 24 Oct, no saving per sentence (35 vs 36 tokens), and
    # without the schema's minimum the 7B wrote 4 sentences instead of 8 -> off
    compact_writer: bool = _env("COMPACT_WRITER", "0") == "1"
    # repair continues the writer conversation (cached prefix): 39 -> 25 s on one note, 38 -> 38 s on another; off
    repair_in_conversation: bool = _env("REPAIR_IN_CONVERSATION", "0") == "1"
    prefill: bool = _env("PREFILL", "1") == "1"     # writer instructions pre-read during search: 104 -> 87 s reading
    llm_cache: bool = _env("LLM_CACHE", "1") == "1"          # off only for timing runs
    llm_threads: int = int(_env("LLM_THREADS", os.cpu_count() or 4))
    llm_ctx: int = int(_env("LLM_CTX", 6144))
    embed_model: str = _env("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    rerank_model: str = _env("RERANK_MODEL", "BAAI/bge-reranker-base")
    # benchmarked on SciFact (eval/compare_verifiers.py): large-wanli has 99% precision / 41% recall at 0.70,
    # vs 95% / 29% for the base model, at ~3x the cost per pair (quotes are short: a few seconds per note)
    nli_model: str = _env("NLI_MODEL", "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli")

    # storage
    data_dir: Path = Path(_env("DATA_DIR", str(ROOT / "data")))
    vault_path: str | None = _env("VAULT", None)          # your Obsidian vault (optional source)
    notes_dir: Path = Path(_env("NOTES_DIR", str(ROOT / "data" / "notes")))

    # retrieval
    # default search sources; also available: "semanticscholar" (papers), "oeis" (integer sequences)
    sources: tuple = ("wikipedia", "arxiv", "openalex", "stackexchange", "cpalgorithms")
    results_per_source: int = 3
    chunk_chars: int = 900
    candidates: int = 30            # hybrid search → reranker
    keep: int = int(_env("KEEP", 6))   # reranker → writer (fewer passages = faster LLM prompt)
    source_cache_days: int = 7

    # verification
    support_threshold: float = 0.70  # entailment probability for SUPPORTED
    context_threshold: float = 0.90  # ...when the quote only passes together with its whole paragraph
    math_check: bool = _env("MATH_CHECK", "1") == "1"   # formulas + numbers checked symbolically
    math_upgrade: bool = _env("MATH_UPGRADE", "1") == "1"   # PARTIAL + every formula proven equivalent -> SUPPORTED
    decontextualise: bool = _env("DECONTEXTUALISE", "0") == "1"   # retry "It ..." with the cited source's subject
    conflict_check: bool = _env("CONFLICT_CHECK", "0") == "1"     # flag passages from other sources that contradict
    decompose: bool = _env("DECOMPOSE", "1") == "1"               # prove "X does A and B" as "X does A" + "X does B"
    titled_premise: bool = _env("TITLED_PREMISE", "1") == "1"     # retry failures with "Title - Section:" before the quote
    semantic_windows: bool = _env("SEMANTIC_WINDOWS", "1") == "1"   # rank quote windows by meaning too
    partial_threshold: float = 0.40  # entailment probability for PARTIAL
    max_repair_rounds: int = 1
    rescue_k: int = int(_env("RESCUE_K", 6))   # claim-driven retrieval: passages per failing sentence (6: +1 correct vs 3, 0 wrong)
    cascade_cut: float = float(_env("CASCADE_CUT", 0))   # >0: small NLI screens, large judges pairs above this
    early_exit: bool = _env("EARLY_EXIT", "0") == "1"   # score the closest quote window first; full set only on failure
    near_verbatim: bool = _env("NEAR_VERBATIM", "0") == "1"      # accept PARTIAL >= min when the sentence ~= its quote
    near_verbatim_min: float = float(_env("NEAR_VERBATIM_MIN", 0.5))
    near_verbatim_overlap: int = int(_env("NEAR_VERBATIM_OVERLAP", 90))
    two_quotes: bool = _env("TWO_QUOTES", "1") == "1"   # 2 closest separate windows joined, needs the 0.90 context bar (gate: lost 16.8% -> 15.1%, 0 wrong)
    nightly_hour: int = int(_env("NIGHTLY_HOUR", 2))   # scheduler: re-index, re-check citations, new key points

    # articles
    pandoc: str = _env("PANDOC", shutil.which("pandoc") or str(Path(os.getenv("LOCALAPPDATA", "")) / "Pandoc" / "pandoc.exe"))
    sources_folder: str = _env("SOURCES_FOLDER", "Sources")     # vault folder for saved articles
    notes_folder: str = _env("NOTES_FOLDER", "Michael")         # vault folder for Michael's notes

    contact: str = _env("CONTACT", "michael-research@example.com")   # set MICHAEL_CONTACT to your e-mail

    @property
    def user_agent(self) -> str:   # Wikipedia and OpenAlex ask for a contact in the User-Agent
        return f"MichaelResearchAgent/0.1 (student project; mailto:{self.contact})"

    extra: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "michael.db"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.notes_dir.mkdir(parents=True, exist_ok=True)
