"""Service layer for dbt_feature_lineage."""

from .model_analysis_service import inspect_model

__all__ = ["inspect_model"]
