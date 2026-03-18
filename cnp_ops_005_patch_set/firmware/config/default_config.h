#pragma once

#define CNP_PROTOCOL_VERSION "CNPv1"
#define DEFAULT_WIFI_CONNECT_TIMEOUT_MS 20000
#define DEFAULT_MQTT_PORT 1883
#define DEFAULT_HEARTBEAT_INTERVAL_SEC 60
#define DEFAULT_TELEMETRY_INTERVAL_SEC 60
#define DEFAULT_OFFLINE_AFTER_SEC 180
#define DEFAULT_EVENT_QUEUE_SIZE 16
#define DEFAULT_MQTT_QOS 1
#define DEFAULT_RECONNECT_BACKOFF_MS 5000
#define DEFAULT_OTA_ENABLED true
#define DEFAULT_COMMAND_TIMEOUT_MS 15000

#define TOPIC_HELLO_FMT "cnp/v1/nodes/%s/hello"
#define TOPIC_HEARTBEAT_FMT "cnp/v1/nodes/%s/heartbeat"
#define TOPIC_STATE_FMT "cnp/v1/nodes/%s/state"
#define TOPIC_EVENT_FMT "cnp/v1/nodes/%s/events"
#define TOPIC_ERROR_FMT "cnp/v1/nodes/%s/errors"
#define TOPIC_ACK_FMT "cnp/v1/nodes/%s/ack"
#define TOPIC_CMD_IN_FMT "cnp/v1/nodes/%s/cmd/in"
#define TOPIC_CMD_OUT_FMT "cnp/v1/nodes/%s/cmd/out"
#define TOPIC_CONFIG_FMT "cnp/v1/nodes/%s/config"
