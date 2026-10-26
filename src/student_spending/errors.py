"""Exceptions that represent expected pipeline failures."""


class PipelineError(Exception):
    """Base class for failures the pipeline can explain to a user."""


class ExtractionError(PipelineError):
    """An input file is missing, empty, or structurally invalid."""


class QualityFailure(PipelineError):
    """A critical data quality check failed."""
