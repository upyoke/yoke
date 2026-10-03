"""Shared wait budgets for systemd user service operations."""

# Mutations include graceful shutdown while a relay finishes an in-flight poll.
SERVICE_OPERATION_TIMEOUT_SECONDS = 180
SERVICE_QUERY_TIMEOUT_SECONDS = 30
