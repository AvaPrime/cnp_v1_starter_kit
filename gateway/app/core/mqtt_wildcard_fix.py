"""
gateway/app/core/mqtt_client.py — excerpt showing the P0-08 wildcard fix only.
Replace the subscription line in the full file.

AUDIT FIX P0-08 (HIGH): MQTT wildcard was cnp/v1/nodes/+/+ which only matches
topics with exactly ONE segment after the node_id. Multi-level topics like
cnp/v1/nodes/{node_id}/cmd/out were silently dropped.

Fix: use # (multi-level wildcard) → cnp/v1/nodes/+/#
This matches: hello, heartbeat, events, errors, ack, cmd/in, cmd/out, state, etc.
"""

# In GatewayMqttBridge._run(), change:
#
#   BEFORE (broken):
#     subscription = "cnp/v1/nodes/+/+"
#
#   AFTER (fixed):
#     subscription = "cnp/v1/nodes/+/#"
#
# Also update the filtered_messages call to match:
#
#   BEFORE:
#     async with client.filtered_messages("cnp/v1/nodes/+/+") as messages:
#         await client.subscribe("cnp/v1/nodes/+/+", qos=1)
#
#   AFTER:
#     async with client.filtered_messages("cnp/v1/nodes/+/#") as messages:
#         await client.subscribe("cnp/v1/nodes/+/#", qos=1)

MQTT_SUBSCRIPTION = "cnp/v1/nodes/+/#"
