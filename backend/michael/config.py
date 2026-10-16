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
    llm_model: str = _env("LLM", "qwen2.5:7b")    # writes clearly better notes than 3b; ~2x slower on CPU
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
    keep: int = 6                   # reranker → writer (fewer passages = faster LLM prompt)
    source_cache_days: int = 7

    # verification
    support_threshold: float = 0.70  # entailment probability for SUPPORTED
    context_threshold: float = 0.90  # ...when the quote only passes together with its whole paragraph
    semantic_windows: bool = _env("SEMANTIC_WINDOWS", "1") == "1"   # rank quote windows by meaning too
    partial_threshold: float = 0.40  # entailment probability for PARTIAL
    max_repair_rounds: int = 1

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
