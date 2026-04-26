FROM python:3.11-slim

# System dependencies (including LaTeX for paper compilation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    tmux \
    curl \
    jq \
    pandoc \
    texlive-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-bibtex-extra \
    latexmk \
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
RUN pip install --no-cache-dir "beads>=1.0.0" || true

WORKDIR /workspace

# Default: long-running container (orchestrator sends commands via docker exec)
CMD ["sleep", "infinity"]
