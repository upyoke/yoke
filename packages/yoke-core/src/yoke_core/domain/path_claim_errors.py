"""Domain failures shared by path claim lifecycle and amendment surfaces."""


class PathClaimError(Exception):
    """Base class for path-claim domain failures."""


class InvalidActor(PathClaimError): ...


class InvalidMode(PathClaimError): ...


class InvalidTargetSet(PathClaimError): ...


class IncompatibleOverlap(PathClaimError): ...


class UpstreamNotReleased(PathClaimError): ...


class ClaimNotFound(PathClaimError): ...


class IllegalTransition(PathClaimError): ...


class InvalidWorkflowBinding(PathClaimError): ...
