"""AC compliance reference for S32 Transport Abstraction (AC-32.01–32.10).

All 10 ACs are fully covered in:
    tests/unit/transport/test_transport.py

AC-32.01  EventBus accepts subscriber registration without error
AC-32.02  EventBus dispatches events to all registered subscribers
AC-32.03  EventBus handles empty subscriber list without error
AC-32.04  EventBus delivers events in registration order
AC-32.05  EventBus supports wildcard / multi-type subscriptions
AC-32.06  EventBus raises on duplicate subscriber registration
AC-32.07  EventBus removes subscriber via unsubscribe
AC-32.08  EventBus isolates per-universe event streams
AC-32.09  EventBus propagates subscriber exceptions as TransportError
AC-32.10  InMemoryEventBus satisfies the EventBus Protocol

No additional test functions are needed in this file.
"""
