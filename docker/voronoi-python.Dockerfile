FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    tmux \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Scientific Python stack
RUN pip install --no-cache-dir \
    scipy \
    numpy \
    matplotlib \
    pandas \
    statsmodels \
    scikit-learn

# Beads (task tracking)
RUN pip install --no-cache-dir beads || true

WORKDIR /workspace

# Default: long-running container (orchestrator sends commands via docker exec)
CMD ["sleep", "infinity"]
