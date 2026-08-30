from __future__ import annotations

import os
from importlib import import_module
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _as_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    engine_mode: str
    crawler_path: Path
    selector_path: Path
    crawler_device: str
    selector_device: str
    selector_batch_size: int
    selector_threshold: float
    preload_models: bool
    prompts_path: Path
    paper_id_path: Path
    paper_db_path: Path
    title_index_path: Path
    max_workers: int
    threads_num: int
    expand_refs_per_paper: int
    local_search_papers: int
    cors_origins: tuple[str, ...]
    mock_step_delay: float
    debug: bool
    internal_token: str
    analysis_enabled: bool
    analysis_top_n: int
    analysis_pair_limit: int
    analysis_batch_size: int
    analysis_abstract_chars: int
    analysis_cache_max_entries: int
    query_planning_enabled: bool
    query_planning_timeout: int
    query_planning_cache_max_entries: int
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str

    @property
    def is_mock(self) -> bool:
        return self.engine_mode == "mock"

    def readiness(self) -> tuple[bool, list[str]]:
        if self.is_mock:
            return True, []
        if self.engine_mode != "production":
            return False, ["PASA_ENGINE_MODE 必须为 production 或 mock"]

        missing: list[str] = []
        for label, path in (
            ("Crawler 模型", self.crawler_path),
            ("Selector 模型", self.selector_path),
            ("提示词", self.prompts_path),
            ("论文 ID 索引", self.paper_id_path),
            ("论文数据库", self.paper_db_path),
        ):
            if not path.exists():
                missing.append(f"{label}不存在: {path}")
        if not os.getenv("SERPER_API_KEY"):
            missing.append("未设置 SERPER_API_KEY")
        if not os.getenv("OPENALEX_API_KEY"):
            missing.append("未设置 OPENALEX_API_KEY")
        if not self.internal_token:
            missing.append("生产模式必须设置 PASA_INTERNAL_TOKEN")
        modules: dict[str, object] = {}
        for module_name, label in (
            ("torch", "PyTorch"),
            ("transformers", "Transformers"),
            ("accelerate", "Accelerate"),
            ("arxiv", "arXiv Python SDK"),
            ("bs4", "BeautifulSoup"),
            ("lxml", "lxml"),
        ):
            try:
                modules[module_name] = import_module(module_name)
            except (ImportError, OSError) as exc:
                missing.append(f"缺少 Python 依赖: {label}")
        transformers_module = modules.get("transformers")
        if transformers_module is not None and not all(
            hasattr(transformers_module, name)
            for name in ("AutoModelForCausalLM", "AutoTokenizer")
        ):
            missing.append("Transformers 安装不完整或未安装仓库定制版本")
        torch_module = modules.get("torch")
        if torch_module is not None and not torch_module.cuda.is_available():
            missing.append("PyTorch 无法使用 CUDA GPU")
        return not missing, missing


def _path_from_env(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default)).expanduser()
    return value if value.is_absolute() else PROJECT_ROOT / value


def get_settings() -> Settings:
    origins = tuple(
        item.strip()
        for item in os.getenv("PASA_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
        if item.strip()
    )
    try:
        mock_step_delay = max(0.0, float(os.getenv("PASA_MOCK_STEP_DELAY", "0.15")))
    except ValueError:
        mock_step_delay = 0.15

    return Settings(
        app_name="PaSa Model Service",
        app_env=os.getenv("PASA_APP_ENV", "development"),
        engine_mode=os.getenv("PASA_ENGINE_MODE", "production").strip().lower(),
        crawler_path=_path_from_env("PASA_CRAWLER_PATH", "checkpoints/pasa-7b-crawler"),
        selector_path=_path_from_env("PASA_SELECTOR_PATH", "checkpoints/pasa-7b-selector"),
        crawler_device=os.getenv("PASA_CRAWLER_DEVICE", "auto").strip() or "auto",
        selector_device=os.getenv("PASA_SELECTOR_DEVICE", "auto").strip() or "auto",
        selector_batch_size=max(1, _as_int("PASA_SELECTOR_BATCH_SIZE", 8)),
        selector_threshold=min(1.0, max(0.0, _as_float("PASA_SELECTOR_THRESHOLD", 0.5))),
        preload_models=_as_bool(os.getenv("PASA_PRELOAD_MODELS"), False),
        prompts_path=_path_from_env("PASA_PROMPTS_PATH", "agent_prompt.json"),
        paper_id_path=_path_from_env("PASA_PAPER_ID_PATH", "data/paper_database/id2paper.json"),
        paper_db_path=_path_from_env("PASA_PAPER_DB_PATH", "data/paper_database/cs_paper_2nd.zip"),
        title_index_path=_path_from_env(
            "PASA_TITLE_INDEX_PATH", "data/paper_database/title_index.sqlite3"
        ),
        max_workers=max(1, _as_int("PASA_MAX_WORKERS", 1)),
        threads_num=max(1, _as_int("PASA_THREADS_NUM", 20)),
        expand_refs_per_paper=max(1, _as_int("PASA_EXPAND_REFS_PER_PAPER", 12)),
        local_search_papers=max(0, _as_int("PASA_LOCAL_SEARCH_PAPERS", 20)),
        cors_origins=origins,
        mock_step_delay=mock_step_delay,
        debug=_as_bool(os.getenv("PASA_DEBUG")),
        internal_token=os.getenv("PASA_INTERNAL_TOKEN", ""),
        analysis_enabled=_as_bool(os.getenv("PASA_ANALYSIS_ENABLED"), True),
        analysis_top_n=max(1, _as_int("PASA_ANALYSIS_TOP_N", 6)),
        analysis_pair_limit=max(1, _as_int("PASA_ANALYSIS_PAIR_LIMIT", 15)),
        analysis_batch_size=max(1, _as_int("PASA_ANALYSIS_BATCH_SIZE", 5)),
        analysis_abstract_chars=max(300, _as_int("PASA_ANALYSIS_ABSTRACT_CHARS", 1600)),
        analysis_cache_max_entries=max(1, _as_int("PASA_ANALYSIS_CACHE_MAX_ENTRIES", 100)),
        query_planning_enabled=_as_bool(os.getenv("PASA_QUERY_PLANNING_ENABLED"), True),
        query_planning_timeout=max(2, _as_int("PASA_QUERY_PLANNING_TIMEOUT", 8)),
        query_planning_cache_max_entries=max(1, _as_int("PASA_QUERY_PLANNING_CACHE_MAX_ENTRIES", 200)),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip(),
    )
