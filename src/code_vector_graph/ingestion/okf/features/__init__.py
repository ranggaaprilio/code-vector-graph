"""Feature-level documentation: discover business features across a repo's
files and generate/maintain one validated Markdown page per feature, on top
of the existing OKF wiki pipeline (see ``ingestion/okf/``).
"""

from code_vector_graph.ingestion.okf.features.build import build_feature_docs
from code_vector_graph.ingestion.okf.features.models import (
    Entity,
    EntryPoint,
    ExistingFeature,
    FeatureBuildDeps,
    FeatureBuildRequest,
    FeatureBuildResult,
    FeatureDoc,
    FeatureFrontmatter,
    FeatureMap,
    FeaturePage,
    FeatureSpec,
    FileInventory,
    ValidationIssue,
    ValidationResult,
)
from code_vector_graph.ingestion.okf.features.template import (
    REQUIRED_H2,
    compose_page,
    render_feature_markdown,
    split_frontmatter,
)
from code_vector_graph.ingestion.okf.features.validate import validate_feature_body, validate_feature_page

__all__ = [
    "Entity",
    "EntryPoint",
    "ExistingFeature",
    "FeatureBuildDeps",
    "FeatureBuildRequest",
    "FeatureBuildResult",
    "FeatureDoc",
    "FeatureFrontmatter",
    "FeatureMap",
    "FeaturePage",
    "FeatureSpec",
    "FileInventory",
    "ValidationIssue",
    "ValidationResult",
    "REQUIRED_H2",
    "build_feature_docs",
    "compose_page",
    "render_feature_markdown",
    "split_frontmatter",
    "validate_feature_body",
    "validate_feature_page",
]
