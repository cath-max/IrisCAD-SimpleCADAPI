"""API retrieval: select exactly RETRIEVE_TOP_K practical docs for an agent."""

from .catalog_io import default_catalog_path, load_catalog
from .load_md import format_api_prompt_slice
from .merge import (
    merge_core_and_ranked,
    merge_core_with_catalog_ranked_rows,
    select_core_hits,
    sort_hits_by_score,
)
from .retrieve import ApiRetriever, retrieve_apis
from .types import RETRIEVE_TOP_K, ApiHit, hit_from_catalog_row

__all__ = [
    "ApiHit",
    "ApiRetriever",
    "RETRIEVE_TOP_K",
    "default_catalog_path",
    "format_api_prompt_slice",
    "hit_from_catalog_row",
    "load_catalog",
    "merge_core_and_ranked",
    "merge_core_with_catalog_ranked_rows",
    "retrieve_apis",
    "select_core_hits",
    "sort_hits_by_score",
]
