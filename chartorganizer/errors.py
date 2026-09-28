class ChartOrganizerError(Exception):
    """User-actionable application error."""


class ValidationError(ChartOrganizerError):
    pass


class AmbiguousMatchError(ChartOrganizerError):
    pass
