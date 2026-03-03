# Demos

Example scenarios to test the agent swarm orchestrator. Each demo includes a ready-to-use prompt and step-by-step instructions.

| Demo | Description | Agents | Waves |
|------|-------------|--------|-------|
| [Coupled Decisions](coupled-decisions/) | Multi-agent reasoning over coupled commercial levers | 8+ | 4 |
| [Forgetting Cure](forgetting-cure/) | Brain-inspired anti-forgetting strategies — computational neuroscience | 9 | 4 |
| [Emergent Ecosystem](emergent-ecosystem/) | Multi-species simulation with emergent communication | 6 | 3 |

## Running a Demo

### Autopilot (recommended — fully automated)

```bash
./scripts/swarm-init.sh                                    # one-time setup
./scripts/autopilot.sh --prompt demos/emergent-ecosystem/PROMPT.md
```

### Interactive (human-in-the-loop)

```bash
./scripts/swarm-init.sh
copilot
> /swarm Build from demos/emergent-ecosystem/PROMPT.md
```
