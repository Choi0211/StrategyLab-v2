"""gaon.control - isolated Trading Mode Controller development modules.

No production wiring. Web / Gaon / the Binance bot are meant to read the
canonical read model here rather than keep their own mode state; the
adapters (service manager, credential provider) are interfaces with fake
implementations for tests only.
"""
