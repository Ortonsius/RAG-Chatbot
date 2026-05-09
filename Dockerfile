FROM ubuntu:25.10

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    wget \
    git \
    jq \
    tree \
    python3 \
    python3-pip \
    python3-venv \
    nodejs \
    npm \
    vim \
    unzip \
    sudo \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash ai_agent && \
    echo "ai_agent ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER ai_agent
WORKDIR /workspace

RUN python3 -m venv /home/ai_agent/venv
ENV PATH="/home/ai_agent/venv/bin:$PATH"

CMD ["/bin/bash"]