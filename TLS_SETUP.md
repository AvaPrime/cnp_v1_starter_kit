# CNP EPIC-02 — P2-01
# TLS Broker Configuration Guide

## Overview

CNP v1 nodes connect to Mosquitto over plain MQTT 1883 in development.
For any pilot or production deployment, TLS must be enabled before
nodes are provisioned with per-node secrets (P2-02).

This guide covers:
1. Generating certificates (development self-signed)
2. Mosquitto TLS configuration
3. Gateway env vars for TLS broker connection
4. ESP32 firmware WiFiClientSecure path
5. Verification steps
6. Production: Let's Encrypt path

---

## 1. Generate self-signed certificates (development)

```bash
mkdir -p certs && cd certs

# CA key + cert
openssl genrsa -out ca.key 4096
openssl req -new -x509 -days 1826 -key ca.key -out ca.crt \
  -subj "/CN=CNP-CA/O=Codessa/C=ZA"

# Server key + CSR + cert
openssl genrsa -out server.key 4096
openssl req -new -key server.key -out server.csr \
  -subj "/CN=mqtt.local/O=Codessa/C=ZA"
openssl x509 -req -days 1826 -in server.csr \
  -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt

# (Optional) Client cert for mutual TLS
openssl genrsa -out client.key 4096
openssl req -new -key client.key -out client.csr \
  -subj "/CN=cnp-gateway/O=Codessa/C=ZA"
openssl x509 -req -days 1826 -in client.csr \
  -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt

cd ..
```

---

## 2. Mosquitto TLS configuration

Replace `examples/mosquitto.conf` with:

```conf
# Plain listener (dev only — comment out for production)
# listener 1883

# TLS listener
listener 8883
cafile   /path/to/certs/ca.crt
certfile /path/to/certs/server.crt
keyfile  /path/to/certs/server.key

# Require client certificate? (mutual TLS)
# require_certificate true
# use_identity_as_username true

# Auth (replace with proper ACL in production)
allow_anonymous false
password_file /etc/mosquitto/passwd

persistence true
persistence_location /tmp/mosquitto/
log_dest stdout
```

Start with:
```bash
mosquitto -c examples/mosquitto.conf
```

Verify TLS connection:
```bash
mosquitto_sub -h localhost -p 8883 \
  --cafile certs/ca.crt \
  -t "cnp/v1/nodes/test/hello" -v
```

Expected: connection established (no cert errors).

Verify TLS rejection without cert:
```bash
mosquitto_sub -h localhost -p 8883 -t "test" -v
```
Expected: connection refused / TLS handshake failed.

---

## 3. Gateway environment variables

```bash
# TLS
MQTT_TLS_ENABLED=true
MQTT_BROKER_PORT=8883
MQTT_TLS_CA_PATH=/path/to/certs/ca.crt
MQTT_TLS_CERT_PATH=/path/to/certs/client.crt    # only for mutual TLS
MQTT_TLS_KEY_PATH=/path/to/certs/client.key     # only for mutual TLS

# Broker auth
MQTT_USERNAME=gateway
MQTT_PASSWORD=<strong-password>
```

---

## 4. Gateway TLS path — mqtt_client.py

The `GatewayMqttBridge` supports TLS via env vars in the default factory.
Add to `gateway/app/core/config.py`:

```python
@dataclass(frozen=True)
class Settings:
    # ... existing fields ...
    mqtt_tls_enabled:  bool = os.getenv("MQTT_TLS_ENABLED", "false").lower() == "true"
    mqtt_tls_ca_path:  str  = os.getenv("MQTT_TLS_CA_PATH", "")
    mqtt_tls_cert_path: str = os.getenv("MQTT_TLS_CERT_PATH", "")
    mqtt_tls_key_path:  str = os.getenv("MQTT_TLS_KEY_PATH", "")
```

Update `_default_factory` in `GatewayMqttBridge`:

```python
def _default_factory(self) -> AsyncContextManager:
    import ssl
    tls_context = None
    if settings.mqtt_tls_enabled:
        tls_context = ssl.create_default_context(cafile=settings.mqtt_tls_ca_path or None)
        if settings.mqtt_tls_cert_path and settings.mqtt_tls_key_path:
            tls_context.load_cert_chain(
                settings.mqtt_tls_cert_path,
                settings.mqtt_tls_key_path,
            )
        tls_context.check_hostname = False   # use IP in dev
    return Client(
        hostname=settings.mqtt_broker_host,
        port=settings.mqtt_broker_port,
        username=settings.mqtt_username or None,
        password=settings.mqtt_password or None,
        tls_context=tls_context,
    )
```

---

## 5. ESP32 firmware WiFiClientSecure path

In `firmware/include/TransportMqtt.h`, add an alternative constructor:

```cpp
// In TransportMqtt.h
#include <WiFiClientSecure.h>

class TransportMqtt {
 public:
  // Plain TCP (development)
  TransportMqtt(Client& netClient);
  // TLS (production) — pass a WiFiClientSecure
  TransportMqtt(WiFiClientSecure& secureClient, const char* caCert);
  ...
};
```

In `firmware/src/Application.cpp`, select transport based on config:

```cpp
bool Application::connectMqtt() {
    if (configManager_.config().mqttTlsEnabled) {
        secureClient_.setCACert(configManager_.config().mqttCaCert.c_str());
        if (!mqttTls_.connect()) return false;
        mqttTls_.subscribe(cmdInTopic_);
        mqttTls_.subscribe(configTopic_);
    } else {
        if (!mqtt_.connect()) return false;
        mqtt_.subscribe(cmdInTopic_);
        mqtt_.subscribe(configTopic_);
    }
    publishHello();
    return true;
}
```

`config.node.example.json` additions:
```json
{
  "mqttPort": 8883,
  "mqttTlsEnabled": true,
  "mqttCaCert": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"
}
```

---

## 6. Production: Let's Encrypt

For a broker with a public FQDN:

```bash
certbot certonly --standalone -d mqtt.yourdomain.com

# Then reference in mosquitto.conf:
cafile   /etc/letsencrypt/live/mqtt.yourdomain.com/chain.pem
certfile /etc/letsencrypt/live/mqtt.yourdomain.com/fullchain.pem
keyfile  /etc/letsencrypt/live/mqtt.yourdomain.com/privkey.pem
```

Cert rotation: add certbot renewal hook to reload Mosquitto:
```bash
# /etc/letsencrypt/renewal-hooks/deploy/mosquitto-reload.sh
#!/bin/bash
systemctl reload mosquitto
```

---

## Certificate rotation policy

| Cert type | Validity | Rotation trigger |
|---|---|---|
| CA cert | 5 years | Manual — requires node reflash if pinned |
| Server cert | 1 year | Auto via certbot renew |
| Client cert | 1 year | Gateway redeploy |
| Node secret (P2-02) | Until rotated | `/api/nodes/{id}/rotate-secret` |

---

*CNP-P2-01 · TLS Configuration Guide · Codessa Systems · March 2026*
