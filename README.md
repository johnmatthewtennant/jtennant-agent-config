# jtennant-agent-config (migration bootstrap)

This former repository name is a compatibility bootstrap for existing installs. The public layer now lives in [`jtennant-agent-config-public`](https://github.com/johnmatthewtennant/jtennant-agent-config-public).

## Install/update

```bash
curl -fsSL https://raw.githubusercontent.com/johnmatthewtennant/jtennant-agent-config/main/install.sh | bash
```

The legacy command remains supported and installs the new public repository. New installs should use:

```bash
curl -fsSL https://raw.githubusercontent.com/johnmatthewtennant/jtennant-agent-config-public/main/install.sh | bash
```

The migration bootstrap is deliberately kept available while existing users move to the new public repository.
