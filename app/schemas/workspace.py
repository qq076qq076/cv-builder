from enum import Enum


class WorkspaceStatus(str, Enum):
    NO_WORKSPACE = "no_workspace"
    EMPTY_WORKSPACE = "empty_workspace"
    HAS_CAREER_DATA = "has_career_data"
    HAS_GENERATED_OUTPUTS = "has_generated_outputs"

