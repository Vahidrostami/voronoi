# Demos

Example scenarios to test the agent swarm orchestrator. Each demo includes a ready-to-use prompt and step-by-step instructions.

| Demo | Description | Agents | Waves |
|------|-------------|--------|-------|
| [Emergent Ecosystem](emergent-ecosystem/) | Multi-species simulation with emergent communication | 6 | 3 |

## Running a Demo

All demos use the Copilot CLI (`copilot`). Make sure you've run `./scripts/swarm-init.sh` first.

```bash
# 1. Initialize (one-time)
./scripts/swarm-init.sh

# 2. Open the demo README and copy the prompt
cat demos/emergent-ecosystem/README.md

# 3. Launch Copilot CLI and paste the prompt
copilot
> /swarm <paste prompt here>
```
