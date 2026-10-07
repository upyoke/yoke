"""Typed domain verdicts, distinct from defects reaching or reading state."""


class DomainRefusal(Exception):
    """A driver read its domain state and refused the requested operation.

    Schema, import, transport implementation, and database-read defects do
    not inherit this type. Rehearsals can accept a domain verdict without
    hiding a broken driver or claiming the refused operation could execute.
    """
