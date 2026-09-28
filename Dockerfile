FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS builder

ARG TARGETARCH
ENV TERRAFORM_VERSION=1.16.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/terraform-install
RUN curl -fsSL -O "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_SHA256SUMS" \
    && curl -fsSL -O "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip" \
    && grep "terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip" "terraform_${TERRAFORM_VERSION}_SHA256SUMS" | sha256sum -c - \
    && python -m zipfile -e "terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip" /tmp/terraform-install \
    && install -m 0755 terraform /usr/local/bin/terraform

WORKDIR /opt/iac-agent
COPY pyproject.toml README.md ./
COPY src ./src
COPY terraform/modules ./terraform/modules

RUN python -m venv /opt/iac-agent/.venv \
    && /opt/iac-agent/.venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/iac-agent/.venv/bin/pip install --no-cache-dir -e ".[api,openai,langfuse]"

RUN python -m venv /opt/checkov \
    && /opt/checkov/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/checkov/bin/pip install --no-cache-dir checkov==3.3.13 \
    && ln -sf /opt/checkov/bin/checkov /usr/local/bin/checkov

RUN mkdir -p /tmp/tf-mirror /opt/terraform/providers /home/iac \
    && printf '%s\n' \
        'terraform {' \
        '  required_providers {' \
        '    aws = {' \
        '      source  = "hashicorp/aws"' \
        '      version = "~> 6.0"' \
        '    }' \
        '  }' \
        '}' > /tmp/tf-mirror/versions.tf \
    && terraform -chdir=/tmp/tf-mirror providers mirror -platform="linux_${TARGETARCH}" /opt/terraform/providers \
    && printf '%s\n' \
        'provider_installation {' \
        '  filesystem_mirror {' \
        '    path    = "/opt/terraform/providers"' \
        '    include = ["registry.terraform.io/hashicorp/aws"]' \
        '  }' \
        '  direct {' \
        '    exclude = ["registry.terraform.io/hashicorp/aws"]' \
        '  }' \
        '}' > /home/iac/.terraformrc

FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS ui
WORKDIR /src/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

RUN groupadd --gid 10001 iac \
    && useradd --uid 10001 --gid 10001 --home-dir /home/iac --shell /usr/sbin/nologin --no-create-home iac \
    && mkdir -p /home/iac /var/lib/iac-agent/state /var/lib/iac-agent/workspaces \
    && chown iac:iac /home/iac /var/lib/iac-agent/state /var/lib/iac-agent/workspaces

COPY --from=builder /usr/local/bin/terraform /usr/local/bin/terraform
COPY --from=builder /usr/local/bin/checkov /usr/local/bin/checkov
COPY --from=builder /opt/iac-agent /opt/iac-agent
COPY --from=builder /opt/checkov /opt/checkov
COPY --from=builder /opt/terraform /opt/terraform
COPY --from=builder /home/iac/.terraformrc /home/iac/.terraformrc
COPY --from=ui /src/ui/dist /opt/iac-agent/ui

ENV IAC_AGENT_BIND_HOST=0.0.0.0 \
    IAC_AGENT_PORT=8000 \
    IAC_AGENT_TRUSTED_MODULE_ROOT=/opt/iac-agent \
    IAC_AGENT_STATE_DB=/var/lib/iac-agent/state/state.db \
    IAC_AGENT_WORKSPACE_ROOT=/var/lib/iac-agent/workspaces \
    IAC_AGENT_OBSERVABILITY=off \
    IAC_AGENT_UI_DIST=/opt/iac-agent/ui \
    HOME=/home/iac \
    PATH="/opt/iac-agent/.venv/bin:/opt/checkov/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    PYTHONDONTWRITEBYTECODE=1

USER iac

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["/opt/iac-agent/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]

CMD ["/opt/iac-agent/.venv/bin/python", "-m", "iac_agent.api"]
