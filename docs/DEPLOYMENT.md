# Deployment Instructions

## Local development

### Broker
Run Mosquitto locally with the included config.

```bash
mosquitto -c examples/mosquitto.conf
```

### Gateway
```bash
cd gateway
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

### Firmware
Recommended toolchain: PlatformIO.

```bash
cd firmware
pio run
pio run -t upload
pio device monitor
```

## Provisioning a node

This starter kit expects configuration in NVS. For first deployment, either:

1. Hard-code initial config during early testing, or
2. Build a serial/bootstrap provisioning utility, or
3. Add captive portal provisioning in a derived branch.

At minimum, set:
- Wi-Fi SSID/password
- MQTT broker host/port
- node name/type

## OTA

The firmware skeleton includes an OTA manager using HTTP(S) update APIs. In production:

- host signed firmware binaries over HTTPS
- pin server certificates if practical
- deliver OTA URL through `config_update` or a maintenance command
- stage rollouts with canary channels (`stable`, `beta`, `dev`)

## Security hardening checklist

- Enable MQTT authentication
- Use TLS for broker and API
- Replace anonymous broker config
- Introduce per-node credentials
- Add replay protection if commands become safety-critical
