"""
Copyright 2025 The Flame Authors.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
    http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import base64
import json
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import bson
import cloudpickle
import pyarrow as pa
import pyarrow.flight as flight

from flamepy.core.types import FlameClientCache, FlameClientTls, FlameContext

Deserializer = Callable[[Any, List[Any]], Any]


@dataclass
class ObjectRef:
    """Object reference for remote cached objects."""

    endpoint: str  # Cache server endpoint (e.g., "grpc://127.0.0.1:9090")
    key: str  # Object key in format "session_id/object_id"
    version: int = 0

    def encode(self) -> bytes:
        data = asdict(self)
        return bson.encode(data)

    @classmethod
    def decode(cls, json_data: bytes) -> "ObjectRef":
        data = bson.decode(json_data)
        return cls(**data)


def _serialize_object(obj: Any) -> pa.RecordBatch:
    """Serialize a Python object to an Arrow RecordBatch.

    Args:
        obj: The object to serialize

    Returns:
        RecordBatch with schema {version: uint64, data: binary}
    """
    # Serialize the object using cloudpickle
    data_bytes = cloudpickle.dumps(obj, protocol=cloudpickle.DEFAULT_PROTOCOL)

    # Create Arrow schema
    schema = pa.schema(
        [
            pa.field("version", pa.uint64()),
            pa.field("data", pa.binary()),
        ]
    )

    # Create RecordBatch
    version_array = pa.array([0], type=pa.uint64())
    data_array = pa.array([data_bytes], type=pa.binary())

    batch = pa.RecordBatch.from_arrays([version_array, data_array], schema=schema)

    return batch


def _deserialize_object(batch: pa.RecordBatch) -> Any:
    """Deserialize a Python object from an Arrow RecordBatch.

    Args:
        batch: RecordBatch with schema {version: uint64, data: binary}

    Returns:
        The deserialized object
    """
    # Extract data from the batch
    data_array = batch.column("data")
    data_bytes = data_array[0].as_py()

    # Deserialize using cloudpickle
    return cloudpickle.loads(data_bytes)


_client_pool: Dict[str, flight.FlightClient] = {}
_client_pool_lock = threading.Lock()


def _get_flight_client(endpoint: str, tls_config: Optional[FlameClientTls] = None) -> flight.FlightClient:
    if endpoint.startswith("grpcs://"):
        location = endpoint.replace("grpcs://", "grpc+tls://")
    else:
        location = endpoint

    with _client_pool_lock:
        if location in _client_pool:
            return _client_pool[location]

        if location.startswith("grpc+tls://"):
            if tls_config and tls_config.ca_file:
                with open(tls_config.ca_file, "rb") as f:
                    root_certs = f.read()
                client = flight.FlightClient(location, tls_root_certs=root_certs)
            else:
                client = flight.FlightClient(location)
        else:
            client = flight.FlightClient(location)

        _client_pool[location] = client
        return client


def _do_put_remote(client: flight.FlightClient, descriptor: flight.FlightDescriptor, batch: pa.RecordBatch) -> "ObjectRef":
    """Perform a remote do_put operation and read the result metadata.

    Args:
        client: Arrow Flight client
        descriptor: Flight descriptor for the put operation
        batch: RecordBatch to upload

    Returns:
        ObjectRef received from the server

    Raises:
        ValueError: If metadata cannot be read from server
    """
    writer, reader = client.do_put(descriptor, batch.schema)

    # Write batch
    writer.write_batch(batch)

    # Signal we're done writing
    writer.done_writing()

    # Read result metadata from PutResult stream before closing
    # Read metadata messages using read() method (returns Buffer/bytes)
    try:
        while True:
            metadata_buffer = reader.read()
            if metadata_buffer is None:
                break
            # Extract ObjectRef from metadata buffer (BSON format)
            obj_ref_data = bson.decode(bytes(metadata_buffer))
            writer.close()
            return ObjectRef(
                endpoint=obj_ref_data["endpoint"],
                key=obj_ref_data["key"],
                version=obj_ref_data["version"],
            )
    except Exception as e:
        writer.close()
        raise ValueError(f"Failed to read metadata from cache server: {e}")

    # If we get here, no PutResult was received
    writer.close()
    raise ValueError("No result metadata received from cache server")


def _get_cache_tls_config() -> Optional[FlameClientTls]:
    """Get TLS configuration for cache from FlameContext.

    FlameContext automatically handles:
    1. Loading from ~/.flame/flame.yaml if it exists
    2. Building from environment variables (FLAME_CA_FILE, etc.) if no config file

    Returns:
        FlameClientTls if configured, None otherwise
    """
    try:
        context = FlameContext()
        cache_config = context.cache
        if isinstance(cache_config, FlameClientCache) and cache_config.tls:
            return cache_config.tls
    except Exception:
        pass
    return None


def put_object(session_id: str, obj: Any) -> "ObjectRef":
    """Put an object into the cache.

    Args:
        session_id: The session ID for the object
        obj: The object to cache (will be pickled)

    Returns:
        ObjectRef pointing to the cached object

    Raises:
        Exception: If cache endpoint is not configured or request fails
    """
    context = FlameContext()
    cache_config = context.cache

    if cache_config is None:
        raise ValueError("Cache configuration not found")

    # Get endpoint, storage, and TLS config from cache config
    if isinstance(cache_config, str):
        # Legacy format - just endpoint string
        cache_endpoint = cache_config
        cache_storage = None
        cache_tls = None
    elif isinstance(cache_config, FlameClientCache):
        # New format - FlameClientCache dataclass
        cache_endpoint = cache_config.endpoint
        cache_storage = cache_config.storage
        cache_tls = cache_config.tls
    else:
        # Dict format (for backward compatibility)
        cache_endpoint = cache_config.get("endpoint")
        cache_storage = cache_config.get("storage")
        cache_tls = None

    if not cache_endpoint:
        raise ValueError("Cache endpoint not configured")

    # Serialize object to Arrow RecordBatch
    batch = _serialize_object(obj)

    # Check if local storage is configured and accessible
    if cache_storage:
        storage_path = Path(cache_storage)
        # Only use local storage if the path exists or can be created
        try:
            storage_path.mkdir(parents=True, exist_ok=True)
            use_local_storage = storage_path.exists() and storage_path.is_dir()
        except (PermissionError, OSError):
            # Path not accessible, fall back to remote cache
            use_local_storage = False
    else:
        use_local_storage = False

    if use_local_storage:
        # Write to local storage (optimization when client has access to cache filesystem)
        object_id = str(uuid.uuid4())
        key = f"{session_id}/{object_id}"

        # Create session directory
        session_dir = storage_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Write Arrow IPC file
        object_path = session_dir / f"{object_id}.arrow"
        writer = pa.ipc.new_file(object_path, batch.schema)
        writer.write_batch(batch)
        writer.close()

        # Get flight info to construct ObjectRef with cache server's endpoint
        client = _get_flight_client(cache_endpoint, cache_tls)
        descriptor = flight.FlightDescriptor.for_path(key)
        flight_info = client.get_flight_info(descriptor)

        # Extract endpoint from flight info
        if flight_info.endpoints:
            remote_endpoint = flight_info.endpoints[0].locations[0]
            # Extract URI string from Location object
            endpoint_str = remote_endpoint.uri.decode("utf-8") if isinstance(remote_endpoint.uri, bytes) else str(remote_endpoint.uri)
        else:
            endpoint_str = cache_endpoint

        return ObjectRef(endpoint=endpoint_str, key=key, version=0)
    else:
        # Use remote cache via Arrow Flight
        client = _get_flight_client(cache_endpoint, cache_tls)

        # Encode session_id in FlightDescriptor path
        upload_descriptor = flight.FlightDescriptor.for_path(session_id)
        return _do_put_remote(client, upload_descriptor, batch)


def get_object(ref: ObjectRef, deserializer: Optional[Deserializer] = None) -> Any:
    """Get an object from the cache.

    Args:
        ref: ObjectRef pointing to the cached object
        deserializer: Optional function to combine base and deltas.
            Signature: (base: Any, deltas: List[Any]) -> Any
            If None, returns just the base object (backward compatible).

    Returns:
        The deserialized object. If deserializer is provided, returns
        deserializer(base, deltas). Otherwise returns the base object.

    Raises:
        Exception: If request fails
    """
    tls_config = _get_cache_tls_config()
    client = _get_flight_client(ref.endpoint, tls_config)
    ticket = flight.Ticket(ref.key.encode())
    reader = client.do_get(ticket)

    table = reader.read_all()
    if table.num_rows == 0:
        raise ValueError(f"No data received for object {ref.key}")

    batches = table.to_batches()
    base = _deserialize_object(batches[0])

    if deserializer is None:
        return base

    deltas: List[Any] = []
    for batch in batches[1:]:
        deltas.append(_deserialize_object(batch))

    return deserializer(base, deltas)


def update_object(ref: ObjectRef, new_obj: Any) -> "ObjectRef":
    """Update an object in the cache.

    This replaces the entire object (base + all deltas) with the new object as base.

    Args:
        ref: ObjectRef pointing to the cached object to update
        new_obj: The new object to store (will be pickled)

    Returns:
        Updated ObjectRef (same as input for now, since version is always 0)

    Raises:
        Exception: If request fails
    """
    # Serialize new object to Arrow RecordBatch
    batch = _serialize_object(new_obj)

    # Connect to cache server
    tls_config = _get_cache_tls_config()
    client = _get_flight_client(ref.endpoint, tls_config)

    # Parse key to validate format
    parts = ref.key.split("/")
    if len(parts) != 2:
        raise ValueError(f"Invalid key format: {ref.key}")

    # Use full key (session_id/object_id) in FlightDescriptor to update existing object
    upload_descriptor = flight.FlightDescriptor.for_path(ref.key)
    return _do_put_remote(client, upload_descriptor, batch)


def patch_object(ref: ObjectRef, delta: Any) -> "ObjectRef":
    """Append delta data to an existing cached object.

    This appends the delta to the object's delta list without modifying the base.
    The delta will be included in subsequent get_object() calls.

    Args:
        ref: ObjectRef pointing to the cached object to patch
        delta: The delta data to append (will be pickled)

    Returns:
        Updated ObjectRef (same key, potentially updated metadata)

    Raises:
        ValueError: If the object doesn't exist (must put first)
        Exception: If request fails
    """
    # Serialize delta to bytes using cloudpickle
    delta_bytes = cloudpickle.dumps(delta, protocol=cloudpickle.DEFAULT_PROTOCOL)

    # Connect to cache server
    tls_config = _get_cache_tls_config()
    client = _get_flight_client(ref.endpoint, tls_config)

    # Encode action body: {key}:{base64(delta_bytes)}
    delta_b64 = base64.b64encode(delta_bytes).decode("utf-8")
    action_body = f"{ref.key}:{delta_b64}"

    # Call do_action with action type "PATCH"
    action = flight.Action("PATCH", action_body.encode("utf-8"))

    # Execute action and get result
    results = list(client.do_action(action))

    if not results:
        raise ValueError("No result received from PATCH action")

    # Parse response to get updated ObjectMetadata
    result_body = results[0].body.to_pybytes().decode("utf-8")
    metadata = json.loads(result_body)

    # Return ObjectRef with same key
    return ObjectRef(
        endpoint=metadata.get("endpoint", ref.endpoint),
        key=metadata.get("key", ref.key),
        version=metadata.get("version", ref.version),
    )
