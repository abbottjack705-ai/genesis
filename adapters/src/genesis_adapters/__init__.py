"""Project Genesis V0.5 slice-1 read-only OddsPapi adapter (design: V05_ADAPTER_ARCHITECTURE.md r3).

This package lives outside every frozen tree. It reads the frozen ``genesis`` package only
through its public API and never opens a network connection except in
``genesis_adapters.oddspapi.transport_http`` (Stage 7, loopback-tested only).
"""
