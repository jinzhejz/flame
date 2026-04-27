"""
Protobuf generated files module.

This module contains auto-generated protobuf files that should not be manually edited.

Import order matters: types_pb2 must be loaded before frontend_pb2 and shim_pb2
because they depend on types.proto being in the descriptor pool.
"""

# isort: skip_file
# ruff: noqa: I001

from flamepy.proto import types_pb2  # noqa: F401 - Must be imported first
from flamepy.proto import frontend_pb2  # noqa: F401
from flamepy.proto import shim_pb2  # noqa: F401
